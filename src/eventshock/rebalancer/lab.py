"""The strategy lab: the same replay window, the same prices, the same costs and the same placebo for every strategy, so they can be compared on equal terms.

Strategies are the baseline sentiment rule, the experimental alternatives (risk limits; sentiment x impact) and two references that do not tilt: **equal weight** (rebalanced to equal
at every close, which is the benchmark) and **buy and hold** (equal weight at the start, then left to drift, no trading). Each is simulated by ``backtest._simulate`` (point-in-time weights,
close-to-close returns, one-way cost on turnover from the drifted weights) and reported with return, volatility, drawdown, hit rate, turnover, cost, rank-IC, windows and a placebo that
shuffles its own scores across companies. A sensitivity grid re-runs the baseline over half-lives, turnover caps, tilts and position limits, and the cost is varied.

Ten sessions cannot separate luck from skill. Nothing here is a claim of skill: the verdict is *computed* from the placebo and is "within the placebo range" unless the real result
falls outside the 5th-95th percentile of the shuffled runs. Prices are not redistributed; the committed file holds only derived series and the sha256 of each price file read.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from pydantic import Field

from ..domain.base import ContractModel
from .backtest import (
    PLACEBO_SEED,
    Sessions,
    _compound,
    _mean_ic,
    _quantile,
    _simulate,
    load_sessions,
    timeline_digest,
)
from .config import DEFAULT_STRATEGY
from .models import RebalancerParams
from .service import RebalancerService
from .weights import turnover

VERSION = "rebalancer-lab-v1"
TRADING_DAYS = 252
ROLLING = 5
HALF_LIVES = [12.0, 24.0, 36.0, 72.0, 144.0]
TURNOVER_CAPS = [0.02, 0.04, 0.08]
TILTS = [1.0, 2.0, 4.0]
POSITION_LIMITS = [0.25, 0.5]   # max_active_ratio: how far a stock may sit from its benchmark weight
COSTS_BPS = [0.0, 5.0, 10.0, 25.0]
REFERENCES = {"equal_weight": ("Equal weight (benchmark)", "Rebalanced to equal weight at every close; pays the cost of the weight drift it has to undo."),
              "buy_and_hold": ("Buy and hold", "Equal weight at the start of the window, then never traded: no turnover, no cost.")}

CAVEATS = [
    "About ten trading sessions: the comparison shows how the mechanics behave, it cannot show that any strategy earns anything. A difference between strategies is not evidence.",
    "Every verdict is computed from a shuffled-score placebo: 'within the placebo range' means the result is what chance gives for this window.",
    "Annualised volatility is the ten-day standard deviation scaled by sqrt(252); it is a rough indication only. Costs are an illustrative one-way rate; no spreads, impact or taxes.",
    "The risk-limit strategy and the impact strategy are experiments with their parameters fixed in configs/rebalancer.yaml before any result existed; the impact model is itself experimental "
    "and a report's impact has no direction. They are never promoted to the baseline on the strength of this window.",
    "The sensitivity grid tries 21 settings. About two of them would fall outside their own 5th-95th placebo range by chance alone, so the best cell is the luckiest cell, not a recommendation: "
    "choosing it would be choosing after seeing the result. The shipped parameters were fixed before any result existed and are not changed by this grid.",
    "The benchmark is equal weight: the repo holds no market-cap data.",
]


class LabWindow(ContractModel):
    label: str
    start: str
    end: str
    sessions: int
    strategy_return: float
    benchmark_return: float
    active_return: float


class LabMetrics(ContractModel):
    cumulative_return: float
    benchmark_return: float
    active_return: float = Field(description="cumulative return minus the equal-weight benchmark's, in return points")
    annualised_vol: float | None = Field(description="daily standard deviation x sqrt(252); null with fewer than three sessions")
    max_drawdown: float = Field(description="the deepest fall from a previous peak of the cumulative net return (zero or negative)")
    hit_rate: float | None = Field(description="share of sessions on which the strategy's net return beat the benchmark's; null for the benchmark itself")
    mean_daily_turnover: float
    total_cost: float
    rank_ic: float | None


class LabPlacebo(ContractModel):
    runs: int
    active_return_p05: float
    active_return_p50: float
    active_return_p95: float
    active_return_percentile: float
    ic_percentile: float


class LabStrategy(ContractModel):
    id: str
    label: str
    description: str
    kind: str = Field(description="TILT (a strategy the service serves) | REFERENCE (equal weight, buy and hold)")
    experimental: bool
    daily_net: list[float]
    cumulative: list[float]
    drawdown: list[float]
    turnover: list[float]
    metrics: LabMetrics
    windows: list[LabWindow]
    windows_positive: int = Field(description="of the rolling windows, how many ended ahead of the benchmark")
    windows_total: int
    placebo: LabPlacebo | None
    verdict: str | None = Field(description="WITHIN_PLACEBO_RANGE | ABOVE_PLACEBO_RANGE | BELOW_PLACEBO_RANGE, computed from the placebo; null for references")
    timeline_sha256: str | None = Field(description="digest of the weight path this was built from; a mismatch with today's marks the lab stale")


class LabCell(ContractModel):
    half_life_hours: float
    max_turnover: float
    tilt: float
    max_active_ratio: float
    active_return: float
    rank_ic: float | None
    placebo_percentile: float
    mean_daily_turnover: float


class LabGrid(ContractModel):
    half_life_by_turnover: list[LabCell]
    tilt_by_position_limit: list[LabCell]
    cells_total: int
    cells_positive: int = Field(description="cells whose active return is above zero")
    cells_outside_placebo_range: int = Field(description="cells whose active return is above the 95th or below the 5th percentile of their own shuffled-score runs")
    expected_outside_by_chance: float = Field(description="how many of that many cells would be outside the 5th-95th range by chance alone (10 % of them)")
    active_min: float
    active_max: float
    placebo_runs: int


class LabCost(ContractModel):
    cost_bps: float
    strategy_return: float
    benchmark_return: float
    active_return: float


class RebalancerLab(ContractModel):
    version: str
    params: RebalancerParams
    cost_bps: float
    tickers: list[str]
    dates: list[str]
    strategies: list[LabStrategy]
    grid: LabGrid
    cost_sensitivity: list[LabCost]
    impact_reports: int = Field(description="reports in the window that carry an impact score")
    reports_used: int
    inputs: dict[str, str]
    caveats: list[str]


class RebalancerLabView(ContractModel):
    status: str = Field(description="AVAILABLE | STALE | UNAVAILABLE")
    reason: str | None = None
    lab: RebalancerLab | None = None


# ----------------------------------------------------------------------------------------------------------------------------------- metrics
def verdict_of(percentile: float) -> str:
    if percentile >= 0.95:
        return "ABOVE_PLACEBO_RANGE"
    if percentile <= 0.05:
        return "BELOW_PLACEBO_RANGE"
    return "WITHIN_PLACEBO_RANGE"


def drawdown(net: list[float]) -> list[float]:
    wealth, peak, out = 1.0, 1.0, []
    for r in net:
        wealth *= 1 + r
        peak = max(peak, wealth)
        out.append(wealth / peak - 1)
    return out


def _std(xs: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _total(xs: list[float]) -> float:
    return _compound(xs)[-1] if xs else 0.0


def windows(dates: list[str], net: list[float], bench: list[float]) -> tuple[list[LabWindow], int, int]:
    n = len(net)
    spans = [("full window", 0, n), ("first half", 0, n // 2), ("second half", n // 2, n)]
    rolling = [(f"{ROLLING}-session window from {dates[i]}", i, i + ROLLING) for i in range(0, n - ROLLING + 1)] if n >= ROLLING else []
    out = []
    for label, a, b in spans + rolling:
        if b - a < 1:
            continue
        s, k = _total(net[a:b]), _total(bench[a:b])
        out.append(LabWindow(label=label, start=dates[a], end=dates[b - 1], sessions=b - a, strategy_return=s, benchmark_return=k, active_return=s - k))
    roll = [w for w in out if "-session window" in w.label]
    return out, sum(1 for w in roll if w.active_return > 0), len(roll)


def _metrics(net: list[float], bench: list[float], tov: list[float], cost: list[float], ic: list[float | None], is_benchmark: bool) -> LabMetrics:
    s, k = _total(net), _total(bench)
    sd = _std(net)
    return LabMetrics(
        cumulative_return=s, benchmark_return=k, active_return=s - k, annualised_vol=None if sd is None else sd * math.sqrt(TRADING_DAYS), max_drawdown=min(drawdown(net), default=0.0),
        hit_rate=None if is_benchmark else sum(1 for a, b in zip(net, bench, strict=True) if a > b) / len(net), mean_daily_turnover=sum(tov) / len(tov), total_cost=sum(cost),
        rank_ic=_mean_ic(ic))


def _pct(xs: list[float], v: float) -> float:
    return sum(1 for x in xs if x <= v) / len(xs)


# ---------------------------------------------------------------------------------------------------------------------------------- one run
def _placebo(service: RebalancerService, params: RebalancerParams, strategy: str, s_rows: list[list[float]], ss: Sessions, bench: list[float], cost_bps: float, runs: int,
             real_active: float, real_ic: float | None) -> LabPlacebo:
    n = len(bench)
    act, ics = [], []
    for k in range(runs):
        perm = list(range(n))
        random.Random(PLACEBO_SEED + k).shuffle(perm)
        shuffled = [[row[perm[i]] for i in range(n)] for row in s_rows]
        path = service.path(shuffled, params, strategy)
        pw = [p[1].weights for p in path]
        run = _simulate([pw[j] for j in ss.cycle_index], [shuffled[j] for j in ss.cycle_index], ss.returns, bench, cost_bps)
        act.append(_total(run.net) - _total(run.benchmark))
        ics.append(_mean_ic(run.ic) or 0.0)
    return LabPlacebo(runs=runs, active_return_p05=_quantile(act, 0.05), active_return_p50=_quantile(act, 0.5), active_return_p95=_quantile(act, 0.95),
                      active_return_percentile=_pct(act, real_active), ic_percentile=_pct(ics, real_ic if real_ic is not None else 0.0))


def _tilt_strategy(service: RebalancerService, sid: str, params: RebalancerParams, ss: Sessions, bench: list[float], cost_bps: float, runs: int) -> LabStrategy:
    tl = service.timeline(params, strategy=sid)
    w_rows, s_rows = [c.weights for c in tl.cycles], [c.scores for c in tl.cycles]
    run = _simulate([w_rows[j] for j in ss.cycle_index], [s_rows[j] for j in ss.cycle_index], ss.returns, bench, cost_bps)
    m = _metrics(run.net, run.benchmark, run.turnover, run.cost, run.ic, False)
    w, pos, tot = windows(ss.dates, run.net, run.benchmark)
    plc = _placebo(service, params, sid, s_rows, ss, bench, cost_bps, runs, m.active_return, m.rank_ic)
    info = service.cfg.strategies[sid]
    return LabStrategy(id=sid, label=info.label, description=info.description, kind="TILT", experimental=sid != DEFAULT_STRATEGY, daily_net=run.net, cumulative=_compound(run.net),
                       drawdown=drawdown(run.net), turnover=run.turnover, metrics=m, windows=w, windows_positive=pos, windows_total=tot, placebo=plc,
                       verdict=verdict_of(plc.active_return_percentile), timeline_sha256=timeline_digest(w_rows, params))


def _reference(sid: str, ss: Sessions, bench: list[float], cost_bps: float) -> LabStrategy:
    label, desc = REFERENCES[sid]
    n = len(bench)
    ew = _simulate([bench] * len(ss.returns), [[0.0] * n] * len(ss.returns), ss.returns, bench, cost_bps)
    if sid == "equal_weight":
        net, tov, cost = ew.net, ew.turnover, ew.cost
    else:   # buy and hold: equal weight on day one, then the weights drift; nothing is traded, so nothing is paid
        w, net = list(bench), []
        for r in ss.returns:
            g = sum(wi * ri for wi, ri in zip(w, r, strict=True))
            net.append(g)
            w = [wi * (1 + ri) / (1 + g) for wi, ri in zip(w, r, strict=True)]
        tov, cost = [0.0] * len(net), [0.0] * len(net)
    m = _metrics(net, ew.net, tov, cost, [None] * len(net), sid == "equal_weight")
    w_, pos, tot = windows(ss.dates, net, ew.net)
    return LabStrategy(id=sid, label=label, description=desc, kind="REFERENCE", experimental=False, daily_net=net, cumulative=_compound(net), drawdown=drawdown(net), turnover=tov,
                       metrics=m, windows=w_, windows_positive=pos, windows_total=tot, placebo=None, verdict=None, timeline_sha256=None)


def _cell(service: RebalancerService, params: RebalancerParams, ss: Sessions, bench: list[float], cost_bps: float, runs: int, ratio: float) -> LabCell:
    tl = service.timeline(params)
    w_rows, s_rows = [c.weights for c in tl.cycles], [c.scores for c in tl.cycles]
    run = _simulate([w_rows[j] for j in ss.cycle_index], [s_rows[j] for j in ss.cycle_index], ss.returns, bench, cost_bps)
    active, ic = _total(run.net) - _total(run.benchmark), _mean_ic(run.ic)
    plc = _placebo(service, params, DEFAULT_STRATEGY, s_rows, ss, bench, cost_bps, runs, active, ic)
    return LabCell(half_life_hours=params.half_life_hours, max_turnover=params.max_turnover, tilt=params.tilt, max_active_ratio=ratio, active_return=active, rank_ic=ic,
                   placebo_percentile=plc.active_return_percentile, mean_daily_turnover=sum(run.turnover) / len(run.turnover))


# ------------------------------------------------------------------------------------------------------------------------------------ build
def build(service: RebalancerService, prices_dir: Path, *, placebo_runs: int = 200, grid_placebo_runs: int = 100) -> RebalancerLab:
    """Run the whole lab at the shipped configuration. Raises loudly if a price file or a session is missing."""
    params = service.default_params()
    base_tl = service.timeline(params)
    if len(base_tl.cycles) < 2:
        raise ValueError("there are no cycles to back-test")
    ss = load_sessions(service, base_tl, prices_dir)
    n = service.cfg.n
    bench = [service.cfg.benchmark_weight] * n
    cost_bps = service.cfg.turnover.cost_bps

    strategies = [_tilt_strategy(service, sid, params, ss, bench, cost_bps, placebo_runs) for sid in service.cfg.strategies if service.resolve_strategy(sid)]
    strategies += [_reference(sid, ss, bench, cost_bps) for sid in REFERENCES]

    d = service.default_params()
    ratio_default = service.cfg.bounds.max_active_ratio
    hl_to = [_cell(service, service.resolve_params(tilt=d.tilt, half_life_hours=h, max_turnover=m), ss, bench, cost_bps, grid_placebo_runs, ratio_default)
             for h in HALF_LIVES for m in TURNOVER_CAPS]
    tilt_lim = []
    for ratio in POSITION_LIMITS:
        svc = service if ratio == ratio_default else service.with_overrides({"bounds.max_active_ratio": ratio})
        for t in TILTS:
            tilt_lim.append(_cell(svc, svc.resolve_params(tilt=t, half_life_hours=d.half_life_hours, max_turnover=d.max_turnover), ss, bench, cost_bps, grid_placebo_runs, ratio))
    cells = hl_to + tilt_lim
    outside = sum(1 for c in cells if c.placebo_percentile >= 0.95 or c.placebo_percentile <= 0.05)
    grid = LabGrid(half_life_by_turnover=hl_to, tilt_by_position_limit=tilt_lim, cells_total=len(cells), cells_positive=sum(1 for c in cells if c.active_return > 0),
                   cells_outside_placebo_range=outside, expected_outside_by_chance=0.10 * len(cells),
                   active_min=min(c.active_return for c in cells), active_max=max(c.active_return for c in cells), placebo_runs=grid_placebo_runs)

    w_rows = [c.weights for c in base_tl.cycles]
    w_in = [w_rows[j] for j in ss.cycle_index]
    s_in = [base_tl.cycles[j].scores for j in ss.cycle_index]
    costs = []
    for bps in COSTS_BPS:
        run = _simulate(w_in, s_in, ss.returns, bench, bps)
        costs.append(LabCost(cost_bps=bps, strategy_return=_total(run.net), benchmark_return=_total(run.benchmark), active_return=_total(run.net) - _total(run.benchmark)))
    with_impact, total = service.impact_coverage()
    return RebalancerLab(version=VERSION, params=params, cost_bps=cost_bps, tickers=base_tl.tickers, dates=ss.dates, strategies=strategies, grid=grid, cost_sensitivity=costs,
                         impact_reports=with_impact, reports_used=total, inputs=ss.inputs, caveats=CAVEATS)


def load_view(service: RebalancerService, path: Path) -> RebalancerLabView:
    """AVAILABLE when the committed lab was built from the weights the service serves today; STALE (still shown) when any strategy's weight path differs; UNAVAILABLE when absent or invalid."""
    if not path.is_file():
        return RebalancerLabView(status="UNAVAILABLE", reason="the lab has not been built (make rebalancer-lab; it reads price files that are not redistributed)")
    try:
        lab = RebalancerLab.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return RebalancerLabView(status="UNAVAILABLE", reason=f"the lab file is not valid: {str(exc).splitlines()[0]}")
    for s in lab.strategies:
        if s.timeline_sha256 is None:
            continue
        try:
            tl = service.timeline(lab.params, strategy=s.id)
        except ValueError as exc:
            return RebalancerLabView(status="STALE", reason=f"strategy '{s.id}' can no longer be served: {exc}", lab=lab)
        if timeline_digest([c.weights for c in tl.cycles], lab.params) != s.timeline_sha256:
            return RebalancerLabView(status="STALE", reason=f"the weights of strategy '{s.id}' differ from the ones the lab was built from; rebuild it (make rebalancer-lab)", lab=lab)
    return RebalancerLabView(status="AVAILABLE", lab=lab)


__all__ = ["RebalancerLab", "RebalancerLabView", "build", "load_view", "turnover"]
