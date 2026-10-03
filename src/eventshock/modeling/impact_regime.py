"""The regime-versus-event battery: is a model learning something about *events*, or only about the volatility regime it is in?

Volatility clusters, so a model that knows "this stock is in a volatile stretch" ranks severity above chance for every report, whatever it says. These
tools separate the two. Everything is pure numpy over episode-level arrays (no model objects), so each can be shown to work on synthetic data where the
answer is known (``tests/unit/test_impact_regime.py``): zero-information text must score ~0, a planted effect must be detected.

1. ``placebo``            skill on a window that ends before the event (market state predicts it, an event cannot).
2. ``neutral_skill``      rank skill after removing the regime from both prediction and outcome (issuer x volatility-bucket cell means from TRAIN).
3. ``within_group_skill`` rank skill inside issuers (and inside volatility terciles), macro-averaged: "which of their reports matters".
4. ``event_vs_control``   on filing events: |z| around an 8-K versus a matched quiet session of the same issuer and volatility bucket.
5. ``block_increment``    paired error difference of a model with a feature block over the same model without it, with interval, per period.
6. ``permutation_effect`` skill lost when a block's values are shuffled among comparable episodes (same issuer, same month) at prediction time.
7. ``leave_block_out``    error added when a block is replaced by its training median at prediction time.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from scipy.stats import rankdata

from .impact_stats import boot_indices, spearman


# --------------------------------------------------------------------------------------------------------- regime cells
def bucket_edges(train_values: np.ndarray, k: int) -> np.ndarray:
    """Interior quantile edges of a volatility proxy, estimated on TRAIN only."""
    v = train_values[~np.isnan(train_values)]
    return np.quantile(v, np.linspace(0, 1, k + 1)[1:-1]) if len(v) else np.array([])


def bucketize(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Bucket index per value (NaN -> -1: its own cell, never silently merged into a regime)."""
    out = np.searchsorted(edges, values, side="right")
    out[np.isnan(values)] = -1
    return out


def cell_keys(groups: np.ndarray, buckets: np.ndarray) -> np.ndarray:
    return np.array([f"{g}|{b}" for g, b in zip(groups, buckets, strict=True)])


def cell_means(keys: np.ndarray, values: np.ndarray) -> tuple[dict[str, float], float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for k, v in zip(keys, values, strict=True):
        if not np.isnan(v):
            acc[k].append(float(v))
    return {k: float(np.mean(v)) for k, v in acc.items()}, float(np.nanmean(values))


def neutralise(keys: np.ndarray, values: np.ndarray, means: dict[str, float], fallback: float) -> np.ndarray:
    return values - np.array([means.get(k, fallback) for k in keys])


def neutral_skill(*, keys_train: np.ndarray, y_train: np.ndarray, pred_train_oof: np.ndarray, keys_eval: np.ndarray, y_eval: np.ndarray,
                  pred_eval: np.ndarray, resamples: int = 1000, seed: int = 7) -> dict[str, Any]:
    """Spearman between the regime-neutral prediction and the regime-neutral outcome (cell means from TRAIN; model cell means from OOF)."""
    ok = ~np.isnan(pred_train_oof)
    my, gy = cell_means(keys_train, y_train)
    mp, gp = cell_means(keys_train[ok], pred_train_oof[ok])
    yn = neutralise(keys_eval, y_eval, my, gy)
    pn = neutralise(keys_eval, pred_eval, mp, gp)
    point = spearman(pn, yn)
    idx = boot_indices(len(yn), resamples, seed)
    vals = np.array([spearman(pn[i], yn[i]) for i in idx])
    vals = vals[~np.isnan(vals)]
    lo, hi = (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))) if len(vals) >= 20 else (float("nan"), float("nan"))
    return {"value": point, "lo": lo, "hi": hi, "n": int(len(yn))}


def within_group_skill(pred: np.ndarray, y: np.ndarray, groups: np.ndarray, min_n: int) -> dict[str, Any]:
    """Macro-average of the Spearman computed inside each group that has at least ``min_n`` episodes."""
    rhos, used = [], 0
    for g in sorted(set(groups.tolist())):
        m = groups == g
        if m.sum() >= min_n:
            r = spearman(pred[m], y[m])
            if r == r:
                rhos.append(r)
                used += 1
    return {"value": float(np.mean(rhos)) if rhos else float("nan"), "groups": used, "min_episodes": min_n}


# --------------------------------------------------------------------------------------------------------- increments
def paired_delta(err_a: np.ndarray, err_b: np.ndarray, resamples: int = 1000, seed: int = 7) -> dict[str, float]:
    """Mean of (|err a| - |err b|) over episodes with a bootstrap interval: negative means ``a`` is better."""
    d = np.abs(err_a) - np.abs(err_b)
    d = d[~np.isnan(d)]
    if len(d) < 20:
        return {"value": float(d.mean()) if len(d) else float("nan"), "lo": float("nan"), "hi": float("nan"), "n": int(len(d))}
    idx = boot_indices(len(d), resamples, seed)
    m = d[idx].mean(axis=1)
    return {"value": float(d.mean()), "lo": float(np.percentile(m, 2.5)), "hi": float(np.percentile(m, 97.5)), "n": int(len(d))}


def block_increment(pred_with: np.ndarray, pred_without: np.ndarray, y: np.ndarray, *, resamples: int = 1000, seed: int = 7) -> dict[str, float]:
    return paired_delta(pred_with - y, pred_without - y, resamples, seed)


