"""An append-only JSONL cache of validated model answers, so the same text is never sent twice (cost, latency, and a stable demo).

The key is the sha256 of (text, model, prompt version, vocabulary version): changing any of them is a different question and misses the cache.
A corrupt line is skipped with a warning rather than stopping start-up (the cache is an optimisation; the source of truth is the text).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("eventshock")


def cache_key(text: str, model: str, prompt_version: str, vocab_version: str) -> str:
    return hashlib.sha256("\x1f".join((text, model, prompt_version, vocab_version)).encode("utf-8")).hexdigest()


class ExtractionCache:
    def __init__(self, path: Path | None, max_entries: int = 5000) -> None:
        self._path = path
        self._max = max_entries
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        if path is not None and path.is_file():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._data[row["key"]] = row["value"]
                except (ValueError, KeyError, TypeError):
                    log.warning("llm cache %s: skipped unreadable line %d", path, n)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            if key in self._data or len(self._data) >= self._max:
                return  # a full cache stops growing; it is never evicted silently into a different answer
            self._data[key] = value
            if self._path is None:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"key": key, "value": value}, sort_keys=True) + "\n")
            except OSError as exc:  # a read-only disk must not break analysis
                log.warning("llm cache %s not written: %s", self._path, exc)
