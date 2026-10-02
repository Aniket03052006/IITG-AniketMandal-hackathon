"""Replay adapter: emits the fixture documents as ``RawDocument`` — the first-class offline source."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..domain import RawDocument
from ..store import load_signal_repository


class ReplayFixtureAdapter:
    """Reads documents from the fixture store. Deterministic order; no network."""

    name = "replay-fixtures"

    def __init__(self, fixtures_dir: Path) -> None:
        self._repo = load_signal_repository(fixtures_dir)

    def fetch(self) -> Iterable[RawDocument]:
        for signal in self._repo.list():
            yield signal.document
