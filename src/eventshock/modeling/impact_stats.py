"""Episode-level metrics with cluster bootstrap for the impact model.

The unit of evidence is the *episode* (ticker, session) or, for the market scope, the session: every document in an episode has the
same realised outcome, so rows are never treated as independent. Predictions are averaged within an episode; metrics and bootstrap
resampling are over episodes. Standard library + numpy + scipy only.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import rankdata

from ..pipeline.impact_card import Estimate


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ok = ~(np.isnan(a) | np.isnan(b))
    if ok.sum() < 5 or np.ptp(a[ok]) < 1e-9 or np.ptp(b[ok]) < 1e-9:  # a constant has no ranking (and float noise must not invent one)
        return float("nan")
    ra, rb = rankdata(a[ok]), rankdata(b[ok])
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0:
        return float("nan")
    return float(np.mean((ra - ra.mean()) * (rb - rb.mean())) / (sa * sb))


def top_decile_lift(pred: np.ndarray, target: np.ndarray) -> float | None:
    n = len(pred)
    if n < 20 or target.mean() <= 0:
        return None
    k = max(1, n // 10)
    top = np.argsort(-pred, kind="stable")[:k]
    return float(target[top].mean() / target.mean())


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def estimate(value: float | None, lo: float | None = None, hi: float | None = None, digits: int = 4) -> Estimate:
    def r(x: float | None) -> float | None:
        return None if x is None or x != x else round(float(x), digits)

    return Estimate(value=r(value), lo=r(lo), hi=r(hi))


@dataclass
class EpisodeView:
    """The rows of one evaluation set grouped into episodes. ``y``/``absz``/``placebo`` are per episode."""

    n_rows: int
    n_ep: int
    inv: np.ndarray  # row -> episode position
    y: np.ndarray  # log1p(|z|)
    absz: np.ndarray
    score: np.ndarray  # realised integer score
    placebo: np.ndarray  # |z| of the pre-event window (NaN where unavailable)
    extra: dict[str, np.ndarray]  # any per-episode label arrays (first row's value)

    def aggregate(self, row_pred: np.ndarray) -> np.ndarray:
        sums = np.bincount(self.inv, weights=row_pred, minlength=self.n_ep)
        cnt = np.bincount(self.inv, minlength=self.n_ep)
        return sums / np.maximum(cnt, 1)


def make_view(episodes: np.ndarray, y: np.ndarray, absz: np.ndarray, score: np.ndarray, placebo: np.ndarray,
              extra: dict[str, np.ndarray] | None = None) -> EpisodeView:
    uniq, first, inv = np.unique(episodes, return_index=True, return_inverse=True)
    return EpisodeView(len(episodes), len(uniq), inv, y[first], absz[first], score[first], placebo[first],
                       {k: v[first] for k, v in (extra or {}).items()})


def boot_indices(n: int, resamples: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, n, size=(resamples, n))


def _percentile_ci(vals: np.ndarray) -> tuple[float, float]:
    vals = vals[~np.isnan(vals)]
    if len(vals) < 20:
        return (float("nan"), float("nan"))
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def boot(stat: Callable[[np.ndarray], float], n: int, idx: np.ndarray) -> np.ndarray:
    return np.array([stat(i) for i in idx]) if n > 0 else np.array([])


def mae_estimate(pred: np.ndarray, view: EpisodeView, idx: np.ndarray) -> Estimate:
    e = np.abs(pred - view.y)
    point = float(e.mean())
    lo, hi = _percentile_ci(e[idx].mean(axis=1))
    return estimate(point, lo, hi)


def spearman_estimate(pred: np.ndarray, target: np.ndarray, idx: np.ndarray, *, boot_n: int | None = None) -> Estimate:
    point = spearman(pred, target)
    if len(pred) < 20:
        return estimate(point)
    vals = np.array([spearman(pred[i], target[i]) for i in idx])
    lo, hi = _percentile_ci(vals)
    return estimate(point, lo, hi)


def delta_mae_estimate(pred_a: np.ndarray, pred_b: np.ndarray, view: EpisodeView, idx: np.ndarray) -> Estimate:
    """Paired mean(|err a|) - mean(|err b|); negative means ``a`` is better."""
    d = np.abs(pred_a - view.y) - np.abs(pred_b - view.y)
    lo, hi = _percentile_ci(d[idx].mean(axis=1))
    return estimate(float(d.mean()), lo, hi)


def rmse(pred: np.ndarray, view: EpisodeView) -> float:
    return float(np.sqrt(np.mean((pred - view.y) ** 2)))


def real_minus_placebo(pred: np.ndarray, view: EpisodeView, idx: np.ndarray) -> Estimate:
    ok = ~np.isnan(view.placebo)
    if ok.sum() < 20:
        return estimate(None)
    p, a, b = pred[ok], view.absz[ok], view.placebo[ok]
    point = spearman(p, a) - spearman(p, b)
    sub = boot_indices(len(p), len(idx), 17)
    vals = np.array([spearman(p[i], a[i]) - spearman(p[i], b[i]) for i in sub])
    lo, hi = _percentile_ci(vals)
    return estimate(point, lo, hi)


def monotone(values: list[float]) -> float | None:
    if len(values) < 4:
        return None
    return spearman(np.arange(len(values), dtype=float), np.asarray(values, dtype=float))


def weighted_median(x: np.ndarray, w: np.ndarray) -> float:
    ok = ~np.isnan(x)
    if not ok.any():
        return float("nan")
    x, w = x[ok], w[ok]
    o = np.argsort(x, kind="stable")
    cw = np.cumsum(w[o])
    return float(x[o][np.searchsorted(cw, cw[-1] / 2)])


def quantiles(x: np.ndarray, qs: list[float]) -> list[float]:
    return [float(v) for v in np.quantile(x, qs)]


__all__ = ["Any", "EpisodeView", "boot_indices", "make_view", "spearman"]
