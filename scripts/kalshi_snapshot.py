#!/usr/bin/env python3
"""Capture a small, hash-pinned snapshot of Kalshi's public market data for the curated themes (network; no key) -> data/external/kalshi_snapshot.json (+ a manifest with its sha256).

Replay and the demo use this file only; the server never calls Kalshi unless EVENTSHOCK_MARKETS=live. Re-running replaces the snapshot (and its manifest). A series that returns nothing is
reported and left out: nothing is invented to fill it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from eventshock.ingestion.kalshi_capture import KalshiRaw  # noqa: E402
from eventshock.markets.config import load_markets_config  # noqa: E402
from eventshock.markets.kalshi import WEB, fixed, parse_candle  # noqa: E402
from eventshock.markets.provider import SCHEMA  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="output file (default: the path in configs/external_markets.yaml)")
    ap.add_argument("--days", type=int, default=None)
    args = ap.parse_args(argv)
    cfg = load_markets_config(REPO / "configs")
    out = Path(args.out) if args.out else REPO / cfg.snapshot.path
    days = args.days or cfg.snapshot.history_days
    k = cfg.providers.kalshi
    raw = KalshiRaw(k.base_url, min_interval=k.min_interval_seconds, timeout=k.timeout_seconds)
    now = datetime.now(UTC)
    start, end = int((now - timedelta(days=days)).timestamp()), int(now.timestamp())
    series_all = sorted({s for t in cfg.themes for s in t.series})
    markets_out: list[dict] = []
    report: list[str] = []
    for series in series_all:
        rows = raw.markets(series, limit=k.page_limit)
        if not rows:
            report.append(f"{series}: no markets returned (skipped)")
            continue
        rows.sort(key=lambda m: (-(fixed(m.get("volume_fp")) or 0.0), -(fixed(m.get("open_interest_fp")) or 0.0), str(m.get("ticker"))))
        kept = 0
        for m in rows[: k.max_markets_per_series]:
            ticker = m.get("ticker")
            if not isinstance(ticker, str):
                continue
            candles = raw.candles(series, ticker, start_ts=start, end_ts=end, period_minutes=cfg.snapshot.candle_minutes)
            pts = []
            for c in candles:
                p = parse_candle(c, cfg.matching.max_spread)
                if p is not None:
                    t, prob, oi, vol = p
                    pts.append({"at": t.isoformat().replace("+00:00", "Z"), "p": prob, "oi": oi, "vol": vol})
            if not pts:
                report.append(f"{series}/{ticker}: no candles (skipped)")
                continue
            markets_out.append({"market_id": ticker, "series_id": series, "question": m.get("title"), "status": m.get("status"), "open_time": m.get("open_time"), "close_time": m.get("close_time"),
                                "source_url": f"{WEB}{series.lower()}", "points": pts})
            kept += 1
        report.append(f"{series}: kept {kept} of {len(rows)} markets")
    if not markets_out:
        print("\n".join(report), file=sys.stderr)
        print("no markets were captured (network down or rate limited): nothing was written", file=sys.stderr)
        return 1
    body = {"schema": SCHEMA, "source": "kalshi-snapshot", "synthetic": False, "captured_at": now.isoformat().replace("+00:00", "Z"), "history_days": days,
            "note": "A captured copy of Kalshi's public market data for EventShock's curated themes. Not proprietary; replay reads only observations at or before the moment it asks about.",
            "markets": sorted(markets_out, key=lambda m: m["market_id"])}
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, separators=(",", ":"), ensure_ascii=False) + "\n"
    out.write_text(text, encoding="utf-8")
    manifest = out.with_suffix(".manifest.json")
    manifest.write_text(json.dumps({"schema": "market-points-manifest-v1", "file": out.name, "sha256": hashlib.sha256(text.encode()).hexdigest(), "markets": len(markets_out),
                                    "captured_at": body["captured_at"]}, indent=1) + "\n", encoding="utf-8")
    print("\n".join(report))
    if raw.errors:
        print(f"{len(raw.errors)} request(s) failed after retries (first: {raw.errors[0]})")
    print(f"wrote {out} ({len(markets_out)} markets, {out.stat().st_size / 1024:.0f} KB) and {manifest.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
