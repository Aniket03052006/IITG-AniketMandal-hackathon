"""Where personal portfolios live: one small JSON file each, in a git-ignored directory, written atomically.

Kept apart from every immutable research/replay artifact: nothing under ``data/replay`` or ``configs`` is ever written to. A damaged or
unreadable file is skipped with a warning (it never takes the app down); a deleted portfolio is a deleted file.
"""

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
from .models import PortfolioInput, StoredPortfolio

log = logging.getLogger("eventshock")
ID_RE = re.compile(r"^pf_[a-z0-9]{6,32}$")


class PortfolioNotFound(LookupError):
    pass


class PortfolioLimit(ValueError):
    pass


class PortfolioStore:
    def __init__(self, directory: Path, *, max_portfolios: int, clock: Callable[[], datetime] | None = None,
                 id_factory: Callable[[], str] | None = None) -> None:
        self._dir = directory
        self._max = max_portfolios
        self._clock = clock or (lambda: datetime.now(UTC))
        self._new_id = id_factory or (lambda: "pf_" + uuid.uuid4().hex[:10])
        self._lock = threading.RLock()

    @property
    def directory(self) -> Path:
        return self._dir

    def _path(self, pid: str) -> Path:
        if not ID_RE.match(pid):
            raise PortfolioNotFound(pid)  # also stops any path traversal
        return self._dir / f"{pid}.json"

    # ------------------------------------------------------------------------------------------------------ reads
    def list(self) -> list[StoredPortfolio]:
        with self._lock:
            out: list[StoredPortfolio] = []
            if not self._dir.is_dir():
                return out
            for p in sorted(self._dir.glob("pf_*.json")):
                sp = self._read(p)
                if sp is not None:
                    out.append(sp)
            return sorted(out, key=lambda s: (s.updated_at, s.id), reverse=True)

    def get(self, pid: str) -> StoredPortfolio:
        with self._lock:
            p = self._path(pid)
            sp = self._read(p) if p.is_file() else None
            if sp is None:
                raise PortfolioNotFound(pid)
            return sp

    @staticmethod
    def _read(path: Path) -> StoredPortfolio | None:
        try:
            return StoredPortfolio.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            log.warning("portfolio file %s is unreadable and was skipped: %s", path.name, str(exc).splitlines()[0])
            return None

    # ----------------------------------------------------------------------------------------------------- writes
    def create(self, inp: PortfolioInput) -> StoredPortfolio:
        with self._lock:
            if len(self.list()) >= self._max:
                raise PortfolioLimit(f"at most {self._max} portfolios can be saved: delete one first")
            now = self._clock()
            sp = StoredPortfolio(id=self._new_id(), created_at=now, updated_at=now, **inp.model_dump())
            self._write(sp)
            return sp

    def update(self, pid: str, inp: PortfolioInput) -> StoredPortfolio:
        with self._lock:
            old = self.get(pid)
            sp = StoredPortfolio(id=pid, created_at=old.created_at, updated_at=max(self._clock(), old.updated_at), **inp.model_dump())
            self._write(sp)
            return sp

    def delete(self, pid: str) -> None:
        with self._lock:
            p = self._path(pid)
            if not p.is_file():
                raise PortfolioNotFound(pid)
            p.unlink()

    def _write(self, sp: StoredPortfolio) -> None:
        atomic_write_text(self._path(sp.id), sp.model_dump_json(indent=1) + "\n")
