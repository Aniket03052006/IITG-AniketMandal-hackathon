"""``outcome-v3``: the realised outcome used by the Stage 8 side-car layers (severity validity, analogues, calibration).

It is ``outcome-v2`` (``modeling.market.PriceStore.target``: a trailing two-factor market model, CAR over the reaction window, standardised by a
residual sigma) with ONE change, the one the pre-registered audit decided (``docs/evidence/outcome_audit.json``,
``configs/evidence_v3.yaml: outcome_audit.adopt_ewma_if``): sigma is a RiskMetrics EWMA of the squared residuals (lambda 0.94, seeded with the
60-session RMS and run over the same 60 residuals) instead of the plain 60-session RMS. The market-model fit, the clock assignment, the window and
the CAR itself are identical, so ``car`` is the same number in both versions and only the standardisation differs.

The frozen v2 table, the trained models and the replay digests keep ``outcome-v2``; nothing here is imported by them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .market import PriceStore

LAMBDA = 0.94
VERSION = "outcome-v3"


@dataclass(frozen=True)
class OutcomeV3:
    car: float            # cumulative abnormal return over the reaction window (a return, e.g. 0.021 = +2.1%)
    sigma60: float        # outcome-v2 sigma (plain 60-session residual RMS)
    sigma_ewma: float     # outcome-v3 sigma
    z60: float            # outcome-v2 standardised move
    z: float              # outcome-v3 standardised move (signed)
    window_sessions: int

    @property
    def abs_z(self) -> float:
        return abs(self.z)


def ewma_sigma(seed_sigma: float, residuals: list[float], lam: float = LAMBDA) -> float:
    """EWMA of squared residuals, oldest first, seeded with ``seed_sigma**2``."""
    v = seed_sigma ** 2
    for r in residuals:
        v = lam * v + (1 - lam) * r * r
    return math.sqrt(v)


def outcome_v3(store: PriceStore, ticker: str, s0: int) -> tuple[OutcomeV3 | None, str]:
    """(outcome, "") or (None, reason). Reasons are those of ``PriceStore.target`` (CENSORED, INSUFFICIENT_HISTORY, MISSING_RETURN, ...)."""
    tgt, why = store.target(ticker, s0)
    if tgt is None:
        return None, why
    fit = tgt.fit
    y, m = store.ret[ticker], store.ret[store.market]
    p = store.peer.get(ticker) or [float("nan")] * len(y)
    res = []
    for i in range(s0 - store.cfg.sigma_window, s0):
        pk = p[i] if fit.c != 0.0 else 0.0
        if y[i] == y[i] and m[i] == m[i] and pk == pk:
            res.append(y[i] - fit.a - fit.b * m[i] - fit.c * pk)
    if len(res) < store.cfg.sigma_window // 2:
        return None, "INSUFFICIENT_HISTORY"
    s_ew = ewma_sigma(fit.sigma, res)
    w = store.cfg.window_sessions
    return OutcomeV3(tgt.car, fit.sigma, s_ew, tgt.z, tgt.car / (s_ew * math.sqrt(w)), w), ""
