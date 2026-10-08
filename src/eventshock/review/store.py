"""Append-only persistence of review decisions: one JSON line per decision in a git-ignored file. The latest decision on an event is its current one; earlier ones stay as history.
A damaged line is skipped with a warning; nothing is edited or deleted here."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .models import ReviewDecision, ReviewStatus

log = logging.getLogger("eventshock.review")


class ReviewLimit(ValueError):
    pass


class ReviewStore:
    def __init__(self, path: Path | None, *, max_records: int, clock: Callable[[], datetime] | None = None, id_factory: Callable[[], str] | None = None) -> None:
        self.path, self.max = path, max_records
        self._clock = clock or (lambda: datetime.now(UTC))
        self._new_id = id_factory or (lambda: "rv_" + uuid.uuid4().hex[:12])
        self._lock = threading.RLock()
        self._items: list[ReviewDecision] = []
        if path is not None and path.is_file():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    self._items.append(ReviewDecision.model_validate_json(line))
                except ValueError as exc:
                    log.warning("review file %s line %d skipped: %s", path, n, str(exc).splitlines()[0])

    def __len__(self) -> int:
        return len(self._items)

    def add(self, *, event_id: str, status: ReviewStatus, note: str | None, analyst_id: str, fingerprint: str, headline: str) -> ReviewDecision:
        with self._lock:
            if len(self._items) >= self.max:
                raise ReviewLimit(f"the review log holds at most {self.max} decisions")
            d = ReviewDecision(decision_id=self._new_id(), event_id=event_id, status=status, note=note, analyst_id=analyst_id, created_at=self._clock(), fingerprint=fingerprint, headline=headline)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(d.model_dump_json() + "\n")
            self._items.append(d)
            return d

    def latest(self) -> dict[str, ReviewDecision]:
        """The current decision of every event that has one (the last recorded wins)."""
        with self._lock:
            out: dict[str, ReviewDecision] = {}
            for d in self._items:
                out[d.event_id] = d
            return out

    def history(self, event_id: str) -> list[ReviewDecision]:
        with self._lock:
            return [d for d in self._items if d.event_id == event_id]

    def all(self) -> list[ReviewDecision]:
        with self._lock:
            return list(self._items)
