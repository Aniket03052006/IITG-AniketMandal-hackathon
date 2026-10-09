"""``configs/rebalancer.yaml``: the mock index, the evidence window, the tilt, the bounds and the turnover limits. Every number is a judgement prior (see the file)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError, _read_yaml
from ..config_overrides import apply_overrides

MIN_UNIVERSE, MAX_UNIVERSE = 10, 20   # the problem statement: "a selection of 10-20 stocks"


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Universe(_Cfg):
    tickers: list[str]
    benchmark: Literal["EQUAL_WEIGHT"]

    @model_validator(mode="after")
    def _valid(self) -> Universe:
        if not MIN_UNIVERSE <= len(self.tickers) <= MAX_UNIVERSE:
            raise ValueError(f"the mock index holds {MIN_UNIVERSE}-{MAX_UNIVERSE} stocks, not {len(self.tickers)}")
        if len(set(self.tickers)) != len(self.tickers):
            raise ValueError("universe.tickers lists a ticker twice")
        if any(not t or t != t.upper() or " " in t for t in self.tickers):
            raise ValueError("universe.tickers must be upper-case tickers")
        return self


class Cycles(_Cfg):
    step_hours: float = Field(gt=0, le=72)
    max_cycles: int = Field(gt=1, le=1000)


class Evidence(_Cfg):
    half_life_hours: float = Field(gt=0, le=720)
    lookback_half_lives: float = Field(gt=0, le=20)
    source_vote_cap: float = Field(gt=0)
    prior_pseudo_count: float = Field(ge=0)
    min_link_confidence: float = Field(ge=0, le=1)


class Tilt(_Cfg):
    strength: float = Field(ge=0)
    strength_max: float = Field(gt=0)


class Bounds(_Cfg):
    max_active_ratio: float = Field(gt=0, lt=1)
    floor: float = Field(ge=0, lt=1)
    cap: float = Field(gt=0, le=1)


class Turnover(_Cfg):
    max_per_cycle: float = Field(gt=0, le=1)
    max_per_cycle_limit: float = Field(gt=0, le=1)
    min_trade: float = Field(ge=0, lt=1)
    cost_bps: float = Field(ge=0, le=500)


class Display(_Cfg):
    top_drivers_per_name: int = Field(gt=0, le=20)
    active_epsilon: float = Field(ge=0, lt=0.01)
    score_epsilon: float = Field(ge=0, lt=0.5)


class StrategySpec(_Cfg):
    """A named combination of a score source and optional constraint sets. Closed registry: a request names one of these, it never composes its own."""

    label: str
    description: str
    score: Literal["sentiment", "sentiment_impact"]
    sector_cap: bool = False
    vol_limit: bool = False
    liquidity_floor: bool = False

    @property
    def needs_risk_inputs(self) -> bool:
        return self.vol_limit or self.liquidity_floor


class SectorCap(_Cfg):
    ratio: float = Field(gt=0, le=1)   # a sector may hold at most its benchmark share x (1 + ratio)


class VolAware(_Cfg):
    gamma: float = Field(gt=0, le=4)
    reference: Literal["median"]   # the volatility a name is compared with: the median of the index


class Liquidity(_Cfg):
    min_adv_usd: float = Field(gt=0)          # average daily dollar volume below which a name may not be overweight
    mock_aum_usd: float = Field(gt=0)         # the notional the mock index is imagined to hold (display of trade size only)
    max_participation: float = Field(gt=0, le=1)   # a trade above this share of a day's volume is flagged


class Risk(_Cfg):
    sector_cap: SectorCap
    vol_aware: VolAware
    liquidity: Liquidity


class ImpactVariant(_Cfg):
    floor: float = Field(gt=0, le=1)   # multiplier on a report's tone at impact 1 (and for a report with no impact score); rises linearly to 1 at impact 10


class Explain(_Cfg):
    thin_evidence_below: float = Field(ge=0)       # evidence mass (sum of c_s) below this is flagged thin
    stale_after_half_lives: float = Field(gt=0)    # newest report older than this many half-lives is flagged stale
    conflict_min_share: float = Field(gt=0, le=0.5)   # both a positive and a negative side must hold at least this share of the absolute contribution


DEFAULT_STRATEGY = "sentiment"


class RebalancerConfig(_Cfg):
    version: str
    universe: Universe
    cycles: Cycles
    evidence: Evidence
    tilt: Tilt
    bounds: Bounds
    turnover: Turnover
    display: Display
    strategies: dict[str, StrategySpec]
    risk: Risk
    impact: ImpactVariant
    explain: Explain

    @property
    def n(self) -> int:
        return len(self.universe.tickers)

    @property
    def benchmark_weight(self) -> float:
        return 1.0 / self.n

    def limits(self) -> tuple[float, float]:
        """(lowest, highest) weight any stock may hold: the active-ratio band around the benchmark, cut by the absolute floor and cap."""
        b = self.benchmark_weight
        return max(self.bounds.floor, b * (1 - self.bounds.max_active_ratio)), min(self.bounds.cap, b * (1 + self.bounds.max_active_ratio))

    @model_validator(mode="after")
    def _consistent(self) -> RebalancerConfig:
        lo, hi = self.limits()
        b = self.benchmark_weight
        if not lo <= b <= hi:
            raise ValueError(f"the benchmark weight {b:.4f} lies outside the allowed band [{lo:.4f}, {hi:.4f}]")
        if lo * self.n > 1 + 1e-12 or hi * self.n < 1 - 1e-12:
            raise ValueError("the weight bounds cannot hold a fully invested index (sum of lower bounds > 1 or sum of upper bounds < 1)")
        if self.tilt.strength > self.tilt.strength_max:
            raise ValueError("tilt.strength exceeds tilt.strength_max")
        if self.turnover.max_per_cycle > self.turnover.max_per_cycle_limit:
            raise ValueError("turnover.max_per_cycle exceeds turnover.max_per_cycle_limit")
        if self.turnover.min_trade >= self.turnover.max_per_cycle:
            raise ValueError("turnover.min_trade must be below turnover.max_per_cycle")
        base = self.strategies.get(DEFAULT_STRATEGY)
        if base is None:
            raise ValueError(f"strategies must include the baseline '{DEFAULT_STRATEGY}'")
        if base.score != "sentiment" or base.sector_cap or base.vol_limit or base.liquidity_floor:
            raise ValueError(f"the baseline strategy '{DEFAULT_STRATEGY}' is the sentiment-only rule with no extra constraint; alternatives are separate strategies")
        return self


def load_rebalancer_config(config_dir: Path, overrides: Mapping[str, Any] | None = None) -> RebalancerConfig:
    try:
        return RebalancerConfig.model_validate(apply_overrides(_read_yaml(config_dir / "rebalancer.yaml"), overrides))
    except ValueError as exc:
        raise ConfigError(f"invalid rebalancer configuration: {exc}") from exc
