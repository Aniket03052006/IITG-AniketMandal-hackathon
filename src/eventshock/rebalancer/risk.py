"""Risk inputs of the optional constraint sets: a volatility per stock and an average daily dollar volume, frozen at the start of the replay window.

They come from ``data/rebalancer/risk_inputs.json`` (derived statistics only, no prices; built offline by ``make rebalancer-risk-inputs`` from the frozen market context and the
git-ignored price files). Both are measured at one early date, so the constraints they define are static and point-in-time safe for every cycle, and a convex step between two
feasible weight vectors stays feasible. The server never reads a price file.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from .config import RebalancerConfig

SCHEMA = "rebalancer-risk-inputs-v1"


@dataclass(frozen=True)
class RiskInputs:
    sigma_60: dict[str, float]      # trailing 60-session daily return volatility, per ticker
    adv_usd_60d: dict[str, float]   # 60-session average of close x volume, in USD, per ticker
    sigma_as_of: str
    adv_as_of: str


def load_risk_inputs(path: Path, tickers: list[str]) -> RiskInputs | None:
    """None when the file is absent (the risk strategies are then reported unavailable); a file that exists but is wrong is an error, never a silent partial."""
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != SCHEMA:
        raise ValueError(f"{path.name}: schema {raw.get('schema')!r}, expected {SCHEMA!r}")
    sigma, adv = raw.get("sigma_60", {}), raw.get("adv_usd_60d", {})
    missing = [t for t in tickers if t not in sigma or t not in adv]
    if missing:
        raise ValueError(f"{path.name} has no volatility or volume for: {', '.join(missing)}")
    if any(not sigma[t] > 0 or not adv[t] > 0 for t in tickers):
        raise ValueError(f"{path.name}: a volatility or volume is not positive")
    return RiskInputs({t: float(sigma[t]) for t in tickers}, {t: float(adv[t]) for t in tickers}, str(raw["sigma_as_of"]), str(raw["adv_as_of"]))


def vol_upper_bounds(cfg: RebalancerConfig, risk: RiskInputs, tickers: list[str], base_hi: float) -> list[float]:
    """hi_i = b (1 + ratio * min(1, (median sigma / sigma_i) ** gamma)), never above the base upper bound and never below the benchmark b."""
    b, ratio, gamma = cfg.benchmark_weight, cfg.bounds.max_active_ratio, cfg.risk.vol_aware.gamma
    ref = statistics.median(risk.sigma_60[t] for t in tickers)
    return [min(base_hi, b * (1.0 + ratio * min(1.0, (ref / risk.sigma_60[t]) ** gamma))) for t in tickers]


def liquidity_upper_bounds(cfg: RebalancerConfig, risk: RiskInputs, tickers: list[str], base_hi: float) -> list[float]:
    """A name whose average daily dollar volume is below the floor may not be overweight: its upper bound is the benchmark weight."""
    b = cfg.benchmark_weight
    return [min(base_hi, b) if risk.adv_usd_60d[t] < cfg.risk.liquidity.min_adv_usd else base_hi for t in tickers]
