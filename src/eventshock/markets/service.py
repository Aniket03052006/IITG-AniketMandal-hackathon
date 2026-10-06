"""``MarketService``: the external-market view of an event, and its timeline. Read-only and derived: it asks the monitor for the event's state and the provider for observations, matches by
explicit gates, and interprets descriptively. A provider failure degrades to UNAVAILABLE with the reason; it can never break event processing, mapping, stress, replay or the brief."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from ..decision.models import ObservationKind, ProvenanceRef
from ..domain import Portfolio
from ..monitor.models import Mode
from ..monitor.service import MonitorService
from ..store import CHANNEL_REPLAY
from .config import MarketsConfig
from .interpret import CAVEATS, interpret
from .match import (
    EventFeatures,
    ThemeHit,
    best_market,
    build_match,
    evaluate_theme,
    market_gates,
    orientation_of,
)
from .models import (
    EventMarketView,
    ExternalMarketObservation,
    Gate,
    MarketMatch,
    MarketTimeline,
    MarketTimelineItem,
    MatchStatus,
    ProviderState,
)
from .provider import MarketProvider


class MarketService:
    def __init__(self, cfg: MarketsConfig, provider: MarketProvider | None, monitor: MonitorService, *, clock: Callable[[], datetime], state: ProviderState) -> None:
        self.cfg = cfg
        self._provider = provider
        self._monitor = monitor
        self._clock = clock
        self._base_state = state

    # ------------------------------------------------------------------------------------------------------------------------------- state
    def provider_state(self) -> ProviderState:
        try:
            return self._provider.state() if self._provider is not None else self._base_state
        except Exception as exc:  # noqa: BLE001 (a provider must never take the app down)
            return self._base_state.model_copy(update={"state": "UNAVAILABLE", "reason": f"the provider failed: {type(exc).__name__}"})

    # --------------------------------------------------------------------------------------------------------------------------- moment
    def _moment(self, ev, cycle: int | None) -> tuple[datetime, datetime, int | None, Mode]:  # noqa: ANN001
        """(the moment, the previous moment, the replay cycle, the mode)."""
        live = any(self._monitor._signals.channel_of(n.signal.id) != CHANNEL_REPLAY for n in ev.nodes)  # noqa: SLF001
        gap = timedelta(hours=self.cfg.providers.kalshi.previous_gap_hours)
        if live:
            now = self._clock()
            return now, now - gap, None, Mode.LIVE
        cycles = self._monitor.cycles()
        if not cycles:
            raise LookupError("the replay has no trusted-clock reports to place on a timeline")
        k = len(cycles) - 1 if cycle is None else cycle
        if not 0 <= k < len(cycles):
            raise ValueError(f"cycle must be between 0 and {len(cycles) - 1}")
        return cycles[k].at, (cycles[k - 1].at if k >= 1 else cycles[k].at - gap), k, Mode.REPLAY

    # ----------------------------------------------------------------------------------------------------------------------------- features
    @staticmethod
    def _features(ev, state, intel, as_of: datetime) -> EventFeatures:  # noqa: ANN001
        nodes = [n for n in ev.nodes if n.time <= as_of]
        lead = next((n.signal for n in nodes if n.signal.id == state.lead_signal_id), nodes[0].signal)
        text = f"{lead.document.headline}. {lead.document.body or ''}"
        themes: set[str] = set()
        regions: set[str] = set()
        for n in nodes:
            sc = n.signal.scope
            if sc is not None:
                themes |= set(sc.themes)
                regions |= set(sc.regions)
            if n.signal.entity.country and n.signal.entity.entity_id != "UNKNOWN_ENTITY":
                regions.add(n.signal.entity.country)
        scope_type = state.scope_type
        if intel is not None:
            for node in [*intel.scope.scope_path, *intel.scope.secondary]:
                if node.type.value in ("THEME", "MACRO"):
                    themes.add(node.value.replace(" ", "_"))
            if intel.scope.scope_type.value == "MARKET" and intel.scope.scope_value:
                themes.add(intel.scope.scope_value.replace(" ", "_").lower())
        return EventFeatures(event_class=state.event_type if state.event_type not in (None, "NO_EVENT") else None, scope_type=scope_type, scope_themes=themes, regions=regions, text=text)

    # ----------------------------------------------------------------------------------------------------------------------------------- view
    def view(self, ident: str, portfolio: Portfolio | None = None, *, cycle: int | None = None) -> EventMarketView:
        ev = self._monitor.resolve_event(ident)
        as_of, prev_at, k, _ = self._moment(ev, cycle)
        pstate = self.provider_state()
        base = dict(event_id=ev.id, signal_id=ev.anchor.signal.id, as_of=as_of, provider=pstate, caveats=CAVEATS,
                    provenance=[ProvenanceRef(kind=ObservationKind.EXTERNAL_MARKET_OBSERVATION, source=pstate.provider, ref_id=ev.id, as_of=as_of)])
        built = self._monitor.builder.build(ev, as_of, portfolio, force_full=True)
        if built is None:
            return EventMarketView(availability="UNAVAILABLE", reason="the event does not exist yet at this moment, or its report times were assigned by the replay and cannot be ordered", match=None,
                                   interpretation=None, eventshock_severity=None, eventshock_materiality=None, **base)
        st = built.state
        feats = self._features(ev, st, built.intel, as_of)
        if pstate.state != "AVAILABLE" or self._provider is None:
            m = MarketMatch(status=MatchStatus.INSUFFICIENT_DATA, reason=f"external market data is unavailable: {pstate.reason or pstate.state.lower()}", theme_id=None, theme_label=None, event_gates=[], market=None,
                            candidates=[], evidence=[])
            return EventMarketView(availability="UNAVAILABLE", reason="External market data unavailable.", match=m, interpretation=None, eventshock_severity=st.severity,
                                   eventshock_materiality=st.materiality, **base)
        if feats.event_class is None or feats.scope_type == "UNRESOLVED":
            why = "the event is not read as a market event" if feats.event_class is None else "the event's scope is unresolved: it is kept as reported, not matched to a market"
            m = MarketMatch(status=MatchStatus.INSUFFICIENT_DATA, reason=why, theme_id=None, theme_label=None, event_gates=[], market=None, candidates=[], evidence=[])
            return EventMarketView(availability="AVAILABLE", match=m, interpretation=None, eventshock_severity=st.severity, eventshock_materiality=st.materiality, **base)

        hits = [evaluate_theme(t, feats) for t in self.cfg.themes]
        passed = [h for h in hits if h.passed]
        near = max(hits, key=lambda h: (sum(g.passed for g in h.gates), h.theme.id), default=None)
        if not passed:
            m = build_match(None, near, [], None, self.cfg)
            return EventMarketView(availability="AVAILABLE", match=m, interpretation=None, eventshock_severity=st.severity, eventshock_materiality=st.materiality, **base)
        # a theme with strong evidence first, then the configured order
        passed.sort(key=lambda h: (not h.strong, [t.id for t in self.cfg.themes].index(h.theme.id)))
        chosen: tuple[ThemeHit, list[tuple[ExternalMarketObservation, list[Gate]]], int | None] | None = None
        for h in passed:
            cands: list[tuple[ExternalMarketObservation, list[Gate]]] = []
            for series in h.theme.series:
                for o in self._provider.markets(series, as_of):
                    cands.append((o, market_gates(o, as_of, self.cfg)))
            idx = best_market(cands)
            if chosen is None:
                chosen = (h, cands, idx)
            if idx is not None:
                chosen = (h, cands, idx)
                break
        assert chosen is not None
        h, cands, idx = chosen
        empty = None
        if not cands and pstate.observed_from is not None and as_of < pstate.observed_from:
            m0 = MarketMatch(status=MatchStatus.INSUFFICIENT_DATA, reason=f"the provider's observations start {pstate.observed_from:%Y-%m-%d}, after this moment: nothing can be matched without looking ahead",
                             theme_id=h.theme.id, theme_label=h.theme.label, event_gates=h.gates, market=None, candidates=[], evidence=h.evidence)
            return EventMarketView(availability="AVAILABLE", match=m0, interpretation=None, eventshock_severity=st.severity, eventshock_materiality=st.materiality, **base)
        m = build_match(h, None, cands, idx, self.cfg, empty_reason=empty)
        interp = None
        if m.market is not None:
            prev_state = self._monitor.builder.build(ev, prev_at, portfolio, force_full=True) if prev_at >= ev.nodes[0].time else None
            orient, basis = orientation_of(h.theme, m.market.question)
            interp = interpret(m.market, orientation=orient, orientation_basis=basis, severity=st.severity, severity_prev=prev_state.state.severity if prev_state else None,
                               materiality=st.materiality, cfg=self.cfg.interpretation)
        return EventMarketView(availability="AVAILABLE", match=m, interpretation=interp, eventshock_severity=st.severity, eventshock_materiality=st.materiality, **base)

    # -------------------------------------------------------------------------------------------------------------------------------- timeline
    def timeline(self, ident: str, portfolio: Portfolio | None = None, *, cycle: int | None = None) -> MarketTimeline:
        ev = self._monitor.resolve_event(ident)
        mem = self._monitor.memory(ev.id, portfolio)
        v = self.view(ev.id, portfolio, cycle=cycle)
        items: list[MarketTimelineItem] = []
        for i in mem.items:
            if i.at is None:
                continue
            kind = {"SOURCE_EVENT": "SOURCE_EVENT", "SCENARIO_ASSUMPTION": "SCENARIO_ASSUMPTION"}.get(i.observation, "EVENTSHOCK_ASSESSMENT")
            items.append(MarketTimelineItem(at=i.at, kind=kind, label=i.label, detail=i.detail, provenance=i.provenance))
        market_id = None
        reason = None
        if v.match is not None and v.match.market is not None and self._provider is not None and v.as_of is not None:
            market_id = v.match.market.market_id
            first = min((r.published_at for r in ev.reports()), default=v.as_of)
            pts = self._provider.history(market_id, first - timedelta(days=2), v.as_of)
            prev: float | None = None
            for at, p in pts:
                ch = (p - prev) * 100.0 if p is not None and prev is not None else None
                items.append(MarketTimelineItem(at=at, kind="EXTERNAL_MARKET_OBSERVATION", label="External market probability", probability=p, change_pp=ch,
                                                detail=(f"{p * 100:.0f}%" + (f" ({'+' if ch > 0 else '−' if ch < 0 else ''}{abs(ch):.1f} pp)" if ch is not None else "") if p is not None else "not priced")
                                                + f" · {v.match.market.question}", provenance=[ProvenanceRef(kind=ObservationKind.EXTERNAL_MARKET_OBSERVATION, source=v.match.market.source, ref_id=market_id, as_of=at)]))
                if p is not None:
                    prev = p
        elif v.availability == "UNAVAILABLE":
            reason = v.reason
        items.sort(key=lambda t: (t.at, {"SOURCE_EVENT": 0, "EVENTSHOCK_ASSESSMENT": 1, "EXTERNAL_MARKET_OBSERVATION": 2, "SCENARIO_ASSUMPTION": 3}.get(t.kind, 4), t.label))
        kinds: dict[str, int] = {}
        for t in items:
            kinds[t.kind] = kinds.get(t.kind, 0) + 1
        return MarketTimeline(event_id=ev.id, availability=v.availability, reason=reason, market_id=market_id, items=items, kinds=dict(sorted(kinds.items())))


__all__ = ["MarketService"]
