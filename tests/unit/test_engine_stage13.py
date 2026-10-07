"""Stage 13 revaluation mechanics: bond convexity, the spread-to-PD hazard link on loans, derivative gamma and CVA.

Every mechanic is opt-in per position. The tests hand-compute the numbers and pin the two things that must never change: a position that
carries none of the new fields is revalued exactly as before, and the portfolio's JSON / content hash does not move.
"""

from __future__ import annotations

import math

import pytest

from eventshock.domain.enums import AssetClass, RiskFactor, ShockScope
from eventshock.stress.engine import revalue_asset
from tests.helpers import make_asset, make_portfolio, shock

MKT = ShockScope.MARKET
EQ, RATES, SPREAD, PD, LGD = (RiskFactor.EQUITY, RiskFactor.RATES_BPS, RiskFactor.CREDIT_SPREAD_BPS, RiskFactor.PD_MULTIPLIER,
                              RiskFactor.LGD_ADD)


def run(asset, shocks):  # noqa: ANN001, ANN201
    return revalue_asset(asset, shocks, None, None)


def bond(**kw):  # noqa: ANN003, ANN201
    return make_asset(**{"asset_type": AssetClass.BOND, "duration": 5.0, **kw})


def loan(**kw):  # noqa: ANN003, ANN201
    base = dict(asset_type=AssetClass.LOAN, pd=0.02, lgd=0.4, market_value=1_000_000 * (1 - 0.02 * 0.4))
    return make_asset(**{**base, **kw})


def deriv(**kw):  # noqa: ANN003, ANN201
    base = dict(asset_type=AssetClass.DERIVATIVE, delta=0.5, notional=2_000_000.0, market_value=50_000.0)
    return make_asset(**{**base, **kw})


class TestConvexity:
    def test_it_adds_half_c_dy_squared_to_the_duration_term(self):
        r = run(bond(convexity=40.0), [shock(RATES, MKT, 100.0)])
        assert r.delta == pytest.approx(1_000_000 * (-5 * 0.01 + 0.5 * 40 * 0.01**2)) == pytest.approx(-48_000)
        assert "C = 40.0" in r.formula

    def test_a_rate_fall_gains_more_than_the_same_rise_loses(self):
        up, down = run(bond(convexity=40.0), [shock(RATES, MKT, 100.0)]), run(bond(convexity=40.0), [shock(RATES, MKT, -100.0)])
        assert down.delta > -up.delta > 0 or down.delta == pytest.approx(52_000)
        assert (up.delta, down.delta) == (pytest.approx(-48_000), pytest.approx(52_000))

    def test_each_factor_gets_its_own_share_of_the_cross_term_and_the_parts_sum(self):
        r = run(bond(convexity=40.0), [shock(RATES, MKT, 100.0), shock(SPREAD, MKT, 50.0)])
        assert r.by_factor[RATES] == pytest.approx(1_000_000 * (-0.05 + 0.003)) and r.by_factor[SPREAD] == pytest.approx(1_000_000 * (-0.025 + 0.0015))
        assert sum(r.by_factor.values()) == pytest.approx(r.delta) == pytest.approx(1_000_000 * (-0.075 + 0.0045))

    def test_unset_convexity_is_the_old_duration_only_result(self):
        assert run(bond(), [shock(RATES, MKT, 100.0)]).delta == pytest.approx(-50_000)
        assert run(bond(convexity=0.0), [shock(RATES, MKT, 100.0)]).delta == pytest.approx(-50_000)

    def test_the_floor_still_applies(self):
        r = run(bond(convexity=400.0, duration=20.0), [shock(RATES, MKT, 600.0)])
        assert r.delta >= -1_000_000 - 1e-6 and r.stressed_value >= -1e-6


