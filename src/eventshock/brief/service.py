"""``BriefService``: gathers the structured outputs one event's brief reads (state, intelligence, materiality, mapping graph, stress, analogues, external market, memory) and hands them to the builder.
It computes nothing itself. A side-car that is absent or fails is a labelled gap in its section, never an error and never an invented value."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from ..domain import Portfolio
from ..monitor.models import Mode
from ..monitor.service import MonitorService
from ..store import CHANNEL_REPLAY
from .builder import BriefInputs, build_brief, to_markdown
from .models import Brief

log = logging.getLogger(__name__)


class BriefService:
    def __init__(self, *, monitor: MonitorService, propagation: Callable[[], object | None], analogues: Callable[[], object | None], markets: Callable[[], object | None],
                 clock: Callable[[], datetime]) -> None:
        self._monitor = monitor
        self._prop = propagation
        self._analogues = analogues
        self._markets = markets
        self._clock = clock

    def _moment(self, ev, cycle: int | None) -> tuple[datetime, int | None, Mode]:  # noqa: ANN001
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

    def build(self, ident: str, portfolio: Portfolio | None = None, *, cycle: int | None = None) -> Brief:
        ev = self._monitor.resolve_event(ident)
        as_of, k, mode = self._moment(ev, cycle)
        built = self._monitor.builder.build(ev, as_of, portfolio, force_full=True)
        if built is None:
            raise LookupError("the event does not exist yet at this moment, or its report times were assigned by the replay and cannot be ordered")
        state = built.state
        lead = next((n.signal for n in ev.nodes if n.signal.id == state.lead_signal_id), ev.anchor.signal)
        prop = self._prop()
        mat = graph = stress = None
        if prop is not None:
            mat = self._try("materiality", lambda: prop.materiality(lead, portfolio))
            graph = self._try("graph", lambda: prop.graph(lead, portfolio))
            stress = self._try("stress", lambda: prop.portfolio_stress(lead, portfolio, store=False))
        an = self._analogues()
        analogues = self._try("analogues", lambda: an.for_signal(lead)) if an is not None else None
        mk = self._markets()
        market = self._try("market", lambda: mk.view(ev.id, portfolio, cycle=k)) if mk is not None else None
        memory = self._try("memory", lambda: self._monitor.memory(ev.id, portfolio))
        pf_name = (mat.portfolio_name if mat is not None else None) or (stress.materiality.portfolio_name if stress is not None else None)
        return build_brief(BriefInputs(event_id=ev.id, mode=mode.value, cycle=k, as_of=as_of, portfolio_id=state.portfolio_id, portfolio_name=pf_name, state=state, intel=built.intel, lead=lead,
                                       materiality=mat, graph=graph, stress=stress, analogues=analogues, market=market, memory=memory))

    @staticmethod
    def _try(name: str, fn):  # noqa: ANN001, ANN205
        """A side-car that fails leaves a labelled gap in its section; it never breaks the brief."""
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("brief: %s unavailable (%s: %s)", name, type(exc).__name__, exc)
            return None

    def markdown(self, brief: Brief) -> str:
        return to_markdown(brief)
