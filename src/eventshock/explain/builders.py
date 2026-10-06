"""Builders: structured outputs in, an ``Explanation`` out. Every reason names the kind of statement it is (model output, product rule, scenario assumption, historical observation) and
the output it was read from. Money and percentages are formatted from the numbers; no sentence is generated from anything that is not a field."""

from __future__ import annotations

from datetime import datetime

from ..decision.models import ObservationKind, ProvenanceRef
from ..intelligence.model import EventIntelligence
from ..lab.models import LabResult, ReverseStressResult
from ..markets.models import EventMarketView
from ..monitor.models import RANK_MATERIALITY, EventState, RiskChange
from ..propagation.models import AutoStressResult, PortfolioMateriality, StressAttribution
from .models import VERSION, Explanation, Reason, ReasonCode, ReasonKind, Subject

K = ReasonKind
C = ReasonCode
LABELS = [
    "Each reason says what kind of statement it is: a model output (EventShock's own reading), a product rule (a deterministic rule on counted facts or on the engine's arithmetic), "
    "a scenario assumption (a hypothetical shock) or a historical observation (what already happened). They are never mixed.",
    "Stress figures are a simulation under an illustrative scenario: not a prediction.",
]
_KIND_OBS = {K.MODEL_OUTPUT: ObservationKind.EVENTSHOCK_ASSESSMENT, K.PRODUCT_RULE: ObservationKind.PRODUCT_RULE, K.SCENARIO_ASSUMPTION: ObservationKind.SCENARIO_ASSUMPTION,
             K.HISTORICAL_OBSERVATION: ObservationKind.HISTORICAL_OBSERVATION, K.EXTERNAL_MARKET_OBSERVATION: ObservationKind.EXTERNAL_MARKET_OBSERVATION}


class ExplanationError(ValueError):
    """A material output had no reason to give: a bug, never an empty explanation."""


def _r(code: ReasonCode, kind: ReasonKind, text: str, source: str, *, value: str | float | None = None, unit: str | None = None, detail: str | None = None, ref: str | None = None,
       at: datetime | None = None) -> Reason:
    return Reason(code=code, kind=kind, text=text, value=value, unit=unit, detail=detail, source_ref=source,
                  provenance=[ProvenanceRef(kind=_KIND_OBS[kind], source=source, ref_id=ref, as_of=at)])


def _pp(x: float | None, signed: bool = False) -> str:
    return "n/a" if x is None else f"{'+' if signed and x > 0 else '−' if x < 0 else ''}{abs(x) * 100:.1f}%"


def finish(subject: Subject, *, event_id: str | None, signal_id: str | None, headline: str, level: str | None, reasons: list[Reason], limitations: list[str], material: bool,
           availability: str = "AVAILABLE", unavailable_reason: str | None = None) -> Explanation:
    if material and not reasons:
        raise ExplanationError(f"{subject.value} explanation for {event_id or signal_id}: a material output must have at least one reason")
    kinds: dict[str, int] = {}
    for r in reasons:
        kinds[r.kind.value] = kinds.get(r.kind.value, 0) + 1
    return Explanation(subject=subject, event_id=event_id, signal_id=signal_id, headline=headline, level=level, availability=availability, unavailable_reason=unavailable_reason, reasons=reasons,
                       kinds=dict(sorted(kinds.items())), limitations=limitations, labels=LABELS)


