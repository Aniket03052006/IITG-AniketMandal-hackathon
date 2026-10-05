"""Stress on a personal portfolio: hand-checked arithmetic, cash and unsupported classes, the optional override, determinism, the exposure chain."""

from __future__ import annotations

import pytest

from eventshock.config import AppConfig
from eventshock.domain import (
    AssetClass,
    Entity,
    EventCategory,
    RiskFactor,
    ScopeBasis,
    ScopeLevel,
    ShockScope,
    SignalScope,
    StressStatus,
)
from eventshock.domain.scenarios import ShockSpec
from eventshock.portfolio.chain import build_exposure_chain
from eventshock.portfolio.compare import compare_runs
from eventshock.portfolio.models import PortfolioListItem
from eventshock.services.stress_service import StressService
from eventshock.store import InMemoryPortfolioRepository, InMemorySignalRepository
from eventshock.stress.scenarios import ScenarioCatalog
from tests.helpers import NOW, make_asset, make_portfolio, make_scenario, make_signal

REG = EventCategory.REGULATORY_LEGAL
SHOCKS = [
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-0.10),
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.SECTOR, value=-0.20),
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.ISSUER, value=-0.30),
    ShockSpec(factor=RiskFactor.RATES_BPS, scope=ShockScope.MARKET, value=100),
    ShockSpec(factor=RiskFactor.CREDIT_SPREAD_BPS, scope=ShockScope.MARKET, value=50),
]
BOOK = [
    make_asset(asset_id="e1", entity_id="E1", sector="Fin", market_value=400_000, notional=400_000, beta=1.5),
    make_asset(asset_id="e2", entity_id="E2", sector="Tech", market_value=200_000, notional=200_000, beta=0.5),
    make_asset(asset_id="tlt", entity_id="USER_TLT", sector="Other", asset_type=AssetClass.BOND, duration=17.0, spread_sensitivity=0.0,
               market_value=100_000, notional=100_000),
    make_asset(asset_id="lqd", entity_id="USER_LQD", sector="Other", asset_type=AssetClass.BOND, duration=8.0,
               market_value=100_000, notional=100_000),
    make_asset(asset_id="cash", entity_id="USER_CASH", sector="Cash", asset_type=AssetClass.CASH, market_value=100_000, notional=100_000),
    make_asset(asset_id="gld", entity_id="USER_GLD", sector="Other", asset_type=AssetClass.OTHER, market_value=100_000, notional=100_000),
]


def svc(signal, default_assets=None, scenario=None):
    scn = scenario or make_scenario(REG, SHOCKS)
    cat = ScenarioCatalog([scn], {REG: scn.id}, require_complete=False)
    default = default_assets or [make_asset(asset_id="d1", entity_id="E1", market_value=1_000_000, notional=1_000_000)]
    ents = [Entity(entity_id=a.entity_id, name=a.entity_id, sector="x", country="US") for a in default]
    return StressService(InMemorySignalRepository([signal], NOW), InMemoryPortfolioRepository(make_portfolio(default), ents), cat, AppConfig())


def company_signal(entity="E1", sector="Fin"):
    return make_signal(entity_id=entity, sector=sector, impact=7)


def by_id(r):
    return {p.asset_id: p for p in r.positions}


def test_mixed_book_arithmetic_is_hand_checkable() -> None:
    r = svc(company_signal()).run("s1", portfolio=make_portfolio(BOOK))
    assert r.status is StressStatus.COMPLETED
    p = by_id(r)
    # severity 7 / reference 7 = scale 1. e1 is the named issuer: the issuer shock (-30%) wins over sector and market, with no beta.
    assert p["e1"].delta == pytest.approx(400_000 * -0.30)
    # e2 is another sector: only the market shock, scaled by beta: V x beta x s
    assert p["e2"].delta == pytest.approx(200_000 * 0.5 * -0.10)
    # a Treasury fund takes the rates shock only (spread sensitivity 0): -D x dy
    assert p["tlt"].delta == pytest.approx(100_000 * -17 * 100 / 10_000)
    # a corporate bond fund takes rates and spread
    assert p["lqd"].delta == pytest.approx(100_000 * -8 * (100 + 50) / 10_000)
    assert p["cash"].delta == 0 and p["gld"].delta == 0 and p["cash"].shocks == [] and p["gld"].shocks == []
    assert r.summary.pnl == pytest.approx(sum(x.delta for x in r.positions))
    assert r.summary.baseline_value == pytest.approx(1_000_000)


