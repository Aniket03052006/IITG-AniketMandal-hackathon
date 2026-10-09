"""An illustration of the mechanics, not evidence of skill: what the rebalanced index would have returned against the equal-weight benchmark over the replay window.

Point-in-time: the weights in force during session d are the weights of the last cycle at or before the CLOSE of session d-1 (16:00 America/New_York), so no
report published after that close touches session d. Returns are close-to-close adjusted prices. Both the index and the benchmark are charged ``cost_bps`` on
the one-way turnover from the (drifted) weights they held at the previous close to the weights they hold for the session, so a tilt that trades more pays more.

Two controls sit beside the result because ten sessions cannot tell luck from skill by themselves: the **rank information coefficient** (does a higher score precede a
higher next-session return, across the 15 stocks?) and a **placebo** that repeats the whole run with the scores shuffled across tickers (same scores, same timing,
wrong company), so the real number can be read against what pure chance gives for this window. Prices are not redistributed: this module reads them, the committed
file holds only derived series and the sha256 of every price file used.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field

from ..domain.base import ContractModel
from .models import RebalancerParams
from .service import RebalancerService
from .weights import turnover

VERSION = "rebalancer-backtest-v1"
NY = ZoneInfo("America/New_York")
CLOSE = time(16, 0)
PLACEBO_SEED = 20260101
MARKET = "^GSPC"

CAVEATS = [
    "About ten trading sessions: this shows how the mechanics behave, it cannot show that sentiment tilting earns anything. Do not read the active return as skill.",
    "The score at each close is built from news headlines the engine could name; the realised return that follows is one number per stock per day, dominated by market and sector moves.",
    "Costs are an illustrative one-way rate on turnover; no spreads, impact or taxes. Weights are reset to the target at each close (no intra-day drift).",
]


class RebalancerBacktestSummary(ContractModel):
    rebalanced_return: float = Field(description="compounded net return of the rebalanced index over the window")
    benchmark_return: float = Field(description="compounded net return of the equal-weight benchmark")
    active_return: float = Field(description="rebalanced minus benchmark, in return points (not compounded active)")
    daily_active_mean: float
    daily_active_std: float | None = Field(description="null with fewer than three sessions")
    mean_daily_turnover: float
    total_cost: float = Field(description="sum of daily costs charged to the rebalanced index, in return points")


class RebalancerRankIC(ContractModel):
    mean: float | None
    daily: list[float | None] = Field(description="Spearman correlation of the score at the previous close with the next session's return, across the stocks; null on a day with no variation")
    days: int


class RebalancerPlacebo(ContractModel):
    runs: int
    seed: int
    active_return_p05: float
    active_return_p50: float
    active_return_p95: float
    mean_ic_p05: float
    mean_ic_p50: float
    mean_ic_p95: float
    active_return_percentile: float = Field(description="share of placebo runs whose active return is at or below the real one")
    ic_percentile: float = Field(description="share of placebo runs whose mean IC is at or below the real one")


class RebalancerBacktest(ContractModel):
    version: str
    params: RebalancerParams
    cost_bps: float
    tickers: list[str]
    dates: list[str] = Field(description="the sessions, oldest first")
    rebalanced: list[float] = Field(description="daily net return of the rebalanced index")
    benchmark: list[float] = Field(description="daily net return of the equal-weight benchmark")
    cumulative_rebalanced: list[float]
    cumulative_benchmark: list[float]
    turnover: list[float] = Field(description="one-way turnover into each session's weights")
    summary: RebalancerBacktestSummary
    rank_ic: RebalancerRankIC
    placebo: RebalancerPlacebo
    inputs: dict[str, str] = Field(description="sha256 of each price file read")
    timeline_sha256: str = Field(description="digest of the weight path the result was built from; a mismatch with the live timeline marks the file stale")
    caveats: list[str]


class RebalancerBacktestView(ContractModel):
    status: str = Field(description="AVAILABLE | STALE | UNAVAILABLE")
    reason: str | None = None
    backtest: RebalancerBacktest | None = None


def timeline_digest(weights: list[list[float]], params: RebalancerParams) -> str:
    payload = json.dumps({"p": [params.tilt, params.half_life_hours, params.max_turnover], "w": [[round(x, 12) for x in row] for row in weights]}, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


# ----------------------------------------------------------------------------------------------------------------------------------- helpers
def _read_closes(path: Path) -> dict[str, float]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["date"]: float(r["adj_close"]) for r in csv.DictReader(fh) if r.get("adj_close") and float(r["adj_close"]) > 0}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decision_time(session_date: str) -> datetime:
    y, m, d = (int(x) for x in session_date.split("-"))
    return datetime(y, m, d, CLOSE.hour, CLOSE.minute, tzinfo=NY).astimezone(UTC)


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    """Rank correlation, or None when either side has no variation (a correlation is undefined, not zero)."""
    if len(a) != len(b) or len(a) < 3:
        raise ValueError("spearman needs two series of the same length, at least three long")
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True)) / math.sqrt(va * vb)


def _quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    pos = q * (len(s) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


@dataclass
class _Run:
    net: list[float]
    benchmark: list[float]
    turnover: list[float]
    cost: list[float]
    ic: list[float | None]


def _simulate(weights_at: list[list[float]], scores_at: list[list[float]], returns: list[list[float]], bench: list[float], cost_bps: float) -> _Run:
    """One pass over the sessions. ``weights_at[d]`` / ``scores_at[d]`` are those in force for session d; ``returns[d]`` the stocks' returns that session."""
    cost = cost_bps / 1e4
    drift_p = list(bench)   # what the index holds going into the first session: the benchmark
    drift_b = list(bench)
    net, ben, tov, costs, ic = [], [], [], [], []
    for w, sc, r in zip(weights_at, scores_at, returns, strict=True):
        gross = sum(wi * ri for wi, ri in zip(w, r, strict=True))
        t = turnover(drift_p, w)
        net.append(gross - cost * t)
        bgross = sum(bi * ri for bi, ri in zip(bench, r, strict=True))
        ben.append(bgross - cost * turnover(drift_b, bench))
        tov.append(t)
        costs.append(cost * t)
        ic.append(spearman(sc, r))
        drift_p = [wi * (1 + ri) / (1 + gross) for wi, ri in zip(w, r, strict=True)]
        drift_b = [bi * (1 + ri) / (1 + bgross) for bi, ri in zip(bench, r, strict=True)]
    return _Run(net, ben, tov, costs, ic)


