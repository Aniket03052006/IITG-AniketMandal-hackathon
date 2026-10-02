"""Daily price history from Yahoo Finance's public chart endpoint (no API key, no new dependency).

Unofficial and for research use: the terms of Yahoo Finance apply. One CSV per symbol in ``data/raw/prices/``
(``date,open,high,low,close,adj_close,volume``, ascending, exchange-session dates), plus a per-symbol log.
Days Yahoo reports without a close (holidays, halts) are dropped and counted, never filled.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .fetch import FetchError, Transport, get_json, urllib_transport, write_jsonl
from .snapshot import atomic_write_text

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]


def file_stem(symbol: str) -> str:
    """``^GSPC`` -> ``_GSPC`` (no special characters in file names)."""
    return symbol.replace("^", "_").replace("/", "-").replace("=", "-")


def chart_url(symbol: str, start: datetime, end: datetime) -> str:
    q = {"period1": str(int(start.timestamp())), "period2": str(int(end.timestamp())), "interval": "1d",
         "events": "div,splits", "includeAdjustedClose": "true"}
    return f"{CHART_URL}{urllib.parse.quote(symbol)}?{urllib.parse.urlencode(q)}"


def parse_chart(payload: Any, symbol: str) -> tuple[list[dict[str, Any]], int]:
    """Return (rows, dropped_days). Raises ``FetchError`` for an error payload or an unexpected shape."""
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise FetchError(f"{symbol}: unexpected response shape")
    if chart.get("error"):
        raise FetchError(f"{symbol}: {chart['error'].get('code')}: {chart['error'].get('description')}")
    result = (chart.get("result") or [None])[0]
    if not isinstance(result, dict) or "timestamp" not in result:
        raise FetchError(f"{symbol}: no price data in response")
    ts = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    adj = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    rows, dropped = [], 0
    for i, t in enumerate(ts):
        o, h, lo, c, v = (quote[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, lo, c):
            dropped += 1
            continue
        rows.append({"date": datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d"), "open": round(o, 4),
                     "high": round(h, 4), "low": round(lo, 4), "close": round(c, 4),
                     "adj_close": round(adj[i] if adj and adj[i] is not None else c, 4), "volume": int(v or 0)})
    seen: dict[str, dict[str, Any]] = {}
    for r in rows:  # a session can appear twice around the live quote: the later row wins
        seen[r["date"]] = r
    return sorted(seen.values(), key=lambda r: r["date"]), dropped


def write_price_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    atomic_write_text(path, buf.getvalue())


def read_price_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [{"date": r["date"], **{k: float(r[k]) for k in COLUMNS[1:6]}, "volume": int(float(r["volume"]))}
                for r in csv.DictReader(fh)]


@dataclass
class PriceFetchResult:
    log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failed(self) -> list[str]:
        return [e["symbol"] for e in self.log if e["status"] == "error"]


def fetch_prices(symbols: Iterable[str], *, start: datetime, end: datetime, out_dir: Path,
                 transport: Transport = urllib_transport, sleep: Callable[[float], None] = time.sleep,
                 pause: float = 1.0, progress: Callable[[str], None] | None = None) -> PriceFetchResult:
    res = PriceFetchResult()
    for i, sym in enumerate(symbols):
        if i:
            sleep(pause)
        try:
            payload = get_json(chart_url(sym, start, end), transport=transport, sleep=sleep, retries=3, backoff=5.0)
            rows, dropped = parse_chart(payload, sym)
            if not rows:
                raise FetchError(f"{sym}: no trading days in range")
        except FetchError as exc:
            res.log.append({"symbol": sym, "status": "error", "error": str(exc)[-200:]})
            if progress:
                progress(f"{sym}: ERROR {exc}")
            continue
        write_price_csv(out_dir / f"{file_stem(sym)}.csv", rows)
        res.log.append({"symbol": sym, "status": "ok", "rows": len(rows), "dropped_days": dropped,
                        "first": rows[0]["date"], "last": rows[-1]["date"]})
        if progress:
            progress(f"{sym}: {len(rows)} days {rows[0]['date']}..{rows[-1]['date']}")
    write_jsonl(out_dir / "prices.log.jsonl", res.log)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols-file", type=Path, required=True, help="JSON list of Yahoo symbols")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default="2026-10-02")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    symbols = json.loads(args.symbols_file.read_text(encoding="utf-8"))
    parse = lambda d: datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=UTC)  # noqa: E731
    res = fetch_prices(symbols, start=parse(args.start), end=parse(args.end), out_dir=args.out,
                       progress=lambda m: print(m, file=sys.stderr, flush=True))
    ok = len(res.log) - len(res.failed)
    print(f"prices: {ok}/{len(symbols)} symbols ok -> {args.out}")
    for s in res.failed:
        print(f"  FAILED: {s}")
    return 1 if ok == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