def test_cash_is_not_uncovered_but_an_unsupported_instrument_is() -> None:
    r = svc(company_signal()).run("s1", portfolio=make_portfolio(BOOK))
    assert r.uncovered is not None and r.uncovered.asset_ids == ["gld"] and r.uncovered.market_value == pytest.approx(100_000)


def test_without_a_portfolio_the_default_is_stressed_exactly_as_before() -> None:
    s = svc(company_signal())
    plain, again = s.run("s1"), s.run("s1", portfolio=None)
    assert plain.run_id == again.run_id and plain.summary == again.summary
    assert plain.audit.portfolio_id == "pf_test"
    mine = s.run("s1", portfolio=make_portfolio(BOOK).model_copy(update={"portfolio_id": "pf_mine"}))
    assert mine.run_id != plain.run_id and mine.audit.portfolio_id == "pf_mine"
    assert [r.audit.portfolio_id for r in s.runs_for("s1", "pf_mine")] == ["pf_mine"]
    assert {r.audit.portfolio_id for r in s.runs_for("s1")} == {"pf_test", "pf_mine"}


def test_same_portfolio_same_event_same_scenario_same_result() -> None:
    pf = make_portfolio(BOOK)
    a, b = svc(company_signal()).run("s1", portfolio=pf), svc(company_signal()).run("s1", portfolio=pf)
    assert a.run_id == b.run_id and a.model_dump_json() == b.model_dump_json()


def test_zero_exposure_book_has_zero_change_and_an_empty_chain() -> None:
    cash_only = make_portfolio([make_asset(asset_id="c", entity_id="USER_CASH", sector="Cash", asset_type=AssetClass.CASH)])
    s = svc(company_signal())
    r = s.run("s1", portfolio=cash_only)
    assert r.status is StressStatus.COMPLETED and r.summary.pnl == 0 and r.uncovered.asset_count == 0
    chain = build_exposure_chain(r, cash_only, s._signals.get("s1"))
    assert chain.steps == [] and "zero" in chain.summary and chain.not_reached is not None and chain.not_reached.share == pytest.approx(1.0)


def test_full_exposure_book_takes_the_whole_market_shock() -> None:
    full = make_portfolio([make_asset(asset_id="x", entity_id="USER_X", sector="Other", market_value=1_000_000, notional=1_000_000, beta=1.0)])
    r = svc(make_signal(entity_id="UNKNOWN_ENTITY", impact=7, scope=SignalScope(level=ScopeLevel.MARKET, basis=ScopeBasis.THEME_TERMS, themes=["rates"]))).run("s1", portfolio=full)
    assert r.status is StressStatus.COMPLETED and r.summary.pnl_pct == pytest.approx(-0.10)


def test_chain_regroups_the_engines_own_numbers() -> None:
    pf = make_portfolio(BOOK)
    s = svc(company_signal())
    r = s.run("s1", portfolio=pf)
    chain = build_exposure_chain(r, pf, s._signals.get("s1"))
    assert chain.total_impact == pytest.approx(r.summary.pnl) and sum(st.impact for st in chain.steps) == pytest.approx(r.summary.pnl)
    top = chain.steps[0]
    assert (top.factor, top.scope) == ("EQUITY", "ISSUER") and top.exposed_share == pytest.approx(0.4) and top.impact == pytest.approx(-120_000)
    rates = next(st for st in chain.steps if st.factor == "RATES_BPS")
    assert rates.exposed_share == pytest.approx(0.2) and "duration 12.5" in rates.sensitivity  # (17 + 8) / 2
    spread = next(st for st in chain.steps if st.factor == "CREDIT_SPREAD_BPS")
    assert spread.exposed_share == pytest.approx(0.1)  # the Treasury fund takes none of it
    assert "You hold E1" in chain.summary and "Company event" in chain.event_line
    assert chain.not_reached is not None and chain.not_reached.share == pytest.approx(0.2)  # cash + unsupported


