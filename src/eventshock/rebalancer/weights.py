"""The weight arithmetic of the rebalancer: pure functions over plain lists, no I/O, no clock, no randomness.

1. ``tilt_target``    benchmark weights tilted by sentiment: p_i = b_i * exp(k * S_i) / sum_j b_j * exp(k * S_j)
2. ``project``        the Euclidean projection of p onto { lo_i <= w_i <= hi_i, sum w = 1 }: w_i = clip(p_i - mu, lo_i, hi_i), mu found by bisection
2b. ``project_grouped`` the same projection with a cap on the total weight of each group (a sector): w_i = clip(p_i - mu - lambda_g(i), lo_i, hi_i), lambda_g >= 0
3. ``step_toward``    move from the old weights toward that target, but trade at most ``max_turnover`` (a convex combination, so it stays feasible)

Turnover is always one-way: 1/2 * sum |new - old|, the share of the index that is sold and bought again.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

SUM_TOL = 1e-9


def turnover(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("turnover needs two weight vectors of the same length")
    return 0.5 * sum(abs(x - y) for x, y in zip(a, b, strict=True))


def tilt_target(bench: Sequence[float], scores: Sequence[float], strength: float) -> list[float]:
    """Benchmark weights tilted by sentiment. Invariant to adding the same constant to every score; ``strength`` 0 returns the (normalised) benchmark."""
    if len(bench) != len(scores):
        raise ValueError("benchmark weights and scores must have the same length")
    if strength < 0:
        raise ValueError("tilt strength cannot be negative")
    if any(b <= 0 for b in bench):
        raise ValueError("benchmark weights must be positive")
    if any(not math.isfinite(s) for s in scores):
        raise ValueError("a score is not a finite number")
    z = [strength * s for s in scores]
    top = max(z)   # subtracting it changes nothing after the normalisation and keeps exp() from overflowing
    raw = [b * math.exp(v - top) for b, v in zip(bench, z, strict=True)]
    total = sum(raw)
    return [r / total for r in raw]


def project(p: Sequence[float], lo: Sequence[float], hi: Sequence[float]) -> list[float]:
    """The point of { lo <= w <= hi, sum w = 1 } closest to ``p`` (Euclidean). Raises if the box cannot hold a fully invested index."""
    n = len(p)
    if not (len(lo) == len(hi) == n):
        raise ValueError("p, lo and hi must have the same length")
    if any(low > high for low, high in zip(lo, hi, strict=True)):
        raise ValueError("a lower bound exceeds its upper bound")
    if sum(lo) > 1 + SUM_TOL or sum(hi) < 1 - SUM_TOL:
        raise ValueError("the bounds cannot hold a fully invested index")

    def clipped(mu: float) -> list[float]:
        return [min(high, max(low, x - mu)) for x, low, high in zip(p, lo, hi, strict=True)]

    # sum(clipped(mu)) falls as mu rises: it is sum(hi) >= 1 at the left end and sum(lo) <= 1 at the right end
    left = min(x - high for x, high in zip(p, hi, strict=True))
    right = max(x - low for x, low in zip(p, lo, strict=True))
    for _ in range(200):
        mid = 0.5 * (left + right)
        if sum(clipped(mid)) > 1:
            left = mid
        else:
            right = mid
    w = clipped(0.5 * (left + right))
    residual = 1 - sum(w)   # at the bisection's float limit (~1e-16); put it on the coordinates that are not at a bound
    free = [i for i in range(n) if lo[i] < w[i] < hi[i]]
    if free and residual:
        for i in free:
            w[i] += residual / len(free)
    return w


def project_grouped(p: Sequence[float], lo: Sequence[float], hi: Sequence[float], groups: Sequence[int], caps: Sequence[float]) -> list[float]:
    """The point of { lo <= w <= hi, sum w = 1, sum of w over group g <= caps[g] } closest to ``p`` (Euclidean).

    KKT form: w_i = clip(p_i - mu - lambda_g(i), lo_i, hi_i) with lambda_g >= 0, positive only for a group held at its cap. For a given mu each group's lambda is found by
    bisection; the group total then equals min(cap, unconstrained total), which falls as mu rises, so mu is found by an outer bisection. With every cap slack this is ``project``.
    Raises if the constraints cannot hold a fully invested index.
    """
    n = len(p)
    if not (len(lo) == len(hi) == len(groups) == n):
        raise ValueError("p, lo, hi and groups must have the same length")
    if any(low > high for low, high in zip(lo, hi, strict=True)):
        raise ValueError("a lower bound exceeds its upper bound")
    n_groups = len(caps)
    if any(not 0 <= g < n_groups for g in groups):
        raise ValueError("a group index is outside the caps given")
    members: list[list[int]] = [[] for _ in range(n_groups)]
    for i, g in enumerate(groups):
        members[g].append(i)
    for g, idx in enumerate(members):
        if idx and sum(lo[i] for i in idx) > caps[g] + SUM_TOL:
            raise ValueError(f"group {g}: its lower bounds alone exceed its cap")
    if sum(lo) > 1 + SUM_TOL or sum(min(caps[g], sum(hi[i] for i in idx)) for g, idx in enumerate(members) if idx) < 1 - SUM_TOL:
        raise ValueError("the bounds and group caps cannot hold a fully invested index")

    def group_total(idx: list[int], shift: float) -> float:
        return sum(min(hi[i], max(lo[i], p[i] - shift)) for i in idx)

    def lam(g: int, mu: float) -> float:
        idx = members[g]
        if not idx or group_total(idx, mu) <= caps[g]:
            return 0.0
        left, right = 0.0, max(p[i] - mu - lo[i] for i in idx)   # at `right` every member sits at its lower bound, whose total is <= the cap
        for _ in range(60):
            mid = 0.5 * (left + right)
            if group_total(idx, mu + mid) > caps[g]:
                left = mid
            else:
                right = mid
        return right

    def weights(mu: float) -> list[float]:
        shift = [lam(g, mu) for g in range(n_groups)]
        return [min(hi[i], max(lo[i], p[i] - mu - shift[groups[i]])) for i in range(n)]

    left = min(x - high for x, high in zip(p, hi, strict=True))
    right = max(x - low for x, low in zip(p, lo, strict=True))
    for _ in range(80):
        mid = 0.5 * (left + right)
        if sum(weights(mid)) > 1:
            left = mid
        else:
            right = mid
    w = weights(0.5 * (left + right))
    residual = 1 - sum(w)   # float limit only; spread it over names strictly inside their bounds whose group is not at its cap
    at_cap = {g for g, idx in enumerate(members) if idx and sum(w[i] for i in idx) >= caps[g] - 1e-12}
    free = [i for i in range(n) if lo[i] < w[i] < hi[i] and groups[i] not in at_cap]
    if free and residual:
        for i in free:
            w[i] += residual / len(free)
    return w


@dataclass(frozen=True)
class Step:
    weights: list[float]
    turnover: float           # actually traded: 1/2 sum |new - old|
    wanted: float             # turnover the full move to the target would have needed
    alpha: float              # the fraction of the way to the target that was taken (0 = held, 1 = full)
    status: str               # TRADED | LIMITED_BY_TURNOVER | HELD_BELOW_MIN_TRADE | AT_TARGET


def step_toward(prev: Sequence[float], target: Sequence[float], *, max_turnover: float, min_trade: float) -> Step:
    """Move from ``prev`` toward ``target``, trading at most ``max_turnover`` and nothing at all if the full move is below ``min_trade``.

    Both ends satisfy the same bounds and sum to one, so every point between them does too; no re-projection is needed.
    """
    if max_turnover <= 0:
        raise ValueError("max_turnover must be positive")
    wanted = turnover(prev, target)
    if wanted == 0:
        return Step(list(prev), 0.0, 0.0, 1.0, "AT_TARGET")
    if wanted < min_trade:
        return Step(list(prev), 0.0, wanted, 0.0, "HELD_BELOW_MIN_TRADE")
    alpha = min(1.0, max_turnover / wanted)
    new = [a + alpha * (t - a) for a, t in zip(prev, target, strict=True)]
    return Step(new, turnover(prev, new), wanted, alpha, "TRADED" if alpha >= 1.0 else "LIMITED_BY_TURNOVER")


def check_weights(w: Sequence[float], lo: Sequence[float], hi: Sequence[float], *, prev: Sequence[float] | None = None, max_turnover: float | None = None,
                  groups: Sequence[int] | None = None, caps: Sequence[float] | None = None) -> None:
    """The invariants every published weight vector satisfies. Raises ``ValueError`` (never silently repairs)."""
    if abs(sum(w) - 1) > SUM_TOL:
        raise ValueError(f"weights sum to {sum(w):.12f}, not 1")
    for i, (x, low, high) in enumerate(zip(w, lo, hi, strict=True)):
        if x < low - SUM_TOL or x > high + SUM_TOL:
            raise ValueError(f"weight {i} = {x:.6f} is outside its bounds [{low:.6f}, {high:.6f}]")
    if groups is not None and caps is not None:
        for g, cap in enumerate(caps):
            total = sum(x for x, k in zip(w, groups, strict=True) if k == g)
            if total > cap + SUM_TOL:
                raise ValueError(f"group {g} holds {total:.6f}, above its cap {cap:.6f}")
    if prev is not None and max_turnover is not None and turnover(prev, w) > max_turnover + SUM_TOL:
        raise ValueError(f"turnover {turnover(prev, w):.6f} exceeds the cap {max_turnover:.6f}")