def _compound(xs: list[float]) -> list[float]:
    out, acc = [], 1.0
    for x in xs:
        acc *= 1 + x
        out.append(acc - 1)
    return out


def _mean_ic(ic: list[float | None]) -> float | None:
    v = [x for x in ic if x is not None]
    return sum(v) / len(v) if v else None


@dataclass(frozen=True)
class Sessions:
    dates: list[str]                 # the sessions whose point-in-time decision lies inside the replay window, oldest first
    returns: list[list[float]]       # per session, the stocks' close-to-close adjusted returns, in ticker order
    cycle_index: list[int]           # per session, the cycle whose weights were in force (the last at or before the previous close)
    inputs: dict[str, str]           # sha256 of each price file read


def load_sessions(service: RebalancerService, tl, prices_dir: Path) -> Sessions:  # noqa: ANN001
    """Align the cycles with the price calendar. The grid does not depend on the strategy, so one result serves every strategy. Raises on a hole in the data."""
    tickers = tl.tickers
    cal = _read_closes(prices_dir / "_GSPC.csv")
    series = {t: _read_closes(prices_dir / f"{t}.csv") for t in tickers}
    inputs = {f"{t}.csv": _sha(prices_dir / f"{t}.csv") for t in tickers} | {"_GSPC.csv": _sha(prices_dir / "_GSPC.csv")}
    dates = sorted(cal)
    first, last = tl.cycles[0].at, tl.cycles[-1].at
    cycle_times = [c.at for c in tl.cycles]
    sessions, returns, idx = [], [], []
    for k in range(1, len(dates)):
        prev, d = dates[k - 1], dates[k]
        t = _decision_time(prev)
        if t < first or t > last:
            continue
        j = max(i for i, at in enumerate(cycle_times) if at <= t)   # the last cycle at or before the close
        for tk in tickers:
            if prev not in series[tk] or d not in series[tk]:
                raise ValueError(f"{tk} has no price on {prev} or {d}: refusing to back-test with a hole in the data")
        sessions.append(d)
        returns.append([series[tk][d] / series[tk][prev] - 1 for tk in tickers])
        idx.append(j)
    if len(sessions) < 2:
        raise ValueError("fewer than two trading sessions fall inside the replay window")
    return Sessions(sessions, returns, idx, inputs)


