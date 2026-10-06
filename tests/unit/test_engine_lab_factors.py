"""The scenario-lab factors (FX and oil): exposure is data on the position, a position without it is not moved, existing JSON and hashes do not change."""

from __future__ import annotations

import pytest

from eventshock.domain import ShockSpec
from eventshock.domain.enums import AssetClass, RiskFactor, ShockScope
from eventshock.domain.scenarios import Scenario
from eventshock.stress.engine import revalue_asset, select_shocks, stress_portfolio
from tests.helpers import make_asset, make_portfolio, shock

MKT, SEC, ISS = ShockScope.MARKET, ShockScope.SECTOR, ShockScope.ISSUER
EQ, FX, OIL = RiskFactor.EQUITY, RiskFactor.FX_PCT, RiskFactor.COMMODITY_PCT


def run(asset, shocks, entity=None, sector=None):  # noqa: ANN001, ANN201
    return revalue_asset(asset, shocks, entity, sector)


class TestFx:
    def test_a_position_in_the_shocked_currency_moves_one_for_one(self):
        r = run(make_asset(currency="EUR"), [shock(FX, MKT, -0.10, currency="EUR")])
        assert r.delta == pytest.approx(-100_000) and r.by_factor[FX] == pytest.approx(-100_000) and "FX EUR" in r.formula
        assert [(s.factor, s.currency) for s in r.shocks] == [(FX, "EUR")]

    def test_a_base_currency_position_and_another_currency_are_untouched(self):
        for a in (make_asset(), make_asset(currency="GBP")):
            r = run(a, [shock(FX, MKT, -0.10, currency="EUR")])
            assert r.delta == 0 and FX not in r.by_factor and r.shocks == []                  # not moved: never "covered by a zero"

    def test_two_currencies_in_one_scenario_each_reach_their_own_positions(self):
        shocks = [shock(FX, MKT, -0.10, currency="EUR"), shock(FX, MKT, 0.05, currency="GBP")]
        assert run(make_asset(currency="EUR"), shocks).delta == pytest.approx(-100_000)
        assert run(make_asset(currency="GBP"), shocks).delta == pytest.approx(50_000)

    def test_bonds_loans_and_cash_in_the_currency_take_it(self):
        bond = make_asset(asset_type=AssetClass.BOND, duration=5.0, currency="EUR")
        loan = make_asset(asset_type=AssetClass.LOAN, pd=0.02, lgd=0.4, market_value=1_000_000 * (1 - 0.02 * 0.4), currency="EUR")
        cash = make_asset(asset_type=AssetClass.CASH, currency="EUR")
        s = [shock(FX, MKT, -0.10, currency="EUR")]
        assert run(bond, s).delta == pytest.approx(-100_000)
        assert run(loan, s).delta == pytest.approx(-0.10 * loan.market_value)
        assert run(cash, s).delta == pytest.approx(-100_000)                                  # foreign-currency cash is exposed to the exchange rate
        assert run(make_asset(asset_type=AssetClass.CASH), s).delta == 0                       # base-currency cash is not

    def test_a_derivative_uses_delta_and_underlying(self):
        d = make_asset(asset_type=AssetClass.DERIVATIVE, delta=0.5, notional=2_000_000.0, market_value=10_000.0, currency="EUR")
        assert run(d, [shock(FX, MKT, -0.10, currency="EUR")]).delta == pytest.approx(0.5 * 2_000_000 * -0.10)

    def test_fx_and_an_equity_shock_add_for_a_foreign_equity(self):
        r = run(make_asset(currency="EUR", beta=1.0), [shock(EQ, MKT, -0.10), shock(FX, MKT, -0.05, currency="EUR")])
        assert r.delta == pytest.approx(-100_000 - 50_000) and set(r.by_factor) == {EQ, FX}


class TestOil:
    def test_equity_with_a_measured_elasticity_moves_by_it(self):
        r = run(make_asset(commodity_sensitivity=0.8), [shock(OIL, MKT, -0.20)])
        assert r.delta == pytest.approx(1_000_000 * 0.8 * -0.20) and "oil" in r.formula

    def test_a_negative_elasticity_gains_when_oil_falls(self):
        assert run(make_asset(commodity_sensitivity=-0.3), [shock(OIL, MKT, -0.20)]).delta == pytest.approx(60_000)

    def test_no_measured_elasticity_means_not_moved(self):
        r = run(make_asset(), [shock(OIL, MKT, -0.20)])
        assert r.delta == 0 and r.shocks == []

    def test_a_derivative_uses_delta_underlying_and_elasticity(self):
        d = make_asset(asset_type=AssetClass.DERIVATIVE, delta=0.5, notional=2_000_000.0, market_value=10_000.0, commodity_sensitivity=0.4)
        assert run(d, [shock(OIL, MKT, -0.20)]).delta == pytest.approx(0.5 * 2_000_000 * 0.4 * -0.20)

    def test_bonds_are_not_given_an_oil_exposure_the_engine_does_not_define(self):
        assert run(make_asset(asset_type=AssetClass.BOND, duration=5.0, commodity_sensitivity=0.5), [shock(OIL, MKT, -0.2)]).delta == 0


