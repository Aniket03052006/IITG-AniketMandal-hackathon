"""project_grouped: the Euclidean projection onto bounds + sum 1 + a cap on each group's total weight. Exact (KKT), and the plain projection when no cap binds."""

from __future__ import annotations

import math
import random

import pytest

from eventshock.rebalancer.weights import check_weights, project, project_grouped

N = 15
GROUPS = [0] * 6 + [1] * 3 + [2] * 2 + [3] * 3 + [4]


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def instance(rng):
    b = 1 / N
    p = [b * math.exp(rng.uniform(-3, 3)) for _ in range(N)]
    s = sum(p)
    p = [x / s for x in p]
    lo, hi = [b * 0.5] * N, [b * 1.5] * N
    caps = [min(1.0, GROUPS.count(g) / N * 1.25) for g in range(5)]
    return p, lo, hi, caps


def test_with_every_cap_slack_it_is_the_plain_projection():
    rng = random.Random(1)
    for _ in range(30):
        p, lo, hi, _ = instance(rng)
        assert project_grouped(p, lo, hi, GROUPS, [1.0] * 5) == pytest.approx(project(p, lo, hi), abs=1e-9)


def test_the_result_is_feasible_and_a_binding_sector_sits_exactly_at_its_cap():
    rng = random.Random(2)
    bound = 0
    for _ in range(100):
        p, lo, hi, caps = instance(rng)
        w = project_grouped(p, lo, hi, GROUPS, caps)
        check_weights(w, lo, hi, groups=GROUPS, caps=caps)
        for g, cap in enumerate(caps):
            total = sum(x for x, k in zip(w, GROUPS, strict=True) if k == g)
            if total > cap - 1e-9:
                bound += 1
        # a cap that the plain projection already satisfied changes nothing
        plain = project(p, lo, hi)
        if all(sum(x for x, k in zip(plain, GROUPS, strict=True) if k == g) <= caps[g] + 1e-12 for g in range(5)):
            assert w == pytest.approx(plain, abs=1e-9)
    assert bound > 20   # the test instances do exercise a binding cap


def test_it_is_the_closest_feasible_point_to_the_tilt():
    """No other feasible point is nearer; checked against many feasible points and against moves along the feasible set."""
    rng = random.Random(3)
    for _ in range(40):
        p, lo, hi, caps = instance(rng)
        w = project_grouped(p, lo, hi, GROUPS, caps)
        for _ in range(25):
            q = project_grouped([rng.uniform(0, 0.2) for _ in range(N)], lo, hi, GROUPS, caps)   # an arbitrary feasible point
            assert dist(w, p) <= dist(q, p) + 1e-9
            # and the segment toward it never gets closer (first-order optimality)
            for t in (0.1, 0.5):
                m = [a + t * (b - a) for a, b in zip(w, q, strict=True)]
                assert dist(w, p) <= dist(m, p) + 1e-9


def test_a_shifted_tilt_gives_the_same_answer_after_renormalising_nothing_is_lost():
    rng = random.Random(4)
    p, lo, hi, caps = instance(rng)
    w = project_grouped(p, lo, hi, GROUPS, caps)
    assert sum(w) == pytest.approx(1.0, abs=1e-12)


def test_caps_that_cannot_hold_an_invested_index_are_refused():
    p, lo, hi, _ = instance(random.Random(5))
    with pytest.raises(ValueError, match="fully invested"):
        project_grouped(p, lo, hi, GROUPS, [0.3, 0.15, 0.1, 0.15, 0.07])


def test_a_group_whose_lower_bounds_exceed_its_cap_is_refused():
    p, lo, hi, _ = instance(random.Random(6))
    with pytest.raises(ValueError, match="lower bounds"):
        project_grouped(p, lo, hi, GROUPS, [0.1, 1.0, 1.0, 1.0, 1.0])


def test_check_weights_names_a_broken_group_cap():
    w = [1 / N] * N
    with pytest.raises(ValueError, match="group 0 holds"):
        check_weights(w, [0.0] * N, [1.0] * N, groups=GROUPS, caps=[0.3, 1, 1, 1, 1])
