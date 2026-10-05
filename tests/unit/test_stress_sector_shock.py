"""A SECTOR shock may name its sector (generated scenarios). Catalog scenarios do not, and nothing about them moves."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eventshock.config import Settings, load_scenarios
from eventshock.domain import AssetClass, RiskFactor, ShockScope
from eventshock.domain.scenarios import Scenario, ShockSpec
from eventshock.domain.stress import AppliedShock
from eventshock.stress.engine import select_shocks, stress_portfolio
from tests.helpers import make_asset, make_portfolio, shock


def applied(factor, scope, value, sector=None):
    return AppliedShock(factor=factor, scope=scope, sector=sector, base_value=value, scaled_value=value, applicable=True)


TECH = make_asset(asset_id="t", entity_id="T", sector="Technology", market_value=100_000, notional=100_000, beta=1.2)
ENERGY = make_asset(asset_id="e", entity_id="E", sector="Energy", market_value=200_000, notional=200_000, beta=0.8)
FIN = make_asset(asset_id="f", entity_id="F", sector="Financials", market_value=300_000, notional=300_000, beta=1.5)


def test_catalog_scenarios_name_no_sector():
    _, scenarios = load_scenarios(Settings())
    assert scenarios and all(sh.sector is None for s in scenarios for sh in s.shocks)


def test_a_sector_shock_without_a_sector_still_binds_to_the_events_sector():
    pf = make_portfolio([TECH, ENERGY])
    res = {p.asset_id: p for p in stress_portfolio(pf, [applied(RiskFactor.EQUITY, ShockScope.SECTOR, -0.2)], None, "Energy")}
    assert res["e"].delta == pytest.approx(-0.2 * 200_000) and res["t"].delta == 0


def test_two_explicit_sector_shocks_apply_to_their_own_sectors_only():
    pf = make_portfolio([TECH, ENERGY, FIN])
    shocks = [applied(RiskFactor.EQUITY, ShockScope.MARKET, -0.10),
              applied(RiskFactor.EQUITY, ShockScope.SECTOR, -0.15, "Technology"),
              applied(RiskFactor.EQUITY, ShockScope.SECTOR, -0.05, "Energy")]
    res = {p.asset_id: p for p in stress_portfolio(pf, shocks, None, None)}
    assert res["t"].delta == pytest.approx(-0.15 * 100_000)  # the sector shock replaces the market one (no beta)
    assert res["e"].delta == pytest.approx(-0.05 * 200_000)
    assert res["f"].delta == pytest.approx(-0.10 * 1.5 * 300_000)  # the market shock, through its beta
    assert res["t"].shocks[0].sector == "Technology" and res["f"].shocks[0].sector is None


def test_explicit_sector_does_not_follow_the_events_sector():
    chosen = select_shocks(ENERGY, [applied(RiskFactor.EQUITY, ShockScope.SECTOR, -0.15, "Technology")], None, "Energy")
    assert chosen == {}


def test_positions_still_reconcile_with_explicit_sector_shocks():
    pf = make_portfolio([TECH, ENERGY, FIN, make_asset(asset_id="b", entity_id="B", sector="Technology", asset_type=AssetClass.BOND, duration=6.0,
                                                       market_value=100_000, notional=100_000)])
    shocks = [applied(RiskFactor.CREDIT_SPREAD_BPS, ShockScope.MARKET, 50), applied(RiskFactor.CREDIT_SPREAD_BPS, ShockScope.SECTOR, 90, "Technology"),
              applied(RiskFactor.EQUITY, ShockScope.SECTOR, -0.1, "Technology")]
    for p in stress_portfolio(pf, shocks, None, None):
        assert sum(p.by_factor.values()) == pytest.approx(p.delta)


class TestContract:
    def test_only_a_sector_scope_shock_can_name_a_sector(self):
        with pytest.raises(ValidationError):
            ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-0.1, sector="Energy")

    def test_the_same_factor_and_scope_may_repeat_for_different_sectors(self):
        sh = [ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.SECTOR, value=-0.1, sector=s) for s in ("Energy", "Technology")]
        Scenario(id="x", version="1", name="x", category="GEOPOLITICAL", description="d", shocks=sh)
        with pytest.raises(ValidationError):
            Scenario(id="x", version="1", name="x", category="GEOPOLITICAL", description="d", shocks=[sh[0], sh[0]])

    def test_helper_shock_default_has_no_sector(self):
        assert shock(RiskFactor.EQUITY, ShockScope.SECTOR, -0.1).sector is None
