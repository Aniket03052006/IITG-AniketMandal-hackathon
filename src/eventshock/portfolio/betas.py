"""Single-factor trailing beta of each issuer against the S&P 500, frozen as derived statistics (no prices).

Why this exists: the stress engine's market shock is ``dV = V x beta x s``, which needs the CAPM-style market beta. The beta in the impact
model's market context is a two-factor (market + sector) coefficient, a partial slope that is not the right input here, and the synthetic
book's betas are sector-tilted random draws. This module fits ``r_stock = a + beta * r_market`` by OLS on the last ``window_sessions`` daily
returns, then shrinks it toward the market average of 1 with a Vasicek (1973) weight ``w = prior_var / (prior_var + se^2)`` built from the
cross-section of the 34 estimates themselves (``configs/portfolio.yaml``), so a noisy slope moves further than a precise one. An issuer with too few
paired observations gets no beta at all rather than a guess. The file keeps the unclipped numbers; the resolver clips the beta it USES to
``[floor, cap]`` (a one-year negative co-movement is not carried into a stress) and says so.

Leakage: the fit reads only returns up to ``as_of`` (the last session in the price files), the same clock the replay market context uses.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text
from .config import BetaRules

SCHEMA = "portfolio-betas-v1"
PATH = Path("data") / "replay" / "market" / "betas.json"


def ols_beta(stock: list[float], market: list[float], min_obs: int) -> tuple[float, float, int, float] | None:
    """(beta, r_squared, n, standard_error) over the pairs where both returns are present, or None below ``min_obs`` pairs or with no market variance."""
    pairs = [(s, m) for s, m in zip(stock, market, strict=True) if s == s and m == m]
    n = len(pairs)
    if n < min_obs:
        return None
    ms = sum(m for _, m in pairs) / n
    ss = sum(s for s, _ in pairs) / n
    var_m = sum((m - ms) ** 2 for _, m in pairs)
    if var_m <= 0:
        return None
    cov = sum((s - ss) * (m - ms) for s, m in pairs)
    var_s = sum((s - ss) ** 2 for s, _ in pairs)
    beta = cov / var_m
    r2 = (cov * cov) / (var_m * var_s) if var_s > 0 else 0.0
    resid_var = max(var_s - cov * cov / var_m, 0.0) / (n - 2)
    return beta, r2, n, math.sqrt(resid_var / var_m)


def vasicek(beta: float, se: float, prior_mean: float, prior_var: float) -> float:
    w = prior_var / (prior_var + se * se)
    return w * beta + (1.0 - w) * prior_mean


def build_betas(store, rules: BetaRules, tickers: list[str], out_path: Path | None = None) -> dict[str, Any]:  # noqa: ANN001
    """``store`` is a ``modeling.market.PriceStore``. Deterministic: same prices, same file."""
    market = store.ret[store.market]
    lo = max(1, len(store.dates) - rules.window_sessions)
    fits: dict[str, tuple[float, float, int, float]] = {}
    for t in sorted(tickers):
        if t in store.ret:
            fit = ols_beta(store.ret[t][lo:], market[lo:], rules.min_observations)
            if fit is not None:
                fits[t] = fit
    betas_ols = [f[0] for f in fits.values()]
    prior_var = rules.prior_variance_floor
    if len(betas_ols) > 1:
        mean = sum(betas_ols) / len(betas_ols)
        xs_var = sum((b - mean) ** 2 for b in betas_ols) / len(betas_ols)
        mean_se2 = sum(f[3] ** 2 for f in fits.values()) / len(fits)
        prior_var = max(xs_var - mean_se2, rules.prior_variance_floor)
    out = {t: {"beta": round(vasicek(b, se, rules.prior_mean, prior_var), 4), "beta_ols": round(b, 4), "se": round(se, 4), "r2": round(r2, 4), "n": n}
           for t, (b, r2, n, se) in fits.items()}
    payload = {
        "schema": SCHEMA, "as_of": store.dates[-1], "window_sessions": rules.window_sessions, "shrinkage": "vasicek",
        "prior_mean": rules.prior_mean, "prior_variance": round(prior_var, 6),
        "market_symbol": store.market, "min_observations": rules.min_observations, "betas": out,
        "note": "derived statistics (no prices): OLS slope of daily returns on the S&P 500 over the trailing window, Vasicek-shrunk toward the prior mean; "
                "a security with fewer than the minimum paired observations has no entry; the resolver clips the beta it uses",
    }
    if out_path is not None:
        atomic_write_text(out_path, json.dumps(payload, sort_keys=True, allow_nan=False, indent=1) + "\n")
    return payload


class IssuerBetas:
    """The committed beta table. Absent file => no reference betas (the resolver then says it used the default)."""

    def __init__(self, data: dict[str, Any]) -> None:
        if data.get("schema") != SCHEMA:
            raise ConfigError(f"portfolio betas: schema {data.get('schema')!r}, expected {SCHEMA!r}")
        self.data = data
        self.as_of: str = data["as_of"]
        self._b: dict[str, dict[str, Any]] = data["betas"]
        for t, v in self._b.items():
            if not math.isfinite(v["beta"]):
                raise ConfigError(f"portfolio betas: non-finite beta for {t}")

    @classmethod
    def load(cls, repo_root: Path) -> IssuerBetas | None:
        p = repo_root / PATH
        return cls(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else None

    def get(self, ticker: str) -> dict[str, Any] | None:
        return self._b.get(ticker)
