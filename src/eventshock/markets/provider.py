"""The provider abstraction and the point-series provider that snapshots and fixtures share.

``MarketProvider`` is deliberately small so a provider of another category (an equity, rate, credit, commodity, FX or volatility observation) can implement it later; none is added now. A provider
answers three questions: what is your state, what do the markets of a series look like at a moment, and what did one market do over a period. It never raises for "no data": it says so.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from ..config import ConfigError
from ..decision.models import ObservationKind, ProvenanceRef
from .models import ExternalMarketObservation, MarketStatus, ProviderCategory, ProviderState

SCHEMA = "market-points-v1"


class MarketProvider(Protocol):
    name: str
    category: ProviderCategory
    synthetic: bool

    def state(self) -> ProviderState: ...

    def markets(self, series: str, as_of: datetime) -> list[ExternalMarketObservation]: ...

    def history(self, market_id: str, start: datetime, end: datetime) -> list[tuple[datetime, float | None]]: ...


def status_of(raw: str | None) -> MarketStatus:
    r = (raw or "").lower()
    if r in ("active", "open", "initialized"):
        return MarketStatus.OPEN
    if r in ("closed", "inactive", "paused"):
        return MarketStatus.CLOSED
    if r in ("finalized", "settled", "determined", "resolved"):
        return MarketStatus.SETTLED
    return MarketStatus.UNKNOWN


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Point:
    at: datetime
    prob: float | None
    open_interest: float | None
    volume: float | None          # contracts traded in the period this point closes


@dataclass
class MarketRecord:
    market_id: str
    series_id: str | None
    question: str
    raw_status: str | None
    open_time: datetime | None
    close_time: datetime | None
    source_url: str | None
    points: list[Point] = field(default_factory=list)


def _dt(x: str) -> datetime:
    t = parse_time(x)
    assert t is not None
    return t


def load_records(data: dict) -> list[MarketRecord]:
    if data.get("schema") != SCHEMA:
        raise ConfigError(f"external market file: schema {data.get('schema')!r}, expected {SCHEMA!r}")
    out: list[MarketRecord] = []
    for m in data["markets"]:
        pts = sorted((Point(at=_dt(p["at"]), prob=p.get("p"), open_interest=p.get("oi"), volume=p.get("vol")) for p in m.get("points", [])), key=lambda p: p.at)
        out.append(MarketRecord(market_id=m["market_id"], series_id=m.get("series_id"), question=m["question"], raw_status=m.get("status"), open_time=parse_time(m.get("open_time")),
                                close_time=parse_time(m.get("close_time")), source_url=m.get("source_url"), points=pts))
    return out


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PointProvider:
    """A provider over recorded points (a captured snapshot or a synthetic fixture). Deterministic: the same records and the same moment give the same observation, with no network and no clock."""

    category = ProviderCategory.PREDICTION_MARKET

    def __init__(self, *, name: str, source: str, synthetic: bool, records: list[MarketRecord], previous_gap_hours: float, mode: str, captured_at: datetime | None = None) -> None:
        self.name, self.source, self.synthetic, self._mode = name, source, synthetic, mode
        self._gap = timedelta(hours=previous_gap_hours)
        self._records = records
        self._by_series: dict[str, list[MarketRecord]] = {}
        self._by_id = {r.market_id: r for r in records}
        for r in records:
            self._by_series.setdefault(r.series_id or "", []).append(r)
        self.captured_at = captured_at
        times = [p.at for r in records for p in r.points]
        self._from, self._through = (min(times), max(times)) if times else (None, None)

    def state(self) -> ProviderState:
        if not self._records:
            return ProviderState(provider=self.name, category=self.category, state="UNAVAILABLE", mode=self._mode, reason="the file holds no markets", synthetic=self.synthetic)
        return ProviderState(provider=self.name, category=self.category, state="AVAILABLE", mode=self._mode, observed_from=self._from, observed_through=self._through, synthetic=self.synthetic,
                             reason=("SYNTHETIC FIXTURE: not market data" if self.synthetic else
                                     f"a captured copy of Kalshi's public data{f' (captured {self.captured_at:%Y-%m-%d})' if self.captured_at else ''}: replay uses only observations at or before the moment asked about"))

    def _obs(self, r: MarketRecord, as_of: datetime) -> ExternalMarketObservation | None:
        if r.open_time is not None and r.open_time > as_of:
            return None                                              # the market did not exist yet
        upto = [p for p in r.points if p.at <= as_of]
        if not upto:
            return None
        cur = upto[-1]
        prev = next((p for p in reversed(upto) if p.at <= cur.at - self._gap), None)
        status = MarketStatus.CLOSED if r.close_time is not None and r.close_time <= as_of else status_of("active")
        vol = sum(p.volume or 0.0 for p in upto)
        change = round((cur.prob - prev.prob) * 100.0, 6) if cur.prob is not None and prev is not None and prev.prob is not None else None
        return ExternalMarketObservation(
            provider=self.name, category=self.category, source=self.source, market_id=r.market_id, series_id=r.series_id, question=r.question, probability=cur.prob,
            previous_probability=prev.prob if prev else None, probability_change_pp=change, observed_at=cur.at, previous_observed_at=prev.at if prev else None, market_status=status,
            raw_status=r.raw_status, volume=vol, volume_24h=cur.volume, open_interest=cur.open_interest, close_time=r.close_time, source_url=r.source_url, synthetic=self.synthetic,
            provenance=[ProvenanceRef(kind=ObservationKind.EXTERNAL_MARKET_OBSERVATION, source=self.source, ref_id=r.market_id, as_of=cur.at)])

    def markets(self, series: str, as_of: datetime) -> list[ExternalMarketObservation]:
        out = [o for r in self._by_series.get(series, []) if (o := self._obs(r, as_of)) is not None]
        return sorted(out, key=lambda o: o.market_id)

    def history(self, market_id: str, start: datetime, end: datetime) -> list[tuple[datetime, float | None]]:
        r = self._by_id.get(market_id)
        return [(p.at, p.prob) for p in (r.points if r else []) if start <= p.at <= end]


def load_point_provider(path: Path, *, name: str, previous_gap_hours: float, expect_synthetic: bool | None = None, manifest: Path | None = None) -> PointProvider:
    """Load a points file. A snapshot is verified against its manifest (a modified or missing-manifest file is a ConfigError, never silently trusted)."""
    if manifest is not None:
        if not manifest.is_file():
            raise ConfigError(f"{path}: its manifest {manifest.name} is missing")
        expected = json.loads(manifest.read_text(encoding="utf-8")).get("sha256")
        if expected != sha256_of(path):
            raise ConfigError(f"{path} does not match its manifest: the captured data was modified (re-capture with `make kalshi-snapshot`)")
    data = json.loads(path.read_text(encoding="utf-8"))
    synthetic = bool(data.get("synthetic", False))
    if expect_synthetic is not None and synthetic != expect_synthetic:
        raise ConfigError(f"{path}: synthetic={synthetic} but this provider expects synthetic={expect_synthetic}")
    return PointProvider(name=name, source=str(data.get("source", "kalshi-snapshot")), synthetic=synthetic, records=load_records(data), previous_gap_hours=previous_gap_hours,
                         mode="fixture" if synthetic else "snapshot", captured_at=parse_time(data.get("captured_at")))
