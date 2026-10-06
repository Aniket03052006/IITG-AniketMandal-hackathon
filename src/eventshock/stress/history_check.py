"""Is a scenario's shock large or small by historical standards? A read-only reality check; the stress arithmetic is untouched.

The scenario magnitudes are illustrative assumptions (``configs/scenarios.yaml``). This module ranks each shock that history can speak to against the empirical
distribution of overlapping k-session moves (k = 1, 5, 21) since 2014: the S&P 500 (market equity shocks), equal-weight sector baskets of the 34 issuers
(sector equity shocks), the 34 issuers themselves (issuer equity shocks) and the 10-year Treasury yield in basis points (rate shocks). Credit-spread, default-
probability and loss-given-default shocks cannot be checked: no free history of them is held, and the result says so instead of guessing.

The committed artifact (``data/replay/market/shock_history.json``) holds only quantiles and the extreme tails of those distributions, never prices. A percentile
here is a historical frequency of a move at least that large in the stated direction over the stated horizon: it is not a probability that the scenario occurs, and
overlapping windows are strongly autocorrelated, so the effective number of independent windows is about ``n / k``.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from ..config import ConfigError
from ..domain import RiskFactor, Scenario, ShockScope
from ..ingestion.snapshot import atomic_write_text
from ..modeling.evidence_v3 import load_evidence_v3
from ..modeling.outcome_audit import build_store, clean
from .engine import scaled_shock_value

SCHEMA = "shock-history-v1"
GRID = [round(0.001 * i, 3) for i in range(1, 1000)]
TAIL = 100
SERIES = {  # (factor, scope) -> series id
    (RiskFactor.EQUITY, ShockScope.MARKET): "SP500", (RiskFactor.EQUITY, ShockScope.SECTOR): "SECTOR_BASKET",
    (RiskFactor.EQUITY, ShockScope.ISSUER): "ISSUER", (RiskFactor.RATES_BPS, ShockScope.MARKET): "US10Y_BP"}
SERIES_LABEL = {"SP500": "the S&P 500", "SECTOR_BASKET": "an equal-weight sector basket of the 34 issuers", "ISSUER": "one of the 34 issuers",
                "US10Y_BP": "the 10-year Treasury yield (bp)"}
NOT_CHECKABLE = {RiskFactor.CREDIT_SPREAD_BPS: "no free credit-spread history is held", RiskFactor.PD_MULTIPLIER: "no default history is held",
                 RiskFactor.LGD_ADD: "no loss-given-default history is held", RiskFactor.FX_PCT: "no exchange-rate history is held",
                 RiskFactor.COMMODITY_PCT: "no oil-price history is held"}
PATH = Path("data") / "replay" / "market" / "shock_history.json"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class HorizonRank(_Strict):
    horizon_sessions: int
    direction: Literal["down", "up"]
    share_as_extreme: float | None = None       # fraction of historical windows with a move at least this large in this direction
    one_in: float | None = None                 # 1 / share
    beyond_history: bool = False                # larger than every observed window
    worst_observed: float                       # the most extreme observed move in this direction (same unit as the shock)
    median_abs: float
    n_windows: int
    independent_windows: int


class ShockCheck(_Strict):
    factor: str
    scope: str
    value: float
    unit: str
    checkable: bool
    basis: str
    horizons: list[HorizonRank] = []
    reading: str


class ScenarioHistoryCheck(_Strict):
    scenario_id: str
    severity_scale: float
    first_session: str
    last_session: str
    checks: list[ShockCheck]
    caveats: list[str]


# ------------------------------------------------------------------------------------------------ build
def _windows(values: list[float], k: int, *, compound: bool) -> list[float]:
    out = []
    for i in range(k, len(values)):
        seg = values[i - k + 1:i + 1] if compound else None
        if compound:
            if any(v != v for v in seg):  # type: ignore[union-attr]
                continue
            out.append(math.prod(1 + v for v in seg) - 1)  # type: ignore[union-attr]
        else:
            a, b = values[i - k], values[i]
            if a == a and b == b:
                out.append((b - a) * 100.0)       # ^TNX is quoted in percent: x100 = basis points
    return out


def _summary(vals: list[float]) -> dict[str, Any]:
    a = np.sort(np.asarray(vals, dtype=float))
    return {"n": int(a.size), "worst": [round(float(x), 6) for x in a[:TAIL]], "best": [round(float(x), 6) for x in a[-TAIL:]],
            "grid": [round(float(x), 6) for x in np.quantile(a, GRID)], "median_abs": round(float(np.median(np.abs(a))), 6)}


def build_shock_history(repo_root: Path, config_dir: Path, out_path: Path | None = None) -> dict[str, Any]:
    pre, pre_sha = load_evidence_v3(config_dir)
    cfg = pre["stress_history"]
    store = build_store(repo_root, config_dir)
    first = bisect_left(store.dates, cfg["first_session_date"])
    daily = {"SP500": store.ret[cfg["index"]][first:]}
    tickers = sorted(t for t in store.sectors if t in store.ret)
    daily_issuer = {t: store.ret[t][first:] for t in tickers}
    sectors = sorted(set(store.sectors.values()))
    basket = {}
    for s in sectors:
        members = [t for t in tickers if store.sectors[t] == s]
        n = len(daily["SP500"])
        basket[s] = [float(np.nanmean([daily_issuer[t][i] for t in members])) if any(daily_issuer[t][i] == daily_issuer[t][i] for t in members) else float("nan")
                     for i in range(n)]
    rates = store.close[cfg["rates"]][first:]
    series: dict[str, dict[str, Any]] = {}
    for k in cfg["horizons_sessions"]:
        sp = _windows(daily["SP500"], k, compound=True)
        sec = [v for s in sectors for v in _windows(basket[s], k, compound=True)]
        iss = [v for t in tickers for v in _windows(daily_issuer[t], k, compound=True)]
        r10 = _windows(rates, k, compound=False)
        for name, vals in (("SP500", sp), ("SECTOR_BASKET", sec), ("ISSUER", iss), ("US10Y_BP", r10)):
            series.setdefault(name, {})[str(k)] = _summary(vals)
    out = {"schema": SCHEMA, "preregistration_sha256": pre_sha, "first_session": store.dates[first], "last_session": store.dates[-1],
           "horizons_sessions": list(cfg["horizons_sessions"]), "grid": GRID, "tickers": len(tickers), "sectors": sectors,
           "units": {"SP500": "fraction", "SECTOR_BASKET": "fraction", "ISSUER": "fraction", "US10Y_BP": "basis points"},
           "reference_quantiles": cfg["quantiles"], "series": series,
           "note": "overlapping k-session windows; quantiles and extreme tails only, no prices; a percentile is a historical frequency, not a probability of occurrence"}
    if out_path is not None:
        atomic_write_text(out_path, json.dumps(clean(out), sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n")
    return out


# ------------------------------------------------------------------------------------------------ read
def _count_at_least(summary: dict[str, Any], grid: list[float], v: float, direction: str) -> tuple[float, bool]:
    """(number of historical windows with a move at least |v| in ``direction``, beyond_history)."""
    n = summary["n"]
    if direction == "down":
        worst = summary["worst"]
        if v < worst[0]:
            return 0.0, True
        if v <= worst[-1]:
            return float(bisect_right(worst, v)), False
        return float(np.interp(v, summary["grid"], grid)) * n, False
    best = summary["best"]
    if v > best[-1]:
        return 0.0, True
    if v >= best[0]:
        return float(len(best) - bisect_left(best, v)), False
    return (1.0 - float(np.interp(v, summary["grid"], grid))) * n, False


class ShockHistory:
    def __init__(self, data: dict[str, Any]) -> None:
        if data.get("schema") != SCHEMA:
            raise ConfigError(f"shock history: schema {data.get('schema')!r}, expected {SCHEMA!r}")
        self.data = data
        self.grid: list[float] = data["grid"]

    @classmethod
    def load(cls, repo_root: Path) -> ShockHistory:
        p = repo_root / PATH
        if not p.is_file():
            raise ConfigError(f"missing {p}: `make shock-history`")
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def check_shock(self, factor: RiskFactor, scope: ShockScope, value: float) -> ShockCheck:
        unit = "bp" if factor in (RiskFactor.RATES_BPS, RiskFactor.CREDIT_SPREAD_BPS) else ("x" if factor is RiskFactor.PD_MULTIPLIER else "fraction")  # FX and oil are fractions
        sid = SERIES.get((factor, scope))
        if sid is None:
            why = NOT_CHECKABLE.get(factor, "history does not speak to this combination")
            return ShockCheck(factor=factor.value, scope=scope.value, value=value, unit=unit, checkable=False, basis=why,
                              reading=f"Not checkable against history: {why}. The magnitude is an unvalidated assumption.")
        direction: Literal["down", "up"] = "down" if value < 0 else "up"
        rows: list[HorizonRank] = []
        for k in self.data["horizons_sessions"]:
            s = self.data["series"][sid][str(k)]
            count, beyond = _count_at_least(s, self.grid, value, direction)
            n = s["n"]
            share = count / n if n and not beyond else (0.0 if beyond else None)
            extreme = (s["worst"][0] if direction == "down" else s["best"][-1])
            rows.append(HorizonRank(horizon_sessions=k, direction=direction, share_as_extreme=share, one_in=(1 / share if share else None), beyond_history=beyond,
                                    worst_observed=extreme, median_abs=s["median_abs"], n_windows=n, independent_windows=n // k))
        return ShockCheck(factor=factor.value, scope=scope.value, value=value, unit=unit, checkable=True, basis=f"{SERIES_LABEL[sid]}, {self.data['first_session']} to {self.data['last_session']}",
                          horizons=rows, reading=self._reading(rows, value, unit, sid))

    @staticmethod
    def _reading(rows: list[HorizonRank], value: float, unit: str, sid: str) -> str:
        fmt = (lambda x: f"{x:+.0f} bp".replace("-", "−")) if unit == "bp" else (lambda x: f"{100 * x:+.1f}%".replace("-", "−"))
        parts = []
        for r in rows:
            if r.beyond_history:
                parts.append(f"over {r.horizon_sessions} session{'s' if r.horizon_sessions > 1 else ''}: larger than any on record (worst {fmt(r.worst_observed)})")
            elif r.one_in:
                parts.append(f"over {r.horizon_sessions} session{'s' if r.horizon_sessions > 1 else ''}: about 1 window in {r.one_in:,.0f}")
        if not parts:
            return "No history to compare."
        return f"A {fmt(value)} move in {SERIES_LABEL[sid]}, historically " + "; ".join(parts) + "."

    def check_scenario(self, scenario: Scenario, *, severity_scale: float = 1.0) -> ScenarioHistoryCheck:
        checks = []
        for sh in scenario.shocks:
            v = scaled_shock_value(sh.factor, sh.value, severity_scale)
            checks.append(self.check_shock(sh.factor, sh.scope, v))
        return ScenarioHistoryCheck(
            scenario_id=scenario.id, severity_scale=severity_scale, first_session=self.data["first_session"], last_session=self.data["last_session"], checks=checks,
            caveats=["A percentile is a historical frequency of a move at least this large over the stated horizon, not a probability that the scenario occurs.",
                     "The scenario applies its shocks instantaneously; the horizon is read as an assumption and the longer horizons are the fairer comparison for a multi-day repricing.",
                     "Overlapping windows are strongly autocorrelated: the number of independent windows is about n / k.",
                     "The history is 2014-2026 of 34 large US issuers and the S&P 500: it contains the 2020 crash and the 2022 rate cycle, and no earlier crisis."])