class TestSpreadToPd:
    def hazard_pd(self, pd, lgd, t, passthrough, ds):  # noqa: ANN001, ANN201
        h = -math.log(1 - pd) / t + passthrough * ds / 1e4 / lgd
        return 1 - math.exp(-h * t)

    def test_a_spread_shock_raises_the_hazard_rate_and_pd(self):
        r = run(loan(maturity_years=5.0, spread_passthrough=1.0), [shock(SPREAD, MKT, 200.0)])
        pd1 = self.hazard_pd(0.02, 0.4, 5.0, 1.0, 200.0)
        assert pd1 == pytest.approx(1 - 0.98 * math.exp(-0.25)) and pd1 > 0.2
        assert r.delta == pytest.approx(-1_000_000 * (pd1 - 0.02) * 0.4) and r.delta == pytest.approx(-86_710, abs=5)
        assert set(r.by_factor) == {SPREAD} and "spread link" in r.formula

    def test_without_the_link_a_spread_shock_does_not_move_a_loan(self):
        r = run(loan(), [shock(SPREAD, MKT, 200.0)])
        assert r.delta == 0 and r.by_factor == {}
        r2 = run(loan(maturity_years=5.0), [shock(SPREAD, MKT, 200.0)])                   # a tenor alone is not a pass-through
        assert r2.delta == 0

    def test_pass_through_scales_the_effect_and_zero_switches_it_off(self):
        full = run(loan(maturity_years=5.0, spread_passthrough=1.0), [shock(SPREAD, MKT, 100.0)]).delta
        half = run(loan(maturity_years=5.0, spread_passthrough=0.5), [shock(SPREAD, MKT, 100.0)]).delta
        none = run(loan(maturity_years=5.0, spread_passthrough=0.0), [shock(SPREAD, MKT, 100.0)]).delta
        assert none == 0 and full < half < 0

    def test_it_stacks_on_the_pd_multiplier_and_the_parts_sum_to_the_total(self):
        a = loan(maturity_years=5.0, spread_passthrough=1.0)
        r = run(a, [shock(PD, MKT, 2.0), shock(SPREAD, MKT, 100.0), shock(LGD, MKT, 0.10)])
        pd_m = 0.04
        pd_s = self.hazard_pd(pd_m, 0.4, 5.0, 1.0, 100.0)
        total = -1_000_000 * (pd_s * 0.5 - 0.02 * 0.4)
        assert r.delta == pytest.approx(total) and sum(r.by_factor.values()) == pytest.approx(total)
        assert set(r.by_factor) == {PD, SPREAD, LGD}

    def test_pd_never_exceeds_one_and_degenerate_inputs_do_not_raise(self):
        huge = run(loan(maturity_years=40.0, spread_passthrough=1.5), [shock(SPREAD, MKT, 2000.0)])
        assert huge.stressed_value >= -1e-6                                                # EL cannot exceed the exposure
        certain = loan(pd=1.0, lgd=0.4, market_value=600_000.0, maturity_years=5.0, spread_passthrough=1.0)
        assert run(certain, [shock(SPREAD, MKT, 200.0)]).delta == 0                         # PD already 1: the link is undefined, not an error
        no_loss = loan(lgd=0.0, market_value=1_000_000.0, maturity_years=5.0, spread_passthrough=1.0)
        assert run(no_loss, [shock(SPREAD, MKT, 200.0)]).delta == 0                         # credit triangle needs LGD > 0

    def test_a_spread_tightening_cannot_push_the_hazard_below_zero(self):
        r = run(loan(maturity_years=5.0, spread_passthrough=1.0), [shock(SPREAD, MKT, -5_000.0)])
        assert r.stressed_value <= 1_000_000 and r.delta >= 0