def test_chain_says_so_when_the_named_company_is_not_held() -> None:
    pf = make_portfolio(BOOK)
    s = svc(company_signal(entity="ELSEWHERE", sector="Tech"))
    r = s.run("s1", portfolio=pf)
    chain = build_exposure_chain(r, pf, s._signals.get("s1"))
    assert "do not hold" in chain.summary and all(st.scope != "ISSUER" for st in chain.steps)


def test_chain_refuses_a_run_with_no_numbers() -> None:
    s = svc(company_signal())
    r = s.run("s1", scenario_id=None, force=False, impact_override=None)  # severity 7 triggers; make a not-triggered one instead
    low = svc(make_signal(impact=3)).run("s1")
    assert low.status is StressStatus.NOT_TRIGGERED
    with pytest.raises(ValueError):
        build_exposure_chain(low, make_portfolio(BOOK), s._signals.get("s1"))
    assert r.status is StressStatus.COMPLETED


def test_compare_lines_up_two_runs_and_names_the_gap() -> None:
    a_pf = make_portfolio(BOOK).model_copy(update={"portfolio_id": "pf_a", "name": "A"})
    b_pf = make_portfolio([make_asset(asset_id="c", entity_id="USER_CASH", sector="Cash", asset_type=AssetClass.CASH),
                           ]).model_copy(update={"portfolio_id": "pf_b", "name": "B"})
    s = svc(company_signal())
    ra, rb = s.run("s1", portfolio=a_pf), s.run("s1", portfolio=b_pf)
    item = lambda pf, n: PortfolioListItem(id=pf.portfolio_id, name=n, kind="USER", base_currency="USD", total_value=pf.total_value, holding_count=len(pf.assets), description="")  # noqa: E731
    cmp = compare_runs("s1", "scn_t", item(a_pf, "A"), item(b_pf, "B"), ra, rb)
    assert cmp.pnl_pct_b == 0 and cmp.pnl_pct_a < 0 and cmp.by_factor[0].gap_pct != 0
    assert cmp.difference.startswith("A shows the larger modeled loss") and "equity price" in cmp.difference
    same = compare_runs("s1", "scn_t", item(a_pf, "A"), item(a_pf, "A2"), ra, ra)
    assert "same modeled change" in same.difference


def test_compare_reports_a_side_with_no_numbers() -> None:
    s = svc(make_signal(impact=3))
    r = s.run("s1")
    item = PortfolioListItem(id="d", name="D", kind="DEFAULT", base_currency="USD", total_value=1.0, holding_count=1, description="")
    cmp = compare_runs("s1", None, item, item, r, r)
    assert cmp.difference.startswith("No comparison") and cmp.by_sector == []


def test_a_default_asset_serialises_exactly_as_before() -> None:
    a = make_asset()
    assert "spread_sensitivity" not in a.model_dump() and "spread_sensitivity" not in a.model_dump(mode="json")
    nd = make_asset(asset_type=AssetClass.BOND, duration=3.0, spread_sensitivity=0.0)
    assert nd.model_dump()["spread_sensitivity"] == 0.0
    assert make_portfolio([a]).content_hash() != make_portfolio([nd]).content_hash()
    assert make_portfolio([make_asset(spread_sensitivity=1.0)]).content_hash() == make_portfolio([a]).content_hash()
