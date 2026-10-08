"""``ReviewService``: the queue and the decisions. It reads the monitor's event states and writes nothing but its own append-only log."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ..decision.config import DecisionConfig
from ..domain import Portfolio
from ..monitor.digest import RankPart
from ..monitor.models import EventState, Mode
from ..monitor.service import MonitorService
from . import rules
from .models import (
    QueueCounts,
    QueueItem,
    ReviewDecision,
    ReviewDecisionInput,
    ReviewDecisionList,
    ReviewQueue,
    ReviewStatus,
)
from .store import ReviewStore

RANKING = ("Ordered, not scored: portfolio materiality tier, then severity, then the number of rules that fired, then the most recently reported, then id. "
           "Every item shows the values it was ordered by.")
LIMITATIONS = [
    "The rules are judgement priors in configs/decision.yaml, not validated: they decide what a person is shown, never what is true.",
    "The queue reads the events the monitor tracks (severity or portfolio materiality at its floor); an event below that floor is not in it.",
    "A decision is a note. It does not change any model, score, threshold or served output, and it is not ground truth.",
    "An event reopens when its own evidence changes (reports, sources, severity, lifecycle, evidence tier, conflict); a change in the book you read it against does not reopen it.",
]


class ReviewInvalid(ValueError):
    pass


class ReviewService:
    def __init__(self, cfg: DecisionConfig, store: ReviewStore, monitor: MonitorService, *, clock: Callable[[], datetime] | None = None) -> None:
        self.cfg, self._store, self._monitor = cfg, store, monitor
        self._clock = clock or (lambda: datetime.now(UTC))

    # --------------------------------------------------------------------------------------------------------------------------- the queue
    def _pool(self, mode: Mode, portfolio: Portfolio | None) -> tuple[dict[str, EventState], datetime | None, str | None]:
        """The tracked events' states for a mode, the moment they describe, and why there are none."""
        if mode is Mode.REPLAY:
            try:
                cyc, states = self._monitor.replay_states(None, portfolio)
            except LookupError as exc:
                return {}, None, str(exc)
            return states.states, cyc.at, None
        states = self._monitor.live_states()
        if not states:
            st = self._monitor.status(Mode.LIVE)
            return {}, None, st.reason or "the live feed has produced no tracked events; REPLAY works without it"
        return states, self._clock(), None

    def _item(self, st: EventState, decision: ReviewDecision | None, cfg_rules) -> QueueItem | None:  # noqa: ANN001
        reasons = rules.evaluate(st, cfg_rules)
        status, changed = ReviewStatus.OPEN, False
        if decision is not None and decision.status is not ReviewStatus.OPEN:
            if decision.fingerprint == rules.intrinsic_fingerprint(st):
                status = decision.status
            else:
                changed = True
                reasons.append(rules.changed_reason(decision.status.value, decision.created_at))
        if not reasons and status is ReviewStatus.OPEN:
            return None
        order = self.cfg.digest.materiality_order
        tier = st.materiality or "NONE"
        key = [RankPart(name="portfolio materiality tier", value=tier), RankPart(name="severity", value="n/a" if st.severity is None else f"{st.severity:g}"),
               RankPart(name="rules fired", value=str(len(reasons))), RankPart(name="last reported", value=st.last_seen.isoformat() if st.last_seen else "unknown"), RankPart(name="id", value=st.event_id)]
        item = QueueItem(
            event_id=st.event_id, signal_id=st.lead_signal_id, headline=st.headline, scope_type=st.scope_type, scope_value=st.scope_value, severity=st.severity, severity_band=st.severity_band,
            materiality=st.materiality, exposure_share=st.exposure_share, independent_sources=st.independent_sources, report_count=st.report_count, evidence_tier=st.evidence_tier, conflict=st.conflict,
            lifecycle=st.lifecycle, stress_pnl_pct=st.stress_pnl_pct, last_seen=st.last_seen, reasons=reasons, rank_key=key, status=status, changed_since_review=changed, decision=decision)
        item._order = (order.index(tier) if tier in order else len(order), -(st.severity if st.severity is not None else -1.0), -len(reasons), -(st.last_seen.timestamp() if st.last_seen else 0.0), st.event_id)  # type: ignore[attr-defined]
        return item

    def queue(self, *, mode: Mode = Mode.REPLAY, status: str = "OPEN", portfolio: Portfolio | None = None, limit: int | None = None) -> ReviewQueue:
        wanted = status.upper()
        if wanted not in ("OPEN", "REVIEWED", "DISMISSED", "ALL"):
            raise ReviewInvalid("status must be OPEN, REVIEWED, DISMISSED or ALL")
        cap = min(limit or self.cfg.review.max_items, self.cfg.review.max_items)
        pf_id = portfolio.portfolio_id if portfolio is not None else None
        pool, as_of, why = self._pool(mode, portfolio)
        catalogue = rules.rule_catalogue(self.cfg.review)
        if why is not None:
            return ReviewQueue(mode=mode, availability="UNAVAILABLE", reason=why, as_of=None, portfolio_id=pf_id, status_filter=wanted, counts=QueueCounts(open=0, reviewed=0, dismissed=0, in_queue=0, tracked_events=0),
                               matching=0, items=[], ranking=RANKING, rules=catalogue, limitations=LIMITATIONS)
        latest = self._store.latest()
        items = [i for i in (self._item(st, latest.get(st.event_id), self.cfg.review) for st in pool.values()) if i is not None]
        counts = QueueCounts(open=sum(i.status is ReviewStatus.OPEN for i in items), reviewed=sum(i.status is ReviewStatus.REVIEWED for i in items),
                             dismissed=sum(i.status is ReviewStatus.DISMISSED for i in items), in_queue=len(items), tracked_events=len(pool))
        shown = sorted((i for i in items if wanted == "ALL" or i.status.value == wanted), key=lambda i: i._order)  # type: ignore[attr-defined]
        return ReviewQueue(mode=mode, availability="AVAILABLE", as_of=as_of, portfolio_id=pf_id, status_filter=wanted, counts=counts, matching=len(shown), items=shown[:cap], ranking=RANKING, rules=catalogue,
                           limitations=LIMITATIONS)

    # ------------------------------------------------------------------------------------------------------------------------- decisions
    def _state_of(self, event_id: str) -> EventState:
        ev = self._monitor.resolve_event(event_id)  # LookupError for an unknown id: a decision about nothing is refused
        try:
            _, states = self._monitor.replay_states(None, None)
            if ev.id in states.states:
                return states.states[ev.id]
        except LookupError:
            pass
        live = self._monitor.live_states().get(ev.id)
        if live is None:
            raise LookupError(f"event {ev.id} is not tracked by the monitor right now, so there is nothing in the queue to decide")
        return live

    def decide(self, inp: ReviewDecisionInput, *, header_analyst: str | None = None) -> ReviewDecision:
        note = (inp.note or "").strip() or None
        if note is not None and len(note) > self.cfg.review.max_note_chars:
            raise ReviewInvalid(f"a note is at most {self.cfg.review.max_note_chars} characters")
        st = self._state_of(inp.event_id)
        analyst = (inp.analyst_id or header_analyst or "anonymous").strip() or "anonymous"
        return self._store.add(event_id=st.event_id, status=inp.status, note=note, analyst_id=analyst, fingerprint=rules.intrinsic_fingerprint(st), headline=st.headline)

    def history(self, event_id: str | None = None, limit: int | None = None) -> ReviewDecisionList:
        items = self._store.all()
        if event_id:
            try:
                eid = self._monitor.resolve_event(event_id).id
            except LookupError:
                eid = event_id
            items = [d for d in items if d.event_id == eid]
        items = list(reversed(items))  # newest first by the order they were recorded (timestamps can tie, the log's order cannot)
        cap = min(limit or self.cfg.review.max_items, 2000)
        return ReviewDecisionList(total=len(items), items=items[:cap])
