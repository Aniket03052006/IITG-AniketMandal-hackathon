"""Kalshi: parsing of its public market data (the current `trade-api/v2` shape: prices are dollar strings, sizes are fixed-point strings) and a live provider over the repo's network transport.

Kalshi is an *adapter*: nothing outside this module and ``ingestion/kalshi_capture.py`` knows its field names. Parsing is defensive: a missing or malformed field is `None`, never a guess, and a
response that is not the expected shape makes the provider UNAVAILABLE rather than producing a number. The live provider is off unless explicitly enabled and is rate-limited; replay never calls it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from ..decision.models import ObservationKind, ProvenanceRef
from ..ingestion.fetch import FetchError, Transport, get_json, urllib_transport
from .config import KalshiCfg
from .models import ExternalMarketObservation, ProviderCategory, ProviderState
from .provider import parse_time, status_of

SOURCE = "kalshi"
WEB = "https://kalshi.com/markets/"


def dollars(x: Any) -> float | None:
    """A Kalshi dollar string ("0.1200") as a float in [0, 1]; anything else is None. A legacy integer cent field is deliberately not read: it is not the current contract."""
    if not isinstance(x, str):
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    return v if 0.0 <= v <= 1.0 else None


def fixed(x: Any) -> float | None:
    """A fixed-point size string ("200.00") as a float; None otherwise."""
    if not isinstance(x, str):
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    return v if v >= 0 else None


def implied_probability(last: float | None, bid: float | None, ask: float | None, traded: bool, max_spread: float) -> float | None:
    """The market's implied probability of YES: the last trade when there was one, else the midpoint of a tight two-sided quote, else None (not priced)."""
    if traded and last is not None and last > 0:
        return last
    if bid is not None and ask is not None and ask >= bid and ask > 0 and (ask - bid) <= max_spread:
        return (bid + ask) / 2.0
    return None


def parse_market(m: dict[str, Any], *, series: str | None, cfg: KalshiCfg, max_spread: float, now: datetime) -> ExternalMarketObservation | None:
    """One `GET /markets` row as an observation; None when it is not a recognisable binary market (so an unexpected shape never becomes a number)."""
    ticker, title = m.get("ticker"), m.get("title")
    if not isinstance(ticker, str) or not isinstance(title, str) or m.get("market_type", "binary") != "binary":
        return None
    vol = fixed(m.get("volume_fp"))
    last = dollars(m.get("last_price_dollars"))
    p = implied_probability(last, dollars(m.get("yes_bid_dollars")), dollars(m.get("yes_ask_dollars")), bool(vol and vol > 0), max_spread)
    prev = dollars(m.get("previous_price_dollars"))
    when = parse_time(m.get("updated_time")) or now
    series_id = series or (m.get("event_ticker") or "").split("-")[0] or None
    return ExternalMarketObservation(
        provider="kalshi", category=ProviderCategory.PREDICTION_MARKET, source=SOURCE, market_id=ticker, series_id=series_id, question=title, probability=p,
        previous_probability=prev if p is not None else None, probability_change_pp=(round((p - prev) * 100.0, 6) if p is not None and prev is not None else None), observed_at=when,
        previous_observed_at=None, market_status=status_of(m.get("status")), raw_status=m.get("status"), volume=vol, volume_24h=fixed(m.get("volume_24h_fp")),
        open_interest=fixed(m.get("open_interest_fp")), close_time=parse_time(m.get("close_time")), source_url=f"{WEB}{(series_id or '').lower()}", synthetic=False,
        provenance=[ProvenanceRef(kind=ObservationKind.EXTERNAL_MARKET_OBSERVATION, source=SOURCE, ref_id=ticker, as_of=when)])


def parse_candle(c: dict[str, Any], max_spread: float) -> tuple[datetime, float | None, float | None, float | None] | None:
    """(period end, probability, open interest, period volume) of a candlestick, or None when it has no timestamp."""
    ts = c.get("end_period_ts")
    if not isinstance(ts, int):
        return None
    price = c.get("price") or {}
    bid, ask = (c.get("yes_bid") or {}).get("close_dollars"), (c.get("yes_ask") or {}).get("close_dollars")
    vol = fixed(c.get("volume_fp"))
    p = implied_probability(dollars(price.get("close_dollars")), dollars(bid), dollars(ask), bool(vol and vol > 0), max_spread)
    return datetime.fromtimestamp(ts, UTC), p, fixed(c.get("open_interest_fp")), vol


class KalshiProvider:
    """The live provider. Off unless `EVENTSHOCK_MARKETS=live`; every failure becomes an UNAVAILABLE state with its reason, never an exception into the caller."""

    name = "kalshi"
    category = ProviderCategory.PREDICTION_MARKET
    synthetic = False

    def __init__(self, cfg: KalshiCfg, *, max_spread: float, transport: Transport = urllib_transport, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.cfg, self._max_spread, self._transport, self._sleep = cfg, max_spread, transport, sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_call = 0.0
        self._error: str | None = None
        self._ok_at: datetime | None = None

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        wait = self.cfg.min_interval_seconds - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()
        url = f"{self.cfg.base_url}{path}?{urlencode(params)}"
        try:
            data = get_json(url, transport=lambda u, t: self._transport(u, min(t, self.cfg.timeout_seconds)), retries=2, sleep=self._sleep)
        except FetchError as exc:
            self._error = f"Kalshi is unreachable or rate limited: {exc}"
            raise
        self._error = None
        self._ok_at = self._clock()
        return data

    def state(self) -> ProviderState:
        if self._error:
            return ProviderState(provider=self.name, category=self.category, state="UNAVAILABLE", mode="live", reason=self._error)
        return ProviderState(provider=self.name, category=self.category, state="AVAILABLE", mode="live", observed_through=self._ok_at,
                             reason="live public data (no key); only reached when explicitly enabled")

    def markets(self, series: str, as_of: datetime) -> list[ExternalMarketObservation]:
        now = self._clock()
        try:
            data = self._get("/markets", {"series_ticker": series, "status": "open", "limit": self.cfg.page_limit})
        except FetchError:
            return []
        rows = data.get("markets") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            self._error = "Kalshi answered in a shape this adapter does not recognise: no value is guessed"
            return []
        obs = [o for m in rows if isinstance(m, dict) and (o := parse_market(m, series=series, cfg=self.cfg, max_spread=self._max_spread, now=now)) is not None]
        obs.sort(key=lambda o: (-(o.volume or 0.0), -(o.open_interest or 0.0), o.market_id))
        return sorted(obs[: self.cfg.max_markets_per_series], key=lambda o: o.market_id)

    def history(self, market_id: str, start: datetime, end: datetime) -> list[tuple[datetime, float | None]]:
        series = market_id.split("-")[0]
        try:
            data = self._get(f"/series/{series}/markets/{market_id}/candlesticks",
                             {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": 1440})
        except FetchError:
            return []
        rows = data.get("candlesticks") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        out = [(t, p) for c in rows if isinstance(c, dict) and (parsed := parse_candle(c, self._max_spread)) is not None for t, p, _, _ in [parsed]]
        return sorted(out)

