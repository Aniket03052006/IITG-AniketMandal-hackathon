"""The persisted overrides file: a sparse map of dotted path -> value, written atomically (a temp file then ``os.replace``).

The file is local, git-ignored runtime state (like the saved portfolios). An unreadable file stops start-up with a clear error rather than being
silently ignored: a silently dropped adjustment would make the app disagree with what the user set.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text

SCHEMA = "overrides-v1"


class OverridesStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._values: dict[str, Any] = {}
        self._updated_at: str | None = None
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot read the adjustments file {self._path}: {exc}. Fix or delete it (it only holds your manual adjustments).") from exc
        if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("values"), dict):
            raise ConfigError(f"{self._path} is not an {SCHEMA} file. Fix or delete it (it only holds your manual adjustments).")
        self._values = dict(data["values"])
        self._updated_at = data.get("updated_at")

    def values(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    @property
    def updated_at(self) -> str | None:
        return self._updated_at

    def version(self) -> str:
        with self._lock:
            return version_of(self._values)

    def replace(self, values: dict[str, Any]) -> None:
        with self._lock:
            now = datetime.now(UTC).isoformat(timespec="seconds")
            if values:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(self._path, json.dumps({"schema": SCHEMA, "updated_at": now, "values": values}, indent=1, sort_keys=True) + "\n")
            elif self._path.is_file():
                self._path.unlink()
            self._values = dict(values)
            self._updated_at = now if values else None


def version_of(values: dict[str, Any]) -> str:
    if not values:
        return "default"
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:12]