# ------------------------------------------------------------------------------------------------------------------------------ priority
def event_reasons(state: EventState, intel: EventIntelligence | None, mat: PortfolioMateriality | None, threshold: float) -> list[Reason]:
    """The ranking key of the executive view, one reason per component, in the order the key reads them."""
    out: list[Reason] = []
    at = state.as_of
    if mat is not None and mat.availability.value != "ABSTAINED":
        out.append(_r(C.MATERIALITY, K.PRODUCT_RULE, f"Relevance to the portfolio is {mat.level}: {mat.summary}", "propagation.materiality", value=mat.level, ref=state.lead_signal_id, at=at,
                      detail="; ".join(mat.why[:3])))
        out.append(_r(C.EXPOSURE_SHARE, K.PRODUCT_RULE, f"The event reaches {mat.reached_share * 100:.1f}% of the book, counted once ({mat.mapping_basis.lower().replace('_', ' ')})",
                      "propagation.materiality", value=mat.reached_share, unit="share of book", ref=state.lead_signal_id, at=at))
        for rule in mat.rules:
            if rule.fired:
                out.append(_r(C.MATERIALITY_RULE, K.PRODUCT_RULE, f"{rule.kind.title()} {rule.id}: {rule.effect}", "propagation.materiality", value=rule.id, ref=state.lead_signal_id, at=at))
    elif mat is not None:
        out.append(_r(C.MAPPING_BASIS, K.PRODUCT_RULE, f"No defensible mapping from this event to the portfolio exists, so relevance is undetermined: {mat.reason or mat.summary}", "propagation.materiality",
                      value="UNDETERMINED", ref=state.lead_signal_id, at=at))
    if state.severity is not None:
        out.append(_r(C.SEVERITY, K.MODEL_OUTPUT, f"Severity {state.severity:g} of 10 ({state.severity_band}): the transparent scorecard, a triage level and not outcome-calibrated"
                      + (" — at or above the stress trigger" if state.severity >= threshold else f" — below the stress trigger of {threshold:g}"), "assessment.severity",
                      value=state.severity, unit="1-10", ref=state.lead_signal_id, at=at))
    else:
        out.append(_r(C.SEVERITY_UNSCORED, K.MODEL_OUTPUT, "The text is not read as a market event, so no severity is scored", "assessment.severity", ref=state.lead_signal_id, at=at))
    out.append(_r(C.INDEPENDENT_SOURCES, K.PRODUCT_RULE, f"{state.independent_sources} independent source{'s' if state.independent_sources != 1 else ''} among {state.report_count} report{'s' if state.report_count != 1 else ''}, "
                  "counted by rule (copies and syndicated repeats are not independent)", "intelligence.evidence", value=state.independent_sources, unit="sources", ref=state.event_id, at=at))
    out.append(_r(C.EVIDENCE_TIER, K.PRODUCT_RULE, f"Evidence is {state.evidence_tier.lower()} (how well corroborated; not the model's confidence)"
                  + (f": {intel.evidence.evidence_strength.rule}" if intel is not None else ""), "intelligence.evidence", value=state.evidence_tier, ref=state.event_id, at=at))
    if state.lifecycle:
        tr = intel.lifecycle.transitions[-1] if intel is not None and intel.lifecycle.transitions else None
        out.append(_r(C.LIFECYCLE, K.PRODUCT_RULE, f"Lifecycle is {state.lifecycle.lower()}" + (f": {tr.rule_text}" if tr else ""), "intelligence.lifecycle", value=state.lifecycle, ref=state.event_id, at=at,
                      detail=(f'Cue: "{tr.evidence_quote}"' if tr and tr.evidence_quote else None)))
    if state.conflict in ("POSSIBLE_CONFLICT", "CONFLICTED"):
        out.append(_r(C.CONFLICT_OPEN, K.PRODUCT_RULE, f"Reports contradict each other on a tracked claim ({state.conflict.lower().replace('_', ' ')}), which caps the evidence tier",
                      "intelligence.contradiction", value=state.conflict, ref=state.event_id, at=at))
    if intel is not None:
        out.append(_r(C.NOVELTY, K.PRODUCT_RULE, f"Novelty: {intel.novelty.label.lower()}" + (f" ({intel.novelty.reason})" if intel.novelty.reason else ""), "intelligence.novelty", value=intel.novelty.label,
                      ref=state.event_id, at=at))
        out.append(_r(C.SCOPE if intel.scope.scope_type.value != "UNRESOLVED" else C.SCOPE_UNRESOLVED, K.PRODUCT_RULE,
                      f"Scope: {intel.scope.scope_type.value.lower()}{f' ({intel.scope.scope_value})' if intel.scope.scope_value else ''}. {intel.scope.reason}", "intelligence.scope",
                      value=intel.scope.scope_type.value, ref=state.event_id, at=at))
    if state.event_type:
        out.append(_r(C.EVENT_CLASS, K.MODEL_OUTPUT, f"Read as {state.event_type.replace('_', ' ').lower()}", "assessment.reading", value=state.event_type, ref=state.lead_signal_id, at=at))
    return out


