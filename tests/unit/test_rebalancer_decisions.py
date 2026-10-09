"""A cycle as a proposal: before / target / after, the trade, the reports behind it, the rule that held it back, and the flags on the evidence."""

from __future__ import annotations

import pytest

from eventshock.rebalancer.models import ConstraintCode, EvidenceQuality, TradeSide
from tests.rebalancer_helpers import cfg, risk_inputs, service, sig

TECH = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META"]


def burst(ticker, x, n=6, start=1.0, prefix="b", spacing=1.0):
    return [sig(f"{prefix}{ticker}{i}", ticker, x, hours=start + i * spacing, source=f"src{i}", headline=f"{ticker} headline {i}") for i in range(n)]


def last(svc, params=None, strategy=None):
    """The busiest cycle (most turnover): later cycles are at the target and trade nothing."""
    p = params or svc.default_params()
    cycles = svc.timeline(p, strategy=strategy).cycles
    i = max(range(len(cycles)), key=lambda k: (cycles[k].turnover, -k))
    return svc.decisions(i, p, strategy=strategy)


def test_every_stock_has_before_target_after_and_the_trade_is_their_difference():
    svc = service(burst("AAPL", 0.9, 8) + burst("XOM", -0.9, 8))
    d = last(svc)
    assert len(d.decisions) == 15 and sorted(x.ticker for x in d.decisions) == sorted(svc.tickers)
    for x in d.decisions:
        assert x.trade == pytest.approx(x.after - x.before, abs=1e-12)
    assert sum(x.after for x in d.decisions) == pytest.approx(1.0, abs=1e-9)
    assert sum(x.trade for x in d.decisions) == pytest.approx(0.0, abs=1e-9)
    assert d.buys + d.sells + d.holds == 15
    assert d.turnover == pytest.approx(0.5 * sum(abs(x.trade) for x in d.decisions), abs=1e-9)


def test_decisions_are_sorted_largest_trade_first_and_buys_follow_good_news():
    svc = service(burst("AAPL", 0.9, 8) + burst("XOM", -0.9, 8))
    d = last(svc)
    sizes = [abs(x.trade) for x in d.decisions]
    assert sizes == sorted(sizes, reverse=True)
    by = {x.ticker: x for x in d.decisions}
    assert by["AAPL"].side is TradeSide.BUY and by["XOM"].side is TradeSide.SELL and by["MSFT"].side is TradeSide.HOLD


def test_each_card_lists_the_headlines_behind_it_and_they_add_up_to_the_score():
    svc = service(burst("AAPL", 0.6, 4))
    x = next(x for x in last(svc).decisions if x.ticker == "AAPL")
    assert x.drivers and all(d.headline.startswith("AAPL headline") and d.published_at for d in x.drivers)
    assert sum(d.contribution for d in x.drivers) == pytest.approx(x.score, abs=1e-9)   # fewer reports than the display limit, so they are all shown
    assert "AAPL" in x.explanation and f"{x.reports} reports" in x.explanation


def test_thin_evidence_and_staleness_are_flagged():
    svc = service([sig("one", "AAPL", 0.8, hours=1.0)] + burst("MSFT", 0.5, 8, start=60, spacing=1.0), as_of_hours=120)
    d = {x.ticker: x for x in last(svc).decisions}
    assert d["AAPL"].evidence_quality is EvidenceQuality.THIN and d["AAPL"].stale
    assert d["MSFT"].evidence_quality is EvidenceQuality.OK and not d["MSFT"].stale
    assert d["JPM"].evidence_quality is EvidenceQuality.NONE and d["JPM"].newest_age_hours is None
    assert "thin" in d["AAPL"].explanation and "stale" in d["AAPL"].explanation


def test_reports_that_disagree_are_flagged_and_unanimous_ones_are_not():
    mixed = [sig(f"p{i}", "AAPL", 0.8, hours=1 + i, source=f"a{i}") for i in range(3)] + [sig(f"n{i}", "AAPL", -0.8, hours=1 + i, source=f"c{i}") for i in range(3)]
    svc = service(mixed + burst("MSFT", 0.8, 6))
    d = {x.ticker: x for x in last(svc).decisions}
    assert d["AAPL"].conflicting and 0.4 < d["AAPL"].positive_share < 0.6
    assert not d["MSFT"].conflicting and d["MSFT"].positive_share == pytest.approx(1.0)
    assert "disagree" in d["AAPL"].explanation


def test_the_turnover_cap_is_named_as_the_rule_that_held_a_trade_back():
    svc = service(burst("AAPL", 1.0, 20) + burst("NVDA", 1.0, 20) + burst("JPM", -1.0, 20) + burst("XOM", -1.0, 20), as_of_hours=120)
    p = svc.resolve_params(tilt=6.0, max_turnover=0.01)
    d = last(svc, p)
    capped = [x for x in d.decisions if any(b.code is ConstraintCode.TURNOVER_CAP for b in x.binding)]
    assert capped and all(abs(x.after - x.target) > 0 for x in capped)
    assert all("turnover cap" in x.explanation for x in capped)


def test_the_risk_strategy_names_the_sector_cap_and_costs_are_in_dollars_of_the_mock_index():
    svc = service([s for t in TECH for s in burst(t, 0.9, 8)] + burst("JPM", -0.5, 8), real_sectors=True, risk=risk_inputs(adv={"JPM": 1e7}))
    p = svc.resolve_params(tilt=6.0, max_turnover=0.25)
    d = last(svc, p, "sentiment_risk")
    assert d.strategy == "sentiment_risk"
    assert any(b.code is ConstraintCode.SECTOR_CAP for x in d.decisions for b in x.binding)
    jpm = next(x for x in d.decisions if x.ticker == "JPM")
    assert jpm.side is TradeSide.SELL
    assert jpm.notional_usd == pytest.approx(abs(jpm.trade) * cfg().risk.liquidity.mock_aum_usd)
    assert jpm.participation == pytest.approx(jpm.notional_usd / 1e7) and jpm.liquidity_flag
    assert d.est_cost_usd == pytest.approx(d.est_cost * cfg().risk.liquidity.mock_aum_usd)
    assert d.est_cost == pytest.approx(sum(abs(x.trade) for x in d.decisions) * cfg().turnover.cost_bps / 1e4)


def test_the_proposal_digest_changes_with_the_strategy_the_parameters_and_the_cycle():
    svc = service(burst("AAPL", 0.9, 8) + burst("XOM", -0.9, 8), real_sectors=True, risk=risk_inputs())
    a = last(svc)
    assert last(svc).proposal_sha256 == a.proposal_sha256
    assert last(svc, strategy="sentiment_impact").proposal_sha256 != a.proposal_sha256
    assert last(svc, svc.resolve_params(tilt=3.0)).proposal_sha256 != a.proposal_sha256
    assert svc.decisions(len(svc.timeline(svc.default_params()).cycles) - 1, svc.default_params()).proposal_sha256 != a.proposal_sha256


def test_a_cycle_that_does_not_exist_is_an_error():
    svc = service(burst("AAPL", 0.5, 4))
    with pytest.raises(LookupError):
        svc.decisions(999, svc.default_params())
    with pytest.raises(ValueError, match="unknown strategy"):
        svc.decisions(0, svc.default_params(), strategy="nope")
