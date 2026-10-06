"""Persistence of the LIVE monitor: an append-only change log (deduplicated by ``change_id``) and the last state of every event it has seen.

REPLAY needs neither: its states and changes are a pure function of the frozen signals and the replay clock. The files are written atomically (temp file + rename),
a damaged line or file is skipped with a warning (never fatal, never silently trusted), and the log is bounded.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ..ingestion.snapshot import atomic_write_text
from .models import EventState, RiskChange

log = logging.getLogger("eventshock.monitor")


class ChangeLog:
    def __init__(self, path: Path | None, max_records: int = 5000) -> None:
        self.path, self.max = path, max_records
        self._lock = threading.RLock()
        self._items: list[RiskChange] = []
        self._ids: set[str] = set()
        if path is not None and path.is_file():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    c = RiskChange.model_validate_json(line)
                except ValueError as exc:
                    log.warning("monitor change log %s line %d skipped: %s", path, n, exc)
                    continue
                if c.change_id not in self._ids:
                    self._ids.add(c.change_id)
                    self._items.append(c)

    def __len__(self) -> int:
        return len(self._items)

    def append(self, changes: list[RiskChange]) -> list[RiskChange]:
        """Record the changes not already logged; returns exactly those. Recording the same change twice is a no-op (idempotence)."""
        fresh: list[RiskChange] = []
        with self._lock:
            for c in changes:
                if c.change_id in self._ids:
                    continue
                self._ids.add(c.change_id)
                self._items.append(c)
                fresh.append(c)
            if not fresh:
                return []
            overflow = len(self._items) - self.max
            if overflow > 0:
                dropped, self._items = self._items[:overflow], self._items[overflow:]
                for d in dropped:
                    self._ids.discard(d.change_id)
                self._rewrite()
            elif self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write("".join(c.model_dump_json() + "\n" for c in fresh))
        return fresh

    def _rewrite(self) -> None:
        if self.path is not None:
            atomic_write_text(self.path, "".join(c.model_dump_json() + "\n" for c in self._items))

    def all(self) -> list[RiskChange]:
        with self._lock:
            return list(self._items)


class StateStore:
    """The last EventState of every event the LIVE monitor has seen (so a restart diffs against what was known, not against nothing)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._states: dict[str, EventState] = {}
        if path is not None and path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self._states = {k: EventState.model_validate(v) for k, v in raw.items()}
            except (ValueError, AttributeError) as exc:
                log.warning("monitor state file %s ignored: %s", path, exc)
                self._states = {}

    def get_all(self) -> dict[str, EventState]:
        with self._lock:
            return dict(self._states)

    def put_all(self, states: dict[str, EventState]) -> None:
        with self._lock:
            self._states = dict(states)
            if self.path is not None:
                atomic_write_text(self.path, json.dumps({k: v.model_dump(mode="json") for k, v in sorted(self._states.items())}, separators=(",", ":")))