def priority(state: EventState, intel: EventIntelligence | None, mat: PortfolioMateriality | None, threshold: float) -> Explanation:
    level = mat.level if mat is not None and mat.availability.value != "ABSTAINED" else None
    head = (f"Priority {level}: relevance to the portfolio, then severity {state.severity:g}, then evidence and lifecycle" if level and state.severity is not None else
            f"Priority {level}: relevance to the portfolio" if level else "Ranked by severity only: this event does not reach the portfolio, or no mapping is defensible")
    reasons = event_reasons(state, intel, mat, threshold)
    return finish(Subject.PRIORITY, event_id=state.event_id, signal_id=state.lead_signal_id, headline=head, level=level, reasons=reasons, material=state.tracked,
                  limitations=["Priority is a deterministic ordering of the components above (materiality tier, severity, size of the change, recency, id), not a score and not a forecast.",
                               "Severity is a transparent scorecard that is not calibrated to market outcomes."])


# ----------------------------------------------------------------------------------------------------------------------------- visibility
def visibility(state: EventState, intel: EventIntelligence | None, mat: PortfolioMateriality | None, threshold: float, *, watch_hits: list[str], changes: list[RiskChange]) -> Explanation:
    out: list[Reason] = []
    at = state.as_of
    if intel is not None:
        sc = intel.scope
        out.append(_r(C.SCOPE if sc.scope_type.value != "UNRESOLVED" else C.SCOPE_UNRESOLVED, K.PRODUCT_RULE, f"Scope match: the event is about {sc.scope_value or 'no resolved subject'} ({sc.scope_type.value.lower()}). {sc.reason}",
                      "intelligence.scope", value=sc.scope_type.value, ref=state.event_id, at=at))
    for w in watch_hits:
        out.append(_r(C.WATCHLIST_MATCH, K.PRODUCT_RULE, f"It matches your watchlist item: {w}", "watchlist.match", value=w, ref=state.event_id, at=at))
    if mat is not None and mat.availability.value != "ABSTAINED":
        out.append(_r(C.EXPOSURE_SHARE, K.PRODUCT_RULE, f"Exposure match: it reaches {mat.reached_share * 100:.1f}% of the portfolio ({mat.mapping_basis.lower().replace('_', ' ')})", "propagation.materiality",
                      value=mat.reached_share, unit="share of book", ref=state.lead_signal_id, at=at))
        out.append(_r(C.MATERIALITY, K.PRODUCT_RULE, f"Portfolio relevance {mat.level}: {mat.summary}", "propagation.materiality", value=mat.level, ref=state.lead_signal_id, at=at))
    if state.severity is not None:
        out.append(_r(C.SEVERITY, K.MODEL_OUTPUT, f"Event severity {state.severity:g} of 10 ({state.severity_band})", "assessment.severity", value=state.severity, unit="1-10", ref=state.lead_signal_id, at=at))
    out.append(_r(C.EVIDENCE_TIER, K.PRODUCT_RULE, f"Evidence quality: {state.evidence_tier.lower()} with {state.independent_sources} independent source{'s' if state.independent_sources != 1 else ''}",
                  "intelligence.evidence", value=state.evidence_tier, ref=state.event_id, at=at))
    for c in changes[:3]:
        out.append(_r(C.RECENT_CHANGE, K.PRODUCT_RULE, f"Recent change: {c.summary}", "monitor.diff", value=c.change_type.value, ref=c.change_id, at=c.at, detail=f"rule {c.rule}"))
    why = []
    if watch_hits:
        why.append("it matches a watchlist")
    if mat is not None and RANK_MATERIALITY.get(mat.level, -1) >= RANK_MATERIALITY["MEDIUM"]:
        why.append("it matters to the portfolio")
    if state.severity is not None and state.severity >= threshold:
        why.append("its severity is at or above the stress trigger")
    if changes:
        why.append("it changed")
    head = "You are seeing this because " + (", and ".join(why) if why else "it is tracked: its severity or its relevance to the portfolio reaches the floor in configs/decision.yaml")
    return finish(Subject.VISIBILITY, event_id=state.event_id, signal_id=state.lead_signal_id, headline=head, level=None, reasons=out, material=True,
                  limitations=["Visibility follows deterministic rules (tracking floor, portfolio materiality, watchlists); nothing is personalised by a model."])


