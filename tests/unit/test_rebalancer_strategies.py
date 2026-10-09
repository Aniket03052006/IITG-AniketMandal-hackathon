"""Strategies: the baseline is untouched, the risk strategy adds named constraints, the impact strategy only shrinks tone, and every constraint a stock meets is named."""

from __future__ import annotations

import json

import pytest

from eventshock.config import REPO_ROOT
from eventshock.rebalancer.backtest import timeline_digest
from eventshock.rebalancer.models import ConstraintCode
from eventshock.rebalancer.scoring import Report, impact_multiplier, score
from tests.rebalancer_helpers import BASE, cfg, risk_inputs, service, sig

EV = cfg().evidence


def burst(ticker: str, x: float, n: int = 6, start: float = 1.0, impact: int = 5) -> list:
    return [sig(f"b{ticker}{i}", ticker, x, hours=start + i, source=f"src{i}", impact=impact) for i in range(n)]


TECH = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META"]


def tech_boom():
    return [s for t in TECH for s in burst(t, 0.9, 8)] + [s for t in ("JPM", "XOM", "JNJ") for s in burst(t, -0.5, 8)]


# ------------------------------------------------------------------------------------------------------------------------------------ baseline
def test_an_unknown_or_unavailable_strategy_is_refused():
    svc = service(burst("AAPL", 0.5))
    with pytest.raises(ValueError, match="unknown strategy"):
        svc.resolve_strategy("magic")
    with pytest.raises(ValueError, match="risk_inputs"):
        svc.resolve_strategy("sentiment_risk")   # no risk inputs given
    assert svc.resolve_strategy(None) == "sentiment"
    info = {i.id: i for i in svc.strategy_info()}
    assert info["sentiment"].available and not info["sentiment_risk"].available and info["sentiment_risk"].reason


def test_the_baseline_is_the_same_rule_as_before_strategies_existed():
    """The committed back-test hashed the baseline's weight path before this feature; the served path must still produce it."""
    committed = json.loads((REPO_ROOT / "data" / "rebalancer" / "backtest.json").read_text(encoding="utf-8"))
    assert "timeline_sha256" in committed   # the e2e test compares it with the replay's own path; here: the digest function is stable
    svc = service(tech_boom())
    tl = svc.timeline(svc.default_params())
    base = svc.timeline(svc.default_params(), strategy="sentiment")
    assert timeline_digest([c.weights for c in tl.cycles], tl.params) == timeline_digest([c.weights for c in base.cycles], base.params)
    assert all(not n.binding or all(b.code in (ConstraintCode.UPPER_BOUND, ConstraintCode.LOWER_BOUND, ConstraintCode.TURNOVER_CAP, ConstraintCode.MIN_TRADE) for b in n.binding)
               for i in range(len(tl.cycles)) for n in svc.cycle(i, svc.default_params()).names)


# --------------------------------------------------------------------------------------------------------------------------- risk constraints
def test_the_sector_cap_holds_the_technology_weight_down():
    sigs = tech_boom()
    base = service(sigs, real_sectors=True, risk=risk_inputs())
    p = base.resolve_params(tilt=6.0, max_turnover=0.25)
    tech = [base.tickers.index(t) for t in TECH]
    w_base = base.timeline(p).cycles[-1].weights
    w_risk = base.timeline(p, strategy="sentiment_risk").cycles[-1].weights
    cap = min(1.0, 6 / 15 * 1.25)
    assert sum(w_base[j] for j in tech) > cap + 1e-6   # without the rule, technology exceeds 50 %
    assert sum(w_risk[j] for j in tech) <= cap + 1e-9
    assert sum(w_risk) == pytest.approx(1.0, abs=1e-9)


def test_a_stock_held_by_the_sector_cap_is_told_so_and_the_effects_telescope():
    base = service(tech_boom(), real_sectors=True, risk=risk_inputs())
    p = base.resolve_params(tilt=6.0, max_turnover=0.25)
    detail = base.cycle(len(base.timeline(p).cycles) - 1, p, strategy="sentiment_risk")
    tech = [n for n in detail.names if n.ticker in TECH]
    assert all(any(b.code is ConstraintCode.SECTOR_CAP for b in n.binding) for n in tech)
    # tilt + every stage's difference = the target, for every stock, exactly
    c = base.run_cycles(p, strategy="sentiment_risk")[-1]
    for j in range(15):
        assert c.stages[0][j] + sum(c.stages[k + 1][j] - c.stages[k][j] for k in range(len(c.stages) - 1)) == pytest.approx(c.target[j], abs=1e-12)


