"""The network entry point of the external-market layer: raw responses from Kalshi's public API (no key), throttled and retried, returned as parsed JSON.

Only `make kalshi-snapshot` (scripts/kalshi_snapshot.py) uses it; the server never calls it, and replay never reaches the network. Parsing into typed observations happens in `eventshock.markets`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from .fetch import FetchError, Transport, get_json, urllib_transport


class KalshiRaw:
    def __init__(self, base_url: str, *, min_interval: float = 0.6, timeout: float = 20.0, transport: Transport = urllib_transport, sleep: Callable[[float], None] = time.sleep,
                 retries: int = 5) -> None:
        self.base, self._min, self._timeout, self._transport, self._sleep, self._retries = base_url.rstrip("/"), min_interval, timeout, transport, sleep, retries
        self._last = 0.0
        self.errors: list[str] = []

    def get(self, path: str, params: dict[str, Any]) -> Any | None:
        wait = self._min - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()
        url = f"{self.base}{path}?{urlencode(params)}"
        try:
            return get_json(url, transport=lambda u, t: self._transport(u, min(t, self._timeout)), retries=self._retries, backoff=2.0, sleep=self._sleep)
        except FetchError as exc:
            self.errors.append(f"{path}: {exc}")
            return None

    def markets(self, series: str, *, limit: int = 200) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor = None
        for _ in range(10):
            params: dict[str, Any] = {"series_ticker": series, "limit": limit}
            if cursor:
                params["cursor"] = cursor
            d = self.get("/markets", params)
            if not isinstance(d, dict) or not isinstance(d.get("markets"), list):
                break
            out += [m for m in d["markets"] if isinstance(m, dict)]
            cursor = d.get("cursor")
            if not cursor:
                break
        return out

    def candles(self, series: str, ticker: str, *, start_ts: int, end_ts: int, period_minutes: int) -> list[dict[str, Any]]:
        d = self.get(f"/series/{series}/markets/{ticker}/candlesticks", {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_minutes})
        rows = d.get("candlesticks") if isinstance(d, dict) else None
        return [c for c in rows if isinstance(c, dict)] if isinstance(rows, list) else []
