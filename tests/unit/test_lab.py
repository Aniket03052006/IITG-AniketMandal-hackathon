"""The scenario lab: validation against bounds and vocabularies, hand-checked arithmetic through the unchanged engine, honest reach, deterministic ids, labelling, comparison."""

from __future__ import annotations

import json

import pytest

from eventshock.lab.models import Assumption as A
from eventshock.lab.models import AssumptionKind as K
from eventshock.lab.models import LabCompareRequest, ScenarioRequest, ScenarioType
from eventshock.lab.service import LabInvalid
from tests.helpers import make_asset, make_portfolio
from tests.lab_helpers import lab, lab_book


def req(*assumptions, **kw):  # noqa: ANN002, ANN003, ANN201
    return ScenarioRequest(assumptions=list(assumptions), **kw)


def run(*assumptions, **kw):  # noqa: ANN002, ANN003, ANN201
    return lab().run(req(*assumptions, **kw))


# ---------------------------------------------------------------------------------------------------------------------------- arithmetic
def test_an_equity_market_shock_is_the_engines_beta_arithmetic():
    r = run(A(kind=K.EQUITY_MARKET, value=-0.10))
    # beta-weighted equities: 300k*1.0 + 400k*1.2 + 200k*1.0 + 100k*1.0 = 1.08m x -10%
    assert r.status == "COMPLETED" and r.result.summary.pnl == pytest.approx(-108_000)
    assert r.result.summary.baseline_value == pytest.approx(1_300_000) and r.result.summary.pnl_pct == pytest.approx(-108_000 / 1_300_000)
    assert r.assumptions[0].pnl == pytest.approx(-108_000) and r.assumptions[0].positions_reached == 4


def test_rates_and_credit_spread_reach_bonds_by_duration_and_spread_sensitivity():
    r = run(A(kind=K.RATES, value=100), A(kind=K.CREDIT_SPREAD, value=50))
    assert r.result.summary.pnl == pytest.approx(200_000 * -8 * 100 / 10_000)          # the Treasury has spread sensitivity 0: only rates reach it
    assert r.assumptions[1].reach == "NOT_REACHED" and "no position carries the exposure" in r.assumptions[1].note


def test_a_sector_and_an_issuer_shock_are_idiosyncratic_without_a_beta():
    r = run(A(kind=K.SECTOR, target="technology", value=-0.20), A(kind=K.ISSUER, target="JPM", value=-0.30))
    assert r.result.summary.pnl == pytest.approx((200_000 + 100_000) * -0.20 + 400_000 * -0.30)
    assert [a.target_label for a in r.assumptions] == ["Technology", "JPMorgan Chase"]


def test_a_currency_shock_reaches_only_positions_in_that_currency():
    r = run(A(kind=K.FX, target="eur", value=-0.10))
    assert r.result.summary.pnl == pytest.approx(-10_000) and r.assumptions[0].positions_reached == 1 and r.assumptions[0].description == "EUR −10.0% against USD"


def test_an_oil_shock_reaches_nothing_without_an_exposure_and_says_so_not_a_zero():
    r = run(A(kind=K.COMMODITY, value=-0.30))
    assert r.status == "NOT_APPLICABLE" and r.result is None and "No position in this portfolio carries the exposure" in r.reason
    assert r.attribution is None and r.assumptions[0].reach == "NOT_REACHED" and "sector-prior estimate" in r.assumptions[0].note


def test_oil_with_the_sector_prior_switch_uses_labelled_judgement_priors_and_never_overrides_a_measured_one():
    book = make_portfolio([*lab_book().assets[:1], make_asset(asset_id="own", entity_id="ENT_OWN", sector="Energy", market_value=100_000, notional=100_000, commodity_sensitivity=0.2)])
    svc = lab(book)
    off = svc.run(req(A(kind=K.COMMODITY, value=-0.50)), None)
    assert off.status == "COMPLETED" and off.result.summary.pnl == pytest.approx(100_000 * 0.2 * -0.50) and off.exposure_priors == []   # only the measured holding
    on = svc.run(req(A(kind=K.COMMODITY, value=-0.50), exposure_priors=True) if False else ScenarioRequest(assumptions=[A(kind=K.COMMODITY, value=-0.50)], exposure_priors=True))
    assert on.exposure_priors and on.exposure_priors[0].sector == "Energy" and on.exposure_priors[0].label == "JUDGEMENT PRIOR"
    assert on.result.summary.pnl == pytest.approx(300_000 * 0.8 * -0.50 + 100_000 * 0.2 * -0.50)         # xom takes the 0.8 prior, 'own' keeps its measured 0.2
    assert on.scenario_id != off.scenario_id                                                              # a different book (priors) is a different scenario


