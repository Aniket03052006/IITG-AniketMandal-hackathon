"""Extension points. Later stages plug in by implementing these Protocols; nothing else changes."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from .domain import Entity, EventCategory, EventStatus, Portfolio, RawDocument, RiskSignal, SourceType


class SourceAdapter(Protocol):
    """Provider-specific ingestion (replay today; GDELT / NewsAPI / X later) -> ``RawDocument``."""

    name: str

    def fetch(self) -> Iterable[RawDocument]: ...


class SignalRepository(Protocol):
    """Read side of the signal store. Stage 2+ swaps the fixture-backed store for pipeline output."""

    as_of: datetime

    def list(
        self,
        *,
        category: EventCategory | None = None,
        source_type: SourceType | None = None,
        min_impact: int | None = None,
        query: str | None = None,
        event_status: EventStatus | None = None,
        scope_level: str | None = None,
    ) -> list[RiskSignal]: ...

    def get(self, signal_id: str) -> RiskSignal | None: ...


class PortfolioRepository(Protocol):
    def get(self) -> Portfolio: ...

    def entities(self) -> list[Entity]: ...
