"""Build data/rebalancer/lab.json: every Module A strategy on the replay window with the same prices, costs and placebo, plus windows, a sensitivity grid and cost sensitivity.

Reads the git-ignored price files (`make fetch-prices`) and writes only derived series plus the sha256 of every file read. Deterministic. Needs data/rebalancer/risk_inputs.json
(`make rebalancer-risk-inputs`) for the risk-limit strategy. The strategies' parameters are fixed in configs/rebalancer.yaml; do not retune them to what this prints.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eventshock.api.deps import build_container
from eventshock.config import REPO_ROOT, Settings
from eventshock.rebalancer.lab import build

OUT = REPO_ROOT / "data" / "rebalancer" / "lab.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prices", type=Path, default=REPO_ROOT / "data" / "raw" / "prices")
    ap.add_argument("--placebo-runs", type=int, default=200)
    ap.add_argument("--grid-placebo-runs", type=int, default=100)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    if not (a.prices / "_GSPC.csv").is_file():
        raise SystemExit(f"no price files under {a.prices}: run `make fetch-prices` first (they are git-ignored on purpose)")
    c = build_container(Settings(profile="replay"))
    if c.rebalancer is None:
        raise SystemExit("the rebalancer needs the replay profile")
    lab = build(c.rebalancer, a.prices, placebo_runs=a.placebo_runs, grid_placebo_runs=a.grid_placebo_runs)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(lab.model_dump_json(indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.out}: {len(lab.dates)} sessions {lab.dates[0]}..{lab.dates[-1]}; impact score on {lab.impact_reports}/{lab.reports_used} reports")
    for s in lab.strategies:
        m = s.metrics
        plc = "" if s.placebo is None else f"  placebo pct {s.placebo.active_return_percentile:.2f} {s.verdict}"
        print(f"  {s.id:18s} return {m.cumulative_return:+.3%}  active {m.active_return:+.3%}  maxDD {m.max_drawdown:.3%}  turnover/day {m.mean_daily_turnover:.4f}{plc}")
    g = lab.grid
    print(f"  grid: {g.cells_positive}/{g.cells_total} cells ahead of the benchmark; active return {g.active_min:+.3%} .. {g.active_max:+.3%}")


if __name__ == "__main__":
    main()