class TestGammaAndCva:
    def test_gamma_adds_the_curvature_term(self):
        r = run(deriv(gamma=4.0), [shock(EQ, MKT, -0.10)])
        assert r.delta == pytest.approx(0.5 * 2_000_000 * -0.10 + 0.5 * 4.0 * 2_000_000 * 0.01) == pytest.approx(-60_000)
        assert "gamma" in r.formula

    def test_a_short_gamma_position_loses_in_both_directions(self):
        up, down = run(deriv(delta=0.0, gamma=-4.0), [shock(EQ, MKT, 0.10)]), run(deriv(delta=0.0, gamma=-4.0), [shock(EQ, MKT, -0.10)])
        assert up.delta == pytest.approx(-40_000) == pytest.approx(down.delta)

    def test_gamma_uses_the_beta_adjusted_move_on_a_market_shock(self):
        r = run(deriv(gamma=4.0, beta=1.5, delta=0.0), [shock(EQ, MKT, -0.10)])
        assert r.delta == pytest.approx(0.5 * 4.0 * 2_000_000 * 0.15**2)

    def test_cva_charges_the_exposure_that_grows_and_the_counterparty_pd_that_rises(self):
        a = deriv(delta=-0.5, counterparty_pd=0.02, counterparty_lgd=0.6)
        r = run(a, [shock(EQ, MKT, -0.10), shock(PD, MKT, 3.0)])
        assert r.delta == pytest.approx(100_000 - 0.02 * 0.6 * 100_000 - (0.06 - 0.02) * 0.6 * 150_000) == pytest.approx(95_200)
        assert r.by_factor[EQ] == pytest.approx(100_000 - 1_200) and r.by_factor[PD] == pytest.approx(-3_600)
        assert sum(r.by_factor.values()) == pytest.approx(r.delta) and "CVA" in r.formula

    def test_a_derivative_that_goes_out_of_the_money_reduces_its_cva(self):
        r = run(deriv(counterparty_pd=0.02, counterparty_lgd=0.6), [shock(EQ, MKT, -0.10)])     # mtm 50k -> -50k: exposure vanishes
        assert r.delta == pytest.approx(-100_000 + 0.02 * 0.6 * 50_000)

    def test_a_pd_multiplier_alone_still_reaches_the_cva(self):
        r = run(deriv(counterparty_pd=0.02, counterparty_lgd=0.6), [shock(PD, MKT, 2.0)])
        assert r.delta == pytest.approx(-(0.04 - 0.02) * 0.6 * 50_000) and set(r.by_factor) == {PD}

    def test_without_a_counterparty_nothing_changes(self):
        assert run(deriv(), [shock(EQ, MKT, -0.10), shock(PD, MKT, 3.0)]).delta == pytest.approx(-100_000)


class TestOptInContract:
    NEW = {"convexity": 30.0, "maturity_years": 5.0, "spread_passthrough": 1.0, "gamma": 1.0, "counterparty_pd": 0.01,
           "counterparty_lgd": 0.6, "rating": "BBB", "spread_bp": 120.0}

    def test_unset_fields_never_appear_in_json_so_every_existing_hash_holds(self):
        for a in (bond(), loan(), deriv(), make_asset()):
            assert not set(a.model_dump(mode="json")) & set(self.NEW)
        assert make_portfolio([bond()]).content_hash() == make_portfolio([bond(convexity=None, rating=None)]).content_hash()
        assert make_portfolio([bond()]).content_hash() != make_portfolio([bond(convexity=30.0)]).content_hash()

    def test_set_fields_round_trip(self):
        a = bond(convexity=30.0, rating="BBB", spread_bp=120.0)
        assert a.model_dump(mode="json")["convexity"] == 30.0 and type(a).model_validate(a.model_dump(mode="json")) == a

    @pytest.mark.parametrize(("kind", "field"), [(AssetClass.EQUITY, "convexity"), (AssetClass.LOAN, "gamma"), (AssetClass.BOND, "maturity_years"),
                                                 (AssetClass.DERIVATIVE, "spread_bp"), (AssetClass.BOND, "counterparty_pd")])
    def test_a_mechanic_on_the_wrong_asset_class_is_refused(self, kind, field):  # noqa: ANN001
        base = {AssetClass.EQUITY: {}, AssetClass.BOND: {"duration": 5.0}, AssetClass.LOAN: {"pd": 0.02, "lgd": 0.4, "market_value": 992_000.0},
                AssetClass.DERIVATIVE: {"delta": 0.5, "market_value": 10.0}}[kind]
        with pytest.raises(ValueError, match="only"):
            make_asset(asset_type=kind, **base, **{field: self.NEW[field]})

    def test_the_link_needs_a_tenor_and_the_cva_needs_both_counterparty_fields(self):
        with pytest.raises(ValueError, match="maturity_years"):
            loan(spread_passthrough=1.0)
        with pytest.raises(ValueError, match="together"):
            deriv(counterparty_pd=0.02)


class TestFxShockMustNameItsCurrency:
    """Found by the multi-factor scenario test: the event-driven path dropped ``currency`` from catalog shocks, and ``None == None`` made every
    base-currency position take an FX shock. Fixed in the service (currency is copied; pinned by tests/integration/test_multifactor_scenarios_api.py) and in the engine (a shock that names none matches nothing)."""

    def test_an_fx_shock_without_a_currency_moves_nothing(self):
        r = run(make_asset(), [shock(RiskFactor.FX_PCT, MKT, -0.10)])
        assert r.delta == 0 and RiskFactor.FX_PCT not in r.by_factor
