"""Enrichment behind the ``Enricher`` protocol: sentiment, event and impact for one document.

``PlaceholderEnricher`` (placeholder-v0) holds deterministic stand-ins for all three stages. ``ModelSentimentEnricher``
swaps in the trained sentiment model and leaves event and impact exactly as they were. Every output is labelled in
``SignalProvenance.stage_origins`` and ``ModelVersions``, so a stage that is still a placeholder can never pass for a model.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol

from ..domain import (
    DataOrigin,
    EventCategory,
    EventClassification,
    ImpactAssessment,
    ImpactDriver,
    SentimentAudit,
    SentimentResult,
    StageOrigin,
)
from .config import EnrichmentConfig
from .normalize import match_form
from .sentiment_model import SentimentModel


@dataclass(frozen=True)
class EnrichmentInput:
    text: str
    source_label: str | None  # human label shipped with the source ("bullish" | "bearish" | "neutral")
    unique_domains: int


@dataclass(frozen=True)
class Enrichment:
    sentiment: SentimentResult
    event: EventClassification
    impact: ImpactAssessment
    stage_origins: dict[str, str]
    versions: dict[str, str]
    data_origin: DataOrigin = DataOrigin.REAL_SOURCE_PLACEHOLDER_NLP
    sentiment_audit: SentimentAudit | None = None


class Enricher(Protocol):
    version: str  # recorded in the pipeline report

    @property
    def report_stage_origins(self) -> dict[str, str]:
        """stage -> plain-language origin, for the pipeline report (what is real, what is a stand-in)."""
        ...

    def unscorable(self, text: str) -> str | None:
        """Why this document cannot be enriched (it is then quarantined, not guessed), or None."""
        ...

    def enrich(self, item: EnrichmentInput) -> Enrichment: ...


def _phrase_re(words: list[str]) -> re.Pattern[str]:
    alts = "|".join(re.escape(match_form(w)) for w in sorted(set(words), key=len, reverse=True))
    return re.compile(r"(?<![a-z0-9])(?:" + alts + r")(?![a-z0-9])")


class PlaceholderEnricher:
    def __init__(self, cfg: EnrichmentConfig) -> None:
        self.cfg = cfg
        self._pos = _phrase_re(cfg.sentiment.positive)
        self._neg = _phrase_re(cfg.sentiment.negative)
        self._events = {c: _phrase_re(w) for c, w in cfg.event_keywords.items()}
        self.version = cfg.version

    @property
    def report_stage_origins(self) -> dict[str, str]:
        return {"ingestion": "REAL", "validation": "REAL", "entity_resolution": "REAL (dictionary)",
                "deduplication": "REAL", "sentiment": "PLACEHOLDER (TFN: source label)",
                "event": "PLACEHOLDER", "impact": "PLACEHOLDER", "stress_engine": "REAL (deterministic)"}

    def unscorable(self, text: str) -> str | None:
        return None  # rules always produce an answer

    def enrich(self, item: EnrichmentInput) -> Enrichment:
        folded = match_form(item.text)
        sentiment, sent_origin, sent_version, audit = self._sentiment_stage(item, folded)
        event = self._event(folded)
        impact = self._impact(event, sentiment, item.unique_domains)
        return Enrichment(
            sentiment=sentiment, event=event, impact=impact,
            stage_origins={"sentiment": sent_origin.value, "event": StageOrigin.PLACEHOLDER_RULES.value,
                           "impact": StageOrigin.PLACEHOLDER_RULES.value},
            versions={"sentiment": sent_version, "event": f"{self.cfg.version}-keywords",
                      "impact": f"{self.cfg.version}-heuristic"},
            data_origin=self.data_origin, sentiment_audit=audit)

    data_origin = DataOrigin.REAL_SOURCE_PLACEHOLDER_NLP

    def _sentiment_stage(self, item: EnrichmentInput, folded: str
                         ) -> tuple[SentimentResult, StageOrigin, str, SentimentAudit | None]:
        sentiment, origin = self._sentiment(folded, item.source_label)
        version = "source-label:tfn" if origin is StageOrigin.SOURCE_LABEL else f"{self.cfg.version}-lexicon"
        return sentiment, origin, version, None

    def _sentiment(self, folded: str, label: str | None) -> tuple[SentimentResult, StageOrigin]:
        if label in {"bullish", "bearish", "neutral"}:
            p, n = (1.0, 0.0) if label == "bullish" else (0.0, 1.0) if label == "bearish" else (0.0, 0.0)
            return (SentimentResult(positive=p, neutral=1.0 - p - n, negative=n, score=p - n),
                    StageOrigin.SOURCE_LABEL)
        pos, neg = len(self._pos.findall(folded)), len(self._neg.findall(folded))
        total = pos + neg + self.cfg.sentiment.neutral_mass
        p, n = pos / total, neg / total
        return (SentimentResult(positive=p, neutral=1.0 - p - n, negative=n, score=p - n),
                StageOrigin.PLACEHOLDER_RULES)

    def _event(self, folded: str) -> EventClassification:
        ep = self.cfg.event_probability
        hits = {c: len(r.findall(folded)) for c, r in self._events.items()}
        best = max(hits.values())
        cats = list(EventCategory)
        if best == 0:
            primary, p = EventCategory.MARKET_VALUATION, ep.unmatched_market_valuation
        else:
            primary = next(c for c in self.cfg.event_keywords if hits[c] == best)  # YAML order breaks ties
            p = min(ep.max_primary, ep.matched_primary + ep.per_extra_hit * (best - 1))
        rest = (1.0 - p) / (len(cats) - 1)
        probs = {c: (p if c is primary else rest) for c in cats}
        return EventClassification(category=primary, probabilities=probs)

    def _impact(self, event: EventClassification, sentiment: SentimentResult, domains: int) -> ImpactAssessment:
        ic = self.cfg.impact
        prior = ic.category_prior[event.category]
        tone = ic.tone_weight * abs(sentiment.score)
        corr = ic.corroboration_weight * min(1.0, math.log2(max(domains, 1)) / 3)
        raw = min(1.0, max(0.0, prior + tone + corr))
        score = min(10, max(1, math.ceil(round(raw * 10, 6))))
        return ImpactAssessment(
            score=score, raw=round(raw, 4),
            drivers=[
                ImpactDriver(feature="event_category_prior", contribution=round(prior, 4),
                             note="Placeholder heuristic, not a trained model"),
                ImpactDriver(feature="tone_magnitude", contribution=round(tone, 4),
                             note="|sentiment| × placeholder weight"),
                ImpactDriver(feature="outlet_corroboration", contribution=round(corr, 4),
                             note="distinct outlets, log-scaled"),
            ],
        )


class ModelSentimentEnricher(PlaceholderEnricher):
    """Sentiment from the trained model; event and impact stay the placeholder rules (and say so).

    The model reads the text only. A ``source_label`` shipped with the document (TFN's human label) is never an input:
    it is the model's training signal, so using it would make the "model" output a copy of its answer key.
    Impact still reads the tone magnitude, so it now sees the model's sentiment instead of the lexicon's.
    """

    data_origin = DataOrigin.REAL_SOURCE_MIXED_NLP

    def __init__(self, cfg: EnrichmentConfig, model: SentimentModel) -> None:
        super().__init__(cfg)
        self.model = model
        self.version = f"{cfg.version}+sentiment:{model.model_id}"

    @property
    def report_stage_origins(self) -> dict[str, str]:
        return {**super().report_stage_origins,
                "sentiment": f"MODEL ({self.model.model_id}, trained on Twitter Financial News)"}

    def unscorable(self, text: str) -> str | None:
        return self.model.unscorable_reason(text)

    def _sentiment_stage(self, item: EnrichmentInput, folded: str
                         ) -> tuple[SentimentResult, StageOrigin, str, SentimentAudit | None]:
        pred = self.model.predict(item.text)  # raises SentimentInputError: run_documents quarantines such documents first
        result = SentimentResult(positive=pred.positive, neutral=pred.neutral, negative=pred.negative, score=pred.score)
        audit = SentimentAudit(model_id=self.model.model_id, model_version=self.model.model_version,
                               artifact_sha256=self.model.artifact_sha256, confidence=pred.confidence,
                               calibrated=True, seen_in_training=pred.seen_in_training)
        return result, StageOrigin.MODEL, f"{self.model.model_id}+{self.model.artifact_sha256[:8]}", audit
