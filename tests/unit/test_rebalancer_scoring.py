"""A company's score: decay, one-source-one-vote, shrinkage, exact decomposition and point-in-time."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from eventshock.config import REPO_ROOT
from eventshock.rebalancer.config import load_rebalancer_config
from eventshock.rebalancer.scoring import Report, score

CFG = load_rebalancer_config(REPO_ROOT / "configs").evidence
T = datetime(2026, 9, 20, 12, tzinfo=UTC)


def rep(i: int, hours_ago: float, x: float, source: str = "wire") -> Report:
    return Report(signal_id=f"s{i}", ticker="AAPL", source=source, published_at=T - timedelta(hours=hours_ago), sentiment=x, headline=f"h{i}")


def test_no_reports_is_a_zero_score_with_no_evidence():
    s = score([], T, CFG)
    assert (s.value, s.evidence, s.reports, s.sources) == (0.0, 0.0, 0, 0)


def test_one_fresh_positive_report_is_a_shrunk_positive_score():
    s = score([rep(1, 0, 1.0)], T, CFG)
    assert s.value == pytest.approx(1.0 / (1.0 + CFG.prior_pseudo_count))
    assert 0 < s.value < 1


def test_more_independent_sources_give_a_stronger_score():
    one = score([rep(1, 1, 0.5, "a")], T, CFG).value
    three = score([rep(1, 1, 0.5, "a"), rep(2, 1, 0.5, "b"), rep(3, 1, 0.5, "c")], T, CFG).value
    assert three > one


def test_one_source_cannot_shout_louder_by_publishing_more():
    many = score([rep(i, 0.5, 0.8, "spam") for i in range(30)], T, CFG)
    single = score([rep(0, 0.5, 0.8, "spam")], T, CFG)
    assert many.value <= 0.8 * CFG.source_vote_cap / (CFG.source_vote_cap + CFG.prior_pseudo_count) + 1e-12
    assert many.sources == 1 and many.reports == 30
    assert many.value > single.value - 1e-12   # more reports from one source never weakens the vote


def test_a_report_loses_half_its_weight_every_half_life():
    fresh = score([rep(1, 0, 1.0)], T, CFG)
    old = score([rep(1, CFG.half_life_hours, 1.0)], T, CFG)
    assert old.contributions[0].decayed_weight == pytest.approx(0.5)
    assert old.value < fresh.value


def test_reports_beyond_the_lookback_are_ignored():
    horizon = CFG.lookback_half_lives * CFG.half_life_hours
    assert score([rep(1, horizon + 1, 1.0)], T, CFG).reports == 0
    assert score([rep(1, horizon - 1, 1.0)], T, CFG).reports == 1


def test_a_shorter_half_life_forgets_faster():
    r = [rep(1, 24, 1.0)]
    assert score(r, T, CFG, half_life_hours=6).value < score(r, T, CFG, half_life_hours=72).value


def test_positive_and_negative_reports_net_out():
    s = score([rep(1, 1, 0.6, "a"), rep(2, 1, -0.6, "b")], T, CFG)
    assert s.value == pytest.approx(0.0, abs=1e-12)


def test_the_contributions_add_up_to_the_score_exactly():
    rng = random.Random(1)
    for _ in range(40):
        rs = [rep(i, rng.uniform(0, 100), rng.uniform(-1, 1), rng.choice("abcd")) for i in range(rng.randint(1, 25))]
        s = score(rs, T, CFG)
        assert sum(k.contribution for k in s.contributions) == pytest.approx(s.value, abs=1e-12)
        assert -1 <= s.value <= 1


def test_a_report_from_the_future_is_never_read():
    """Point-in-time: a report published after the instant cannot change the score at that instant."""
    past = [rep(1, 5, 0.4, "a")]
    future = past + [Report("late", "AAPL", "b", T + timedelta(minutes=1), -1.0, "late")]
    assert score(past, T, CFG) == score(future, T, CFG)


def test_the_score_does_not_depend_on_the_order_the_reports_arrive_in():
    rs = [rep(i, i * 3.0, (-1) ** i * 0.5, "ab"[i % 2]) for i in range(10)]
    assert score(rs, T, CFG).value == score(list(reversed(rs)), T, CFG).value


def test_a_nonpositive_half_life_is_an_error():
    with pytest.raises(ValueError, match="half_life"):
        score([rep(1, 0, 1.0)], T, CFG, half_life_hours=0)
