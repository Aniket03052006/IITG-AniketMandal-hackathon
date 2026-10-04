"""Fixture loading and in-memory repositories (replay mode). Everything is validated on load."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
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


def _matches(s: RiskSignal, category: EventCategory | None, source_type: SourceType | None, min_impact: int | None,
             q: str | None, event_status: EventStatus | None, scope_level: str | None) -> bool:
    """The one filter both repositories apply. ``category`` matches only CLASSIFIED events: a NO_EVENT/UNCERTAIN best guess is not a finding."""
    if category and (s.event.category != category or s.event.status is not EventStatus.CLASSIFIED):
        return False
    if event_status and s.event.status is not event_status:
        return False
    if source_type and s.document.source_type != source_type:
        return False
    if min_impact is not None and (s.impact is None or s.impact.score < min_impact):
        return False
    if scope_level and (s.scope is None or s.scope.level.value != scope_level):
        return False
    if q and q not in " ".join([s.document.headline, s.document.body, s.entity.entity_name or "", s.entity.ticker or ""]).lower():
        return False
    return True


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
        scope_level: str | None = None,
    ) -> list[RiskSignal]:
        q = query.strip().lower() if query else None
        return [s for s in self._signals if _matches(s, category, source_type, min_impact, q, event_status, scope_level)]

    def get(self, signal_id: str) -> RiskSignal | None:
        return self._by_id.get(signal_id)


CHANNEL_REPLAY, CHANNEL_LIVE, CHANNEL_MANUAL = "REPLAY", "LIVE", "MANUAL"
CHANNELS = (CHANNEL_REPLAY, CHANNEL_LIVE, CHANNEL_MANUAL)


@dataclass
class SignalMeta:
    """How a signal in the live overlay arrived and when it last changed (``seq`` is the store's monotonic change counter)."""

    channel: str
    first_seq: int
    updated_seq: int


class LiveSignalStore:
    """The bounded overlay of signals produced after start-up: the live feed and pasted text. Every method takes one lock: the engine writes from a worker thread while requests read.

    Bounds: nothing older than ``retention_hours`` (by publication time) and at most ``max_signals`` (oldest published go first),
    so memory cannot grow without limit on a small host.
    """

    def __init__(self, retention_hours: float = 48.0, max_signals: int = 1500) -> None:
        self.retention = timedelta(hours=retention_hours)
        self.max_signals = max_signals
        self.seq = 0
        self._signals: dict[str, RiskSignal] = {}
        self._meta: dict[str, SignalMeta] = {}
        self._alias: dict[str, str] = {}  # a signal id that was merged into another -> the one that replaced it
        self._lock = threading.RLock()  # the engine writes from a worker thread while requests read

    def __len__(self) -> int:
        return len(self._signals)

    def upsert(self, signal: RiskSignal, channel: str) -> SignalMeta:
        with self._lock:
            self.seq += 1
            prev = self._meta.get(signal.id)
            meta = SignalMeta(channel=prev.channel if prev else channel, first_seq=prev.first_seq if prev else self.seq,
                              updated_seq=self.seq)
            self._signals[signal.id], self._meta[signal.id] = signal, meta
            self._alias.pop(signal.id, None)
            return meta

    def supersede(self, old_id: str, new_id: str) -> None:
        """``old_id`` is now part of ``new_id`` (its cluster's earliest report changed): keep its links working."""
        with self._lock:
            if old_id != new_id and old_id in self._signals:
                del self._signals[old_id], self._meta[old_id]
                self.seq += 1
            if old_id != new_id:
                self._alias[old_id] = new_id

    def evict(self, now: datetime) -> list[str]:
        """Drop signals past retention, then the oldest published beyond ``max_signals``. Returns the removed ids."""
        with self._lock:
            cutoff = now - self.retention
            gone = [i for i, s in self._signals.items() if s.document.published_at < cutoff]
            expired = set(gone)
            rest = sorted((i for i in self._signals if i not in expired), key=lambda i: self._signals[i].document.published_at)
            gone += rest[: max(0, len(rest) - self.max_signals)]
            for i in gone:
                del self._signals[i], self._meta[i]
            if gone:
                self.seq += 1
                self._alias = {k: v for k, v in self._alias.items() if v in self._signals}
            return gone

    def get(self, signal_id: str) -> RiskSignal | None:
        with self._lock:
            return self._signals.get(self._alias.get(signal_id, signal_id))

    def meta(self, signal_id: str) -> SignalMeta | None:
        with self._lock:
            return self._meta.get(self._alias.get(signal_id, signal_id))

    def items(self) -> list[tuple[RiskSignal, SignalMeta]]:
        """A consistent snapshot of every live signal with its meta."""
        with self._lock:
            return [(s, self._meta[i]) for i, s in self._signals.items()]


class CombinedSignalRepository:
    """The replay signals (immutable, deterministic) plus the live overlay, behind the same ``SignalRepository`` interface.

    ``as_of`` stays the replay clock: replay results must not move because a live signal arrived.
    """

    def __init__(self, base: InMemorySignalRepository, live: LiveSignalStore) -> None:
        self.base, self.live = base, live
        self.as_of = base.as_of

    @property
    def seq(self) -> int:
        return self.live.seq

    def channel_of(self, signal_id: str) -> str:
        m = self.live.meta(signal_id)
        return m.channel if m else CHANNEL_REPLAY

    def meta_of(self, signal_id: str) -> SignalMeta | None:
        return self.live.meta(signal_id)

    def list(
        self,
        *,
        category: EventCategory | None = None,
        source_type: SourceType | None = None,
        min_impact: int | None = None,
        query: str | None = None,
        event_status: EventStatus | None = None,
        scope_level: str | None = None,
        channel: str | None = None,
        since_seq: int | None = None,
    ) -> list[RiskSignal]:
        q = query.strip().lower() if query else None
        out: list[RiskSignal] = []
        if channel in (None, CHANNEL_REPLAY) and since_seq is None:
            out += [s for s in self.base._signals  # noqa: SLF001 (same package: the base is ours)
                    if _matches(s, category, source_type, min_impact, q, event_status, scope_level)]
        for s, m in self.live.items():
            if channel and m.channel != channel:
                continue
            if since_seq is not None and m.updated_seq <= since_seq:
                continue
            if _matches(s, category, source_type, min_impact, q, event_status, scope_level):
                out.append(s)
        return sorted(out, key=lambda s: (s.document.published_at, s.id), reverse=True)

    def get(self, signal_id: str) -> RiskSignal | None:
        return self.live.get(signal_id) or self.base.get(signal_id)


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
