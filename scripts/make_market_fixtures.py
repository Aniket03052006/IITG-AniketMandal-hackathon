#!/usr/bin/env python3
"""Regenerate the synthetic external-market fixtures (data/fixtures/external_markets/markets.json). Deterministic: no randomness, no network, no real market data.

Every market here is SYNTHETIC and says so in its question and in the file: it exists to exercise matching and interpretation (a matched market, a probability increase and decrease, a market that
is aligned and one that diverges, a thin one, an unpriced one, a closed one). It is never shown as market data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "external_markets" / "markets.json"
START = datetime(2026, 8, 25, 12, tzinfo=UTC)
DAYS = 40
JUMP = datetime(2026, 9, 25, 12, tzinfo=UTC)          # the day the scripted moves happen (inside the replay window)


def path(before: float | None, after: float | None, *, oi: float, vol: float, jump: datetime = JUMP) -> list[dict]:
    pts = []
    for d in range(DAYS):
        t = START + timedelta(days=d)
        pts.append({"at": t.isoformat().replace("+00:00", "Z"), "p": before if t < jump else after, "oi": oi, "vol": vol})
    return pts


MARKETS = [
    ("FIXTURE-FED-CUT", "KXFEDDECISION", "[SYNTHETIC FIXTURE] Will the Fed cut rates at its next meeting?", "active", datetime(2026, 12, 16, tzinfo=UTC), path(0.48, 0.72, oi=5000, vol=800)),
    ("FIXTURE-CPI-ABOVE-3.5", "KXUSCPIYEAR", "[SYNTHETIC FIXTURE] Will US CPI inflation be above 3.5% at year end?", "active", datetime(2027, 1, 15, tzinfo=UTC), path(0.63, 0.55, oi=3000, vol=500)),
    ("FIXTURE-CPI-BELOW-2.5", "KXUSCPIYEAR", "[SYNTHETIC FIXTURE] Will US CPI inflation be below 2.5% at year end?", "active", datetime(2027, 1, 15, tzinfo=UTC), path(0.20, 0.20, oi=400, vol=60)),
    ("FIXTURE-U3-ABOVE-5", "KXU3EOY", "[SYNTHETIC FIXTURE] Will the US unemployment rate be above 5.0% at year end?", "active", datetime(2027, 1, 8, tzinfo=UTC), path(0.30, 0.34, oi=2000, vol=300)),
    ("FIXTURE-TARIFF-ABOVE-15", "KXEFFTARIFF", "[SYNTHETIC FIXTURE] Will the US effective tariff rate be above 15%?", "active", datetime(2026, 12, 31, tzinfo=UTC), path(0.41, 0.406, oi=1500, vol=250)),
    ("FIXTURE-DEFAULT-2029", "KXDEFAULT", "[SYNTHETIC FIXTURE] Will the US default on its debt by 2029?", "active", datetime(2029, 12, 31, tzinfo=UTC), path(0.12, 0.12, oi=3, vol=0.2)),
    ("FIXTURE-FUNDS-UNPRICED", "KXFEDFUNDSYEAR", "[SYNTHETIC FIXTURE] Will the federal funds upper bound be above 4.5% at year end?", "active", datetime(2026, 12, 31, tzinfo=UTC), path(None, None, oi=400, vol=0)),
    ("FIXTURE-FEDCUT-CLOSED", "KXFEDCUT", "[SYNTHETIC FIXTURE] Will the Fed cut rates by September 30, 2026?", "finalized", datetime(2026, 9, 1, tzinfo=UTC), path(0.50, 0.50, oi=900, vol=100)),
]


def main() -> None:
    body = {"schema": "market-points-v1", "source": "fixture", "synthetic": True, "captured_at": None,
            "note": "SYNTHETIC FIXTURES: invented for tests and the offline demo. Not market data.",
            "markets": [{"market_id": mid, "series_id": s, "question": q, "status": st, "open_time": "2026-08-01T00:00:00Z", "close_time": c.isoformat().replace("+00:00", "Z"),
                         "source_url": None, "points": pts} for mid, s, q, st, c, pts in MARKETS]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(body, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(MARKETS)} synthetic markets)")


if __name__ == "__main__":
    main()
