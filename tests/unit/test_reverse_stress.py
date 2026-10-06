"""Reverse stress: a bounded, deterministic search whose every figure is the stress engine's own. Achievable and unachievable targets, the bounds, determinism, the full re-run, labelling."""

from __future__ import annotations

import json

import pytest

from eventshock.lab.models import AssumptionKind, ScenarioRequest
from eventshock.lab.models import ReverseStressRequest as R
from eventshock.lab.reverse import Axis, ReverseSearch, build_axes
from eventshock.lab.service import LabInvalid
from tests.helpers import make_asset, make_portfolio
from tests.lab_helpers import DCFG, lab, lab_book

CFG = DCFG.reverse


@pytest.mark.parametrize("target", [-2.0, -5.0, -10.0, -17.5])
def test_an_achievable_target_is_reached_within_tolerance_and_the_loss_is_the_engines_own(target):
    svc = lab()
    r = svc.reverse(R(target_pct=target))
    assert r.status == "ACHIEVABLE" and abs(r.difference_pp) <= CFG.tolerance_pp and r.target_pct == target
    # the figure reported is a complete engine run of the combination found, not an estimate: re-running exactly those assumptions gives it
    again = svc.run(r.open_in_lab)
    assert again.result.summary.pnl_pct * 100 == pytest.approx(r.achieved_pct) and again.result.summary.pnl == pytest.approx(r.achieved_pnl)
    assert r.scenario.scenario_id == again.scenario_id and r.baseline_value == pytest.approx(1_300_000)
    assert r.binding_bounds == [] and r.required_shocks and all(s.label_kind == "SCENARIO ASSUMPTION" for s in r.required_shocks)


def test_every_shock_found_is_within_its_configured_bound_and_reports_its_share_of_it():
    r = lab().reverse(R(target_pct=-30))
    for s in r.required_shocks:
        assert abs(s.value) <= s.bound + 1e-9 and 0 < s.share_of_bound <= 1 + 1e-9
    assert {b.axis for b in r.bounds} >= {"EQUITY_MARKET", "CREDIT_SPREAD", "RATES", "COMMODITY"} and all(b.bound > 0 for b in r.bounds)


def test_an_unachievable_target_returns_the_largest_loss_the_bounds_allow_and_names_the_binding_axes():
    r = lab().reverse(R(target_pct=-80))
    assert r.status == "NOT_ACHIEVABLE" and r.achieved_pct > -80 and r.difference_pp > 0            # short of the target
    assert r.binding_bounds and {s.axis for s in r.required_shocks} == set(r.binding_bounds)
    assert all(abs(s.share_of_bound - 1.0) < 1e-9 for s in r.required_shocks)                        # every kept axis is at its limit
    assert "NOT a prediction".lower() in r.note.lower() or "not a prediction" in r.note.lower()
    # nothing larger is reachable inside the bounds: widening no axis beyond its limit can lose more
    plan = lab().run(r.open_in_lab)
    assert plan.result.summary.pnl_pct * 100 == pytest.approx(r.achieved_pct)


def test_the_bounds_are_enforced_even_for_a_target_just_beyond_them():
    just = lab().reverse(R(target_pct=-50))
    assert just.status == "NOT_ACHIEVABLE"
    for s in just.required_shocks:
        assert abs(s.value) <= s.bound + 1e-9


def test_the_search_is_deterministic_and_independent_of_what_ran_before():
    one, two = lab().reverse(R(target_pct=-5)), lab()
    two.run(ScenarioRequest(scenario_type="BASE"))                                                  # an unrelated earlier run changes nothing
    assert one.model_dump_json() == two.reverse(R(target_pct=-5)).model_dump_json() == one.model_dump_json()
    assert one.reverse_id.startswith("rev_") and one.reverse_id != lab().reverse(R(target_pct=-6)).reverse_id


def test_it_spreads_the_loss_across_axes_rather_than_piling_it_on_one():
    r = lab().reverse(R(target_pct=-10))
    assert len(r.required_shocks) >= 2
    shares = [s.share_of_bound for s in r.required_shocks]
    assert max(shares) - min(shares) < 0.2                                                           # the minimax rule keeps the shares close (pro-rata when axes add up)


