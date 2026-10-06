"""Builds the state of one event at one moment from the existing layers. Nothing is inferred here: every field is read from the grouping, the assessment, the event
intelligence, the propagation layer or the stress engine, and a missing layer leaves its fields empty (never a guessed value).

The state at ``as_of`` uses only report clusters published at or before ``as_of`` (the layers below are future-invariant), so replaying the same clock gives the same state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..decision.config import MonitorCfg
from ..domain import Portfolio
from ..intelligence.grouping import Event, Node
from ..intelligence.model import Availability, EventIntelligence
from ..intelligence.service import IntelligenceService
from ..propagation.service import PropagationService
from .models import RANK_MATERIALITY, EventState, fingerprint_of


@dataclass
class Built:
    state: EventState
    intel: EventIntelligence | None


class StateBuilder:
    def __init__(self, cfg: MonitorCfg, *, intelligence: Callable[[], IntelligenceService | None], propagation: Callable[[], PropagationService | None],
                 assessments: Any) -> None:  # AssessmentService | None
        self._cfg = cfg
        self._intel = intelligence
        self._prop = propagation
        self._assess = assessments
        self._floor = RANK_MATERIALITY[cfg.track_min_materiality]

    # ------------------------------------------------------------------------------------------------------------------------------ light
    def _severity(self, node: Node) -> tuple[float | None, str | None, str | None]:
        if self._assess is None:
            return None, None, None
        a = self._assess.assess(node.signal)
        if a.severity is None:
            return None, None, a.reading.event_type
        return float(a.severity.score), a.severity.band, a.reading.event_type

    def visible(self, event: Event, as_of: datetime) -> list[Node]:
        return [n for n in event.nodes if n.time <= as_of]

    def lead(self, nodes: list[Node], portfolio: Portfolio | None = None) -> tuple[Node, float | None, str | None, str | None]:
        """The cluster with the highest severity. Ties go to the one that matters most to the portfolio, then the earliest, then the lowest id: the choice never depends on arrival order."""
        scored = [(n, *self._severity(n)) for n in sorted(nodes, key=lambda n: (n.time, n.signal.id))]
        top = max((-1.0 if sev is None else sev) for _, sev, _, _ in scored)
        tied = [t for t in scored if (-1.0 if t[1] is None else t[1]) == top]
        best = tied[0]
        prop = self._prop()
        if len(tied) > 1 and prop is not None:
            best = max(tied, key=lambda t: RANK_MATERIALITY.get(prop.materiality(t[0].signal, portfolio).level, -1))  # max() keeps the first (earliest) of equals
        return best[0], best[1], best[2], best[3]

    # ------------------------------------------------------------------------------------------------------------------------------- full
    def build(self, event: Event, as_of: datetime, portfolio: Portfolio | None, *, force_full: bool = False) -> Built | None:
        """The state of ``event`` at ``as_of``; None when the event does not exist yet, its report times are assigned by the replay (never placed on a timeline), or the
        intelligence layer is not running. ``force_full`` computes every field even for an event below the tracking floor (the event-memory view asks for that)."""
        intel_svc, prop = self._intel(), self._prop()
        if intel_svc is None or not event.trusted:
            return None
        nodes = self.visible(event, as_of)
        if not nodes:
            return None
        lead, sev, band, etype = self.lead(nodes, portfolio)
        mat_level = share = pf_id = None
        if prop is not None:
            mat = prop.materiality(lead.signal, portfolio)
            mat_level, share, pf_id = mat.level, mat.reached_share, mat.portfolio_id
        tracked = (sev is not None and sev >= self._cfg.track_min_severity) or (mat_level is not None and RANK_MATERIALITY.get(mat_level, -1) >= self._floor)
        if not tracked and not force_full:
            return Built(self._assemble(event, nodes, lead, sev, band, etype, as_of, None, tracked=False, mat_level=mat_level, share=share, pf_id=pf_id,
                                        stress=(None, None, None)), None)
        try:
            intel = intel_svc.for_signal(event.anchor.signal, as_of=as_of, portfolio=portfolio, include_stress=False)
        except ValueError:  # as_of precedes the event's first report
            return None
        stress = self._stress(prop, lead, portfolio, sev) if prop is not None else (None, None, None)
        return Built(self._assemble(event, nodes, lead, sev, band, etype, as_of, intel, tracked=tracked, mat_level=mat_level, share=share, pf_id=pf_id, stress=stress), intel)

    def _stress(self, prop: PropagationService, lead: Node, portfolio: Portfolio | None, sev: float | None) -> tuple[str | None, float | None, str | None]:
        gen = prop.scenario(lead.signal, portfolio)
        if gen.scenario is None or gen.availability is not Availability.AVAILABLE:
            return gen.availability.value, None, None
        res = prop.portfolio_stress(lead.signal, portfolio, store=False)    # a derived view never changes which runs exist
        run = res.run
        if run is None or run.summary is None:
            return gen.availability.value, None, None
        return "COMPLETED", run.summary.pnl_pct, run.run_id

    def _assemble(self, event: Event, nodes: list[Node], lead: Node, sev: float | None, band: str | None, etype: str | None, as_of: datetime,
                  intel: EventIntelligence | None, *, tracked: bool, mat_level: str | None, share: float | None, pf_id: str | None,
                  stress: tuple[str | None, float | None, str | None]) -> EventState:
        reports = [r for n in nodes for r in n.reports if r.published_at <= as_of]
        life = intel.lifecycle.state.value if intel is not None and intel.lifecycle.state is not None else None
        values: dict[str, Any] = dict(
            event_id=event.id, anchor_signal_id=event.anchor.signal.id, lead_signal_id=lead.signal.id, headline=lead.signal.document.headline, as_of=as_of, tracked=tracked,
            member_count=len(nodes), report_count=len(reports) if intel is None else intel.group.report_count,
            independent_sources=sum(1 for r in _independent(reports)) if intel is None else intel.group.independent_sources,
            first_seen=min((r.published_at for r in reports), default=None), last_seen=max((r.published_at for r in reports), default=None),
            event_type=etype, scope_type=intel.scope.scope_type.value if intel is not None else "UNKNOWN", scope_value=intel.scope.scope_value if intel is not None else None,
            severity=sev, severity_band=band, lifecycle=life,
            evidence_tier=intel.evidence.evidence_strength.tier if intel is not None else "INSUFFICIENT",
            conflict=intel.contradiction.state.value if intel is not None else "NO_CONFLICT",
            velocity_per_hour=intel.velocity.velocity_per_hour if intel is not None else None,
            portfolio_id=pf_id, materiality=mat_level, exposure_share=share, stress_status=stress[0], stress_pnl_pct=stress[1], stress_run_id=stress[2],
            clock_trusted=event.trusted)
        values["fingerprint"] = fingerprint_of(values)
        return EventState(**values)


def _independent(reports: list) -> list:  # noqa: ANN001
    seen: set[str] = set()
    out = []
    for r in sorted(reports, key=lambda r: (r.published_at, r.id)):
        if r.relation not in ("SYNDICATED", "NEAR_DUPLICATE") and r.domain and r.domain not in seen:
            seen.add(r.domain)
            out.append(r)
    return out
