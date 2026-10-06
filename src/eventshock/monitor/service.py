"""``MonitorService``: what changed, for REPLAY (a deterministic clock over the frozen signals) and LIVE (the live overlay, diffed after every poll).

REPLAY is a pure function: the cycle grid is fixed by configuration and the replay clock, the state of an event at a cycle uses only reports published by then, and
nothing is written anywhere, so two runs (and a run after a side-car rebuild) give the same answer. LIVE keeps the last state of every event it has seen and appends
a change only when a configured threshold is crossed; recording the same change twice is a no-op, so repeated polling of unchanged data produces nothing.

An article never becomes a risk of its own: it belongs to the event the grouping assigned it to, and at most it changes that event's state.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..decision.config import DecisionConfig
from ..decision.models import ObservationKind, ProvenanceRef
from ..domain import Portfolio
from ..intelligence.grouping import Event, mark_independence
from ..intelligence.model import EventIntelligence
from ..intelligence.service import IntelligenceService
from ..store import CHANNEL_REPLAY, CombinedSignalRepository
from .diff import ORDER, diff_states
from .memory import classify_reports
from .models import (
    ChangeDraft,
    ChangeSet,
    ChangeType,
    EventMemory,
    EventState,
    HistoryPoint,
    MemoryItem,
    Mode,
    MonitorCycle,
    MonitorStatus,
    PortfolioImpact,
    RiskChange,
    SupportingEvidence,
)
from .state import Built, StateBuilder
from .store import ChangeLog, StateStore

LABELS = [
    "A change is a difference between two states of the same event, detected by a configured threshold (a judgement prior, unvalidated).",
    "Severity, lifecycle, evidence tier and conflict are EventShock's own assessment; stress is a simulation under an illustrative scenario, never a forecast.",
    "REPLAY reproduces the same changes every run; LIVE needs the live feed (or a capture replayed as if live).",
]
LIMITATIONS = [
    "In the frozen replay, each report cluster's severity, scope and scenario are fixed; what moves between cycles is how many reports and sources an event has, its lifecycle, "
    "its evidence tier and its conflicts. Exposure and stress changes appear mainly when a new report cluster joins an event or the portfolio or an adjustment changes.",
    "Events whose report times were assigned by the replay (social posts) are never placed on a timeline: their order would be invented.",
    "Thresholds decide when a change is worth reporting; they do not measure how much it matters.",
]

_MEMO = 64
log = logging.getLogger("eventshock.monitor")


@dataclass
class CycleStates:
    states: dict[str, EventState]
    built: int
    untracked: int
    truncated: bool
    excluded_untrusted: int
    intel: dict[str, EventIntelligence] = field(default_factory=dict)


def _step_floor(t: datetime, step_s: float) -> datetime:
    return datetime.fromtimestamp(math.floor(t.timestamp() / step_s) * step_s, UTC)


class MonitorService:
    def __init__(self, cfg: DecisionConfig, *, signals: CombinedSignalRepository, intelligence: Callable[[], IntelligenceService | None], builder: StateBuilder,
                 changelog: ChangeLog, states: StateStore, live_status: Callable[[], tuple[bool, str | None, str | None]] | None = None,
                 clock: Callable[[], datetime] | None = None, adjust_version: Callable[[], str] | None = None) -> None:
        self.cfg = cfg
        self._signals = signals
        self._intel = intelligence
        self._builder = builder
        self._log = changelog
        self._states = states
        self._live_status = live_status or (lambda: (False, None, None))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._adjust_version = adjust_version or (lambda: "default")
        self._lock = threading.RLock()
        self._memo: OrderedDict[tuple, CycleStates] = OrderedDict()
        self._cycles: tuple[tuple, list[MonitorCycle]] | None = None

    # -------------------------------------------------------------------------------------------------------------------------------- helpers
    def _svc(self) -> IntelligenceService:
        svc = self._intel()
        if svc is None:
            raise LookupError("the monitor needs the event-intelligence layer (replay profile)")
        return svc

    def _copy_relations(self) -> frozenset[str]:
        return frozenset(self._svc().cfg.sources.copy_relations)

    @staticmethod
    def _pf_key(pf: Portfolio | None) -> str:
        return "default" if pf is None else pf.content_hash()

    # -------------------------------------------------------------------------------------------------------------------------------- cycles
    def cycles(self) -> list[MonitorCycle]:
        """The REPLAY clock: a fixed grid from the first trusted report to the replay clock. Deterministic: nothing here reads the wall clock."""
        idx = self._svc().index()
        key = (self._signals.seq, len(self._signals.base._signals), self.cfg.monitor.replay_step_hours)  # noqa: SLF001
        with self._lock:
            if self._cycles is not None and self._cycles[0] == key:
                return self._cycles[1]
        times = [n.time for ev in idx.events if ev.trusted for n in ev.nodes if self._signals.channel_of(n.signal.id) == CHANNEL_REPLAY]
        end = self._signals.as_of
        out: list[MonitorCycle] = []
        if times:
            step = self.cfg.monitor.replay_step_hours * 3600.0
            first = min(times)
            grid = []
            t = _step_floor(first, step) + timedelta(seconds=step)  # the first boundary after the first report
            while t < end:
                grid.append(t)
                t += timedelta(seconds=step)
            grid.append(end)
            grid = grid[-self.cfg.monitor.replay_max_cycles:]
            out = [MonitorCycle(index=i, at=at, baseline=i == 0) for i, at in enumerate(grid)]
        with self._lock:
            self._cycles = (key, out)
        return out

    # ---------------------------------------------------------------------------------------------------------------------- public read API
    @property
    def builder(self) -> StateBuilder:
        return self._builder

    def replay_states(self, cycle: int | None, portfolio: Portfolio | None = None) -> tuple[MonitorCycle, CycleStates]:
        """The tracked events' states at a REPLAY cycle (default: the last), with the intelligence they were built from."""
        cycles = self.cycles()
        if not cycles:
            raise LookupError("the replay has no trusted-clock reports to place on a timeline")
        k = len(cycles) - 1 if cycle is None else cycle
        if not 0 <= k < len(cycles):
            raise ValueError(f"cycle must be between 0 and {len(cycles) - 1}")
        return cycles[k], self._states_at(cycles[k].at, portfolio, replay_only=True)

    def live_states(self) -> dict[str, EventState]:
        """The last state the LIVE monitor saw of each event."""
        return self._states.get_all()

    def logged_changes(self) -> list[RiskChange]:
        return self._log.all()

    # ----------------------------------------------------------------------------------------------------------------------- states of a cycle
    def _states_at(self, as_of: datetime, pf: Portfolio | None, *, replay_only: bool) -> CycleStates:
        idx = self._svc().index()
        key = (as_of.isoformat(), self._pf_key(pf), self._adjust_version(), self._signals.seq, replay_only)
        with self._lock:
            hit = self._memo.get(key)
            if hit is not None:
                self._memo.move_to_end(key)
                return hit
        states: dict[str, EventState] = {}
        intel: dict[str, EventIntelligence] = {}
        untracked = excluded = 0
        for ev in idx.events:
            if not ev.trusted:
                excluded += 1
                continue
            if replay_only and any(self._signals.channel_of(n.signal.id) != CHANNEL_REPLAY for n in ev.nodes):
                continue
            b = self._builder.build(ev, as_of, pf)
            if b is None:
                continue
            if not b.state.tracked:
                untracked += 1
                continue
            states[ev.id] = b.state
            if b.intel is not None:
                intel[ev.id] = b.intel
        truncated = False
        cap = self.cfg.monitor.max_tracked_events
        if len(states) > cap:
            keep = sorted(states, key=lambda e: (-(states[e].severity or 0.0), e))[:cap]
            states = {e: states[e] for e in sorted(keep)}
            truncated = True
        out = CycleStates(states=states, built=len(states), untracked=untracked, truncated=truncated, excluded_untrusted=excluded, intel={e: intel[e] for e in states if e in intel})
        with self._lock:
            self._memo[key] = out
            while len(self._memo) > _MEMO:
                self._memo.popitem(last=False)
        return out

    # ----------------------------------------------------------------------------------------------------------------------------- change build
    @staticmethod
    def _change_id(event_id: str, ctype: ChangeType, prev: EventState | None, curr: EventState, at: datetime) -> str:
        raw = "|".join([event_id, ctype.value, prev.fingerprint if prev else "", curr.fingerprint, at.isoformat()])
        return "chg_" + hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _evidence(self, draft: ChangeDraft, prev: EventState | None, curr: EventState, intel: EventIntelligence | None) -> list[SupportingEvidence]:
        out: list[SupportingEvidence] = []
        if intel is None:
            return out
        since = prev.as_of if prev is not None else None
        fresh = [r for r in intel.group.reports if since is None or r.published_at > since][:3]
        if draft.change_type in (ChangeType.NEW_EVENT, ChangeType.EVENT_UPDATED, ChangeType.EVIDENCE_STRENGTHENED, ChangeType.EVIDENCE_WEAKENED):
            for r in (fresh or intel.group.reports[:2]):
                out.append(SupportingEvidence(kind="REPORT", text=r.headline, at=r.published_at, report_id=r.id, signal_id=r.signal_id, source=r.source))
        if draft.change_type in (ChangeType.EVENT_ESCALATED, ChangeType.EVENT_DE_ESCALATED, ChangeType.LIFECYCLE_CHANGED):
            for t in intel.lifecycle.transitions:
                if since is None or t.at > since:
                    out.append(SupportingEvidence(kind="LIFECYCLE_TRANSITION", text=t.evidence_quote or t.rule_text, at=t.at,
                                                  report_id=t.evidence_report_ids[0] if t.evidence_report_ids else None, rule=t.rule))
            if draft.rule.startswith("SEVERITY"):
                out.append(SupportingEvidence(kind="SCORE", text=f"Lead report: {curr.headline} (severity {curr.severity})", signal_id=curr.lead_signal_id))
        if draft.change_type in (ChangeType.CONFLICT_APPEARED, ChangeType.CONFLICT_RESOLVED):
            for cf in intel.contradiction.conflicts[:2]:
                for side in (cf.side_a, cf.side_b):
                    out.append(SupportingEvidence(kind="CONFLICT", text=side.evidence_span.quote, at=side.published_at, report_id=side.report_id, signal_id=side.signal_id,
                                                  source=side.source, rule=cf.axis))
        if draft.change_type in (ChangeType.PORTFOLIO_EXPOSURE_CHANGED, ChangeType.STRESS_CHANGED):
            out.append(SupportingEvidence(kind="SCORE", text=f"Lead report: {curr.headline}", signal_id=curr.lead_signal_id))
        return out

    def _make_change(self, draft: ChangeDraft, prev: EventState | None, curr: EventState, at: datetime, mode: Mode, cycle: int | None,
                     intel: EventIntelligence | None) -> RiskChange:
        evidence = self._evidence(draft, prev, curr, intel)
        prov = [ProvenanceRef(kind=ObservationKind.EVENTSHOCK_ASSESSMENT, source="monitor.diff", ref_id=curr.event_id, as_of=at)]
        prov += [ProvenanceRef(kind=ObservationKind.SOURCE_EVENT, source=e.source or "report", ref_id=e.report_id, as_of=e.at) for e in evidence if e.kind == "REPORT"][:3]
        if draft.change_type is ChangeType.STRESS_CHANGED:
            prov.append(ProvenanceRef(kind=ObservationKind.SCENARIO_ASSUMPTION, source="propagation.generated_scenario", ref_id=curr.stress_run_id, as_of=at))
        impact = PortfolioImpact(
            portfolio_id=curr.portfolio_id, materiality_previous=prev.materiality if prev else None, materiality_current=curr.materiality,
            exposure_share_previous=prev.exposure_share if prev else None, exposure_share_current=curr.exposure_share,
            stress_pnl_pct_previous=prev.stress_pnl_pct if prev else None, stress_pnl_pct_current=curr.stress_pnl_pct) if curr.portfolio_id is not None else None
        return RiskChange(
            change_id=self._change_id(curr.event_id, draft.change_type, prev, curr, at), event_id=curr.event_id, change_type=draft.change_type, mode=mode, cycle=cycle, at=at,
            headline=curr.headline, summary=draft.summary, rule=draft.rule, previous=prev, current=curr, changed_fields=draft.fields, supporting_evidence=evidence,
            portfolio_impact=impact, provenance=prov)

    # ------------------------------------------------------------------------------------------------------------------------------ REPLAY
    def replay_changes(self, *, cycle: int | None = None, window: int = 1, portfolio: Portfolio | None = None, types: set[ChangeType] | None = None) -> ChangeSet:
        cycles = self.cycles()
        if not cycles:
            return self._empty(Mode.REPLAY, "UNAVAILABLE", "the replay has no trusted-clock reports to place on a timeline", portfolio, cycle, window)
        k = len(cycles) - 1 if cycle is None else cycle
        if not 0 <= k < len(cycles):
            raise ValueError(f"cycle must be between 0 and {len(cycles) - 1}")
        window = max(1, window)
        lo = max(1, k - window + 1)  # cycle 0 is the baseline: it reports no changes
        changes: list[RiskChange] = []
        last = self._states_at(cycles[k].at, portfolio, replay_only=True)
        for j in range(lo, k + 1):
            prev = self._states_at(cycles[j - 1].at, portfolio, replay_only=True)
            curr = last if j == k else self._states_at(cycles[j].at, portfolio, replay_only=True)
            for eid in sorted(curr.states):
                for d in diff_states(prev.states.get(eid), curr.states[eid], self.cfg.monitor):
                    if types is None or d.change_type in types:
                        changes.append(self._make_change(d, prev.states.get(eid), curr.states[eid], cycles[j].at, Mode.REPLAY, j, curr.intel.get(eid)))
        changes.sort(key=lambda c: (-(c.cycle or 0), -(c.current.severity or 0.0), c.event_id, ORDER.index(c.change_type)))
        return self._set(Mode.REPLAY, changes, last, portfolio, k, window, cycles[lo - 1].at if lo >= 1 else cycles[0].at, cycles[k].at)

    def _set(self, mode: Mode, changes: list[RiskChange], last: CycleStates | None, portfolio: Portfolio | None, cycle: int | None, window: int,
             from_at: datetime | None, to_at: datetime | None) -> ChangeSet:
        cap = self.cfg.monitor.max_changes_returned
        counts: dict[str, int] = {}
        for c in changes:
            counts[c.change_type.value] = counts.get(c.change_type.value, 0) + 1
        return ChangeSet(
            mode=mode, availability="AVAILABLE", portfolio_id=(portfolio.portfolio_id if portfolio is not None else None), cycle=cycle, window=window, from_at=from_at, to_at=to_at,
            tracked_events=last.built if last else 0, untracked_events=last.untracked if last else 0, excluded_untrusted_clock=last.excluded_untrusted if last else 0,
            truncated=len(changes) > cap or bool(last and last.truncated), changes=changes[:cap], counts=dict(sorted(counts.items())), labels=LABELS, limitations=LIMITATIONS)

    def _empty(self, mode: Mode, availability: str, reason: str, portfolio: Portfolio | None, cycle: int | None, window: int) -> ChangeSet:
        return ChangeSet(mode=mode, availability=availability, reason=reason, portfolio_id=(portfolio.portfolio_id if portfolio is not None else None), cycle=cycle, window=window,
                         from_at=None, to_at=None, tracked_events=0, untracked_events=0, excluded_untrusted_clock=0, truncated=False, changes=[], counts={}, labels=LABELS,
                         limitations=LIMITATIONS)

    # -------------------------------------------------------------------------------------------------------------------------------- LIVE
    def observe(self, now: datetime | None = None, portfolio: Portfolio | None = None) -> list[RiskChange]:
        """Diff the live overlay's events against the last states seen and log what changed. Idempotent: observing unchanged data records nothing."""
        now = now or self._clock()
        svc = self._intel()
        if svc is None:
            return []
        idx = svc.index()
        prev = self._states.get_all()
        curr: dict[str, EventState] = {}
        changes: list[RiskChange] = []
        for ev in idx.events:
            if not ev.trusted or all(self._signals.channel_of(n.signal.id) == CHANNEL_REPLAY for n in ev.nodes):
                continue
            b: Built | None = self._builder.build(ev, now, portfolio)
            if b is None:
                continue
            curr[ev.id] = b.state
            for d in diff_states(prev.get(ev.id), b.state, self.cfg.monitor):
                changes.append(self._make_change(d, prev.get(ev.id), b.state, now, Mode.LIVE, None, b.intel))
        fresh = self._log.append(changes)
        if curr:
            self._states.put_all({**prev, **curr})
        return fresh

    def live_changes(self, *, since: datetime | None = None, types: set[ChangeType] | None = None, portfolio: Portfolio | None = None) -> ChangeSet:
        enabled, state, _ = self._live_status()
        items = [c for c in self._log.all() if (since is None or c.at > since) and (types is None or c.change_type in types)]
        items.sort(key=lambda c: (-c.at.timestamp(), -(c.current.severity or 0.0), c.event_id, ORDER.index(c.change_type)))
        reason = None if enabled else "the live feed is off (start with `make run-live` or `make run-capture`); REPLAY works without it"
        cs = self._set(Mode.LIVE, items, None, portfolio, None, 1, since, items[0].at if items else None)
        cs.availability = "AVAILABLE" if enabled or items else "UNAVAILABLE"
        cs.reason = reason if not items else None
        cs.tracked_events = len(self._states.get_all())
        return cs

    def warm(self, last: int = 6) -> None:
        """Compute the states of the last ``last`` cycles ahead of the first request (a cold cycle costs seconds: the grouping, assessment and mapping of every event). A failure is
        logged and the monitor simply computes on demand."""
        try:
            cycles = self.cycles()
            for c in cycles[-last:]:
                self._states_at(c.at, None, replay_only=True)
        except Exception:  # noqa: BLE001 (warming is an optimisation, never a reason to stop the server)
            log.exception("monitor warm-up failed")

    # ------------------------------------------------------------------------------------------------------------------------------- status
    def status(self, mode: Mode = Mode.REPLAY) -> MonitorStatus:
        enabled, state, source = self._live_status()
        cycles = self.cycles() if self._intel() is not None else []
        live_ok = enabled and state in ("OK", "IDLE")
        if mode is Mode.LIVE:
            st = "OFF" if not enabled else ("OK" if live_ok else "DEGRADED")
            reason = None if enabled else "the live feed is off; REPLAY works without it"
            if enabled and not live_ok:
                reason = f"the live feed is {state}: changes already detected are kept; nothing new arrives until it recovers"
        else:
            st, reason = ("OK", None) if cycles else ("UNAVAILABLE", "no replay clock: the replay has no trusted-clock reports")
        return MonitorStatus(mode=mode, available=st in ("OK", "DEGRADED"), state=st, reason=reason, live_enabled=enabled, live_state=state, live_source_mode=source,
                             replay_cycles=len(cycles), replay_step_hours=self.cfg.monitor.replay_step_hours, replay_first=cycles[0].at if cycles else None,
                             replay_last=cycles[-1].at if cycles else None, tracked_floor=f"severity >= {self.cfg.monitor.track_min_severity:g} or portfolio materiality >= {self.cfg.monitor.track_min_materiality}",
                             changes_logged=len(self._log), labels=LABELS, limitations=LIMITATIONS)

    # ------------------------------------------------------------------------------------------------------------------------------- memory
    def resolve_event(self, ident: str) -> Event:
        idx = self._svc().index()
        ev = idx.event(ident) or idx.event_of(ident)
        if ev is None:
            raise LookupError(f"no event or signal {ident!r}")
        return ev

    def memory(self, ident: str, portfolio: Portfolio | None = None) -> EventMemory:
        ev = self.resolve_event(ident)
        sig_ids = ev.signal_ids
        live = any(self._signals.channel_of(i) != CHANNEL_REPLAY for i in sig_ids)
        mode = Mode.LIVE if live else Mode.REPLAY
        base = dict(event_id=ev.id, anchor_signal_id=ev.anchor.signal.id, headline=ev.anchor.signal.document.headline, mode=mode, signal_ids=sig_ids, labels=LABELS)
        if not ev.trusted:
            return EventMemory(availability="UNAVAILABLE", reason="the report times of this event were assigned by the replay, not published by the source: its order, "
                               "lifecycle and history cannot be followed", as_of=None, portfolio_id=None, clock_trusted=False, current=None, items=[], history=[],
                               update_counts={}, limitations=LIMITATIONS, **base)
        last_report = max(r.published_at for r in ev.reports())
        final = max(self._clock(), last_report) if live else last_report
        b = self._builder.build(ev, final, portfolio, force_full=True)
        if b is None or b.intel is None:
            return EventMemory(availability="UNAVAILABLE", reason="the event could not be assessed at its latest report", as_of=final, portfolio_id=None, clock_trusted=True,
                               current=None, items=[], history=[], update_counts={}, limitations=LIMITATIONS, **base)
        intel = b.intel
        reports = mark_independence([r for r in ev.reports() if r.published_at <= final], set(self._copy_relations()))
        classified = classify_reports(reports, intel.lifecycle.transitions, self.cfg.memory, self._copy_relations())
        items: list[MemoryItem] = []
        for c in classified:
            r = c.report
            items.append(MemoryItem(
                at=r.published_at, kind="REPORT", observation=ObservationKind.SOURCE_EVENT.value, label=r.headline, detail=c.detail, update_kind=c.kind, rule=c.rule,
                signal_id=r.signal_id, report_id=r.id, source=r.source, independent=r.independent,
                provenance=[ProvenanceRef(kind=ObservationKind.SOURCE_EVENT, source=r.source, ref_id=r.id, as_of=r.published_at)]))
        for t in intel.lifecycle.transitions:
            items.append(MemoryItem(
                at=t.at, kind="LIFECYCLE", observation=ObservationKind.EVENTSHOCK_ASSESSMENT.value, label=f"{(t.from_state.value if t.from_state else 'start')} -> {t.to_state.value}",
                detail=t.rule_text + (f' Cue: "{t.evidence_quote}".' if t.evidence_quote else ""), rule=t.rule,
                report_id=t.evidence_report_ids[0] if t.evidence_report_ids else None,
                provenance=[ProvenanceRef(kind=ObservationKind.EVENTSHOCK_ASSESSMENT, source="intelligence.lifecycle", ref_id=ev.id, as_of=t.at)]))
        history = self._history(ev, portfolio, final, mode)
        prev_state: EventState | None = None
        kinds = {ChangeType.EVENT_ESCALATED: "SEVERITY", ChangeType.EVENT_DE_ESCALATED: "SEVERITY", ChangeType.EVIDENCE_STRENGTHENED: "EVIDENCE", ChangeType.EVIDENCE_WEAKENED: "EVIDENCE",
                 ChangeType.CONFLICT_APPEARED: "EVIDENCE", ChangeType.CONFLICT_RESOLVED: "EVIDENCE", ChangeType.PORTFOLIO_EXPOSURE_CHANGED: "PORTFOLIO", ChangeType.STRESS_CHANGED: "STRESS"}
        for _, st in history:
            if prev_state is not None:
                for d in diff_states(prev_state, st, self.cfg.monitor):
                    k = kinds.get(d.change_type)
                    if k is None:
                        continue
                    obs = ObservationKind.SCENARIO_ASSUMPTION if k == "STRESS" else ObservationKind.EVENTSHOCK_ASSESSMENT
                    items.append(MemoryItem(at=st.as_of, kind=k, observation=obs.value, label=d.change_type.value.replace("_", " ").title(), detail=d.summary, rule=d.rule,
                                            signal_id=st.lead_signal_id, provenance=[ProvenanceRef(kind=obs, source=f"monitor.{k.lower()}", ref_id=ev.id, as_of=st.as_of)]))
            prev_state = st
        items.sort(key=lambda i: (i.at or datetime.min.replace(tzinfo=UTC), {"REPORT": 0, "LIFECYCLE": 1}.get(i.kind, 2), i.report_id or "", i.label))
        counts: dict[str, int] = {}
        for c in classified:
            counts[c.kind.value] = counts.get(c.kind.value, 0) + 1
        pts = [HistoryPoint(cycle=cy, at=st.as_of, severity=st.severity, lifecycle=st.lifecycle, evidence_tier=st.evidence_tier, conflict=st.conflict, materiality=st.materiality,
                            exposure_share=st.exposure_share, stress_pnl_pct=st.stress_pnl_pct, report_count=st.report_count, independent_sources=st.independent_sources)
               for cy, st in history]
        return EventMemory(availability="AVAILABLE", as_of=final, portfolio_id=b.state.portfolio_id, clock_trusted=True, current=b.state, items=items, history=pts,
                           update_counts=dict(sorted(counts.items())), limitations=LIMITATIONS, **base)

    def _history(self, ev: Event, portfolio: Portfolio | None, final: datetime, mode: Mode) -> list[tuple[int | None, EventState]]:
        first = min(r.published_at for r in ev.reports())
        pts: list[tuple[int | None, EventState]] = []
        if mode is Mode.REPLAY:
            for c in self.cycles():
                if c.at >= first and c.at <= final:
                    b = self._builder.build(ev, c.at, portfolio, force_full=True)
                    if b is not None:
                        pts.append((c.index, b.state))
        else:
            seen = {s.fingerprint for _, s in pts}
            for ch in sorted((c for c in self._log.all() if c.event_id == ev.id), key=lambda c: c.at):
                if ch.current.fingerprint not in seen:
                    seen.add(ch.current.fingerprint)
                    pts.append((None, ch.current))
        b = self._builder.build(ev, final, portfolio, force_full=True)
        if b is not None and (not pts or pts[-1][1].fingerprint != b.state.fingerprint):
            pts.append((None, b.state))
        return pts
