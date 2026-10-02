"""PLACEHOLDER enrichment (placeholder-v0): deterministic stand-ins for the sentiment, event and impact models.

This is deliberately small and honest. It exists so real documents can reach the existing UI and stress engine
before the NLP stages are built; every output is labelled in ``SignalProvenance.stage_origins`` and
``ModelVersions``. Replace this module (the ``Enricher`` protocol) when the real stages land.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol

from ..domain import (
    EventCategory,
    EventClassification,
    ImpactAssessment,
    ImpactDriver,
    SentimentResult,
    StageOrigin,
)
from .config import EnrichmentConfig
from .normalize import match_form


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


class Enricher(Protocol):
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

    def enrich(self, item: EnrichmentInput) -> Enrichment:
        folded = match_form(item.text)
        sentiment, sent_origin = self._sentiment(folded, item.source_label)
        event = self._event(folded)
        impact = self._impact(event, sentiment, item.unique_domains)
        return Enrichment(
            sentiment=sentiment, event=event, impact=impact,
            stage_origins={"sentiment": sent_origin.value, "event": StageOrigin.PLACEHOLDER_RULES.value,
                           "impact": StageOrigin.PLACEHOLDER_RULES.value},
            versions={
                "sentiment": ("source-label:tfn" if sent_origin is StageOrigin.SOURCE_LABEL
                              else f"{self.version}-lexicon"),
                "event": f"{self.version}-keywords",
                "impact": f"{self.version}-heuristic",
            },
        )

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