def test_the_base_scenario_is_the_identity():
    r = lab().run(ScenarioRequest(scenario_type=ScenarioType.BASE))
    assert r.scenario_type is ScenarioType.BASE and r.status == "COMPLETED" and r.result.summary.pnl == 0 and r.result.summary.stressed_value == r.result.summary.baseline_value
    assert r.assumptions == [] and r.name == "Base (no shock)"
    with pytest.raises(LabInvalid, match="no assumptions"):
        lab().run(ScenarioRequest(scenario_type=ScenarioType.BASE, assumptions=[A(kind=K.RATES, value=10)]))


def test_the_result_carries_everything_the_spec_asks_for():
    r = run(A(kind=K.EQUITY_MARKET, value=-0.05, rationale="a sell-off I am worried about"))
    d = r.model_dump(mode="json")
    for k in ("scenario_id", "scenario_type", "created_at", "portfolio_id", "assumptions", "result", "attribution", "provenance"):
        assert d[k] is not None
    assert r.attribution.reconciled and abs(r.attribution.total_pnl - r.result.summary.pnl) < 0.01
    assert r.assumptions[0].rationale == "a sell-off I am worried about"


# ----------------------------------------------------------------------------------------------------------------------------- labelling
def test_every_user_value_is_a_scenario_assumption_and_nothing_is_called_a_prediction():
    r = run(A(kind=K.EQUITY_MARKET, value=-0.05), A(kind=K.RATES, value=75), A(kind=K.FX, target="EUR", value=-0.05))
    assert r.label == "SCENARIO SIMULATION — NOT A PREDICTION" and all(a.label == "SCENARIO ASSUMPTION" and a.origin == "USER" for a in r.assumptions)
    # the labels of the user's own values (not the disclaimer, which says what they are NOT) never use a banned word
    mine = json.dumps([[a.label, a.description, a.kind, a.origin] for a in r.assumptions] + [r.label, r.name, r.scenario_type.value]).lower()
    for banned in ("expected return", "model output", "prediction", "forecast"):
        assert banned not in mine.replace("not a prediction", "")
    assert r.note.startswith("A hypothetical stress analysis") and "not a prediction" in r.note
    assert all(p.kind.value in ("SCENARIO_ASSUMPTION", "PRODUCT_RULE") for p in r.provenance) and any(p.source == "stress.engine" for p in r.provenance)


# --------------------------------------------------------------------------------------------------------------------------- determinism
def test_the_same_assumptions_give_the_same_id_and_result_in_any_order():
    a, b = A(kind=K.EQUITY_MARKET, value=-0.05), A(kind=K.RATES, value=75)
    one, two = lab().run(req(a, b)), lab().run(req(b, a))
    assert one.scenario_id == two.scenario_id and one.scenario_id.startswith("scn_lab_")
    assert one.result.summary == two.result.summary and one.result.run_id == two.result.run_id
    assert one.model_dump(mode="json")["attribution"] == two.model_dump(mode="json")["attribution"]
    assert lab().run(req(a, b)).model_dump_json() == one.model_dump_json()


def test_a_different_size_or_a_different_book_is_a_different_scenario():
    base = lab().run(req(A(kind=K.EQUITY_MARKET, value=-0.05))).scenario_id
    assert lab().run(req(A(kind=K.EQUITY_MARKET, value=-0.06))).scenario_id != base
    other = make_portfolio([make_asset(asset_id="x", entity_id="E", sector="Technology")], ) if False else lab_book().model_copy(update={"assets": lab_book().assets[:3]})
    assert lab(other).run(req(A(kind=K.EQUITY_MARKET, value=-0.05))).scenario_id != base


