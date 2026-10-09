"""The weight arithmetic: the tilt, the projection onto the bounds and the turnover-limited step. Property tests over seeded random inputs; no randomness in the code under test."""

from __future__ import annotations

import math
import random

import pytest

from eventshock.rebalancer.weights import check_weights, project, step_toward, tilt_target, turnover

N = 15
B = [1 / N] * N
LO, HI = [1 / N * 0.5] * N, [1 / N * 1.5] * N


def rnd_scores(rng: random.Random, n: int = N) -> list[float]:
    return [rng.uniform(-1, 1) for _ in range(n)]


def test_zero_scores_or_zero_strength_hold_the_benchmark():
    assert tilt_target(B, [0.0] * N, 3.0) == pytest.approx(B)
    assert tilt_target(B, [0.9, -0.9] + [0.3] * (N - 2), 0.0) == pytest.approx(B)


def test_the_tilt_is_unchanged_by_a_common_shift_of_every_score():
    s = [0.1 * i - 0.5 for i in range(N)]
    assert tilt_target(B, s, 2.0) == pytest.approx(tilt_target(B, [x + 0.37 for x in s], 2.0))


def test_a_higher_score_never_gets_a_lower_target():
    rng = random.Random(7)
    for _ in range(50):
        s = rnd_scores(rng)
        p = tilt_target(B, s, rng.uniform(0.1, 6))
        order = sorted(range(N), key=lambda i: s[i])
        assert all(p[order[k]] <= p[order[k + 1]] + 1e-15 for k in range(N - 1))
        assert sum(p) == pytest.approx(1.0)


def test_positive_sentiment_raises_the_weight_and_negative_lowers_it():
    p = tilt_target(B, [0.8, -0.8] + [0.0] * (N - 2), 2.0)
    assert p[0] > B[0] > p[1]


def test_a_huge_strength_does_not_overflow():
    p = tilt_target(B, [1.0] + [-1.0] * (N - 1), 700.0)
    assert math.isfinite(sum(p)) and sum(p) == pytest.approx(1.0)


@pytest.mark.parametrize("bad", [dict(strength=-1.0), dict(scores=[0.0] * (N - 1)), dict(scores=[float("nan")] + [0.0] * (N - 1))])
def test_a_malformed_tilt_is_an_error(bad):
    args = dict(scores=[0.0] * N, strength=1.0) | bad
    with pytest.raises(ValueError):
        tilt_target(B, args["scores"], args["strength"])


def test_the_projection_respects_the_bounds_and_the_sum_for_any_target():
    rng = random.Random(11)
    for _ in range(200):
        raw = [rng.random() ** 3 for _ in range(N)]
        p = [x / sum(raw) for x in raw]
        w = project(p, LO, HI)
        check_weights(w, LO, HI)


def test_a_target_already_inside_the_bounds_is_left_alone():
    p = tilt_target(B, [0.05, -0.05] + [0.0] * (N - 2), 1.0)
    assert project(p, LO, HI) == pytest.approx(p, abs=1e-12)


def test_the_projection_is_the_closest_feasible_point():
    """Optimality: no feasible point found by moving weight between two names is closer to the target."""
    rng = random.Random(3)
    for _ in range(30):
        s = rnd_scores(rng)
        p = tilt_target(B, s, 5.0)
        w = project(p, LO, HI)
        base = sum((a - b) ** 2 for a, b in zip(w, p, strict=True))
        for _ in range(40):
            i, j = rng.sample(range(N), 2)
            d = rng.uniform(0, 0.01)
            v = list(w)
            v[i] += d
            v[j] -= d
            if v[i] > HI[i] or v[j] < LO[j]:
                continue
            assert sum((a - b) ** 2 for a, b in zip(v, p, strict=True)) >= base - 1e-12


def test_the_projection_keeps_the_order_of_the_targets():
    rng = random.Random(5)
    for _ in range(50):
        p = tilt_target(B, rnd_scores(rng), 4.0)
        w = project(p, LO, HI)
        order = sorted(range(N), key=lambda i: p[i])
        assert all(w[order[k]] <= w[order[k + 1]] + 1e-12 for k in range(N - 1))


def test_bounds_that_cannot_hold_a_fully_invested_index_are_refused():
    with pytest.raises(ValueError, match="fully invested"):
        project(B, [0.1] * N, [0.2] * N)
    with pytest.raises(ValueError, match="fully invested"):
        project(B, [0.0] * N, [0.05] * N)
    with pytest.raises(ValueError, match="exceeds"):
        project(B, [0.07] * N, [0.06] * N)


def test_the_step_never_trades_more_than_the_cap():
    rng = random.Random(13)
    prev = list(B)
    for _ in range(100):
        target = project(tilt_target(B, rnd_scores(rng), 6.0), LO, HI)
        st = step_toward(prev, target, max_turnover=0.03, min_trade=0.001)
        check_weights(st.weights, LO, HI, prev=prev, max_turnover=0.03)
        assert st.turnover <= 0.03 + 1e-12
        prev = st.weights


def test_the_step_reaches_the_target_when_the_cap_allows():
    target = project(tilt_target(B, [0.4, -0.4] + [0.0] * (N - 2), 1.0), LO, HI)
    st = step_toward(B, target, max_turnover=0.5, min_trade=0.0)
    assert st.status == "TRADED" and st.alpha == 1.0 and st.weights == pytest.approx(target)


def test_a_capped_step_moves_toward_the_target_and_says_so():
    target = project(tilt_target(B, [1.0, -1.0] + [0.0] * (N - 2), 6.0), LO, HI)
    st = step_toward(B, target, max_turnover=0.01, min_trade=0.0)
    assert st.status == "LIMITED_BY_TURNOVER" and 0 < st.alpha < 1 and st.turnover == pytest.approx(0.01)
    assert turnover(st.weights, target) < turnover(B, target)


def test_a_rebalance_below_the_minimum_trade_is_held():
    target = project(tilt_target(B, [0.01, -0.01] + [0.0] * (N - 2), 1.0), LO, HI)
    st = step_toward(B, target, max_turnover=0.05, min_trade=0.01)
    assert st.status == "HELD_BELOW_MIN_TRADE" and st.weights == B and st.turnover == 0.0


def test_standing_on_the_target_is_not_a_trade():
    assert step_toward(B, B, max_turnover=0.05, min_trade=0.0).status == "AT_TARGET"


def test_check_weights_fails_loudly():
    with pytest.raises(ValueError, match="sum to"):
        check_weights([0.5] * N, LO, HI)
    w = list(B)
    w[0] += 0.5
    w[1] -= 0.5
    with pytest.raises(ValueError, match="outside its bounds"):
        check_weights(w, LO, HI)
    with pytest.raises(ValueError, match="exceeds the cap"):
        check_weights([B[i] + (0.02 if i == 0 else -0.02 if i == 1 else 0) for i in range(N)], LO, HI, prev=B, max_turnover=0.01)
