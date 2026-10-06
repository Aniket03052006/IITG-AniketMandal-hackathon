"""The brief builder: structured outputs in, fixed-order sections out. Every sentence is a template over fields (money and percentages are formatted from the numbers) and cites the source it was
read from. Where an input is absent the section says so in a fixed sentence; nothing is invented to fill a gap. A statement without a resolvable source raises ``BriefError``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..decision.models import LABEL_EXTERNAL_MARKET, LABEL_HISTORICAL, LABEL_SIMULATION, ObservationKind
from ..domain import RiskSignal
from ..intelligence.model import EventIntelligence
from ..markets.models import EventMarketView
from ..monitor.models import EventMemory, EventState
from ..propagation.models import AutoStressResult, PortfolioMateriality, PropagationGraph
from ..retrieval.model import AnalogueSet
from .models import (
    MARKET_UNAVAILABLE,
    NO_ANALOGUE,
    NO_MARKET,
    NOT_RUN,
    SECTIONS,
    VERSION,
    Brief,
    BriefSection,
    SourceRef,
    Statement,
)

K = ObservationKind


class BriefError(ValueError):
    """A statement had no source to cite: a bug, never a brief."""


@dataclass
class BriefInputs:
    event_id: str
    mode: str
    cycle: int | None
    as_of: datetime | None
    portfolio_id: str | None
    portfolio_name: str | None
    state: EventState
    intel: EventIntelligence | None
    lead: RiskSignal
    materiality: PortfolioMateriality | None
    graph: PropagationGraph | None
    stress: AutoStressResult | None
    analogues: AnalogueSet | None
    market: EventMarketView | None
    memory: EventMemory | None


def pct(x: float | None, digits: int = 1, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    sign = "+" if signed and x > 0 else "−" if x < 0 else ""
    return f"{sign}{abs(x) * 100:.{digits}f}%"


def num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:,.0f}"


def words(code: str | None) -> str:
    return (code or "unknown").replace("_", " ").lower()


class _Writer:
    """Collects sections and the sources they cite, and refuses a statement that cites nothing known."""

    def __init__(self, i: BriefInputs) -> None:
        self.i = i
        self.sources: dict[str, SourceRef] = {}
        self.sections: list[BriefSection] = []
        self._cur: list[Statement] = []
        lead = i.lead
        sid = lead.id
        at = i.as_of
        self._src("report", K.SOURCE_EVENT, f"The lead report: {lead.document.source}", f"/api/signals/{sid}", sid, lead.document.published_at)
        self._src("state", K.EVENTSHOCK_ASSESSMENT, "EventShock's state of the event at this moment", f"/api/events/{i.event_id}/timeline", i.event_id, at)
        self._src("brief", K.PRODUCT_RULE, "The brief's own templates and fixed sentences", None, None, None)
        if i.intel is not None:
            self._src("intelligence", K.EVENTSHOCK_ASSESSMENT, "Event intelligence (scope, evidence, novelty, velocity, conflicts, lifecycle)", f"/api/signals/{sid}/intelligence", sid, i.intel.as_of)
        if i.materiality is not None:
            self._src("materiality", K.EVENTSHOCK_ASSESSMENT, "Portfolio materiality (an exposure-by-severity lookup)", f"/api/signals/{sid}/propagation", sid, at)
        if i.graph is not None:
            self._src("graph", K.EVENTSHOCK_ASSESSMENT, "The event-to-portfolio mapping graph", f"/api/signals/{sid}/propagation", sid, at)
        if i.stress is not None:
            self._src("scenario", K.SCENARIO_ASSUMPTION, "The generated scenario and its shock sizes (configured judgement priors)", f"/api/signals/{sid}/propagation", sid, at)
            self._src("stress", K.SCENARIO_ASSUMPTION, f"The stress run ({LABEL_SIMULATION})", f"/api/signals/{sid}/propagation", i.stress.run.run_id if i.stress.run else None, at)
            if i.stress.attribution is not None:
                self._src("attribution", K.SCENARIO_ASSUMPTION, "Stress attribution (reconciled to the run's total)", f"/api/signals/{sid}/propagation", i.stress.attribution.run_id, at)
        if i.analogues is not None:
            self._src("analogues", K.HISTORICAL_OBSERVATION, "Historical analogues (retrieved precedent; hindsight outcomes)", f"/api/events/{i.event_id}/analogues", sid, None)
        if i.market is not None:
            self._src("market", K.EXTERNAL_MARKET_OBSERVATION, "External market view (a prediction market; never an input)", f"/api/events/{i.event_id}/external-markets", i.event_id, i.market.as_of)
        if i.memory is not None:
            self._src("memory", K.EVENTSHOCK_ASSESSMENT, "Event memory (reports classified by rule)", f"/api/events/{i.event_id}/timeline", i.event_id, i.memory.as_of)

    def _src(self, id: str, kind: ObservationKind, label: str, endpoint: str | None, ref_id: str | None, as_of: datetime | None) -> None:  # noqa: A002
        self.sources[id] = SourceRef(id=id, kind=kind, label=label, endpoint=endpoint, ref_id=ref_id, as_of=as_of)

    # --------------------------------------------------------------------------------------------------------------------------- statements
    def say(self, text: str, kind: ObservationKind, *refs: str) -> None:
        refs_ = [r for r in refs if r in self.sources] or []
        if not refs_:
            raise BriefError(f"statement without a source: {text[:80]!r} (cited {list(refs)})")
        self._cur.append(Statement(text=text, kind=kind, source_refs=list(dict.fromkeys(refs_))))

    def fallback(self, text: str, *refs: str) -> None:
        self.say(text, K.PRODUCT_RULE, *refs, "brief")

    def close(self, sid: str, title: str, availability: str = "AVAILABLE") -> None:
        if not self._cur:
            raise BriefError(f"section {sid} produced no statement: it must state its fallback")
        self.sections.append(BriefSection(id=sid, title=title, availability=availability, statements=self._cur))
        self._cur = []


def _lead_status(i: BriefInputs) -> str:
    s = i.state
    return f"severity {s.severity:.0f}/10 ({s.severity_band})" if s.severity is not None else "not scored as a market event"


def build_brief(i: BriefInputs) -> Brief:
    w = _Writer(i)
    s, intel, mat, graph, stress = i.state, i.intel, i.materiality, i.graph, i.stress
    title = dict(SECTIONS)
    label = (intel.event.event_label if intel is not None else None) or words(s.event_type)
    book = i.portfolio_name or "the portfolio"
    run = stress.run if stress is not None else None
    ran = run is not None and run.summary is not None

    # 1 ------------------------------------------------------------------------------------------------------------------ executive summary
    w.say(f"“{s.headline}” is read as {label}; scope {words(s.scope_type)}{f' ({s.scope_value})' if s.scope_value else ''}; {_lead_status(i)}. Severity is a transparent triage scale, not an outcome-calibrated probability.",
          K.EVENTSHOCK_ASSESSMENT, "state", "report")
    if mat is not None:
        w.say(f"Relevance to {book}: {mat.level} ({mat.summary}).", K.EVENTSHOCK_ASSESSMENT, "materiality")
    else:
        w.fallback("Portfolio relevance was not assessed for this event.", "state")
    if ran:
        w.say(f"Under the generated scenario the modeled P&L is {pct(run.summary.pnl_pct, 2, True)} of the book ({LABEL_SIMULATION}).", K.SCENARIO_ASSUMPTION, "stress")
    else:
        w.fallback(NOT_RUN, "stress" if "stress" in w.sources else "state")
    w.close("EXECUTIVE_SUMMARY", title["EXECUTIVE_SUMMARY"])

    # 2 ---------------------------------------------------------------------------------------------------------------------- what happened
    d = i.lead.document
    w.say(f"{d.source} reported on {d.published_at:%Y-%m-%d %H:%M} UTC: “{d.headline}”.", K.SOURCE_EVENT, "report")
    w.say(f"The event has {s.report_count} report(s) in {s.member_count} cluster(s) from {s.independent_sources} independent source(s)"
          + (f", first seen {s.first_seen:%Y-%m-%d %H:%M} UTC and last seen {s.last_seen:%Y-%m-%d %H:%M} UTC." if s.first_seen and s.last_seen else ", with report times that cannot be ordered."), K.EVENTSHOCK_ASSESSMENT, "state")
    if i.memory is not None and i.memory.update_counts:
        parts = ", ".join(f"{n} {words(k)}" for k, n in sorted(i.memory.update_counts.items()))
        w.say(f"Reports classified by rule: {parts}.", K.EVENTSHOCK_ASSESSMENT, "memory")
    w.close("WHAT_HAPPENED", title["WHAT_HAPPENED"])

    # 3 ----------------------------------------------------------------------------------------------------------------------- current status
    if intel is not None and intel.lifecycle.state is not None:
        lc = intel.lifecycle
        w.say(f"Lifecycle: {lc.state.value.lower()}" + (f" since {lc.since:%Y-%m-%d %H:%M} UTC" if lc.since else "") + ".", K.EVENTSHOCK_ASSESSMENT, "intelligence")
    else:
        w.fallback("Lifecycle is unavailable" + (f": {intel.lifecycle.reason}" if intel is not None and intel.lifecycle.reason else " (the report times were assigned by the replay or no intelligence layer ran).") , "intelligence" if intel is not None else "state")
    if intel is not None:
        n = intel.novelty
        w.say(f"Novelty: {n.label.lower()}." if n.availability.value == "AVAILABLE" else f"Novelty is unavailable: {n.reason}", K.EVENTSHOCK_ASSESSMENT, "intelligence")
        v = intel.velocity
        w.say(f"Coverage velocity: {v.velocity_per_hour:.2f} independent source(s) per hour ({v.source_growth})." if v.velocity_per_hour is not None else f"Coverage velocity is unavailable: {v.reason or 'too few timed reports'}.",
              K.EVENTSHOCK_ASSESSMENT, "intelligence")
    w.say(f"Evidence tier {s.evidence_tier.lower()}; conflict state {words(s.conflict)}; as of {i.as_of:%Y-%m-%d %H:%M} UTC ({i.mode}).", K.EVENTSHOCK_ASSESSMENT, "state")
    w.close("CURRENT_STATUS", title["CURRENT_STATUS"])

    # 4 ------------------------------------------------------------------------------------------------------------------------- why it matters
    if mat is not None and mat.why:
        for line in mat.why[:5]:
            w.say(line.rstrip(".") + ".", K.EVENTSHOCK_ASSESSMENT, "materiality")
        w.say(f"Mapping basis: {words(mat.mapping_basis.value)}.", K.PRODUCT_RULE, "materiality")
    else:
        w.fallback(mat.reason if mat is not None and mat.reason else "No defensible link between this event and the portfolio's holdings was found.", "materiality" if mat is not None else "state")
    w.close("WHY_IT_MATTERS", title["WHY_IT_MATTERS"], "AVAILABLE" if mat is not None and mat.why else "UNAVAILABLE")

    # 5 ----------------------------------------------------------------------------------------------------------------------------- evidence
    if intel is not None:
        e = intel.evidence
        w.say(f"{e.source_count} report(s), {e.independent_sources} independent source(s), {e.unique_domains} domain(s), {e.syndicated_copies} syndicated copy(ies); evidence strength {e.evidence_strength.tier.lower()} "
              f"(rule {e.evidence_strength.rule}). Evidence strength is about corroboration, not model confidence.", K.EVENTSHOCK_ASSESSMENT, "intelligence")
        if e.authoritative_supported:
            w.say(f"{e.authoritative_sources} source(s) on the authoritative list" + (f": {', '.join(e.authoritative_domains[:4])}." if e.authoritative_domains else "."), K.EVENTSHOCK_ASSESSMENT, "intelligence")
        else:
            w.say("Whether any source is authoritative is not known for these domains (0 here means not known, not none).", K.PRODUCT_RULE, "intelligence")
        for sp in intel.scope.scope_evidence[:3]:
            if sp.quote:
                w.say(f"Text evidence for the {sp.dimension.replace('_', ' ')} read: “{sp.quote}”.", K.SOURCE_EVENT, "intelligence", "report")
        for mc in e.model_confidence[:3]:
            if mc.value is not None:
                w.say(f"Model confidence ({mc.stage}, {mc.status}): {mc.value:.2f}, kept apart from evidence strength.", K.EVENTSHOCK_ASSESSMENT, "intelligence")
    else:
        w.fallback("Evidence detail is unavailable: no event-intelligence layer ran for this event.", "state")
    w.close("EVIDENCE", title["EVIDENCE"], "AVAILABLE" if intel is not None else "UNAVAILABLE")

    # 6 ---------------------------------------------------------------------------------------------------------------------------- conflicts
    if intel is not None and intel.contradiction.availability.value in ("AVAILABLE", "PARTIAL"):
        c = intel.contradiction
        if c.conflicts:
            for cf in c.conflicts[:3]:
                w.say(f"{cf.axis_label}: {cf.reason} ({cf.side_a.source}: {cf.side_a.polarity}; {cf.side_b.source}: {cf.side_b.polarity}).", K.EVENTSHOCK_ASSESSMENT, "intelligence")
        else:
            w.say("No contradictory claims were found among the reports (claims are read from a closed vocabulary, never from tone).", K.EVENTSHOCK_ASSESSMENT, "intelligence")
        for sc in c.sequential_changes[:2]:
            w.say(f"A change of state over time, not a contradiction: {sc.reason}", K.EVENTSHOCK_ASSESSMENT, "intelligence")
    else:
        why = intel.contradiction.reason if intel is not None else None
        w.fallback(f"Conflict detection is unavailable{': ' + why if why else ' for this event.'}", "intelligence" if intel is not None else "state")
    w.close("CONFLICTS", title["CONFLICTS"])

    # 7 ------------------------------------------------------------------------------------------------------------------ affected entities/sectors
    if intel is not None and (intel.affected.entities or intel.affected.sectors or intel.affected.regions or intel.affected.risk_factors):
        a = intel.affected
        for en in a.entities[:5]:
            w.say(f"{en.name} ({en.role}, {'resolved' if en.resolved else 'not resolved to an entity'}{f', {en.ticker}' if en.ticker else ''}); identified by {en.origin.lower()}.", K.EVENTSHOCK_ASSESSMENT, "intelligence")
        if a.sectors:
            w.say("Sectors: " + "; ".join(f"{x.sector} ({x.basis})" for x in a.sectors[:5]) + ".", K.EVENTSHOCK_ASSESSMENT, "intelligence")
        if a.regions:
            w.say("Regions: " + ", ".join(a.regions[:6]) + ".", K.EVENTSHOCK_ASSESSMENT, "intelligence")
        if a.risk_factors:
            w.say("Risk factors: " + "; ".join(f"{x.factor} ({x.origin.lower()}: an assumption, not a measured exposure)" for x in a.risk_factors[:5]) + ".", K.EVENTSHOCK_ASSESSMENT, "intelligence")
    else:
        w.fallback("No affected entity, sector, region or risk factor could be identified from the text; none is guessed.", "intelligence" if intel is not None else "state")
    w.close("AFFECTED", title["AFFECTED"])

    # 8 ----------------------------------------------------------------------------------------------------------------------- portfolio exposure
    if mat is not None and graph is not None and graph.availability.value != "UNAVAILABLE":
        w.say(f"{mat.level} materiality for {book}: the event reaches {pct(graph.reached_share)} of the book ({pct(graph.direct_share)} directly, {pct(graph.indirect_share)} indirectly).", K.EVENTSHOCK_ASSESSMENT, "materiality", "graph")
        w.say(f"Of the reached value, {pct(graph.evidenced_share)} rests on evidence in the text or the holdings and {pct(graph.assumed_share)} on a configured assumption alone.", K.EVENTSHOCK_ASSESSMENT, "graph")
        for r in graph.reached[:5]:
            w.say(f"{r.name} ({r.asset_type.lower()}, {r.sector}): {pct(r.share)} of the book, {words(r.basis.value)}.", K.EVENTSHOCK_ASSESSMENT, "graph")
        if graph.not_reached:
            w.say("Mapped but not held: " + "; ".join(graph.not_reached[:3]) + ".", K.EVENTSHOCK_ASSESSMENT, "graph")
    else:
        w.fallback(mat.reason if mat is not None and mat.reason else "The portfolio exposure to this event could not be determined.", "materiality" if mat is not None else "state")
    w.close("PORTFOLIO_EXPOSURE", title["PORTFOLIO_EXPOSURE"], "AVAILABLE" if graph is not None and graph.availability.value != "UNAVAILABLE" else "UNAVAILABLE")

    # 9 ------------------------------------------------------------------------------------------------------------------------------ propagation
    if graph is not None and graph.availability.value != "UNAVAILABLE":
        from collections import Counter
        st = Counter(e.status.value for e in graph.edges)
        w.say(f"{len(graph.edges)} mapping edge(s): " + ", ".join(f"{n} {words(k)}" for k, n in sorted(st.items())) + ". An edge is a mapping, not a proven causal link.", K.EVENTSHOCK_ASSESSMENT, "graph")
        for f in graph.active_factors[:5]:
            how = {"ENGINE": "modelled by the stress engine", "PROXY": "approximated through sector proxies", "NOT_MODELLED": "not modelled by the stress engine"}.get(f.modelled, words(f.modelled))
            w.say(f"Risk factor {f.label}: {how}; active because {'the text uses its vocabulary' if f.origin == 'TEXT' else 'it is assumed for this class of event'}.", K.EVENTSHOCK_ASSESSMENT, "graph")
    else:
        w.fallback(graph.reason if graph is not None and graph.reason else "No defensible propagation path from this event to the portfolio exists, so none is drawn.", "graph" if graph is not None else "state")
    w.close("PROPAGATION", title["PROPAGATION"], "AVAILABLE" if graph is not None and graph.availability.value != "UNAVAILABLE" else "UNAVAILABLE")

    # 10 ---------------------------------------------------------------------------------------------------------------------------------- stress
    if stress is not None and stress.scenario.availability.value in ("AVAILABLE", "PARTIAL") and stress.scenario.scenario is not None:
        sc = stress.scenario
        w.say(f"{LABEL_SIMULATION}: the scenario “{sc.scenario.name}” ({len(sc.scenario.shocks)} shock(s)) is a hypothetical, not a forecast.", K.SCENARIO_ASSUMPTION, "scenario")
        if ran:
            sm = run.summary
            w.say(f"Modeled value {num(sm.baseline_value)} → {num(sm.stressed_value)} (P&L {num(sm.pnl)}, {pct(sm.pnl_pct, 2, True)}).", K.SCENARIO_ASSUMPTION, "stress")
        else:
            w.say(f"The stress run did not complete: {words(run.status.value) if run else 'not run'}{(' — ' + run.reason) if run and run.reason else ''}.", K.SCENARIO_ASSUMPTION, "stress")
    else:
        why = stress.scenario.reason if stress is not None and stress.scenario.reason else NOT_RUN
        failed = [g for g in (stress.scenario.gates if stress is not None else []) if not g.passed]
        w.fallback(f"SCENARIO UNAVAILABLE: {why}" + (f" (gate {failed[0].label.lower()}: {failed[0].detail})" if failed else ""), "scenario" if stress is not None else "state")
    w.close("STRESS", title["STRESS"], "AVAILABLE" if ran else "UNAVAILABLE")

    # 11 ------------------------------------------------------------------------------------------------------------------------------ top drivers
    att = stress.attribution if stress is not None else None
    if att is not None and att.drivers.rows:
        for r in att.drivers.rows[:3]:
            w.say(f"{r.label}: {num(r.delta)} ({pct(r.share_of_total, 0)} of the modeled change).", K.SCENARIO_ASSUMPTION, "attribution")
        for t in att.tables:
            if t.dimension in ("sector", "risk_factor") and t.rows:
                r = t.rows[0]
                w.say(f"Largest {t.label.lower()}: {r.label} ({num(r.delta)}).", K.SCENARIO_ASSUMPTION, "attribution")
        w.say("Every attribution table reconciles to the run's total within a cent.", K.PRODUCT_RULE, "attribution")
    else:
        w.fallback("No stress run, so there is nothing to attribute.", "stress" if stress is not None else "state")
    w.close("TOP_DRIVERS", title["TOP_DRIVERS"], "AVAILABLE" if att is not None and att.drivers.rows else "UNAVAILABLE")

    # 12 ------------------------------------------------------------------------------------------------------------------------ historical context
    an = i.analogues
    if an is not None and an.status == "OK" and an.aggregate is not None:
        g = an.aggregate
        w.say(f"{LABEL_HISTORICAL}: {g.reading} ({g.n_used} of {g.n_stories} distinct past stories; median move {g.car_pct_q50:+.2f}%).", K.HISTORICAL_OBSERVATION, "analogues")
        w.say("Precedent about other events, shown for context; it never changes the severity score.", K.PRODUCT_RULE, "analogues")
    elif an is not None:
        w.say(f"{NO_ANALOGUE if an.status == 'NO_RELIABLE_ANALOGUE' else 'Historical analogues are unavailable.'} {an.reason}", K.HISTORICAL_OBSERVATION, "analogues")
    else:
        w.fallback("Historical analogues are unavailable in this profile.", "state")
    w.close("HISTORICAL_CONTEXT", title["HISTORICAL_CONTEXT"], "AVAILABLE" if an is not None and an.status == "OK" else "UNAVAILABLE")

    # 13 ------------------------------------------------------------------------------------------------------------------------- external market
    mk = i.market
    if mk is None or mk.availability == "UNAVAILABLE":
        w.say(MARKET_UNAVAILABLE, K.EXTERNAL_MARKET_OBSERVATION, "market" if mk is not None else "brief")
    elif mk.match is not None and mk.match.market is not None:
        o = mk.match.market
        pr = "not priced" if o.probability is None else f"{o.probability * 100:.0f}%"
        w.say(f"{LABEL_EXTERNAL_MARKET}: “{o.question}” was priced at {pr}" + (f" ({o.probability_change_pp:+.1f} pp since the previous observation)" if o.probability_change_pp is not None else "")
              + f" at {o.observed_at:%Y-%m-%d %H:%M} UTC" + (" — a SYNTHETIC FIXTURE, not market data." if o.synthetic else "."), K.EXTERNAL_MARKET_OBSERVATION, "market")
        if mk.interpretation is not None:
            w.say(mk.interpretation.text, K.EXTERNAL_MARKET_OBSERVATION, "market")
        w.say("An external market price is an observation, never an input to any EventShock number, and not ground truth.", K.PRODUCT_RULE, "market")
    else:
        w.say(NO_MARKET + (f" ({mk.match.reason})" if mk.match is not None else ""), K.EXTERNAL_MARKET_OBSERVATION, "market")
    w.close("EXTERNAL_MARKET_VIEW", title["EXTERNAL_MARKET_VIEW"], "AVAILABLE" if mk is not None and mk.availability == "AVAILABLE" and mk.match is not None and mk.match.market is not None else "UNAVAILABLE")

    # 14 ---------------------------------------------------------------------------------------------------------------------------- assumptions
    if stress is not None and stress.scenario.origins:
        from collections import Counter
        cnt = Counter(o.source for o in stress.scenario.origins)
        w.say("Scenario shocks: " + ", ".join(f"{n} {words(k)}" for k, n in sorted(cnt.items())) + f"; every size is a configured judgement prior ({LABEL_SIMULATION}).", K.SCENARIO_ASSUMPTION, "scenario")
    if graph is not None and graph.assumed_share > 0:
        w.say(f"{pct(graph.assumed_share)} of the reached value is reached only through a configured transmission edge: an assumption.", K.SCENARIO_ASSUMPTION, "graph")
    w.say("The severity scorecard is a heuristic triage scale (HEURISTIC_UNCALIBRATED against realised moves), not a validated forecast.", K.PRODUCT_RULE, "state")
    if mat is not None:
        w.say("Materiality levels and the gates that generate a scenario are configured judgement priors.", K.PRODUCT_RULE, "materiality")
    w.close("ASSUMPTIONS", title["ASSUMPTIONS"])

    # 15 ---------------------------------------------------------------------------------------------------------------------------- uncertainty
    if intel is not None and intel.abstentions:
        for ab in [a for a in intel.abstentions if not (ran and a.field == "portfolio stress")][:5]:       # the brief runs the stress itself
            w.say(f"{ab.field.replace('_', ' ')}: {ab.state.lower().replace('_', ' ')} — {ab.reason}", K.EVENTSHOCK_ASSESSMENT, "intelligence")
    if not s.clock_trusted:
        w.say("Report times were assigned by the replay and cannot be ordered, so velocity, lifecycle and novelty are not stated.", K.PRODUCT_RULE, "state")
    for lim in (intel.limitations[:3] if intel is not None else []):
        w.say(lim, K.PRODUCT_RULE, "intelligence")
    w.say("A change of any configured prior (see the assumptions above) would change the figures here; none is validated against outcomes.", K.PRODUCT_RULE, "brief")
    w.close("UNCERTAINTY", title["UNCERTAINTY"])

    # 16 ---------------------------------------------------------------------------------------------------------------------- what to monitor
    rules: list[tuple[str, str]] = []
    if s.conflict in ("POSSIBLE_CONFLICT", "CONFLICTED"):
        rules.append(("M1", "Whether the contradictory claims are resolved by a later report: the conflict state is open."))
    if s.evidence_tier in ("INSUFFICIENT", "WEAK"):
        rules.append(("M2", f"Corroboration from additional independent sources: the evidence tier is {s.evidence_tier.lower()}."))
    if s.lifecycle in ("DEVELOPING", "ESCALATING"):
        rules.append(("M3", f"Whether coverage continues: the lifecycle is {s.lifecycle.lower()}; resolution is read only from explicit evidence, not from falling volume."))
    if s.materiality in ("HIGH", "CRITICAL"):
        rules.append(("M4", f"The portfolio's exposure and the modeled scenario P&L: materiality is {s.materiality.lower()}."))
    if mk is not None and mk.availability == "AVAILABLE" and mk.match is not None and mk.match.market is not None:
        rules.append(("M5", "The matched external market's probability and whether it diverges from EventShock's assessment."))
    if not rules:
        rules.append(("M0", "No open condition triggers a monitoring rule; the event is tracked and any change will be reported."))
    for rid, text in rules:
        w.say(f"{text} (rule {rid})", K.PRODUCT_RULE, "state", "brief")
    w.close("WHAT_TO_MONITOR", title["WHAT_TO_MONITOR"])

    return Brief(version=VERSION, event_id=i.event_id, signal_id=i.lead.id, headline=s.headline, mode=i.mode, as_of=i.as_of, cycle=i.cycle, portfolio_id=i.portfolio_id,
                 portfolio_name=i.portfolio_name, sections=w.sections, sources=list(w.sources.values()),
                 labels=[LABEL_SIMULATION if ran else "NO SCENARIO RUN", LABEL_EXTERNAL_MARKET, LABEL_HISTORICAL])


def to_markdown(b: Brief) -> str:
    """Deterministic Markdown: the same brief always renders to the same bytes."""
    idx = {s.id: n + 1 for n, s in enumerate(b.sources)}
    out = [f"# Executive risk brief: {b.headline}", "",
           f"*{b.mode} · as of {b.as_of:%Y-%m-%d %H:%M} UTC · portfolio: {b.portfolio_name or 'default'} · brief {VERSION}*", "", f"> {b.note}", ""]
    for n, sec in enumerate(b.sections, 1):
        out += [f"## {n}. {sec.title}", ""]
        for st in sec.statements:
            out.append(f"- {st.text} *[{st.kind.value}]* " + "".join(f"[{idx[r]}]" for r in st.source_refs))
        out.append("")
    out += ["## Sources", ""] + [f"{idx[s.id]}. {s.label}" + (f" — `{s.endpoint}`" if s.endpoint else "") for s in b.sources]
    return "\n".join(out) + "\n"