def test_a_volatile_stock_may_be_overweight_less_than_a_calm_one():
    risk = risk_inputs(sigma={"NVDA": 0.06})   # three times the median
    svc = service(burst("NVDA", 0.9, 10) + burst("MSFT", 0.9, 10), real_sectors=True, risk=risk)
    p = svc.resolve_params(tilt=6.0, max_turnover=0.25)
    cons = {c.ticker: c.upper for c in svc.constituents("sentiment_risk")}
    b = 1 / 15
    assert cons["NVDA"] < cons["MSFT"] and cons["NVDA"] >= b - 1e-12
    w = svc.timeline(p, strategy="sentiment_risk").cycles[-1].weights
    assert w[svc.tickers.index("NVDA")] <= cons["NVDA"] + 1e-9
    detail = svc.cycle(len(svc.timeline(p).cycles) - 1, p, strategy="sentiment_risk")
    nv = next(n for n in detail.names if n.ticker == "NVDA")
    assert any(b_.code is ConstraintCode.VOL_LIMIT for b_ in nv.binding)


def test_a_thinly_traded_stock_cannot_be_overweight():
    svc = service(burst("PFE", 0.9, 10), real_sectors=True, risk=risk_inputs(adv={"PFE": 1e8}))   # $0.1 bn a day, below the $0.5 bn floor
    p = svc.resolve_params(tilt=6.0, max_turnover=0.25)
    w = svc.timeline(p, strategy="sentiment_risk").cycles[-1].weights[svc.tickers.index("PFE")]
    assert w <= 1 / 15 + 1e-9
    n = next(x for x in svc.cycle(len(svc.timeline(p).cycles) - 1, p, strategy="sentiment_risk").names if x.ticker == "PFE")
    assert any(b.code is ConstraintCode.LIQUIDITY_FLOOR for b in n.binding)


def test_risk_constraints_never_leak_into_the_baseline():
    sigs = tech_boom()
    svc = service(sigs, real_sectors=True, risk=risk_inputs())
    p = svc.resolve_params(tilt=6.0, max_turnover=0.25)
    before = [c.weights for c in svc.timeline(p).cycles]
    svc.timeline(p, strategy="sentiment_risk")
    assert [c.weights for c in svc.timeline(p).cycles] == before


# ----------------------------------------------------------------------------------------------------------------------------------- impact
def test_the_impact_multiplier_runs_from_the_floor_to_one():
    assert impact_multiplier(1, 0.5) == pytest.approx(0.5) and impact_multiplier(10, 0.5) == pytest.approx(1.0)
    assert impact_multiplier(None, 0.5) == 0.5
    assert 0.5 < impact_multiplier(5, 0.5) < 1.0


def test_the_impact_strategy_keeps_the_exact_decomposition_and_never_amplifies():
    from datetime import timedelta
    reports = [Report(f"r{i}", "AAPL", f"src{i}", BASE + timedelta(hours=i), 0.8, impact=k) for i, k in enumerate((1, 5, 10, None))]
    at = BASE + timedelta(hours=10)
    plain, scaled = score(reports, at, EV), score(reports, at, EV, impact_floor=0.5)
    assert sum(c.contribution for c in scaled.contributions) == pytest.approx(scaled.value, abs=1e-12)
    assert abs(scaled.value) < abs(plain.value)
    assert sorted(c.multiplier for c in scaled.contributions) == pytest.approx(sorted([0.5, 0.5, impact_multiplier(5, 0.5), 1.0]))
    assert all(c.multiplier == 1.0 for c in plain.contributions)


def test_high_impact_reports_move_the_impact_strategy_more_than_low_impact_ones():
    hi = service(burst("AAPL", 0.9, 8, impact=10) + burst("MSFT", 0.9, 8, impact=1))
    p = hi.resolve_params(tilt=1.0, max_turnover=0.25)
    w = hi.timeline(p, strategy="sentiment_impact").cycles[-1].weights
    assert w[hi.tickers.index("AAPL")] > w[hi.tickers.index("MSFT")]
    wb = hi.timeline(p).cycles[-1].weights
    assert wb[hi.tickers.index("AAPL")] == pytest.approx(wb[hi.tickers.index("MSFT")], abs=1e-9)   # the baseline cannot tell them apart