# --------------------------------------------------------------------------------------------------------------------------------- change
def change(c: RiskChange) -> Explanation:
    out = [_r(C.CHANGE_RULE, K.PRODUCT_RULE, f"{c.change_type.value.replace('_', ' ').capitalize()}: {c.summary}", "monitor.diff", value=c.rule, ref=c.change_id, at=c.at)]
    for f in c.changed_fields:
        out.append(_r(C.CHANGE_FIELD, K.MODEL_OUTPUT if f.field in ("severity", "lead_signal_id") else K.PRODUCT_RULE, f"{f.field.replace('_', ' ')}: {f.previous if f.previous is not None else 'n/a'} → {f.current if f.current is not None else 'n/a'}",
                      "monitor.state", value=str(f.current), ref=c.event_id, at=c.at))
    for p in (c.portfolio_impact,) if c.portfolio_impact and c.change_type.value == "STRESS_CHANGED" else ():
        out.append(_r(C.STRESS_TOTAL, K.SCENARIO_ASSUMPTION, f"Modeled scenario P&L {_pp(p.stress_pnl_pct_previous, True)} → {_pp(p.stress_pnl_pct_current, True)} of the book (a simulation under an illustrative scenario)",
                      "propagation.generated_scenario", ref=c.change_id, at=c.at))
    for e in c.supporting_evidence[:3]:
        out.append(_r(C.CHANGE_FIELD, K.PRODUCT_RULE, f'Evidence ({e.kind.lower().replace("_", " ")}): "{e.text}"', "monitor.evidence", ref=e.report_id, at=e.at))
    return finish(Subject.CHANGE, event_id=c.event_id, signal_id=c.current.lead_signal_id, headline=f"Flagged as {c.change_type.value.replace('_', ' ').lower()} by rule {c.rule}", level=c.change_type.value,
                  reasons=out, material=True, limitations=["A change is reported when a configured threshold is crossed (judgement priors, unvalidated); it does not measure how much the change matters."])


# ---------------------------------------------------------------------------------------------------------------------------------- stress
def _rows(att: StressAttribution, dim: str, n: int = 2):  # noqa: ANN202
    t = next((t for t in att.tables if t.dimension == dim), None)
    return (t.rows if t else [])[:n]


