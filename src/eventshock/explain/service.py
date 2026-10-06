"""``ExplainService``: the one place that asks for an explanation. It gathers the structured outputs an explanation needs (the event's state at a moment, its intelligence, its materiality,
its stress run, the watchlists it matches, the changes it had) and hands them to the builders; it computes nothing itself."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ..domain import Portfolio
from ..lab.models import ReverseStressRequest, ScenarioRequest
from ..monitor.models import Mode, RiskChange
from ..monitor.service import MonitorService
from ..store import CHANNEL_REPLAY
from . import builders
from .models import Explanation, Subject


class ExplainService:
    def __init__(self, *, monitor: MonitorService, propagation: Callable[[], object | None], watchlists: Callable[[], object | None], lab: Callable[[], object | None],
                 markets: Callable[[], object | None] = lambda: None, threshold: Callable[[], float], clock: Callable[[], datetime]) -> None:
        self._monitor = monitor
        self._prop = propagation
        self._watch = watchlists
        self._lab = lab
        self._markets = markets
        self._threshold = threshold
        self._clock = clock

    # ------------------------------------------------------------------------------------------------------------------------------- helpers
    def _prop_svc(self):  # noqa: ANN202
        p = self._prop()
        if p is None:
            raise LookupError("explanations need the propagation layer (replay profile)")
        return p

    def _moment(self, ev, cycle: int | None) -> tuple[datetime, int | None, Mode]:  # noqa: ANN001
        """The moment an explanation is about: a REPLAY cycle (default the last), or now for an event the live overlay holds."""
        live = any(self._monitor._signals.channel_of(n.signal.id) != CHANNEL_REPLAY for n in ev.nodes)  # noqa: SLF001
        if live:
            return self._clock(), None, Mode.LIVE
        cycles = self._monitor.cycles()
        if not cycles:
            raise LookupError("the replay has no trusted-clock reports to place on a timeline")
        k = len(cycles) - 1 if cycle is None else cycle
        if not 0 <= k < len(cycles):
            raise ValueError(f"cycle must be between 0 and {len(cycles) - 1}")
        return cycles[k].at, k, Mode.REPLAY

    def _changes(self, event_id: str, k: int | None, pf: Portfolio | None, window: int = 3) -> list[RiskChange]:
        if k is None:
            return [c for c in self._monitor.logged_changes() if c.event_id == event_id][-window:]
        if k < 1:
            return []
        cs = self._monitor.replay_changes(cycle=k, window=window, portfolio=pf)
        return [c for c in cs.changes if c.event_id == event_id]

    # ----------------------------------------------------------------------------------------------------------------------------------- event
    def event(self, ident: str, subject: Subject, portfolio: Portfolio | None = None, *, cycle: int | None = None, change_id: str | None = None) -> Explanation:
        ev = self._monitor.resolve_event(ident)
        as_of, k, mode = self._moment(ev, cycle)
        built = self._monitor.builder.build(ev, as_of, portfolio, force_full=True)
        if built is None:
            return builders.finish(subject, event_id=ev.id, signal_id=ev.anchor.signal.id, headline="Nothing to explain at this moment", level=None, reasons=[], material=False,
                                   availability="UNAVAILABLE", unavailable_reason="the event does not exist yet at this moment, or its report times were assigned by the replay and cannot be ordered",
                                   limitations=[])
        state, intel = built.state, built.intel
        prop = self._prop_svc()
        lead = next((n.signal for n in ev.nodes if n.signal.id == state.lead_signal_id), ev.anchor.signal)
        mat = prop.materiality(lead, portfolio)
        thr = self._threshold()
        if subject is Subject.PRIORITY:
            return builders.priority(state, intel, mat, thr)
        if subject is Subject.VISIBILITY:
            w = self._watch()
            hits = w.event_hits(ev, as_of, mode, portfolio) if w is not None else []
            return builders.visibility(state, intel, mat, thr, watch_hits=hits, changes=self._changes(ev.id, k, portfolio))
        if subject is Subject.CHANGE:
            changes = self._changes(ev.id, k, portfolio, window=12 if k is not None else 50)
            if change_id:
                changes = [c for c in changes if c.change_id == change_id]
                if not changes:
                    raise LookupError(f"no change {change_id!r} for this event")
            if not changes:
                return builders.finish(subject, event_id=ev.id, signal_id=state.lead_signal_id, headline="No recent change to explain", level=None, reasons=[], material=False,
                                       availability="UNAVAILABLE", unavailable_reason="no change was detected for this event in the recent cycles", limitations=[])
            return builders.change(changes[0])
        if subject is Subject.MARKET:
            mk = self._markets()
            if mk is None:
                raise LookupError("external market data is not available in this profile")
            return builders.market(mk.view(ev.id, portfolio, cycle=cycle))
        if subject is Subject.STRESS:
            return builders.stress(prop.portfolio_stress(lead, portfolio, store=False), as_of)
        raise ValueError(f"{subject.value} is not an event explanation")

    # ------------------------------------------------------------------------------------------------------------------------------ lab, reverse
    def lab(self, req: ScenarioRequest, portfolio: Portfolio | None = None) -> Explanation:
        svc = self._lab()
        if svc is None:
            raise LookupError("the scenario lab is not available")
        return builders.lab(svc.run(req, portfolio))

    def reverse(self, req: ReverseStressRequest, portfolio: Portfolio | None = None) -> Explanation:
        svc = self._lab()
        if svc is None:
            raise LookupError("the scenario lab is not available")
        return builders.reverse(svc.reverse(req, portfolio))

