"""``AssessmentService``: turns a ``RiskSignal`` into a ``RiskAssessment`` (extraction + severity + threshold) and memoises it.

Which text gets the language model: new text (a paste, the live feed) does; the frozen replay signals are assessed by the deterministic rule
extractor unless a caller asks for a refinement, so opening the app never costs a call and replay results stay reproducible.
The assessment is derived from the signal and never stored on it, so ``RiskSignal`` and the replay output digest are untouched.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from ..config import StressConfig
from ..domain import EventCategory, RiskSignal
from ..services.stress_service import SeverityView
from ..store import CHANNEL_REPLAY, CombinedSignalRepository
from .extractor import SemanticExtractor
from .freshness import assess_market, previous_weekday
from .model import (
    Agreement,
    Conflict,
    ExtractionMode,
    IndicatorBasis,
    Origin,
    ProvenanceLine,
    ReferenceReading,
    RiskAssessment,
    SemanticReading,
    SeverityAssessment,
    ThresholdState,
)
from .reference import Reference, analysed_text
from .rubric import RubricDeriver
from .severity import SeverityInputs, SeverityScorer
from .vocab import NO_EVENT, build_summary

BASIS = "SCORECARD"
LABELS = [
    "A scorecard: four anchored answers about the event, a fixed severity matrix and two bounded data adjustments. Not validated, not a forecast.",
    "The severity score is a triage of how materially this kind of event could affect financial markets, not a predicted price move.",
]
LIMITATIONS = [
    "Matrix anchors, certainty and direction factors and the data adjustments are documented judgements (configs/severity.yaml), fixed before the benchmark and not fitted to outcomes: no outcome labels are used.",
    "The rubric answers are the least certain part: the rules baseline is crude and a language model's judgement is only as good as the model. Both are shown, and the AI's effect is bounded.",
    "The range shows sensitivity to the judgement parameters, not a statistical interval.",
    "A name in the text that the entity master does not hold is kept as a mention, never as an issuer.",
]


def _market_state(signal: RiskSignal) -> tuple[float | None, str | None]:
    """(VIX level, the session its close is from), from the market state the pipeline recorded at event time.

    The pipeline's features are the state strictly before the reaction session, so for a report with a reaction date that is the weekday before it; for a
    report after the end of the frozen pack the state is the pack's last session."""
    audit = signal.provenance.impact if signal.provenance else None
    if audit is None:
        return None, None
    level = next((float(v) for k in ("f_vix_level", "m_vix_level") if (v := audit.inputs.get(k)) is not None and math.isfinite(v)), None)
    if level is None:
        return None, None
    if audit.session == "NEXT":
        return level, audit.market_context_as_of
    try:
        return level, previous_weekday(date.fromisoformat(audit.session)).isoformat()
    except ValueError:
        return level, None


def reference_reading(signal: RiskSignal) -> ReferenceReading:
    prov = signal.provenance
    if signal.impact is None:
        return ReferenceReading(available=False, note=(prov.impact_note if prov and prov.impact_note else "The trained model gave no score for this signal."))
    origin = "MODEL" if prov and prov.stage_origins.get("impact") == "MODEL" else "PLACEHOLDER"
    life = prov.impact.lifecycle.value if prov and prov.impact else None
    if origin == "MODEL":
        note = ("Trained market-reaction model (experimental). It estimates the size of an abnormal price move; in its own evaluation that skill "
                "comes mostly from the volatility regime, not from the news. Shown for reference; it does not drive the trigger.")
    else:
        note = "A labelled placeholder rule (the trained model could not score this report). Shown for reference; it does not drive the trigger."
    return ReferenceReading(available=True, model_id=signal.model_versions.impact, lifecycle=life, origin=origin, score=signal.impact.score,
                            score_low=signal.impact.score_low, score_high=signal.impact.score_high, note=note)


