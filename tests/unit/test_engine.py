"""Engine formulas against hand-computed values."""

from __future__ import annotations

import pytest

from eventshock.domain.enums import AssetClass, RiskFactor, ShockScope
from eventshock.stress.engine import revalue_asset, scaled_shock_value, select_shocks
from tests.helpers import make_asset, shock

MKT, SEC, ISS = ShockScope.MARKET, ShockScope.SECTOR, ShockScope.ISSUER
EQ, RT, SP = RiskFactor.EQUITY, RiskFactor.RATES_BPS, RiskFactor.CREDIT_SPREAD_BPS
PDM, LGD = RiskFactor.PD_MULTIPLIER, RiskFactor.LGD_ADD


def run(asset, shocks, entity="E1", sector="Fin"):
    return revalue_asset(asset, shocks, entity, sector)


class TestScaling:
    def test_linear_factors_scale_linearly(self):
        assert scaled_shock_value(EQ, -0.10, 1.5) == pytest.approx(-0.15)
        assert scaled_shock_value(RT, 100, 0.5) == pytest.approx(50)

    @pytest.mark.parametrize(("base", "scale", "expected"), [(2.0, 1.5, 2.5), (1.25, 0.5, 1.125), (1.0, 1.5, 1.0)])
    def test_pd_multiplier_scales_excess_over_one(self, base, scale, expected):
        assert scaled_shock_value(PDM, base, scale) == pytest.approx(expected)


class TestShockSelection:
    def test_issuer_beats_sector_beats_market(self):
        shocks = [shock(EQ, MKT, -0.08), shock(EQ, SEC, -0.14), shock(EQ, ISS, -0.18)]
        issuer = select_shocks(make_asset(entity_id="E1"), shocks, "E1", "Fin")
        sector = select_shocks(make_asset(entity_id="E2", sector="Fin"), shocks, "E1", "Fin")
        other = select_shocks(make_asset(entity_id="E3", sector="Tech"), shocks, "E1", "Fin")
        assert issuer[EQ].scope is ISS
        assert sector[EQ].scope is SEC
        assert other[EQ].scope is MKT

    def test_inapplicable_shock_is_skipped(self):
        shocks = [shock(EQ, ISS, -0.18, applicable=False)]
        assert select_shocks(make_asset(), shocks, None, None) == {}

    def test_no_double_counting_across_scopes(self):
        r = run(make_asset(), [shock(EQ, MKT, -0.08), shock(EQ, ISS, -0.18)])
        assert r.delta == pytest.approx(-180_000)  # issuer only, not -260k


class TestEquity:
    def test_market_scope_uses_beta(self):
        r = run(make_asset(entity_id="E2", sector="Tech", beta=1.2), [shock(EQ, MKT, -0.08)])
        assert r.delta == pytest.approx(-96_000)
        assert r.stressed_value == pytest.approx(904_000)
        assert r.delta_pct == pytest.approx(-0.096)

    def test_issuer_scope_is_idiosyncratic_no_beta(self):
        r = run(make_asset(beta=1.5), [shock(EQ, ISS, -0.18)])
        assert r.delta == pytest.approx(-180_000)

    def test_no_shock_no_change_and_flagged_uncovered(self):
        r = run(make_asset(), [])
        assert r.delta == 0 and r.shocks == []


class TestBond:
    def bond(self, **kw):
        return make_asset(asset_type=AssetClass.BOND, duration=5.0, **kw)

    def test_rates_and_spread(self):
        r = run(self.bond(), [shock(RT, MKT, -20), shock(SP, MKT, 60)])
        # -5 * (-20)/1e4 = +1.0% ; -5 * 60/1e4 = -3.0%
        assert r.by_factor[RT] == pytest.approx(10_000)
        assert r.by_factor[SP] == pytest.approx(-30_000)
        assert r.delta == pytest.approx(-20_000)

    def test_rates_up_hurts(self):
        r = run(self.bond(), [shock(RT, MKT, 100)])
        assert r.delta == pytest.approx(-50_000)

    def test_loss_floored_at_total_value_and_attribution_still_sums(self):
        b = make_asset(asset_type=AssetClass.BOND, duration=10.0)
        r = run(b, [shock(SP, MKT, 1500), shock(RT, MKT, 500)])
        assert r.delta == pytest.approx(-1_000_000)
        assert r.stressed_value == pytest.approx(0)
        assert sum(r.by_factor.values()) == pytest.approx(r.delta)

    def test_zero_duration_is_immune(self):
        b = make_asset(asset_type=AssetClass.BOND, duration=0.0)
        assert run(b, [shock(RT, MKT, 500)]).delta == 0


class TestLoan:
    def loan(self, **kw):
        base = dict(asset_type=AssetClass.LOAN, pd=0.02, lgd=0.5, market_value=990_000.0,
                    default_sensitivity=1.0)
        return make_asset(**{**base, **kw})

    def test_pd_and_lgd_stress(self):
        r = run(self.loan(), [shock(PDM, ISS, 2.0), shock(LGD, ISS, 0.10)])
        # EL: 1e6*.02*.5 = 10,000 -> 1e6*.04*.6 = 24,000
        assert r.delta == pytest.approx(-14_000)
        assert r.by_factor[PDM] == pytest.approx(-10_000)
        assert r.by_factor[LGD] == pytest.approx(-4_000)
        assert sum(r.by_factor.values()) == pytest.approx(r.delta)

    def test_default_sensitivity_dampens_pd_uplift(self):
        r = run(self.loan(default_sensitivity=0.5), [shock(PDM, ISS, 2.0)])
        # PD' = .02 * (1 + 1*.5) = .03 -> EL 15,000 -> delta -5,000
        assert r.delta == pytest.approx(-5_000)

    def test_pd_capped_at_one(self):
        r = run(self.loan(pd=0.9, market_value=1e6 * (1 - 0.9 * 0.5)), [shock(PDM, ISS, 5.0)])
        # PD' capped at 1.0 -> EL = 500,000; base EL 450,000
        assert r.delta == pytest.approx(-50_000)

    def test_lgd_capped_at_one(self):
        r = run(self.loan(), [shock(LGD, ISS, 0.9)])
        # LGD' = 1.0 -> EL = 1e6*.02*1 = 20,000 ; delta -10,000
        assert r.delta == pytest.approx(-10_000)


class TestDerivative:
    def deriv(self, delta, **kw):
        return make_asset(asset_type=AssetClass.DERIVATIVE, delta=delta, notional=2_000_000.0,
                          market_value=50_000.0, **kw)

    def test_long_delta_loses_when_underlying_falls(self):
        r = run(self.deriv(0.5), [shock(EQ, MKT, -0.08)])
        assert r.delta == pytest.approx(-80_000)

    def test_short_delta_gains(self):
        r = run(self.deriv(-0.4), [shock(EQ, MKT, -0.08)])
        assert r.delta == pytest.approx(64_000)

    def test_pct_uses_absolute_baseline_even_when_mtm_negative(self):
        d = make_asset(asset_type=AssetClass.DERIVATIVE, delta=0.5, notional=2e6, market_value=-10_000.0)
        r = run(d, [shock(EQ, MKT, -0.08)])
        assert r.delta_pct == pytest.approx(-8.0)
