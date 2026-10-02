"""Fixture loading and in-memory repositories (replay mode). Everything is validated on load."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import ConfigError
from .domain import Entity, EventCategory, EventStatus, Portfolio, RiskSignal, SourceType


def _read_json(path: Path) -> object:
    if not path.is_file():
        raise ConfigError(f"missing fixture file: {path} (run `python scripts/generate_fixtures.py`)")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc


class InMemorySignalRepository:
    """Signals ordered newest first. ``as_of`` is the fixed replay clock."""

    def __init__(self, signals: list[RiskSignal], as_of: datetime) -> None:
        ids = [s.id for s in signals]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate signal ids")
        self.as_of = as_of
        self._signals = sorted(signals, key=lambda s: (s.document.published_at, s.id), reverse=True)
        self._by_id = {s.id: s for s in signals}

    def list(
        self,
        *,
        category: EventCategory | None = None,
        source_type: SourceType | None = None,
        min_impact: int | None = None,
        query: str | None = None,
        event_status: EventStatus | None = None,
    ) -> list[RiskSignal]:
        """``category`` matches only CLASSIFIED events: a NO_EVENT/UNCERTAIN best guess is not a finding."""
        q = query.strip().lower() if query else None
        out = []
        for s in self._signals:
            if category and (s.event.category != category or s.event.status is not EventStatus.CLASSIFIED):
                continue
            if event_status and s.event.status is not event_status:
                continue
            if source_type and s.document.source_type != source_type:
                continue
            if min_impact is not None and (s.impact is None or s.impact.score < min_impact):
                continue
            if q and q not in " ".join(
                [s.document.headline, s.document.body, s.entity.entity_name or "", s.entity.ticker or ""]
            ).lower():
                continue
            out.append(s)
        return out

    def get(self, signal_id: str) -> RiskSignal | None:
        return self._by_id.get(signal_id)


class InMemoryPortfolioRepository:
    def __init__(self, portfolio: Portfolio, entities: list[Entity]) -> None:
        known = {e.entity_id for e in entities}
        orphans = sorted({a.entity_id for a in portfolio.assets} - known)
        if orphans:
            raise ValueError(f"portfolio references unknown entities: {orphans}")
        self._portfolio = portfolio
        self._entities = entities

    def get(self) -> Portfolio:
        return self._portfolio

    def entities(self) -> list[Entity]:
        return list(self._entities)


def load_signal_repository(fixtures_dir: Path) -> InMemorySignalRepository:
    raw = _read_json(fixtures_dir / "signals.json")
    if not isinstance(raw, dict):
        raise ConfigError("signals.json must be an object with `as_of` and `signals`")
    signals = [RiskSignal.model_validate(s) for s in raw["signals"]]
    return InMemorySignalRepository(signals, datetime.fromisoformat(raw["as_of"]))


def load_portfolio_repository(fixtures_dir: Path) -> InMemoryPortfolioRepository:
    return load_portfolio_files(fixtures_dir / "portfolio.json", fixtures_dir / "entities.json")


def load_portfolio_files(portfolio_path: Path, entities_path: Path) -> InMemoryPortfolioRepository:
    portfolio = Portfolio.model_validate(_read_json(portfolio_path))
    entities = [Entity.model_validate(e) for e in _read_json(entities_path)]  # type: ignore[union-attr]
    return InMemoryPortfolioRepository(portfolio, entities)