class TestIssuerShockNamingItsIssuer:
    def test_an_issuer_shock_that_names_its_issuer_reaches_it_without_a_signal(self):
        shocks = [shock(EQ, ISS, -0.30, entity_id="E7")]
        assert run(make_asset(entity_id="E7"), shocks, entity=None).delta == pytest.approx(-300_000)
        assert run(make_asset(entity_id="E8"), shocks, entity=None).delta == 0

    def test_it_beats_a_market_shock_for_that_issuer_only(self):
        shocks = [shock(EQ, MKT, -0.05), shock(EQ, ISS, -0.30, entity_id="E7")]
        assert select_shocks(make_asset(entity_id="E7", beta=1.0), shocks, None, None)[EQ].scope is ISS
        assert select_shocks(make_asset(entity_id="E8", beta=1.0), shocks, None, None)[EQ].scope is MKT

    def test_without_an_entity_id_the_shock_still_binds_to_the_events_issuer(self):
        assert run(make_asset(entity_id="E1"), [shock(EQ, ISS, -0.18)], entity="E1").delta == pytest.approx(-180_000)


class TestContractsAndInvariants:
    def test_the_lab_factors_must_name_what_they_need(self):
        with pytest.raises(ValueError, match="must name its currency"):
            ShockSpec(factor=FX, scope=MKT, value=-0.1)
        with pytest.raises(ValueError, match="no other shock may"):
            ShockSpec(factor=EQ, scope=MKT, value=-0.1, currency="EUR")
        with pytest.raises(ValueError, match="three-letter"):
            ShockSpec(factor=FX, scope=MKT, value=-0.1, currency="euro")
        with pytest.raises(ValueError, match="market-wide"):
            ShockSpec(factor=OIL, scope=SEC, value=-0.1, sector="Energy")
        with pytest.raises(ValueError, match="only an ISSUER"):
            ShockSpec(factor=EQ, scope=MKT, value=-0.1, entity_id="E1")
        with pytest.raises(ValueError, match="fraction"):
            ShockSpec(factor=OIL, scope=MKT, value=-1.5)

    def test_two_fx_shocks_of_different_currencies_are_not_duplicates(self):
        specs = [ShockSpec(factor=FX, scope=MKT, value=-0.1, currency="EUR"), ShockSpec(factor=FX, scope=MKT, value=0.1, currency="GBP")]
        Scenario(id="s", version="v", name="n", category="MACROECONOMIC", description="d", shocks=specs)
        with pytest.raises(ValueError, match="duplicate"):
            Scenario(id="s", version="v", name="n", category="MACROECONOMIC", description="d", shocks=[specs[0], specs[0]])

    def test_unset_lab_fields_never_appear_in_json_so_existing_hashes_hold(self):
        a = make_asset()
        assert "currency" not in a.model_dump(mode="json") and "commodity_sensitivity" not in a.model_dump(mode="json")
        assert make_portfolio([a]).content_hash() == make_portfolio([make_asset(currency=None, commodity_sensitivity=None)]).content_hash()
        assert make_portfolio([a]).content_hash() != make_portfolio([make_asset(currency="EUR")]).content_hash()
        spec = ShockSpec(factor=EQ, scope=MKT, value=-0.1)
        assert set(spec.model_dump(mode="json")) == {"factor", "scope", "value", "rationale", "sector"}
        assert set(shock(EQ, MKT, -0.1).model_dump(mode="json")) == {"factor", "scope", "base_value", "scaled_value", "sector", "applicable", "not_applicable_reason", "rationale"}

    def test_every_catalog_scenario_is_unchanged_by_the_lab_fields(self):
        from tests.prop_helpers import catalog
        for s in catalog()._by_id.values():  # noqa: SLF001
            for sh in s.shocks:
                assert sh.currency is None and sh.entity_id is None and sh.factor not in (FX, OIL)

    def test_the_engine_is_deterministic_and_order_independent(self):
        pf = make_portfolio([make_asset(asset_id="a", currency="EUR", commodity_sensitivity=0.5), make_asset(asset_id="b", entity_id="E2", sector="Tech")])
        shocks = [shock(FX, MKT, -0.1, currency="EUR"), shock(OIL, MKT, -0.2), shock(EQ, MKT, -0.05)]
        key = lambda ps: [(p.asset_id, round(p.delta, 6), {f.value: round(v, 6) for f, v in p.by_factor.items()}) for p in ps]  # noqa: E731
        assert key(stress_portfolio(pf, shocks, None, None)) == key(stress_portfolio(pf, list(reversed(shocks)), None, None))
