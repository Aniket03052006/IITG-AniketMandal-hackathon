"""The evidence view and the "what was known when" timeline: built from the signal, its assessment and the existing per-signal context.

Both views keep four things apart (``Kind``): source text, model/extraction inference, judgement priors and scenario assumptions, plus the realised
outcome, which is display-only. Everything dated after the report is tagged ``AFTER_REPORT`` and ``used_in_severity=False``.
"""

from __future__ import annotations

from datetime import datetime

from ..api.schemas import SignalContext
from ..domain import EventCategory, RiskSignal
from ..stress.scenarios import ScenarioCatalog
from .model import (
    EvidenceView,
    InferenceLine,
    Kind,
    ModelInference,
    Phase,
    RiskAssessment,
    ScenarioAssumptions,
    SourceEvidence,
    SourceReport,
    TimelineItem,
    TimelineView,
)

EXCLUDED = [
    "Reports published after this one (later coverage): shown on the timeline, never scored",
    "How many outlets eventually carried the story",
    "SEC filings accepted at or after the report",
    "The realised market move (shown for audit only)",
    "Scheduled calendar items (8-K, FOMC): read only by the reference market-reaction model, not by the severity score",
]


_FACTOR_WORDS = {
    "EQUITY": "Equity prices", "RATES_BPS": "Yields", "CREDIT_SPREAD_BPS": "Credit spreads", "PD_MULTIPLIER": "Default probability", "LGD_ADD": "Loss given default",
}
_SCOPE_WORDS = {"MARKET": "market-wide", "SECTOR": "the affected sector", "ISSUER": "the named issuer"}


def _shock_words(factor: object, scope: object, value: float) -> str:
    """A configured shock in plain units: "Equity prices, market-wide: -8.0%"."""
    f, sc = getattr(factor, "value", str(factor)), getattr(scope, "value", str(scope))
    amount = {"EQUITY": f"{value * 100:+.1f}%", "RATES_BPS": f"{value:+g} bp", "CREDIT_SPREAD_BPS": f"{value:+g} bp",
              "PD_MULTIPLIER": f"x{value:g}", "LGD_ADD": f"{value * 100:+.1f} pp"}.get(f, f"{value:+g}")
    return f"{_FACTOR_WORDS.get(f, f)}, {_SCOPE_WORDS.get(sc, sc)}: {amount}"


def _report_phase(published: datetime, t0: datetime) -> Phase:
    return Phase.AFTER_REPORT if published > t0 else Phase.BEFORE_REPORT


def build_evidence(signal: RiskSignal, a: RiskAssessment, catalog: ScenarioCatalog, stress_min: float, stress_max: float) -> EvidenceView:
    t0 = signal.document.published_at
    prov = signal.provenance
    reports = [SourceReport(source=signal.document.source, source_type=signal.document.source_type.value, published_at=t0,
                            headline=signal.document.headline, url=signal.document.url, relation="THIS_REPORT", phase=Phase.AT_REPORT,
                            used_in_score=True)]
    for c in signal.evidence.corroborating:
        ph = _report_phase(c.published_at, t0)
        reports.append(SourceReport(source=c.source, source_type=c.source_type.value, published_at=c.published_at, headline=c.headline, url=c.url,
                                    relation=c.relation, phase=ph, used_in_score=ph is not Phase.AFTER_REPORT))
    entity_match = None
    if prov and prov.entity_audit.matched_text:
        entity_match = f"{prov.entity_audit.matched_text!r} matched by rule {prov.entity_audit.rule}"
    note = ("Quotes are verbatim excerpts of the report. " + (f"{a.later_reports_excluded} later report(s) about the same story are listed but were not scored."
                                                          if a.later_reports_excluded else "No later reports about this story are known."))
    source = SourceEvidence(headline=signal.document.headline, text=a.reading.text, spans=a.reading.evidence, reports=reports,
                            entity_match=entity_match, note=note)

    r = a.reading
    ext = a.extraction
    who = "a language model" if ext.mode.value == "LLM" else "deterministic rules over the trained models"
    lines = [
        InferenceLine(label="Event", value=f"{r.event_label} / {r.event_subtype_label}", kind=Kind.EXTRACTION,
                      detail=f"read by {who}" + (f"; confidence {r.event_confidence:.0%}" if r.event_confidence is not None else "")),
        InferenceLine(label="Tone", value=f"{r.sentiment_label} ({r.sentiment:+.2f})", kind=Kind.EXTRACTION, detail=f"intensity {r.sentiment_intensity}"),
        InferenceLine(label="Affected", value=", ".join([*r.sectors, *r.regions, *r.asset_classes]) or "not identified", kind=Kind.EXTRACTION,
                      detail="sectors, regions and asset classes named or implied by the text"),
    ]
    if a.severity:
        lines.append(InferenceLine(label="Severity", value=f"{a.severity.score}/10 (range {a.severity.low}-{a.severity.high})", kind=Kind.JUDGEMENT_PRIOR,
                                   detail=a.severity.formula))
        lines += [InferenceLine(label=f.label, value=("n/a" if f.value is None else f"{f.value:.2f}"), kind=f.kind, detail=f.detail) for f in a.severity.factors]
    if a.reference.available:
        lines.append(InferenceLine(label="Reference market-reaction model", value=f"{a.reference.score}/10", kind=Kind.MODEL_REFERENCE, detail=a.reference.note))
    inference = ModelInference(lines=lines, agreement=a.agreement, note="Model inference is not source evidence: it is a reading of the text, and the weights are judgements.")

    cat = EventCategory(r.event_type) if r.event_type != "NO_EVENT" else signal.event.category
    scn = catalog.default_for(cat) if r.event_type != "NO_EVENT" else None
    if scn is None:
        assumptions = ScenarioAssumptions(
            scenario_id=None, scenario_name=None, reference_impact=None, shocks=[], trigger_threshold=a.threshold.threshold if a.threshold else 0.0,
            severity_scaling="", note="No scenario applies: the text is not a market event." if r.event_type == "NO_EVENT" else "No scenario template is mapped to this class.")
    else:
        assumptions = ScenarioAssumptions(
            scenario_id=scn.id, scenario_name=scn.name, illustrative=scn.illustrative, reference_impact=scn.reference_impact,
            shocks=[f"{_shock_words(s.factor, s.scope, s.value)} at reference severity {scn.reference_impact:g}" + (f" ({s.rationale})" if s.rationale else "")
                    for s in scn.shocks],
            trigger_threshold=a.threshold.threshold if a.threshold else 0.0,
            severity_scaling=f"shock x clamp(severity / {scn.reference_impact:g}, {stress_min:g}, {stress_max:g})",
            note="Scenario shocks are configured assumptions, labelled illustrative; they are applied mechanically by the deterministic stress engine.")
    return EvidenceView(signal_id=signal.id, source_evidence=source, model_inference=inference, scenario_assumptions=assumptions)