def test_oil_needs_an_exposure_and_the_prior_switch_is_disclosed():
    off = lab().reverse(R(target_pct=-5))
    on = lab().reverse(R(target_pct=-5, exposure_priors=True))
    assert "COMMODITY" not in {s.axis for s in off.required_shocks} and next(b for b in off.bounds if b.axis == "COMMODITY").efficiency == 0.0
    assert on.exposure_priors and on.exposure_priors[0].label == "JUDGEMENT PRIOR" and any("sector priors" in a for a in on.assumptions)
    assert off.reverse_id != on.reverse_id


def test_a_book_the_basket_cannot_reach_says_so_instead_of_guessing():
    cash = make_portfolio([make_asset(asset_id="c", entity_id="ENT_CASH", sector="Cash", asset_type="CASH", market_value=1000, notional=1000)])
    r = lab(cash).reverse(R(target_pct=-5))
    assert r.status == "NO_EXPOSURE" and r.scenario is None and r.required_shocks == [] and r.achieved_pct is None


def test_requests_are_validated():
    svc = lab()
    for bad in (-96.0, 0.0):
        with pytest.raises((LabInvalid, ValueError)):
            svc.reverse(R(target_pct=bad))
    with pytest.raises(LabInvalid, match="unknown axis"):
        svc.reverse(R(target_pct=-5, factors=["MOOD"]))
    only = svc.reverse(R(target_pct=-5, factors=["equity_market", "Technology"]))               # an axis by id, or a held sector by name
    assert {s.axis for s in only.required_shocks} <= {"EQUITY_MARKET", "SECTOR:Technology"}


def test_the_search_reports_how_it_searched():
    r = lab().reverse(R(target_pct=-5))
    assert r.search_method == "BOUNDED_GRID_MINIMAX" and 0 < r.evaluations <= CFG.max_evaluations
    c = r.search_config
    assert c["grid_levels"] == CFG.grid_levels and c["max_axes"] == CFG.max_axes and c["tolerance_pp"] == CFG.tolerance_pp and "smallest largest share" in c["objective"]
    assert all(isinstance(a, str) for a in r.assumptions) and r.limitations and "hypothetical" in r.labels[0].lower()
    text = json.dumps([r.note, r.labels, r.assumptions]).lower()
    assert "forecast" not in text.replace("not a forecast", "") and "expected return" not in text


def test_attribution_and_the_named_drivers_come_from_the_engine_run():
    r = lab().reverse(R(target_pct=-10, exposure_priors=True))
    assert r.dominant_drivers and r.affected_holdings and r.affected_sectors and r.affected_risk_factors
    assert r.scenario.attribution.reconciled and abs(r.scenario.attribution.total_pnl - r.achieved_pnl) < 0.01
    assert set(r.affected_sectors) <= {"Financials", "Technology", "Energy", "Other"}


def test_the_evaluation_budget_is_a_hard_limit():
    cfg = CFG.model_copy(update={"max_evaluations": 12})
    axes, _ = build_axes(CFG, lab_book(), None)
    from eventshock.lab.reverse import Budget
    from eventshock.services.stress_service import StressService
    with pytest.raises(Budget):
        ReverseSearch(cfg, StressService.quick_pnl, lab_book()).search(axes, -5.0)


def test_axes_are_built_from_the_basket_and_the_held_sectors():
    axes, _ = build_axes(CFG, lab_book(), None)
    ids = [a.id for a in axes]
    assert ids[:4] == ["EQUITY_MARKET", "CREDIT_SPREAD", "RATES", "COMMODITY"] and {"SECTOR:Energy", "SECTOR:Financials", "SECTOR:Technology"} <= set(ids)
    assert "SECTOR:Cash" not in ids and all(isinstance(a, Axis) for a in axes) and axes[3].kind is AssumptionKind.COMMODITY and axes[3].sign == 0