def by_period(pred_with: np.ndarray, pred_without: np.ndarray, y: np.ndarray, periods: np.ndarray, min_n: int, *, resamples: int = 500,
              seed: int = 7) -> dict[str, dict[str, float]]:
    """Increment per calendar period (years with fewer than ``min_n`` episodes are left out, never padded)."""
    out = {}
    for p in sorted(set(periods.tolist())):
        m = periods == p
        if m.sum() >= min_n:
            out[str(p)] = block_increment(pred_with[m], pred_without[m], y[m], resamples=resamples, seed=seed)
    return out


def helpful_share(per_period: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Share of periods in which the block lowers error (point difference below zero)."""
    vals = [v["value"] for v in per_period.values() if v["value"] == v["value"]]
    return {"periods": len(vals), "helpful": int(sum(v < 0 for v in vals)), "share": (sum(v < 0 for v in vals) / len(vals)) if vals else float("nan")}


# --------------------------------------------------------------------------------------------------------- block ablations
def permute_within(X: np.ndarray, cols: Sequence[int], groups: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A copy of ``X`` whose ``cols`` rows are shuffled together within each group (so each episode keeps a plausible block, just another episode's)."""
    out = X.copy()
    by: dict[Any, list[int]] = defaultdict(list)
    for i, g in enumerate(groups):
        by[g].append(i)
    for idx in by.values():
        if len(idx) > 1:
            perm = rng.permutation(idx)
            out[np.ix_(idx, list(cols))] = X[np.ix_(perm, list(cols))]
    return out


def permutation_effect(predict: Callable[[np.ndarray], np.ndarray], X: np.ndarray, cols: Sequence[int], groups: np.ndarray, y_rank: np.ndarray,
                       y_log: np.ndarray, *, repeats: int, seed: int) -> dict[str, float]:
    """Skill lost (Spearman) and error added (MAE) when the block is shuffled within ``groups`` at prediction time. No refit."""
    base = predict(X)
    rng = np.random.default_rng(seed)
    d_sp, d_mae = [], []
    for _ in range(repeats):
        p = predict(permute_within(X, cols, groups, rng))
        d_sp.append(spearman(base, y_rank) - spearman(p, y_rank))
        d_mae.append(float(np.abs(p - y_log).mean() - np.abs(base - y_log).mean()))
    sp, mae = np.array(d_sp), np.array(d_mae)
    return {"spearman_lost": float(np.nanmean(sp)), "spearman_lost_lo": float(np.nanpercentile(sp, 2.5)),
            "spearman_lost_hi": float(np.nanpercentile(sp, 97.5)), "mae_added": float(mae.mean()), "mae_added_lo": float(np.percentile(mae, 2.5)),
            "mae_added_hi": float(np.percentile(mae, 97.5)), "repeats": repeats}


def leave_block_out(predict: Callable[[np.ndarray], np.ndarray], X: np.ndarray, cols: Sequence[int], fill: np.ndarray, y_rank: np.ndarray,
                    y_log: np.ndarray) -> dict[str, float]:
    base = predict(X)
    Z = X.copy()
    Z[:, list(cols)] = fill
    p = predict(Z)
    return {"spearman_lost": float(spearman(base, y_rank) - spearman(p, y_rank)),
            "mae_added": float(np.abs(p - y_log).mean() - np.abs(base - y_log).mean())}


# --------------------------------------------------------------------------------------------------------- event vs control
def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(a random event's severity exceeds a random control's), ties half (Mann-Whitney)."""
    pos, neg = pos[~np.isnan(pos)], neg[~np.isnan(neg)]
    if not len(pos) or not len(neg):
        return float("nan")
    r = rankdata(np.concatenate([pos, neg]))
    return float((r[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def match_controls(events: Sequence[dict[str, Any]], pool: Sequence[dict[str, Any]], *, max_distance: int) -> list[tuple[int, int]]:
    """Pair each event with the nearest unused quiet session of the same issuer and volatility bucket (|s0 difference| <= max_distance).

    ``events`` and ``pool`` carry ``ticker``, ``s0`` and ``bucket``. Deterministic: events are processed in (s0, ticker) order, ties go to the earlier
    session, and a pool row serves at most one event. Returns (event index, pool index) pairs; unmatched events are simply absent (counted by the caller).
    """
    by: dict[tuple[str, int], list[int]] = defaultdict(list)
    for j, p in enumerate(pool):
        by[(p["ticker"], p["bucket"])].append(j)
    used: set[int] = set()
    pairs = []
    for i in sorted(range(len(events)), key=lambda k: (events[k]["s0"], events[k]["ticker"])):
        e = events[i]
        cands = [j for j in by.get((e["ticker"], e["bucket"]), []) if j not in used and abs(pool[j]["s0"] - e["s0"]) <= max_distance]
        if not cands:
            continue
        j = min(cands, key=lambda j: (abs(pool[j]["s0"] - e["s0"]), pool[j]["s0"]))
        used.add(j)
        pairs.append((i, j))
    return pairs


def event_vs_control(ev_y: np.ndarray, ctl_y: np.ndarray, *, resamples: int = 1000, seed: int = 7) -> dict[str, Any]:
    """Paired lift of log-severity (event minus its matched control), bootstrap interval, and the AUC of event vs control severity."""
    d = ev_y - ctl_y
    idx = boot_indices(len(d), resamples, seed)
    m = d[idx].mean(axis=1)
    return {"n_pairs": int(len(d)), "lift": float(d.mean()), "lo": float(np.percentile(m, 2.5)), "hi": float(np.percentile(m, 97.5)),
            "auc": auc(ev_y, ctl_y), "event_mean": float(ev_y.mean()), "control_mean": float(ctl_y.mean())}