def _agreement(r: SemanticReading, ref: Reference) -> Agreement:
    ev = ref.event_category
    ev_agrees = None if ev is None or ref.event_status != "CLASSIFIED" else (r.event_type == ev)
    sd = None
    if ref.sentiment is not None:
        a, b = r.sentiment_label, ("negative" if ref.sentiment <= -0.15 else "positive" if ref.sentiment >= 0.15 else "neutral")
        sd = a == b
    bits = []
    if ev_agrees is False:
        bits.append(f"The trained event model reads this as {ev}; the assessment reads {r.event_type}.")
    if sd is False:
        bits.append("The trained tone model and the assessment disagree on tone.")
    return Agreement(
        reference_event_type=ev, reference_event_status=ref.event_status, reference_event_confidence=ref.event_confidence,
        event_type_agrees=ev_agrees, reference_sentiment=ref.sentiment, sentiment_direction_agrees=sd,
        note=" ".join(bits) or "The assessment and the trained models agree (or the trained models made no firm call).")


class AssessmentService:
    def __init__(self, extractor: SemanticExtractor, scorer: SeverityScorer, deriver: RubricDeriver, signals: CombinedSignalRepository, *,
                 stress: StressConfig, clock: Callable[[], datetime] | None = None) -> None:
        self.extractor, self.scorer, self.deriver, self._signals, self._stress = extractor, scorer, deriver, signals, stress
        self._clock = clock or (lambda: datetime.now(UTC))
        self._memo: dict[str, tuple[tuple, RiskAssessment]] = {}
        self._lock = threading.RLock()
        self._by_entity: dict[str, list[RiskSignal]] | None = None

    # -------------------------------------------------------------------------------------------------------------------- core
    @property
    def threshold(self) -> float:
        return self._stress.trigger_threshold

    def _wants_llm(self, signal: RiskSignal, refine: bool) -> bool:
        return refine or self._signals.channel_of(signal.id) != CHANNEL_REPLAY

    def assess(self, signal: RiskSignal, *, refine: bool = False) -> RiskAssessment:
        want_llm = self._wants_llm(signal, refine)  # the extractor says why when the model is wanted but unavailable (no key)
        fp = (signal.created_at, signal.evidence.source_count, signal.document.id, signal.status.value)
        with self._lock:
            hit = self._memo.get(signal.id)
            if hit and hit[0] == fp and (not (want_llm and self.extractor.llm_ready) or hit[1].extraction.mode.value == "LLM"
                                         or hit[1].extraction.fallback_reason):
                return hit[1]
        a = self._build(signal, want_llm)
        with self._lock:
            self._memo[signal.id] = (fp, a)
        return a

    def detail(self, signal: RiskSignal, *, refine: bool = False) -> RiskAssessment:
        """``assess`` plus the conflict check (which looks at other signals, so it is not memoised)."""
        a = self.assess(signal, refine=refine)
        return a.model_copy(update={"conflict": self.conflict_for(signal)})

    def _build(self, signal: RiskSignal, use_llm: bool) -> RiskAssessment:
        ref = Reference.from_signal(signal)
        doc = signal.document
        text = analysed_text(doc.headline, doc.body)
        reading, info = self.extractor.extract(text, ref, use_llm=use_llm)
        # the rubric's deterministic baseline always comes from the rule extractor, even when a model read the text: the model then adjusts it within a bound
        rules_reading = reading if info.mode is ExtractionMode.RULES else self.extractor.rules.extract(text, ref)[0]
        rubric = self.deriver.combine(text, rules_reading, reading.ai_rubric)
        t0 = doc.published_at
        corro = [c for c in signal.evidence.corroborating if c.published_at <= t0]
        later = [c for c in signal.evidence.corroborating if c.published_at > t0]
        vix, m_as_of = _market_state(signal)
        market = assess_market(t0, m_as_of, vix, self.scorer.cfg.regime)
        severity = self.scorer.score(SeverityInputs(
            reading=reading, rubric=rubric, market=market, novelty=signal.evidence.novelty_score if signal.evidence.novelty_measured else None,
            source_type=doc.source_type.value, corroborating_at_event_time=len({c.source for c in corro})))
        threshold = None
        severity_note = None
        if severity is None:
            severity_note = "The text does not describe a market event, so nothing is scored for it."
        else:
            crosses = severity.score >= self.threshold
            msg = (f"Severity {severity.score}/10 ({severity.band_label.lower()}) meets the automatic trigger ({self.threshold:g}): the default scenario is suggested "
                   "and can run now. This is a triage score, not a forecast."
                   if crosses else
                   f"Severity {severity.score}/10 ({severity.band_label.lower()}) is below the automatic trigger ({self.threshold:g}): no stress runs automatically. "
                   "You can still run it as a what-if. This is a triage score, not a forecast.")
            threshold = ThresholdState(threshold=self.threshold, score=severity.score, crosses=crosses,
                                       status="ABOVE_TRIGGER" if crosses else "BELOW_TRIGGER", message=msg)
        prov = signal.provenance
        return RiskAssessment(
            signal_id=signal.id, headline=doc.headline, source=doc.source, source_type=doc.source_type.value, published_at=doc.published_at,
            ingested_at=doc.ingested_at, analysed_at=self._clock() if self._signals.channel_of(signal.id) != CHANNEL_REPLAY else signal.created_at,
            timestamp_origin=prov.timestamp_origin.value if prov else "UNKNOWN", summary=build_summary(reading), extraction=info,
            reading=reading, agreement=_agreement(reading, ref), severity=severity, severity_note=severity_note, threshold=threshold,
            reference=reference_reading(signal), conflict=None, corroborating_at_event_time=len({c.source for c in corro}),
            later_reports_excluded=len(later), provenance=self._provenance(reading, info, ref, severity), labels=LABELS, limitations=LIMITATIONS)

    # ----------------------------------------------------------------------------------------------------------- provenance
    def _provenance(self, r: SemanticReading, info, ref: Reference, sev: SeverityAssessment | None) -> list[ProvenanceLine]:
        llm = info.mode is ExtractionMode.LLM
        who = f"language model {info.model_id}" if llm else "deterministic cue phrases and the trained classifiers"
        trained_event = not llm and ref.event_is_finding and ref.event_category == r.event_type
        ind = r.severity_indicators
        counts = {b: sum(1 for h in ind if h.basis is b) for b in IndicatorBasis}
        lines = [
            ProvenanceLine(part="Event class and subtype", origin=Origin.AI if (llm or trained_event) else Origin.RULES,
                           detail=(f"read by the {who}" if llm else "the trained event classifier (experimental)" if trained_event else "cue phrases in the text")),
            ProvenanceLine(part="Tone", origin=Origin.AI, detail=("read by the language model" if llm else "the trained sentiment classifier (experimental)")),
            ProvenanceLine(part="Entities", origin=Origin.HYBRID if llm else Origin.RULES,
                           detail=("named by the model, then checked against the text and the entity master; only the master can make an issuer" if llm
                                   else "the entity master and institution list; a company-looking name stays a mention")),
            ProvenanceLine(part="Severity indicators", origin=Origin.HYBRID if counts[IndicatorBasis.INFERRED] else (Origin.AI if llm else Origin.RULES),
                           detail=f"{counts[IndicatorBasis.QUOTED]} quoted, {counts[IndicatorBasis.KEYWORD]} matched by a configured phrase, "
                                  f"{counts[IndicatorBasis.INFERRED]} inferred by the AI (an inference is never shown as a quote)"),
        ]
        if sev is not None:
            ai_moves = [f.label.lower() for f in sev.rubric if f.adjustment in ("AI_WITHIN_BOUND", "AI_QUOTE_BACKED")]
            lines += [
                ProvenanceLine(part="Rubric answers (magnitude, reach, certainty, direction)", origin=Origin.HYBRID if any(f.origin is Origin.HYBRID for f in sev.rubric) else Origin.RULES,
                               detail=("deterministic rules, then the AI may move each answer one step (more only with a verbatim quote)" if any(f.origin is Origin.HYBRID for f in sev.rubric)
                                       else "deterministic rules only: no language model answered the rubric") + (f"; the AI moved: {', '.join(ai_moves)}" if ai_moves else "")),
                ProvenanceLine(part="Severity matrix and scaling", origin=Origin.ASSUMPTION, detail="configured anchors and factors: judgements fixed before the benchmark, not fitted"),
                ProvenanceLine(part="Market regime", origin=Origin.DATA, detail=sev.market.reason),
                ProvenanceLine(part="Novelty", origin=Origin.RULES if not any(o.id == "novelty" for o in sev.omitted) else Origin.RULES,
                               detail=("compared with earlier reports of the same issuer" if not any(o.id == "novelty" for o in sev.omitted) else "not measurable: no issuer to compare against")),
                ProvenanceLine(part="Report reliability", origin=Origin.DATA, detail=sev.reliability.basis),
            ]
        lines += [
            ProvenanceLine(part="Scenario", origin=Origin.ASSUMPTION, detail="configured shocks, labelled illustrative"),
            ProvenanceLine(part="Portfolio impact", origin=Origin.RULES, detail="the deterministic stress engine: no model, no randomness"),
        ]
        return lines

    # -------------------------------------------------------------------------------------------------------- stress hook
    def severity_view(self, signal: RiskSignal) -> SeverityView | None:
        """What the stress engine reads: score, event class for the scenario, a sector for sector shocks. None when nothing is scored."""
        a = self.assess(signal)
        if a.severity is None or a.reading.event_type == NO_EVENT:
            return None
        return SeverityView(
            score=a.severity.score, category=EventCategory(a.reading.event_type), sector=a.reading.sectors[0] if a.reading.sectors else None,
            basis=BASIS, version=a.severity.version, extraction_mode=a.extraction.mode.value)

    # ----------------------------------------------------------------------------------------------------------------- conflict
    def _entity_index(self) -> dict[str, list[RiskSignal]]:
        if self._by_entity is None:
            idx: dict[str, list[RiskSignal]] = {}
            for s in self._signals.base._signals:  # noqa: SLF001 (same package; the replay base is immutable)
                if not s.entity.is_unknown:
                    idx.setdefault(s.entity.entity_id, []).append(s)
            self._by_entity = idx
        return self._by_entity

    def conflict_for(self, signal: RiskSignal) -> Conflict | None:
        """Another report on the same issuer within the window, with the opposite tone, both strongly so."""
        if signal.entity.is_unknown:
            return None
        cfg = self.scorer.cfg.conflict
        s0 = signal.sentiment.score
        if abs(s0) < cfg.min_abs_sentiment:
            return None
        pool = list(self._entity_index().get(signal.entity.entity_id, []))
        pool += [s for s, _ in self._signals.live.items() if s.entity.entity_id == signal.entity.entity_id]
        window = timedelta(hours=cfg.window_hours)
        best: tuple[float, RiskSignal] | None = None
        for o in pool:
            if o.id == signal.id:
                continue
            gap = abs((o.document.published_at - signal.document.published_at).total_seconds())
            if gap > window.total_seconds() or abs(o.sentiment.score) < cfg.min_abs_sentiment or o.sentiment.score * s0 >= 0:
                continue
            if best is None or gap < best[0]:
                best = (gap, o)
        if best is None:
            return None
        gap, o = best
        return Conflict(signal_id=o.id, headline=o.document.headline, sentiment=o.sentiment.score, hours_apart=round(gap / 3600.0, 2),
                        note=(f"Another report on {signal.entity.entity_name or signal.entity.entity_id} within {cfg.window_hours:g} hours has the "
                              "opposite tone. Both are kept; neither is discounted."))
