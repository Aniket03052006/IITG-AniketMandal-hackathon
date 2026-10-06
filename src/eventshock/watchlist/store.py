"""Where watchlists live: one small JSON file each in a git-ignored directory, written atomically. A damaged file is skipped with a warning; a deleted list is a deleted file."""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ..ingestion.snapshot import atomic_write_text
from .models import Watchlist, WatchlistInput

log = logging.getLogger("eventshock.watchlist")
ID_RE = re.compile(r"^wl_[a-z0-9]{6,32}$")


class WatchlistNotFound(LookupError):
    pass


class WatchlistLimit(ValueError):
    pass


class WatchlistStore:
    def __init__(self, directory: Path, *, max_watchlists: int, clock: Callable[[], datetime] | None = None, id_factory: Callable[[], str] | None = None) -> None:
        self._dir, self._max = directory, max_watchlists
        self._clock = clock or (lambda: datetime.now(UTC))
        self._new_id = id_factory or (lambda: "wl_" + uuid.uuid4().hex[:10])
        self._lock = threading.RLock()

    def _path(self, wid: str) -> Path:
        if not ID_RE.match(wid):
            raise WatchlistNotFound(wid)  # also stops any path traversal
        return self._dir / f"{wid}.json"

    def list(self) -> list[Watchlist]:
        with self._lock:
            out: list[Watchlist] = []
            if self._dir.is_dir():
                for p in sorted(self._dir.glob("wl_*.json")):
                    w = self._read(p)
                    if w is not None:
                        out.append(w)
            return sorted(out, key=lambda w: (w.created_at, w.id))

    def get(self, wid: str) -> Watchlist:
        with self._lock:
            p = self._path(wid)
            w = self._read(p) if p.is_file() else None
            if w is None:
                raise WatchlistNotFound(wid)
            return w

    @staticmethod
    def _read(path: Path) -> Watchlist | None:
        try:
            return Watchlist.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            log.warning("watchlist file %s is unreadable and was skipped: %s", path.name, str(exc).splitlines()[0])
            return None

    def create(self, inp: WatchlistInput) -> Watchlist:
        with self._lock:
            if len(self.list()) >= self._max:
                raise WatchlistLimit(f"at most {self._max} watchlists can be saved: delete one first")
            now = self._clock()
            w = Watchlist(id=self._new_id(), created_at=now, updated_at=now, **inp.model_dump())
            self._write(w)
            return w

    def update(self, wid: str, inp: WatchlistInput) -> Watchlist:
        with self._lock:
            old = self.get(wid)
            w = Watchlist(id=wid, created_at=old.created_at, updated_at=max(self._clock(), old.updated_at), **inp.model_dump())
            self._write(w)
            return w

    def delete(self, wid: str) -> None:
        with self._lock:
            p = self._path(wid)
            if not p.is_file():
                raise WatchlistNotFound(wid)
            p.unlink()

    def _write(self, w: Watchlist) -> None:
        atomic_write_text(self._path(w.id), w.model_dump_json(indent=1) + "\n")