def test_a_risk_factor_shock_and_the_matching_direct_shock_are_the_same_calculation():
    direct = run(A(kind=K.RATES, value=100))
    rf = run(A(kind=K.RISK_FACTOR, target="RATES", value=100))
    assert direct.scenario_id == rf.scenario_id and direct.result.summary == rf.result.summary


# -------------------------------------------------------------------------------------------------------------------------- risk factors
def test_a_proxy_risk_factor_spreads_over_the_sectors_its_edges_name_with_each_edge_an_assumption():
    r = run(A(kind=K.RISK_FACTOR, target="INFLATION", value=-0.10))
    shocks = r.assumptions[0].shocks
    assert [s.sector for s in shocks] == ["Consumer"] and shocks[0].value == pytest.approx(-0.10 * 0.4)
    assert "edge consumer_costs" in shocks[0].basis and "an assumption" in shocks[0].basis
    assert r.status == "NOT_APPLICABLE" and "Consumer" not in {a.sector for a in lab_book().assets}      # the book holds no consumer stock: nothing is moved


def test_oil_energy_as_a_risk_factor_is_the_oil_engine_factor_not_a_proxy_and_credit_default_is_a_pd_multiplier():
    r = lab().run(ScenarioRequest(assumptions=[A(kind=K.RISK_FACTOR, target="OIL_ENERGY", value=-0.2)], exposure_priors=True))
    assert r.assumptions[0].shocks[0].factor == "COMMODITY_PCT" and r.status == "COMPLETED"
    assert lab().plan(req(A(kind=K.RISK_FACTOR, target="CREDIT_DEFAULT", value=2.0)))[1][0].shocks[0].factor.value == "PD_MULTIPLIER"


def test_attribution_by_risk_factor_names_fx_and_oil():
    r = lab().run(ScenarioRequest(assumptions=[A(kind=K.COMMODITY, value=-0.2), A(kind=K.FX, target="EUR", value=-0.1)], exposure_priors=True))
    rf = next(t for t in r.attribution.tables if t.dimension == "risk_factor")
    assert {row.label for row in rf.rows} == {"Oil and energy prices", "Currencies"} and rf.reconciled


# --------------------------------------------------------------------------------------------------------------------------- validation
@pytest.mark.parametrize("assumption,needle", [
    (A(kind=K.EQUITY_MARKET, value=-0.95), "outside the limits"),
    (A(kind=K.EQUITY_MARKET, value=float("nan")), "finite"),
    (A(kind=K.RATES, value=900), "outside the limits"),
    (A(kind=K.SECTOR, target="Space Tourism", value=-0.1), "unknown sector"),
    (A(kind=K.SECTOR, value=-0.1), "unknown sector"),
    (A(kind=K.ISSUER, target="Acme Rocket Co", value=-0.1), "free text is never turned into a company"),
    (A(kind=K.FX, value=-0.1), "three-letter code"),
    (A(kind=K.FX, target="USD", value=-0.1), "base currency"),
    (A(kind=K.FX, target="euro", value=-0.1), "three-letter code"),
    (A(kind=K.RISK_FACTOR, target="MOOD", value=0.1), "unknown risk factor"),
    (A(kind=K.RISK_FACTOR, target="REGULATION", value=-0.1), "unknown risk factor"),
    (A(kind=K.RISK_FACTOR, target="FX", value=-0.1), "names its currency"),
    (A(kind=K.CREDIT_SPREAD, target="Moonshots", value=50), "unknown sector"),
])
def test_invalid_assumptions_are_refused_with_the_reason(assumption, needle):
    plan, _ = lab().plan(req(assumption))
    assert not plan.ok and any(needle in i.message for i in plan.issues)
    with pytest.raises(LabInvalid, match=needle):
        lab().run(req(assumption))


def test_the_bounds_are_inclusive_and_all_issues_come_back_together():
    assert lab().plan(req(A(kind=K.EQUITY_MARKET, value=-0.80)))[0].ok
    plan, _ = lab().plan(req(A(kind=K.EQUITY_MARKET, value=-0.81), A(kind=K.RATES, value=501)))
    assert [i.index for i in plan.issues] == [0, 1]


