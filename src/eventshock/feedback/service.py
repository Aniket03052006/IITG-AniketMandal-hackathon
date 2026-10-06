"""``FeedbackService``: validates, stores and counts. It reads the monitor only to resolve an event id; it writes nothing but its own append-only log."""

from __future__ import annotations

from ..decision.config import FeedbackCfg
from ..monitor.service import MonitorService
from . import stats
from .models import Feedback, FeedbackInput, FeedbackList, FeedbackStats
from .store import FeedbackStore


class FeedbackInvalid(ValueError):
    pass


class FeedbackService:
    def __init__(self, cfg: FeedbackCfg, store: FeedbackStore, monitor: MonitorService) -> None:
        self.cfg, self._store, self._monitor = cfg, store, monitor

    def submit(self, inp: FeedbackInput, *, header_analyst: str | None = None, portfolio_id: str | None = None) -> Feedback:
        comment = (inp.comment or "").strip() or None
        if comment is not None and len(comment) > self.cfg.max_comment_chars:
            raise FeedbackInvalid(f"a comment is at most {self.cfg.max_comment_chars} characters")
        ev = self._monitor.resolve_event(inp.event_id)           # LookupError for an unknown id: feedback about nothing is refused
        analyst = (inp.analyst_id or header_analyst or "anonymous").strip() or "anonymous"
        return self._store.add(event_id=ev.id, signal_id=inp.event_id if inp.event_id != ev.id else ev.anchor.signal.id, analyst_id=analyst, type_=inp.type, value=inp.value, comment=comment,
                               portfolio_id=portfolio_id, cycle=inp.cycle)

    def list(self, event_id: str | None = None, limit: int | None = None) -> FeedbackList:
        items = self._store.all()
        if event_id:
            try:
                eid = self._monitor.resolve_event(event_id).id
            except LookupError:
                eid = event_id
            items = [f for f in items if f.event_id == eid]
        items = sorted(items, key=lambda f: (f.created_at, f.feedback_id), reverse=True)
        cap = min(limit or self.cfg.max_list, self.cfg.max_list)
        return FeedbackList(total=len(items), items=items[:cap])

    def statistics(self) -> FeedbackStats:
        return stats.compute(self._store.all())

