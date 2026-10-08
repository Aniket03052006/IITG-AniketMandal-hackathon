"""Stress attribution: every table adds up to the run's total, on catalog and generated scenarios, floors, loans, cash and a mixed personal book."""

from __future__ import annotations

import pytest

from eventshock.config import AppConfig
from eventshock.domain import AssetClass, Entity, EventCategory, RiskFactor, ShockScope, StressStatus
from eventshock.domain.scenarios import ShockSpec
from eventshock.propagation.attribution import OTHER, build_attribution
from eventshock.services.stress_service import StressService
from eventshock.store import InMemoryPortfolioRepository, InMemorySignalRepository
from tests.helpers import NOW, make_scenario, make_signal
from tests.prop_helpers import NAMES, PROP_CFG, asset, book, catalog, mapper
from tests.unit.test_propagation_scenario import gen

LABELS = {k: v.label for k, v in PROP_CFG.risk_factors.items()}


def service(pf, signal=None, scenarios=None):
    sig = signal or make_signal("s1", category=EventCategory.GEOPOLITICAL, impact=8, entity_id="UNKNOWN_ENTITY")
    ents = [Entity(entity_id=e, name=NAMES.get(e, e), sector="x", country="US") for e in sorted({a.entity_id for a in pf.assets})]
    return StressService(InMemorySignalRepository([sig], NOW), InMemoryPortfolioRepository(pf, ents), catalog(), AppConfig())


def attribute(run, pf, origins=None):
    return build_attribution(run, pf, industry_of=mapper().industry_of, origins=origins, engine_factor_map=PROP_CFG.engine_factor_map, risk_factor_labels=LABELS,
                             entity_names=NAMES)


def assert_reconciles(att, run):
    assert att.reconciled and att.total_pnl == run.summary.pnl
    for t in [att.drivers, *att.tables]:
        assert t.reconciled and abs(t.sum - att.total_pnl) <= att.tolerance and abs(t.residual) <= att.tolerance, t.dimension
        assert sum(r.delta for r in t.rows) == pytest.approx(att.total_pnl, abs=att.tolerance)


def test_generated_scenario_attribution_reconciles_in_every_dimension():
    pf = book()
    g = gen()
    svc = service(pf)
    run = svc.run_scenario("s1", g.scenario, portfolio=pf)
    assert run.status is StressStatus.COMPLETED
    att = attribute(run, pf, g.origins)
    assert_reconciles(att, run)
    assert {t.dimension for t in att.tables} == {"issuer", "sector", "industry", "market_factor", "risk_factor", "asset_class", "position"}
    # the sector-by-market-factor table is the same total regrouped again, and agrees with the one-way tables
    mx = att.matrix
    assert mx is not None and mx.unit == "pnl" and mx.reconciled and mx.sum == pytest.approx(att.total_pnl, abs=att.tolerance)
    by_sector = {r.key: r.delta for r in next(t for t in att.tables if t.dimension == "sector").rows}
    by_factor = {r.key: r.delta for r in next(t for t in att.tables if t.dimension == "market_factor").rows}
    assert {r.key: r.total for r in mx.rows} == pytest.approx(by_sector) and {c.key: c.total for c in mx.cols} == pytest.approx(by_factor)
    assert [r.total for r in mx.rows] == sorted(r.total for r in mx.rows)  # the largest loss first
    assert att.drivers.dimension == "driver" and {r.key for r in att.drivers.rows} <= {"MARKET", "SECTOR", "ISSUER", OTHER}
    # propagated sector shocks are attributed to the risk factor that wrote them
    rf = {r.key for r in next(t for t in att.tables if t.dimension == "risk_factor").rows}
    assert "OIL_ENERGY" in rf or "GEOPOLITICAL" in rf


def test_catalog_scenario_attribution_reconciles():
    pf = book()
    run = service(pf, make_signal("s1", category=EventCategory.GEOPOLITICAL, impact=8, entity_id="UNKNOWN_ENTITY")).run("s1", portfolio=pf)
    assert run.status is StressStatus.COMPLETED
    assert_reconciles(attribute(run, pf), run)