def build_timeline(signal: RiskSignal, a: RiskAssessment, ctx: SignalContext, as_of: datetime) -> TimelineView:
    t0 = signal.document.published_at
    used_vix = a.severity is not None and any(f.id == "market_regime" and f.available for f in a.severity.factors)
    items: list[TimelineItem] = []

    audit = signal.provenance.impact if signal.provenance else None
    if audit is not None:
        items.append(TimelineItem(
            at=None, kind="MARKET_STATE", phase=Phase.BEFORE_REPORT, known_at_assessment=True, used_in_severity=used_vix, used_by_reference_model=True,
            number_kind=Kind.MARKET_STATE, label=f"Market state as of the last session before the report ({audit.market_context_as_of})",
            detail="Prices, volatility and rates up to the previous close. The severity score reads only the VIX level from it; the reference model reads all of it."))
    for f in ctx.filings:
        after = f.role == "AFTER_REPORT"
        items.append(TimelineItem(
            at=f.acceptance_utc, kind="FILING", phase=Phase.AFTER_REPORT if after else Phase.BEFORE_REPORT, known_at_assessment=f.known_at_assessment,
            used_in_severity=False, used_by_reference_model=f.role == "FEEDS_MODEL", number_kind=Kind.MARKET_STATE,
            label=f"SEC {f.form} filing ({', '.join(f.items) or 'no items'})", detail=f.role_note))

    items.append(TimelineItem(
        at=t0, kind="REPORT", phase=Phase.AT_REPORT, known_at_assessment=True, used_in_severity=True, used_by_reference_model=True, number_kind=Kind.SOURCE,
        label=f"Report published: {signal.document.source}", detail="The text of the report is the primary input to the reading and the score."))
    for c in signal.evidence.corroborating:
        after = c.published_at > t0
        items.append(TimelineItem(
            at=c.published_at, kind="CORROBORATION", phase=Phase.AFTER_REPORT if after else Phase.BEFORE_REPORT,
            known_at_assessment=c.published_at <= as_of, used_in_severity=not after, used_by_reference_model=False, number_kind=Kind.SOURCE,
            label=f"{'Later report' if after else 'Earlier report'}: {c.source}",
            detail=("Published after the report: shown for audit, never scored." if after else "Existed when the report appeared: counted in source credibility.")))
    items.append(TimelineItem(
        at=signal.document.ingested_at, kind="INGESTED", phase=Phase.AT_REPORT, known_at_assessment=True, used_in_severity=False, used_by_reference_model=False,
        number_kind=Kind.SOURCE, label="Ingested by EventShock", detail=f"Timestamp origin: {a.timestamp_origin}."))
    items.append(TimelineItem(
        at=a.analysed_at, kind="ASSESSED", phase=Phase.AT_REPORT, known_at_assessment=True, used_in_severity=False, used_by_reference_model=False,
        number_kind=Kind.EXTRACTION, label=f"Assessed ({a.extraction.mode.value.lower()} reading, hybrid {a.severity.version if a.severity else 'n/a'})",
        detail="Everything above this line in time, and flagged as used, is what the score could see."))
    if ctx.outcome is not None:
        items.append(TimelineItem(
            at=None, kind="OUTCOME", phase=Phase.AFTER_REPORT, known_at_assessment=False, used_in_severity=False, used_by_reference_model=False,
            number_kind=Kind.REALISED, label=f"Realised move (session {ctx.outcome.session})", detail=ctx.outcome.note + ". Display only: never an input."))

    order = {Phase.BEFORE_REPORT: 0, Phase.AT_REPORT: 1, Phase.AFTER_REPORT: 2}
    far = datetime.max.replace(tzinfo=t0.tzinfo)
    items.sort(key=lambda i: (order[i.phase], i.at or far))
    return TimelineView(
        signal_id=signal.id, report_time=t0, assessed_at=a.analysed_at, timestamp_origin=a.timestamp_origin, items=items, excluded=EXCLUDED,
        note=("Items marked 'used' were available when the report appeared and can influence the score. Everything dated after the report is shown "
              "for audit and cannot."))