def attribution_reasons(att: StressAttribution, *, source: str, ref: str | None, at: datetime | None, label: str = "the scenario") -> list[Reason]:
    out = [_r(C.STRESS_TOTAL, K.PRODUCT_RULE, f"Modeled change {att.pnl_pct * 100:+.2f}% of the portfolio ({att.total_pnl:+,.0f}) under {label}: a regrouping of the engine's own result that adds up to its total",
              source, value=att.pnl_pct, unit="fraction of book", ref=ref, at=at)]
    for r in att.drivers.rows[:2]:
        out.append(_r(C.STRESS_DRIVER_KIND, K.PRODUCT_RULE, f"{r.label}: {r.delta:+,.0f} ({(r.share_of_total or 0) * 100:.0f}% of the total)", source, value=r.delta, ref=ref, at=at))
    for r in _rows(att, "market_factor"):
        out.append(_r(C.STRESS_DRIVER_FACTOR, K.PRODUCT_RULE, f"Market factor {r.label.lower()}: {r.delta:+,.0f} ({(r.share_of_total or 0) * 100:.0f}%)", source, value=r.delta, ref=ref, at=at))
    for r in _rows(att, "risk_factor"):
        out.append(_r(C.STRESS_DRIVER_RISK_FACTOR, K.PRODUCT_RULE, f"Risk factor {r.label.lower()}: {r.delta:+,.0f} ({(r.share_of_total or 0) * 100:.0f}%)", source, value=r.delta, ref=ref, at=at))
    for r in _rows(att, "sector"):
        out.append(_r(C.STRESS_DRIVER_SECTOR, K.PRODUCT_RULE, f"Sector {r.label}: {r.delta:+,.0f} ({(r.share_of_total or 0) * 100:.0f}%)", source, value=r.delta, ref=ref, at=at))
    for r in _rows(att, "issuer"):
        out.append(_r(C.STRESS_DRIVER_ISSUER, K.PRODUCT_RULE, f"Issuer {r.label}: {r.delta:+,.0f} ({(r.share_of_total or 0) * 100:.0f}%)", source, value=r.delta, ref=ref, at=at))
    return out


def stress(flow: AutoStressResult, at: datetime | None) -> Explanation:
    sig = flow.signal_id
    gen = flow.scenario
    if flow.run is None or flow.attribution is None:
        why = flow.note or gen.reason or "no defensible scenario for this event"
        out = [_r(C.STRESS_NOT_RUN, K.PRODUCT_RULE, f"No stress was run: {why}", "propagation.scenario", ref=sig, at=at)]
        for g in gen.gates:
            if not g.passed:
                out.append(_r(C.STRESS_NOT_RUN, K.PRODUCT_RULE, f"Gate {g.label.lower()} not passed: {g.detail}", "propagation.scenario", value=g.id, ref=sig, at=at))
        return finish(Subject.STRESS, event_id=None, signal_id=sig, headline="No stress result to explain: SCENARIO UNAVAILABLE", level=None, reasons=out, material=False,
                      limitations=["A scenario is generated only when severity, relevance, direction and mapping gates pass."], availability="PARTIAL")
    run = flow.run
    out = [_r(C.STRESS_SCENARIO, K.SCENARIO_ASSUMPTION, f"Scenario: {run.scenario.name if run.scenario else 'generated'}. Its shocks are configured assumptions, not forecasts", "propagation.generated_scenario",
              value=run.scenario.id if run.scenario else None, ref=run.run_id, at=at)]
    for s in run.shocks[:6]:
        if s.applicable:
            unit = "bp" if s.factor.value.endswith("BPS") else "%" if s.factor.value in ("EQUITY", "FX_PCT", "COMMODITY_PCT") else ""
            val = f"{s.scaled_value:+.0f} bp" if unit == "bp" else f"{s.scaled_value * 100:+.1f}%" if unit == "%" else f"{s.scaled_value:g}"
            out.append(_r(C.STRESS_SHOCK, K.SCENARIO_ASSUMPTION, f"{s.factor.value.replace('_', ' ').title()} {val} ({s.scope.value.lower()}{f', {s.sector}' if s.sector else ''}), an assumption", "propagation.generated_scenario",
                          value=s.scaled_value, ref=run.run_id, at=at))
    out += attribution_reasons(flow.attribution, source="stress.attribution", ref=run.run_id, at=at, label="this scenario")
    if gen.history_check is not None:
        for c in gen.history_check.checks[:3]:
            if c.checkable and c.horizons:
                h = c.horizons[-1]
                share = f"{h.share_as_extreme * 100:.1f}% of {h.horizon_sessions}-session windows" if h.share_as_extreme is not None else "beyond every observed window"
                out.append(_r(C.STRESS_HISTORY, K.HISTORICAL_OBSERVATION, f"{c.factor.replace('_', ' ').title()} shock: a move this large occurred in {share} since {gen.history_check.first_session[:4]} (a historical frequency, not a probability)",
                              "stress.history_check", value=h.share_as_extreme, ref=run.run_id, at=at))
    return finish(Subject.STRESS, event_id=None, signal_id=sig, headline=f"Why the portfolio moves {flow.attribution.pnl_pct * 100:+.1f}% under this scenario (a simulation, not a prediction)",
                  level=None, reasons=out, material=True,
                  limitations=["The shock sizes are assumptions; the contributions are the engine's arithmetic on them, not causal attribution.", "Historical context describes how unusual a shock size has been, not that it will happen."])


