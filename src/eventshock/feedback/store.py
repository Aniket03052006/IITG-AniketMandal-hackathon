"""Append-only persistence of analyst feedback: one JSON line per record in a git-ignored file. A damaged line is skipped with a warning; records are never edited or deleted here."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .models import Feedback

log = logging.getLogger("eventshock.feedback")


class FeedbackLimit(ValueError):
    pass


class FeedbackStore:
    def __init__(self, path: Path | None, *, max_records: int, clock: Callable[[], datetime] | None = None, id_factory: Callable[[], str] | None = None) -> None:
        self.path, self.max = path, max_records
        self._clock = clock or (lambda: datetime.now(UTC))
        self._new_id = id_factory or (lambda: "fb_" + uuid.uuid4().hex[:12])
        self._lock = threading.RLock()
        self._items: list[Feedback] = []
        if path is not None and path.is_file():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    self._items.append(Feedback.model_validate_json(line))
                except ValueError as exc:
                    log.warning("feedback file %s line %d skipped: %s", path, n, str(exc).splitlines()[0])

    def __len__(self) -> int:
        return len(self._items)

    def add(self, *, event_id: str, signal_id: str | None, analyst_id: str, type_, value, comment: str | None, portfolio_id: str | None, cycle: int | None) -> Feedback:  # noqa: ANN001
        with self._lock:
            if len(self._items) >= self.max:
                raise FeedbackLimit(f"the feedback log holds at most {self.max} records")
            fb = Feedback(feedback_id=self._new_id(), event_id=event_id, signal_id=signal_id, analyst_id=analyst_id, type=type_, value=value, comment=comment, created_at=self._clock(),
                          portfolio_id=portfolio_id, cycle=cycle)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(fb.model_dump_json() + "\n")
            self._items.append(fb)
            return fb

    def all(self) -> list[Feedback]:
        with self._lock:
            return list(self._items)