# ------------------------------------------------------------------------------------------------------------------------------------- build
def build(service: RebalancerService, prices_dir: Path, *, placebo_runs: int = 200) -> RebalancerBacktest:
    """Run the backtest at the shipped parameters. Raises ``FileNotFoundError`` / ``ValueError`` loudly if a price file or a session is missing."""
    params = service.default_params()
    tl = service.timeline(params)
    if len(tl.cycles) < 2:
        raise ValueError("there are no cycles to back-test")
    tickers = tl.tickers
    ss = load_sessions(service, tl, prices_dir)
    sessions, returns, idx, inputs = ss.dates, ss.returns, ss.cycle_index, ss.inputs
    n = len(tickers)
    bench = [service.cfg.benchmark_weight] * n
    w_rows = [c.weights for c in tl.cycles]
    s_rows = [c.scores for c in tl.cycles]
    w_in = [w_rows[j] for j in idx]
    s_in = [s_rows[j] for j in idx]

    real = _simulate(w_in, s_in, returns, bench, service.cfg.turnover.cost_bps)
    cum_p, cum_b = _compound(real.net), _compound(real.benchmark)
    active_daily = [a - b for a, b in zip(real.net, real.benchmark, strict=True)]
    m = sum(active_daily) / len(active_daily)
    sd = math.sqrt(sum((x - m) ** 2 for x in active_daily) / (len(active_daily) - 1)) if len(active_daily) >= 3 else None
    real_active = cum_p[-1] - cum_b[-1]
    real_ic = _mean_ic(real.ic)

    # placebo: the same scores in the same cycles, assigned to the wrong companies (one fixed shuffle per run)
    act_p, ic_p = [], []
    for k in range(placebo_runs):
        perm = list(range(n))
        random.Random(PLACEBO_SEED + k).shuffle(perm)
        shuffled = [[row[perm[i]] for i in range(n)] for row in s_rows]
        path = service.path(shuffled, params)
        pw, ps = [p[1].weights for p in path], shuffled
        run = _simulate([pw[j] for j in idx], [ps[j] for j in idx], returns, bench, service.cfg.turnover.cost_bps)
        c1, c2 = _compound(run.net), _compound(run.benchmark)
        act_p.append(c1[-1] - c2[-1])
        ic_p.append(_mean_ic(run.ic) or 0.0)

    def pct(xs: list[float], v: float) -> float:
        return sum(1 for x in xs if x <= v) / len(xs)

    return RebalancerBacktest(
        version=VERSION, params=params, cost_bps=service.cfg.turnover.cost_bps, tickers=tickers, dates=sessions, rebalanced=real.net, benchmark=real.benchmark,
        cumulative_rebalanced=cum_p, cumulative_benchmark=cum_b, turnover=real.turnover,
        summary=RebalancerBacktestSummary(rebalanced_return=cum_p[-1], benchmark_return=cum_b[-1], active_return=real_active, daily_active_mean=m, daily_active_std=sd,
                                mean_daily_turnover=sum(real.turnover) / len(real.turnover), total_cost=sum(real.cost)),
        rank_ic=RebalancerRankIC(mean=real_ic, daily=real.ic, days=sum(1 for x in real.ic if x is not None)),
        placebo=RebalancerPlacebo(runs=placebo_runs, seed=PLACEBO_SEED, active_return_p05=_quantile(act_p, 0.05), active_return_p50=_quantile(act_p, 0.5), active_return_p95=_quantile(act_p, 0.95),
                        mean_ic_p05=_quantile(ic_p, 0.05), mean_ic_p50=_quantile(ic_p, 0.5), mean_ic_p95=_quantile(ic_p, 0.95),
                        active_return_percentile=pct(act_p, real_active), ic_percentile=pct(ic_p, real_ic if real_ic is not None else 0.0)),
        inputs=inputs, timeline_sha256=timeline_digest(w_rows, params), caveats=CAVEATS)


def load_view(service: RebalancerService, path: Path) -> RebalancerBacktestView:
    """The committed backtest, or an explicit reason it cannot be shown. A file built from a different weight path than the one now served is STALE (still returned, flagged)."""
    if not path.is_file():
        return RebalancerBacktestView(status="UNAVAILABLE", reason="no backtest has been built: `make rebalancer-backtest` (it reads the git-ignored price files; nothing is invented to fill the gap)")
    try:
        bt = RebalancerBacktest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return RebalancerBacktestView(status="UNAVAILABLE", reason=f"{path.name} is not a valid backtest file ({str(exc).splitlines()[0]}); rebuild it with `make rebalancer-backtest`")
    tl = service.timeline(service.default_params())
    if timeline_digest([c.weights for c in tl.cycles], tl.params) != bt.timeline_sha256:
        return RebalancerBacktestView(status="STALE", reason="the weights now served differ from the ones this backtest was built from (signals, models or configuration changed): rebuild it with `make rebalancer-backtest`",
                            backtest=bt)
    return RebalancerBacktestView(status="AVAILABLE", backtest=bt)