def lab(result: LabResult) -> Explanation:
    at = result.created_at
    out: list[Reason] = []
    for a in result.assumptions:
        kind = K.SCENARIO_ASSUMPTION
        out.append(_r(C.STRESS_SHOCK, kind, f"{a.description} — {'EventShock configured this assumption' if a.origin == 'ASSESSED' else 'a SCENARIO ASSUMPTION you chose'}"
                      + (f"; it reached {a.positions_reached} position{'s' if a.positions_reached != 1 else ''} ({a.share_reached * 100:.0f}% of the book)" if a.origin == "USER" and a.reach == "APPLIED" else "; it reached nothing" if a.reach == "NOT_REACHED" else ""),
                      "scenario_lab.assumption", value=a.value, ref=result.scenario_id, at=at, detail=a.note))
    if result.attribution is not None:
        out += attribution_reasons(result.attribution, source="stress.attribution", ref=result.scenario_id, at=at, label=f"“{result.name}”")
    if result.exposure_priors:
        out.append(_r(C.STRESS_SHOCK, K.SCENARIO_ASSUMPTION, "Oil exposure was estimated from sector priors: " + ", ".join(f"{p.sector} {p.sensitivity:.2f}" for p in result.exposure_priors) + " (a judgement prior you switched on)",
                      "scenario_lab.exposure_prior", ref=result.scenario_id, at=at))
    if result.status != "COMPLETED":
        out.append(_r(C.STRESS_NOT_RUN, K.PRODUCT_RULE, result.reason or "no position carries the exposure", "scenario_lab", ref=result.scenario_id, at=at))
    pct = f"{result.result.summary.pnl_pct * 100:+.2f}%" if result.result and result.result.summary else "no change"
    return finish(Subject.LAB, event_id=None, signal_id=None, headline=f"Why “{result.name}” moves the portfolio {pct} (a hypothetical, not a prediction)", level=None, reasons=out,
                  material=result.status == "COMPLETED", limitations=result.limitations)