def test_one_value_per_shock_and_a_bounded_number_of_assumptions():
    plan, _ = lab().plan(req(A(kind=K.EQUITY_MARKET, value=-0.05), A(kind=K.EQUITY_MARKET, value=-0.10)))
    assert not plan.ok and "one value per shock" in plan.issues[0].message
    plan, _ = lab().plan(req(A(kind=K.SECTOR, target="Energy", value=-0.1), A(kind=K.RISK_FACTOR, target="GEOPOLITICAL", value=-0.1)))
    assert not plan.ok                                                                                           # both set the Energy equity shock
    many = [A(kind=K.ISSUER, target="JPM", value=-0.01)] * 13
    assert any("at most 12" in i.message for i in lab().plan(req(*many))[0].issues)
    assert not lab().plan(ScenarioRequest())[0].ok


def test_validate_returns_the_resolved_plan_without_running():
    plan, _ = lab().plan(req(A(kind=K.SECTOR, target="energy", value=-0.2)))
    assert plan.ok and plan.scenario_id.startswith("scn_lab_") and plan.assumptions[0].description == "Energy equities −20.0%" and "SECTOR" in plan.bounds
    assert plan.assumptions[0].pnl is None                                                                       # nothing was run


# ----------------------------------------------------------------------------------------------------------------------------- compare
def test_compare_runs_two_or_three_scenarios_and_shows_what_differs():
    svc = lab()
    c = svc.compare([req(A(kind=K.EQUITY_MARKET, value=-0.05), name="Mild"), req(A(kind=K.EQUITY_MARKET, value=-0.20), A(kind=K.RATES, value=100), name="Severe"),
                     ScenarioRequest(scenario_type=ScenarioType.BASE)])
    assert [r.name for r in c.results] == ["Mild", "Severe", "Base (no shock)"] and [r.scenario_type.value for r in c.rows] == ["CUSTOM", "CUSTOM", "BASE"]
    mild, severe, base = c.rows
    assert severe.pnl < mild.pnl < 0 == base.pnl and c.worst_scenario_id == severe.scenario_id
    assert severe.dominant_driver and severe.top_sectors and severe.top_risk_factors and severe.top_holdings
    eq = next(r for r in c.assumption_diff if r.key.startswith("EQUITY_MARKET"))
    rates = next(r for r in c.assumption_diff if r.key.startswith("RATES"))
    assert eq.values == ["−5.0%", "−20.0%", None] and eq.differs and rates.values == [None, "+100 bp", None]
    assert c.model_dump_json() == svc.compare([req(A(kind=K.EQUITY_MARKET, value=-0.05), name="Mild"), req(A(kind=K.EQUITY_MARKET, value=-0.20), A(kind=K.RATES, value=100), name="Severe"),
                                              ScenarioRequest(scenario_type=ScenarioType.BASE)]).model_dump_json()


def test_compare_needs_two_to_three_scenarios():
    with pytest.raises(LabInvalid, match="between 2 and 3"):
        lab().compare([req(A(kind=K.RATES, value=10))] * 4)
    with pytest.raises(ValueError):
        LabCompareRequest(scenarios=[req(A(kind=K.RATES, value=10))])


def test_a_comparison_that_includes_an_unreached_scenario_still_ranks_the_others():
    c = lab().compare([req(A(kind=K.COMMODITY, value=-0.3)), req(A(kind=K.EQUITY_MARKET, value=-0.1))])
    assert c.rows[0].status == "NOT_APPLICABLE" and c.rows[0].pnl is None and c.worst_scenario_id == c.rows[1].scenario_id


def test_the_options_come_from_the_same_vocabulary_the_validator_enforces():
    o = lab().options()
    assert o.base_currency == "USD" and "EUR" in o.held_currencies and "USD" not in {c.value for c in o.currencies}
    assert {k.kind.value for k in o.kinds} == {k.value for k in K} and o.max_compared == 3
    assert "Energy" in {s.value for s in o.sectors} and {"ENT_JPM", "ENT_XOM"} <= {i.value for i in o.issuers} and "INFLATION" in {r.value for r in o.risk_factors}
    assert o.oil_priors and o.oil_priors[0].label == "JUDGEMENT PRIOR"
