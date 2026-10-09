"""``RebalancerService``: the mock index's weights over time, from the reports the engine has published.

REPLAY is a pure function: the cycle grid is fixed by configuration and the replay clock, the score at a cycle reads only reports published by then, and nothing
is written anywhere, so two runs (and a run after a restart) give the same answer. ``include_live`` also reads the live feed's reports (never pasted text), on the
same grid extended to the newest report; that is the "real-time" mode, and it is off by default so the index of record never moves because a live report arrived.

A cycle is: score every company -> tilt the benchmark by the scores -> project onto the bounds -> move toward that target by at most the turnover cap. The result
of every cycle is checked (sums to one, within bounds, within the cap) or the request fails: nothing is repaired silently.

A **strategy** (``configs/rebalancer.yaml: strategies``) is a closed combination of a score source and optional constraint sets (sector cap, volatility-aware upper bound,
liquidity floor). The default, ``sentiment``, is the baseline rule and is byte-identical to the version before strategies existed. For every cycle the service keeps the
*constraint ladder*: the projection of the tilt onto the constraints added one at a time, so each stock's weight can be explained by the rule that held it back.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..config_overrides import apply_overrides
from ..domain import Entity, RiskSignal
from ..domain.provenance import TRUSTED_TIMESTAMPS, StageOrigin
from ..store import CHANNEL_LIVE, CHANNEL_REPLAY, CombinedSignalRepository
from .config import DEFAULT_STRATEGY, RebalancerConfig, StrategySpec
from .models import (
    LABELS,
    LIMITATIONS,
    VERSION,
    ConstraintCode,
    ConstraintEffect,
    IndexConstituent,
    RebalanceCycle,
    RebalanceCycleDetail,
    RebalanceName,
    RebalancerOverview,
    RebalancerParams,
    RebalancerTimeline,
    ScoreDriver,
    StrategyInfo,
    WeightReason,
)
from .risk import RiskInputs, liquidity_upper_bounds, vol_upper_bounds
from .scoring import Report, Score, score
from .weights import Step, check_weights, project, project_grouped, step_toward, tilt_target, turnover

HALF_LIFE_MIN, HALF_LIFE_MAX = 1.0, 720.0
SENTIMENT_ORIGINS = frozenset({StageOrigin.MODEL, StageOrigin.SOURCE_LABEL})   # a trained model, or a human label that shipped with the source data
_MEMO = 24
_EPS = 1e-9
_TOL = 1e-9


@dataclass
class _Collected:
    by_ticker: dict[str, list[Report]]
    used: int
    excluded_untrusted: int
    excluded_other: int
    first: datetime | None
    last: datetime | None


@dataclass
class _Cycle:
    index: int
    at: datetime
    scores: list[Score]
    target: list[float]
    weights: list[float]
    stages: list[list[float]]   # the constraint ladder: [tilt, after bounds, after + each enabled rule ...]; the last is `target`
    step_status: str
    alpha: float
    traded: float
    wanted: float
    new_reports: int


@dataclass(frozen=True)
class _Stage:
    code: ConstraintCode | None   # None for the per-stock bounds, which are always on
    hi: list[float]               # cumulative upper bounds at this stage
    caps: list[float] | None      # sector caps when the sector rule is on at this stage


@dataclass(frozen=True)
class _Plan:
    spec: StrategySpec
    lo: list[float]
    stages: list[_Stage]
    groups: list[int]
    group_names: list[str]

    @property
    def hi(self) -> list[float]:
        return self.stages[-1].hi

    @property
    def caps(self) -> list[float] | None:
        return self.stages[-1].caps


def _floor(t: datetime, step_s: float) -> datetime:
    return datetime.fromtimestamp(math.floor(t.timestamp() / step_s) * step_s, UTC)


class RebalancerService:
    def __init__(self, cfg: RebalancerConfig, *, signals: CombinedSignalRepository, entities: Callable[[], list[Entity]], risk: RiskInputs | None = None) -> None:
        self.cfg = cfg
        self._signals = signals
        self._entities = entities
        self._risk = risk
        self._plans: dict[str, _Plan] = {}
        self._lock = threading.RLock()
        self._collected: tuple[tuple, _Collected] | None = None
        self._memo: OrderedDict[tuple, list[_Cycle]] = OrderedDict()
        self.tickers = list(cfg.universe.tickers)
        self._lo, self._hi = cfg.limits()
        self._bench = [cfg.benchmark_weight] * cfg.n
        self._constituents = self._build_constituents()

    # ----------------------------------------------------------------------------------------------------------------------------- construction
    def _build_constituents(self) -> list[IndexConstituent]:
        by_t = {e.ticker.upper(): e for e in self._entities() if e.ticker}
        missing = [t for t in self.tickers if t not in by_t]
        if missing:
            raise ValueError(f"rebalancer universe names tickers the entity master does not know: {', '.join(missing)}")
        return [IndexConstituent(ticker=t, name=by_t[t].name, sector=by_t[t].sector, benchmark_weight=self.cfg.benchmark_weight, lower=self._lo, upper=self._hi)
                for t in self.tickers]

    # ------------------------------------------------------------------------------------------------------------------------------ strategies
    def strategy_info(self) -> list[StrategyInfo]:
        out = []
        for sid, sp in self.cfg.strategies.items():
            reason = "needs data/rebalancer/risk_inputs.json (make rebalancer-risk-inputs)" if sp.needs_risk_inputs and self._risk is None else None
            out.append(StrategyInfo(id=sid, label=sp.label, description=sp.description, score=sp.score, sector_cap=sp.sector_cap, vol_limit=sp.vol_limit,
                                    liquidity_floor=sp.liquidity_floor, available=reason is None, reason=reason, experimental=sid != DEFAULT_STRATEGY))
        return out

    def resolve_strategy(self, strategy: str | None) -> str:
        """The strategy id, validated. Raises ``ValueError`` (the API answers 422) for an unknown or unavailable one."""
        sid = strategy or DEFAULT_STRATEGY
        spec = self.cfg.strategies.get(sid)
        if spec is None:
            raise ValueError(f"unknown strategy '{sid}' (choose one of: {', '.join(self.cfg.strategies)})")
        if spec.needs_risk_inputs and self._risk is None:
            raise ValueError(f"strategy '{sid}' needs data/rebalancer/risk_inputs.json, which has not been built (make rebalancer-risk-inputs)")
        return sid

    def plan(self, strategy: str | None = None) -> _Plan:
        sid = self.resolve_strategy(strategy)
        with self._lock:
            cached = self._plans.get(sid)
        if cached is not None:
            return cached
        spec = self.cfg.strategies[sid]
        n = self.cfg.n
        sectors = [c.sector for c in self._constituents]
        names = sorted(set(sectors))
        groups = [names.index(x) for x in sectors]
        caps = [min(1.0, (sectors.count(g) / n) * (1.0 + self.cfg.risk.sector_cap.ratio)) for g in names] if spec.sector_cap else None
        hi = [self._hi] * n
        stages = [_Stage(None, list(hi), None)]
        if spec.sector_cap:
            stages.append(_Stage(ConstraintCode.SECTOR_CAP, list(hi), caps))
        if spec.vol_limit:
            assert self._risk is not None
            hi = [min(a, b) for a, b in zip(hi, vol_upper_bounds(self.cfg, self._risk, self.tickers, self._hi), strict=True)]
            stages.append(_Stage(ConstraintCode.VOL_LIMIT, list(hi), caps))
        if spec.liquidity_floor:
            assert self._risk is not None
            hi = [min(a, b) for a, b in zip(hi, liquidity_upper_bounds(self.cfg, self._risk, self.tickers, self._hi), strict=True)]
            stages.append(_Stage(ConstraintCode.LIQUIDITY_FLOOR, list(hi), caps))
        plan = _Plan(spec, [self._lo] * n, stages, groups, names)
        for st in stages:   # fail loudly at plan time, not on the first cycle
            self._project(self._bench, plan, st)
        with self._lock:
            self._plans[sid] = plan
        return plan

    def constituents(self, strategy: str | None = None) -> list[IndexConstituent]:
        plan = self.plan(strategy)
        return [c.model_copy(update={"upper": u}) for c, u in zip(self._constituents, plan.hi, strict=True)]

    @staticmethod
    def _project(p: list[float], plan: _Plan, st: _Stage) -> list[float]:
        if st.caps is None:
            return project(p, plan.lo, st.hi)
        return project_grouped(p, plan.lo, st.hi, plan.groups, st.caps)

    def default_params(self) -> RebalancerParams:
        return RebalancerParams(tilt=self.cfg.tilt.strength, half_life_hours=self.cfg.evidence.half_life_hours, max_turnover=self.cfg.turnover.max_per_cycle, is_default=True)

    def resolve_params(self, tilt: float | None = None, half_life_hours: float | None = None, max_turnover: float | None = None) -> RebalancerParams:
        """The default parameters with the caller's overrides, validated against the configured limits. Raises ``ValueError`` (the API answers 422)."""
        d = self.default_params()
        k = d.tilt if tilt is None else tilt
        h = d.half_life_hours if half_life_hours is None else half_life_hours
        m = d.max_turnover if max_turnover is None else max_turnover
        if not 0 <= k <= self.cfg.tilt.strength_max:
            raise ValueError(f"tilt must be between 0 and {self.cfg.tilt.strength_max:g}")
        if not HALF_LIFE_MIN <= h <= HALF_LIFE_MAX:
            raise ValueError(f"half_life_hours must be between {HALF_LIFE_MIN:g} and {HALF_LIFE_MAX:g}")
        if not 0 < m <= self.cfg.turnover.max_per_cycle_limit:
            raise ValueError(f"max_turnover must be above 0 and at most {self.cfg.turnover.max_per_cycle_limit:g}")
        return RebalancerParams(tilt=k, half_life_hours=h, max_turnover=m, is_default=(k, h, m) == (d.tilt, d.half_life_hours, d.max_turnover))

    # --------------------------------------------------------------------------------------------------------------------------------- reports
    def _collect(self, include_live: bool) -> _Collected:
        key = (self._signals.seq, len(self._signals.base._signals), include_live)  # noqa: SLF001
        with self._lock:
            if self._collected is not None and self._collected[0] == key:
                return self._collected[1]
        universe = set(self.tickers)
        by_ticker: dict[str, list[Report]] = {t: [] for t in self.tickers}
        used = untrusted = other = 0
        for s in self._signals.list(scope_level="COMPANY"):
            ticker = (s.entity.ticker or "").upper()
            if ticker not in universe:
                continue
            channel = self._signals.channel_of(s.id)
            if channel != CHANNEL_REPLAY and not (include_live and channel == CHANNEL_LIVE):
                continue   # pasted text (MANUAL) never moves the index; live reports do only when asked
            prov = s.provenance
            if prov is not None and prov.timestamp_origin not in TRUSTED_TIMESTAMPS:
                untrusted += 1
                continue
            # A PARTIAL signal is one the event / impact stage declined to score ("not a market event"); its sentiment is still a model output and is used.
            # What is refused is a sentiment that is not one: a placeholder rule, or a link to the company below the confidence floor.
            origin = prov.stage_origins.get("sentiment") if prov is not None else None
            if (origin is not None and origin not in SENTIMENT_ORIGINS) or s.entity.link_confidence < self.cfg.evidence.min_link_confidence:
                other += 1
                continue
            by_ticker[ticker].append(_report(s, ticker))
            used += 1
        times = [r.published_at for rs in by_ticker.values() for r in rs]
        for rs in by_ticker.values():
            rs.sort(key=lambda r: (r.published_at, r.signal_id))
        out = _Collected(by_ticker, used, untrusted, other, min(times) if times else None, max(times) if times else None)
        with self._lock:
            self._collected = (key, out)
        return out

    # ----------------------------------------------------------------------------------------------------------------------------------- grid
    def grid(self, include_live: bool = False) -> list[datetime]:
        """A fixed grid from the first boundary after the first trusted report to the replay clock (or the newest live report), capped to the last ``max_cycles``."""
        col = self._collect(include_live)
        if col.first is None:
            return []
        step = self.cfg.cycles.step_hours * 3600.0
        end = self._signals.as_of
        if include_live and col.last is not None and col.last > end:
            end = col.last
        grid: list[datetime] = []
        t = _floor(col.first, step) + timedelta(seconds=step)
        while t < end:
            grid.append(t)
            t += timedelta(seconds=step)
        grid.append(end)
        return grid[-self.cfg.cycles.max_cycles:]

    def path(self, score_rows: list[list[float]], params: RebalancerParams, strategy: str | None = None) -> list[tuple[list[float], Step]]:
        """The weights a sequence of score vectors (one per cycle, in universe order) produces, starting from the benchmark: (bounded target, step) per cycle.

        The one place the rule is applied, so the timeline and the backtest's placebo (which feeds it shuffled scores) cannot disagree about what the rule is.
        """
        plan = self.plan(strategy)
        return [(stages[-1], step) for stages, step in self._path(score_rows, params, plan, full=False)]

    def _path(self, score_rows: list[list[float]], params: RebalancerParams, plan: _Plan, *, full: bool) -> list[tuple[list[list[float]], Step]]:
        out: list[tuple[list[list[float]], Step]] = []
        prev = list(self._bench)
        last = plan.stages[-1]
        for row in score_rows:
            p = tilt_target(self._bench, row, params.tilt)
            ladder = [self._project(p, plan, st) for st in plan.stages] if full else [self._project(p, plan, last)]
            target = ladder[-1]
            step = step_toward(prev, target, max_turnover=params.max_turnover, min_trade=self.cfg.turnover.min_trade)
            check_weights(target, plan.lo, last.hi, groups=plan.groups, caps=last.caps)
            check_weights(step.weights, plan.lo, last.hi, prev=prev, max_turnover=params.max_turnover, groups=plan.groups, caps=last.caps)
            out.append(([p, *ladder], step))
            prev = step.weights
        return out

    # ------------------------------------------------------------------------------------------------------------------------------- the run
    def _run(self, params: RebalancerParams, include_live: bool, strategy: str | None = None) -> list[_Cycle]:
        plan = self.plan(strategy)
        sid = self.resolve_strategy(strategy)
        col = self._collect(include_live)
        key = (self._signals.seq, len(self._signals.base._signals), include_live, params.tilt, params.half_life_hours, params.max_turnover, sid)  # noqa: SLF001
        with self._lock:
            if key in self._memo:
                self._memo.move_to_end(key)
                return self._memo[key]
        grid = self.grid(include_live)
        floor = self.cfg.impact.floor if plan.spec.score == "sentiment_impact" else None
        scores_by_cycle = [[score(col.by_ticker[t], at, self.cfg.evidence, half_life_hours=params.half_life_hours, impact_floor=floor) for t in self.tickers] for at in grid]
        path = self._path([[s.value for s in row] for row in scores_by_cycle], params, plan, full=True)
        cycles: list[_Cycle] = []
        published_before = 0
        for i, (at, scores, (stages, step)) in enumerate(zip(grid, scores_by_cycle, path, strict=True)):
            published = sum(1 for t in self.tickers for r in col.by_ticker[t] if r.published_at <= at)
            cycles.append(_Cycle(i, at, scores, stages[-1], step.weights, stages, step.status, step.alpha, step.turnover, step.wanted, published - published_before))
            published_before = published
        with self._lock:
            self._memo[key] = cycles
            while len(self._memo) > _MEMO:
                self._memo.popitem(last=False)
        return cycles

    def run_cycles(self, params: RebalancerParams, include_live: bool = False, strategy: str | None = None) -> list[_Cycle]:
        """The cycles of a run (cached): the public door for the decision builder and the lab."""
        return self._run(params, include_live, strategy)

    def check_allocation(self, strategy: str | None, weights: list[float]) -> None:
        """Raises ``ValueError`` naming the broken rule if ``weights`` is not a fully invested allocation inside this strategy's bounds and sector caps."""
        plan = self.plan(strategy)
        check_weights(weights, plan.lo, plan.hi, groups=plan.groups, caps=plan.caps)

    def impact_coverage(self) -> tuple[int, int]:
        """(reports that carry an impact score, reports used): how much of the evidence the impact strategy can actually re-weight."""
        col = self._collect(False)
        every = [r for rs in col.by_ticker.values() for r in rs]
        return sum(1 for r in every if r.impact is not None), len(every)

    def with_overrides(self, overrides: dict) -> RebalancerService:
        """A service over the same signals with some configuration keys changed (the lab's sensitivity grid); the shipped configuration is untouched."""
        raw = apply_overrides(self.cfg.model_dump(mode="json"), overrides)
        return RebalancerService(RebalancerConfig.model_validate(raw), signals=self._signals, entities=self._entities, risk=self._risk)

    def adv_usd(self, ticker: str) -> float | None:
        return self._risk.adv_usd_60d.get(ticker) if self._risk is not None else None

    def decisions(self, index: int, params: RebalancerParams, include_live: bool = False, strategy: str | None = None):  # noqa: ANN201
        from . import decisions as _decisions
        return _decisions.build(self, index, params, include_live, strategy)

    @property
    def bench(self) -> list[float]:
        return list(self._bench)

    # --------------------------------------------------------------------------------------------------------------------------------- reads
    def overview(self) -> RebalancerOverview:
        grid = self.grid()
        return RebalancerOverview(
            version=VERSION, available=bool(grid), params=self.default_params(), tilt_max=self.cfg.tilt.strength_max,
            max_turnover_limit=self.cfg.turnover.max_per_cycle_limit, half_life_hours_default=self.cfg.evidence.half_life_hours,
            benchmark="Equal weight", constituents=self._constituents, cycle_count=len(grid), step_hours=self.cfg.cycles.step_hours,
            first_cycle=grid[0] if grid else None, last_cycle=grid[-1] if grid else None,
            bounds={"lower": self._lo, "upper": self._hi, "benchmark": self.cfg.benchmark_weight, "max_active_ratio": self.cfg.bounds.max_active_ratio,
                    "floor": self.cfg.bounds.floor, "cap": self.cfg.bounds.cap, "min_trade": self.cfg.turnover.min_trade, "cost_bps": self.cfg.turnover.cost_bps},
            strategies=self.strategy_info(), curve=self.curve(self.cfg.tilt.strength), labels=LABELS, limitations=LIMITATIONS)

    def curve(self, tilt: float, points: int = 21) -> list[dict[str, float]]:
        """The rule drawn: one stock at score S, every other at 0. ``target`` is the tilt alone, ``bounded`` after the bounds (the weight it would hold)."""
        n = self.cfg.n
        out = []
        for k in range(points):
            s = -1.0 + 2.0 * k / (points - 1)
            p = tilt_target(self._bench, [s] + [0.0] * (n - 1), tilt)
            w = project(p, [self._lo] * n, [self._hi] * n)
            out.append({"score": round(s, 6), "target": p[0], "bounded": w[0]})
        return out

    def timeline(self, params: RebalancerParams, include_live: bool = False, strategy: str | None = None) -> RebalancerTimeline:
        sid = self.resolve_strategy(strategy)
        col = self._collect(include_live)
        cycles = self._run(params, include_live, sid)
        prev = self._bench
        summaries, total = [], 0.0
        for c in cycles:
            reports = [s.reports for s in c.scores]
            summaries.append(RebalanceCycle(index=c.index, at=c.at, weights=c.weights, scores=[s.value for s in c.scores], reports=reports, turnover=c.traded,
                                          wanted_turnover=c.wanted, status=c.step_status, new_reports=max(0, c.new_reports)))
            total += turnover(prev, c.weights)
            prev = c.weights
        return RebalancerTimeline(
            version=VERSION, strategy=sid, params=params, tickers=self.tickers, constituents=self.constituents(sid), cycles=summaries, cumulative_turnover=total,
            mean_turnover=total / len(cycles) if cycles else 0.0, reports_used=col.used, excluded_untrusted_clock=col.excluded_untrusted,
            excluded_other=col.excluded_other, include_live=include_live, labels=LABELS, limitations=LIMITATIONS)

    def cycle(self, index: int, params: RebalancerParams, include_live: bool = False, strategy: str | None = None) -> RebalanceCycleDetail:
        sid = self.resolve_strategy(strategy)
        plan = self.plan(sid)
        cycles = self._run(params, include_live, sid)
        if not 0 <= index < len(cycles):
            raise LookupError(f"cycle {index} does not exist (0..{len(cycles) - 1})" if cycles else "there are no cycles: no company report is available")
        c = cycles[index]
        prev_w = cycles[index - 1].weights if index else self._bench
        names, drivers = [], {}
        for j, t in enumerate(self.tickers):
            sc = c.scores[j]
            active = c.weights[j] - self._bench[j]
            names.append(RebalanceName(
                ticker=t, score=sc.value, evidence=sc.evidence, reports=sc.reports, sources=sc.sources, target_weight=c.target[j], weight=c.weights[j], active=active,
                change=c.weights[j] - prev_w[j], reason=self._reason(j, c, sc, plan), binding=self.binding(j, c, plan)))
            drivers[t] = [ScoreDriver(signal_id=k.report.signal_id, headline=k.report.headline, source=k.report.source, published_at=k.report.published_at, age_hours=k.age_hours,
                                 sentiment=k.report.sentiment, decayed_weight=k.decayed_weight, contribution=k.contribution, url=k.report.url, multiplier=k.multiplier)
                          for k in sc.contributions[:self.cfg.display.top_drivers_per_name]]
        return RebalanceCycleDetail(version=VERSION, strategy=sid, params=params, index=index, at=c.at, previous_at=cycles[index - 1].at if index else None, status=c.step_status,
                           turnover=c.traded, wanted_turnover=c.wanted, alpha=c.alpha, names=names, drivers=drivers, labels=LABELS)

    def _reason(self, j: int, c: _Cycle, sc: Score, plan: _Plan) -> WeightReason:
        d = self.cfg.display
        w, tgt = c.weights[j], c.target[j]
        if w >= plan.hi[j] - _EPS:
            return WeightReason.AT_UPPER_BOUND
        if w <= plan.lo[j] + _EPS:
            return WeightReason.AT_LOWER_BOUND
        if abs(w - tgt) > d.active_epsilon and c.step_status in ("LIMITED_BY_TURNOVER", "HELD_BELOW_MIN_TRADE"):
            return WeightReason(c.step_status)
        if sc.reports == 0:
            return WeightReason.NO_EVIDENCE
        active = w - self._bench[j]
        if abs(sc.value) < d.score_epsilon or abs(active) <= d.active_epsilon:
            return WeightReason.NO_CLEAR_SENTIMENT
        return WeightReason.TILT_UP if active > 0 else WeightReason.TILT_DOWN

    def binding(self, j: int, c: _Cycle, plan: _Plan) -> list[ConstraintEffect]:
        """Every rule that bound stock ``j`` at this cycle, in the order the rules apply, with the weight it moved.

        ``c.stages`` is the tilt, then its projection onto the constraints added one at a time (each stage is itself a joint projection), so the effect of a rule is the difference
        between two consecutive stages. A rule is *named* only if the stock was actually held by it (at the bound it introduced, or in a sector held at its cap); the redistribution
        every other stock receives is not a binding. The differences telescope: tilt + the sum of every stage's difference + the turnover step = the weight.
        """
        out: list[ConstraintEffect] = []
        prev_hi = [self._hi] * self.cfg.n
        for k, st in enumerate(plan.stages):
            before, after = c.stages[k][j], c.stages[k + 1][j]
            if st.code is None:   # the always-on per-stock bounds, measured against the raw tilt
                if after >= st.hi[j] - _TOL and before > st.hi[j] + _TOL:
                    out.append(ConstraintEffect(code=ConstraintCode.UPPER_BOUND, effect=after - before))
                elif after <= plan.lo[j] + _TOL and before < plan.lo[j] - _TOL:
                    out.append(ConstraintEffect(code=ConstraintCode.LOWER_BOUND, effect=after - before))
            else:
                before = c.stages[k][j]
                if st.code is ConstraintCode.SECTOR_CAP:
                    members = [i for i, g in enumerate(plan.groups) if g == plan.groups[j]]
                    cap = st.caps[plan.groups[j]] if st.caps else 1.0
                    if sum(c.stages[k + 1][i] for i in members) >= cap - _TOL and sum(c.stages[k][i] for i in members) > cap + _TOL:
                        out.append(ConstraintEffect(code=st.code, effect=after - before))
                elif st.hi[j] < prev_hi[j] - _TOL and after >= st.hi[j] - _TOL and before > st.hi[j] + _TOL:
                    out.append(ConstraintEffect(code=st.code, effect=after - before))
            prev_hi = st.hi
        gap = c.weights[j] - c.target[j]
        if abs(gap) > self.cfg.display.active_epsilon:
            if c.step_status == "LIMITED_BY_TURNOVER":
                out.append(ConstraintEffect(code=ConstraintCode.TURNOVER_CAP, effect=gap))
            elif c.step_status == "HELD_BELOW_MIN_TRADE":
                out.append(ConstraintEffect(code=ConstraintCode.MIN_TRADE, effect=gap))
        return out


def _report(s: RiskSignal, ticker: str) -> Report:
    return Report(signal_id=s.id, ticker=ticker, source=s.document.source, published_at=s.document.published_at, sentiment=s.sentiment.score,
                  headline=s.document.headline, url=s.document.url, impact=s.impact.score if s.impact is not None else None)