def reverse(r: ReverseStressResult) -> Explanation:
    at = r.scenario.created_at if r.scenario else None
    out = [_r(C.REVERSE_TARGET, K.PRODUCT_RULE, f"Target {r.target_pct:+.1f}% of the portfolio; achieved {r.achieved_pct:+.2f}% ({r.status.replace('_', ' ').lower()})" if r.achieved_pct is not None
              else f"Target {r.target_pct:+.1f}%: no basket shock reaches this portfolio", "scenario_lab.reverse", value=r.target_pct, unit="percent", ref=r.reverse_id, at=at),
           _r(C.REVERSE_METHOD, K.PRODUCT_RULE, f"Method {r.search_method.replace('_', ' ').lower()}: {r.search_config.get('objective')}. {r.evaluations} engine evaluations, tolerance {r.search_config.get('tolerance_pp')} pp",
              "scenario_lab.reverse", value=r.search_method, ref=r.reverse_id, at=at)]
    for s in r.required_shocks:
        out.append(_r(C.REVERSE_SHOCK, K.SCENARIO_ASSUMPTION, f"{s.label}: uses {s.share_of_bound * 100:.0f}% of its configured limit — a SCENARIO ASSUMPTION found by the search", "scenario_lab.reverse", value=s.value, ref=r.reverse_id, at=at))
    for b in r.bounds:
        if not b.used and b.note:
            out.append(_r(C.REVERSE_BOUND, K.PRODUCT_RULE, f"{b.label} not used: {b.note}", "scenario_lab.reverse", ref=r.reverse_id, at=at))
    if r.binding_bounds:
        out.append(_r(C.REVERSE_BINDING, K.PRODUCT_RULE, f"The bounds cannot reach the target: {', '.join(r.binding_bounds)} are already at their limit", "scenario_lab.reverse", ref=r.reverse_id, at=at))
    if r.scenario and r.scenario.attribution is not None:
        out += attribution_reasons(r.scenario.attribution, source="stress.attribution", ref=r.reverse_id, at=at, label="this combination")
    return finish(Subject.REVERSE, event_id=None, signal_id=None, headline=f"Why these shocks reach {r.target_pct:+.1f}% (a hypothetical stress analysis)", level=r.status, reasons=out, material=True,
                  limitations=r.limitations)


__all__ = ["priority", "visibility", "change", "stress", "lab", "reverse", "ExplanationError", "VERSION"]


# ----------------------------------------------------------------------------------------------------------------------------------- market
def market(v: EventMarketView) -> Explanation:
    """Why this market was (or was not) matched, what it moved, and how that reads beside EventShock's assessment. Every reason is an EXTERNAL_MARKET_OBSERVATION or a product rule."""
    lim = ["An external market's price is an observation by independent participants; it is never an input to any EventShock number and is not ground truth.",
           "The theme-to-series mapping and every threshold are judgement priors, unvalidated."]
    m = v.match
    if v.availability == "UNAVAILABLE" or m is None:
        return finish(Subject.MARKET, event_id=v.event_id, signal_id=v.signal_id, headline="External market data unavailable", level=None, reasons=[], material=False,
                      availability="UNAVAILABLE", unavailable_reason=v.reason or "external market data unavailable", limitations=lim)
    out = [_r(C.MARKET_MATCH, K.PRODUCT_RULE, f"Match status {m.status.value.replace('_', ' ').lower()}: {m.reason}", "markets.match", value=m.status.value, ref=m.theme_id, at=v.as_of)]
    for g in m.event_gates:
        out.append(_r(C.MARKET_MATCH, K.PRODUCT_RULE, f"{g.id.replace('_', ' ').lower()} gate {'passed' if g.passed else 'failed'}: {g.detail}", "markets.match", value=g.id, ref=m.theme_id, at=v.as_of))
    o = m.market
    if o is not None:
        pr = "not priced" if o.probability is None else f"{o.probability * 100:.0f}%"
        out.append(_r(C.MARKET_MOVE, K.EXTERNAL_MARKET_OBSERVATION, f"{o.question}: {pr}" + ("" if o.probability_change_pp is None else f" ({o.probability_change_pp:+.1f} pp since the previous observation)")
                      + (" · SYNTHETIC FIXTURE, not market data" if o.synthetic else ""), o.source, value=o.probability, unit="probability", ref=o.market_id, at=o.observed_at))
    i = v.interpretation
    if i is not None:
        out.append(_r(C.MARKET_INTERPRETATION, K.PRODUCT_RULE, f"{i.text} ({i.reason})", "markets.interpret", value=i.code.value, ref=i.rule, at=v.as_of))
    return finish(Subject.MARKET, event_id=v.event_id, signal_id=v.signal_id, headline=("An external market is matched to this event" if o is not None else "No external market is matched to this event"),
                  level=m.status.value, reasons=out, material=True, limitations=lim)
