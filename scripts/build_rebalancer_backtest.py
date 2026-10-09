"""Build data/rebalancer/backtest.json: the rebalanced index against the equal-weight benchmark over the replay window, with the rank-IC and a shuffled-score placebo.

Reads the git-ignored price files (`make fetch-prices`; Yahoo data is not redistributed) and writes only derived series plus the sha256 of every file read. Deterministic.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eventshock.api.deps import build_container
from eventshock.config import REPO_ROOT, Settings
from eventshock.rebalancer.backtest import build

OUT = REPO_ROOT / "data" / "rebalancer" / "backtest.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prices", type=Path, default=REPO_ROOT / "data" / "raw" / "prices")
    ap.add_argument("--placebo-runs", type=int, default=200)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    if not (a.prices / "_GSPC.csv").is_file():
        raise SystemExit(f"no price files under {a.prices}: run `make fetch-prices` first (they are git-ignored on purpose)")
    c = build_container(Settings(profile="replay"))
    if c.rebalancer is None:
        raise SystemExit("the rebalancer needs the replay profile")
    bt = build(c.rebalancer, a.prices, placebo_runs=a.placebo_runs)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(bt.model_dump_json(indent=1) + "\n", encoding="utf-8")
    s = bt.summary
    print(f"wrote {a.out.relative_to(REPO_ROOT)}: {len(bt.dates)} sessions {bt.dates[0]}..{bt.dates[-1]}")
    print(f"  rebalanced {s.rebalanced_return:+.4%}  benchmark {s.benchmark_return:+.4%}  active {s.active_return:+.4%}  mean turnover/day {s.mean_daily_turnover:.4f}")
    print(f"  rank IC mean {bt.rank_ic.mean if bt.rank_ic.mean is None else round(bt.rank_ic.mean, 4)} over {bt.rank_ic.days} days; "
          f"placebo active p05..p95 [{bt.placebo.active_return_p05:+.4%}, {bt.placebo.active_return_p95:+.4%}], real at percentile {bt.placebo.active_return_percentile:.2f}")


if __name__ == "__main__":
    main()
