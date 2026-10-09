"""Build data/rebalancer/risk_inputs.json: a volatility and an average daily dollar volume per stock of the mock index, both measured at the FIRST session of the frozen market context.

Volatility is read from data/replay/market/context.json (derived statistics, committed). Dollar volume (close x volume, mean of the last 60 sessions up to that date) is read from the
git-ignored price files; only the derived number and the sha256 of every file read are written. One early date for every cycle keeps the constraints static and point-in-time safe.
Deterministic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from eventshock.config import REPO_ROOT, Settings
from eventshock.rebalancer.config import load_rebalancer_config
from eventshock.rebalancer.risk import SCHEMA

OUT = REPO_ROOT / "data" / "rebalancer" / "risk_inputs.json"
CONTEXT = REPO_ROOT / "data" / "replay" / "market" / "context.json"
WINDOW = 60


def adv_usd(path: Path, as_of: str) -> float:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["date"] <= as_of and r.get("close") and r.get("volume")]
    rows = rows[-WINDOW:]
    if len(rows) < WINDOW:
        raise SystemExit(f"{path.name}: only {len(rows)} sessions up to {as_of}, need {WINDOW}")
    if rows[-1]["date"] != as_of:
        raise SystemExit(f"{path.name}: no session on {as_of}")
    return sum(float(r["close"]) * float(r["volume"]) for r in rows) / len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prices", type=Path, default=REPO_ROOT / "data" / "raw" / "prices")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    cfg = load_rebalancer_config(Settings().config_dir)
    ctx = json.loads(CONTEXT.read_text(encoding="utf-8"))
    sessions = sorted(next(iter(ctx["issuer"].values())))
    as_of = sessions[0]
    sigma, adv, hashes = {}, {}, {}
    for t in cfg.universe.tickers:
        if t not in ctx["issuer"] or as_of not in ctx["issuer"][t]:
            raise SystemExit(f"{t} has no market context on {as_of}")
        sigma[t] = round(float(ctx["issuer"][t][as_of]["sigma_60"]), 8)
        p = a.prices / f"{t}.csv"
        if not p.is_file():
            raise SystemExit(f"no price file {p}: run `make fetch-prices` first (they are git-ignored on purpose)")
        adv[t] = round(adv_usd(p, as_of), 2)
        hashes[f"{t}.csv"] = hashlib.sha256(p.read_bytes()).hexdigest()
    out = {"schema": SCHEMA, "note": "derived statistics only (no prices, no volumes); measured at one early date so the constraints they define are static and point-in-time safe",
           "sigma_as_of": as_of, "adv_as_of": as_of, "adv_window_sessions": WINDOW, "sigma_60": sigma, "adv_usd_60d": adv,
           "built_from": {"context_sha256": hashlib.sha256(CONTEXT.read_bytes()).hexdigest(), "price_files_sha256": hashes}}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.out.relative_to(REPO_ROOT)} as of {as_of}")
    for t in cfg.universe.tickers:
        print(f"  {t:6s} sigma_60 {sigma[t]:.4f}  ADV ${adv[t] / 1e9:6.2f} bn")


if __name__ == "__main__":
    main()