def test_the_headline_says_the_total_and_the_drivers():
    pf = book()
    g = gen()
    run = service(pf).run_scenario("s1", g.scenario, portfolio=pf)
    att = attribute(run, pf, g.origins)
    assert "Total modeled change" in att.headline and "$" in att.headline


def test_bond_floor_loans_and_cash_reconcile():
    pf = book([asset("long", "ENT_UST", "Other", 100_000, AssetClass.BOND, duration=30.0)])
    scn = make_scenario(EventCategory.GEOPOLITICAL, [
        ShockSpec(factor=RiskFactor.RATES_BPS, scope=ShockScope.MARKET, value=2000),  # -100% on a 30-year bond: the floor
        ShockSpec(factor=RiskFactor.PD_MULTIPLIER, scope=ShockScope.MARKET, value=3.0),
        ShockSpec(factor=RiskFactor.LGD_ADD, scope=ShockScope.MARKET, value=0.2),
        ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-0.1)])
    run = service(pf).run_scenario("s1", scn, portfolio=pf)
    assert run.status is StressStatus.COMPLETED
    att = attribute(run, pf)
    assert_reconciles(att, run)
    cash = next((r for r in next(t for t in att.tables if t.dimension == "asset_class").rows if r.key == "CASH"), None)
    assert cash is None  # cash is never moved, so it contributes nothing and is omitted
    assert any(r.key == "LOAN" for r in next(t for t in att.tables if t.dimension == "asset_class").rows)


def test_industry_dimension_marks_unclassified_holdings():
    pf = book()
    g = gen()
    run = service(pf).run_scenario("s1", g.scenario, portfolio=pf)
    rows = {r.key: r for r in next(t for t in attribute(run, pf, g.origins).tables if t.dimension == "industry").rows}
    assert "Unclassified" in rows  # Apple and the Treasuries have no industry in the entity master


def test_issuer_names_come_from_the_entity_master():
    pf = book()
    g = gen()
    run = service(pf).run_scenario("s1", g.scenario, portfolio=pf)
    labels = {r.label for r in next(t for t in attribute(run, pf, g.origins).tables if t.dimension == "issuer").rows}
    assert "Exxon Mobil" in labels and not any("loan" in x for x in labels)


def test_a_table_that_does_not_add_up_fails_loudly():
    pf = book()
    g = gen()
    run = service(pf).run_scenario("s1", g.scenario, portfolio=pf)
    broken = run.model_copy(update={"summary": run.summary.model_copy(update={"pnl": run.summary.pnl - 5.0})})
    with pytest.raises(ValueError, match="does not reconcile"):
        attribute(broken, pf, g.origins)


def test_only_a_completed_run_can_be_attributed():
    pf = book()
    run = service(pf, make_signal("s1", category=EventCategory.GEOPOLITICAL, impact=2, entity_id="UNKNOWN_ENTITY")).run("s1", portfolio=pf)
    assert run.status is StressStatus.NOT_TRIGGERED
    with pytest.raises(ValueError, match="completed"):
        attribute(run, pf)


def test_unexplained_part_of_a_position_is_other_not_dropped():
    pf = book()
    g = gen()
    run = service(pf).run_scenario("s1", g.scenario, portfolio=pf)
    p0 = run.positions[0]
    skewed = run.model_copy(update={"positions": [p0.model_copy(update={"by_factor": {}}), *run.positions[1:]]})
    att = attribute(skewed, pf, g.origins)
    assert_reconciles(att, skewed)
    assert OTHER in {r.key for r in att.drivers.rows}


def test_origins_missing_still_reconciles():
    pf = book()
    g = gen()
    run = service(pf).run_scenario("s1", g.scenario, portfolio=pf)
    assert_reconciles(attribute(run, pf, None), run)

