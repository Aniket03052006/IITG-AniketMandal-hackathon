"""The scenario-lab endpoints over the real replay pack: BASE / CUSTOM / ASSESSED, validation as 422 with reasons, a deterministic id, comparison and the options."""

from __future__ import annotations

import pytest


def post(c, path, **body):  # noqa: ANN001, ANN003, ANN201
    return c.post(f"/api{path}", json=body)


@pytest.fixture(scope="module")
def assessed_signal(replay_container):  # noqa: ANN001, ANN201
    """A real signal for which the propagation layer generates a scenario."""
    thr = replay_container.assessments.threshold
    for s in replay_container.signals.list():
        a = replay_container.assessments.assess(s)
        if a.severity is not None and a.severity.score >= thr and replay_container.propagation.scenario(s).availability.value == "AVAILABLE":
            return s.id
    pytest.skip("no replay signal generates a scenario")


def test_the_capability_is_advertised_in_replay_only(replay_client, client):
    assert replay_client.get("/api/meta").json()["capabilities"]["scenario_lab"] is True
    assert client.get("/api/meta").json()["capabilities"]["scenario_lab"] is False
    assert client.post("/api/scenarios", json={"scenario_type": "BASE"}).status_code == 404


def test_base_is_the_book_as_it_is(replay_client):
    r = post(replay_client, "/scenarios", scenario_type="BASE").json()
    assert r["scenario_type"] == "BASE" and r["status"] == "COMPLETED" and r["result"]["summary"]["pnl"] == 0 and r["assumptions"] == []
    assert r["result"]["summary"]["baseline_value"] > 1e8


def test_a_custom_scenario_runs_through_the_engine_with_every_value_labelled(replay_client):
    r = post(replay_client, "/scenarios", scenario_type="CUSTOM", name="Mine", assumptions=[
        {"kind": "EQUITY_MARKET", "value": -0.10}, {"kind": "RATES", "value": 75}, {"kind": "CREDIT_SPREAD", "value": 100}]).json()
    assert r["status"] == "COMPLETED" and r["scenario_id"].startswith("scn_lab_") and r["name"] == "Mine" and r["label"] == "SCENARIO SIMULATION — NOT A PREDICTION"
    s = r["result"]["summary"]
    assert s["pnl"] < 0 and s["stressed_value"] == pytest.approx(s["baseline_value"] + s["pnl"])
    assert [a["label"] for a in r["assumptions"]] == ["SCENARIO ASSUMPTION"] * 3 and all(a["origin"] == "USER" for a in r["assumptions"])
    assert r["attribution"]["reconciled"] and r["attribution"]["total_pnl"] == pytest.approx(s["pnl"], abs=0.01)
    assert r["history_check"] is not None and {c["checkable"] for c in r["history_check"]["checks"]} == {True, False}      # equity and rates are checkable, credit is not
    again = post(replay_client, "/scenarios", scenario_type="CUSTOM", name="Mine", assumptions=[
        {"kind": "CREDIT_SPREAD", "value": 100}, {"kind": "RATES", "value": 75}, {"kind": "EQUITY_MARKET", "value": -0.10}]).json()
    assert again == r                                                                                         # entry order does not matter, and nothing differs but the ids already agree


def test_the_default_book_has_no_fx_or_oil_exposure_and_the_answer_says_so(replay_client):
    fx = post(replay_client, "/scenarios", assumptions=[{"kind": "FX", "target": "EUR", "value": -0.2}]).json()
    assert fx["status"] == "NOT_APPLICABLE" and fx["result"] is None and "carries the exposure" in fx["reason"]
    oil = post(replay_client, "/scenarios", assumptions=[{"kind": "COMMODITY", "value": -0.3}]).json()
    assert oil["status"] == "NOT_APPLICABLE" and oil["assumptions"][0]["reach"] == "NOT_REACHED"
    priors = post(replay_client, "/scenarios", assumptions=[{"kind": "COMMODITY", "value": -0.3}], exposure_priors=True).json()
    assert priors["status"] == "COMPLETED" and priors["exposure_priors"] and all(p["label"] == "JUDGEMENT PRIOR" for p in priors["exposure_priors"])
    assert priors["scenario_id"] != oil["scenario_id"] and priors["result"]["summary"]["pnl"] != 0


def test_issuer_and_sector_shocks_name_real_vocabulary(replay_client):
    opts = replay_client.get("/api/lab/options").json()
    issuer = opts["issuers"][0]["value"]
    sector = opts["sectors"][0]["value"]
    r = post(replay_client, "/scenarios", assumptions=[{"kind": "ISSUER", "target": issuer, "value": -0.4}, {"kind": "SECTOR", "target": sector, "value": -0.1}]).json()
    assert r["status"] == "COMPLETED" and r["assumptions"][0]["positions_reached"] >= 1 and r["result"]["summary"]["pnl"] < 0


def test_invalid_requests_are_422_with_a_reason_per_assumption(replay_client):
    r = post(replay_client, "/scenarios", assumptions=[{"kind": "EQUITY_MARKET", "value": -0.99}, {"kind": "ISSUER", "target": "Acme Rocket", "value": -0.1}])
    assert r.status_code == 422
    d = r.json()["detail"]
    assert [x["loc"][-1] for x in d] == [0, 1] and "outside the limits" in d[0]["msg"] and "free text" in d[1]["msg"]
    assert post(replay_client, "/scenarios", assumptions=[]).status_code == 422
    assert post(replay_client, "/scenarios", scenario_type="NOPE").status_code == 422
    assert post(replay_client, "/scenarios", scenario_type="ASSESSED").status_code == 422
    assert post(replay_client, "/scenarios", scenario_type="ASSESSED", signal_id="sig_nope").status_code == 404
    assert post(replay_client, "/scenarios", scenario_type="BASE", portfolio_id="pf_nope0000").status_code == 404


def test_validate_returns_the_plan_without_running(replay_client):
    p = post(replay_client, "/scenarios/validate", assumptions=[{"kind": "SECTOR", "target": "energy", "value": -0.2}, {"kind": "RATES", "value": 900}]).json()
    assert p["ok"] is False and p["issues"][0]["index"] == 1 and p["assumptions"][0]["pnl"] is None and p["scenario_id"] is None
    ok = post(replay_client, "/scenarios/validate", assumptions=[{"kind": "RATES", "value": 50}]).json()
    assert ok["ok"] and ok["scenario_id"].startswith("scn_lab_") and "RATES" in ok["bounds"]


def test_an_assessed_scenario_is_the_events_own_and_stays_distinct(replay_client, assessed_signal):
    r = post(replay_client, "/scenarios", scenario_type="ASSESSED", signal_id=assessed_signal).json()
    assert r["scenario_type"] == "ASSESSED" and r["status"] == "COMPLETED" and r["assumptions"]
    assert all(a["origin"] == "ASSESSED" and a["kind"] == "ASSESSED_SHOCK" for a in r["assumptions"])
    direct = replay_client.post(f"/api/signals/{assessed_signal}/portfolio-stress", json={}).json()
    assert r["result"] == direct["run"] and r["attribution"] == direct["attribution"]                 # the very run Stage 11 makes, not a second valuation
    assert any(p["source"] == "assessment.severity" for p in r["provenance"])


def test_an_assessed_scenario_that_cannot_be_generated_says_why(replay_client, replay_container):
    sid = next(s.id for s in replay_container.signals.list() if replay_container.propagation.scenario(s).availability.value == "UNAVAILABLE")
    r = post(replay_client, "/scenarios", scenario_type="ASSESSED", signal_id=sid).json()
    assert r["status"] == "UNAVAILABLE" and r["reason"] and r["result"] is None and r["assumptions"] == []


def test_compare_two_and_three_scenarios(replay_client, assessed_signal):
    c = post(replay_client, "/scenarios/compare", scenarios=[
        {"scenario_type": "BASE"}, {"name": "Mild", "assumptions": [{"kind": "EQUITY_MARKET", "value": -0.05}]},
        {"scenario_type": "ASSESSED", "signal_id": assessed_signal}]).json()
    assert [r["scenario_type"] for r in c["rows"]] == ["BASE", "CUSTOM", "ASSESSED"] and c["worst_scenario_id"] in {r["scenario_id"] for r in c["rows"]}
    base, mild, assessed = c["rows"]
    assert base["pnl"] == 0 > mild["pnl"] and assessed["dominant_driver"] and c["assumption_diff"]
    assert post(replay_client, "/scenarios/compare", scenarios=[{"scenario_type": "BASE"}]).status_code == 422
    assert post(replay_client, "/scenarios/compare", scenarios=[{"scenario_type": "BASE"}] * 4).status_code == 422


def test_options_describe_the_editor(replay_client):
    o = replay_client.get("/api/lab/options").json()
    assert o["max_compared"] == 3 and {k["kind"] for k in o["kinds"]} >= {"FX", "COMMODITY", "RISK_FACTOR"} and o["held_currencies"] == []
    assert o["currencies"] and o["risk_factors"] and o["label"] == "SCENARIO ASSUMPTION"


def test_a_personal_portfolio_with_a_foreign_currency_holding_takes_a_currency_shock(replay_client):
    body = {"name": "With euros", "base_currency": "USD", "mode": "WEIGHT", "holdings": [
        {"ticker": "AAPL", "weight_pct": 60}, {"ticker": "MSFT", "weight_pct": 20, "currency": "EUR"}, {"ticker": "CASH", "weight_pct": 20}]}
    made = replay_client.post("/api/portfolios", json=body)
    assert made.status_code == 201, made.text
    pid = made.json()["id"]
    try:
        assert "EUR" in replay_client.get("/api/lab/options", params={"portfolio_id": pid}).json()["held_currencies"]
        r = post(replay_client, "/scenarios", portfolio_id=pid, assumptions=[{"kind": "FX", "target": "EUR", "value": -0.10}]).json()
        assert r["status"] == "COMPLETED" and r["assumptions"][0]["positions_reached"] == 1 and r["portfolio_id"] == pid
        total = r["result"]["summary"]["baseline_value"]
        assert r["result"]["summary"]["pnl"] == pytest.approx(-0.10 * 0.20 * total, rel=1e-3)             # a 20% EUR holding losing 10%
        default = post(replay_client, "/scenarios", assumptions=[{"kind": "FX", "target": "EUR", "value": -0.10}]).json()
        assert default["status"] == "NOT_APPLICABLE" and default["scenario_id"] != r["scenario_id"]       # the same assumption on the default book reaches nothing
    finally:
        replay_client.delete(f"/api/portfolios/{pid}")


# ------------------------------------------------------------------------------------------------------------------------------ reverse stress
def test_reverse_stress_finds_a_combination_and_the_loss_is_an_engine_run(replay_client):
    r = post(replay_client, "/reverse-stress", target_pct=-5).json()
    assert r["status"] == "ACHIEVABLE" and abs(r["difference_pp"]) <= 0.02 and r["search_method"] == "BOUNDED_GRID_MINIMAX"
    assert r["required_shocks"] and all(s["label_kind"] == "SCENARIO ASSUMPTION" and abs(s["value"]) <= s["bound"] for s in r["required_shocks"])
    assert r["scenario"]["result"]["summary"]["pnl_pct"] * 100 == pytest.approx(r["achieved_pct"]) and r["scenario"]["scenario_type"] == "CUSTOM"
    assert r["dominant_drivers"] and r["affected_holdings"] and r["affected_sectors"] and r["affected_risk_factors"] and r["bounds"] and r["assumptions"]
    assert "not a prediction" in r["note"].lower()
    # forking the answer into the lab reproduces it exactly
    forked = post(replay_client, "/scenarios", **r["open_in_lab"]).json()
    assert forked["scenario_id"] == r["scenario"]["scenario_id"] and forked["result"]["summary"] == r["scenario"]["result"]["summary"]
    assert post(replay_client, "/reverse-stress", target_pct=-5).json() == r                          # deterministic


def test_reverse_stress_unachievable_and_invalid(replay_client):
    big = post(replay_client, "/reverse-stress", target_pct=-90).json()
    assert big["status"] == "NOT_ACHIEVABLE" and big["difference_pp"] > 0 and big["binding_bounds"]
    assert post(replay_client, "/reverse-stress", target_pct=5).status_code == 422
    assert post(replay_client, "/reverse-stress", target_pct=-99).status_code == 422
    assert post(replay_client, "/reverse-stress", target_pct=-5, factors=["MOOD"]).status_code == 422
    assert post(replay_client, "/reverse-stress", target_pct=-5, portfolio_id="pf_nope0000").status_code == 404


def test_the_options_list_the_presets_and_axes(replay_client):
    o = replay_client.get("/api/lab/options").json()["reverse"]
    assert o["presets_pct"] == [-2, -5, -10] and o["method"] == "BOUNDED_GRID_MINIMAX" and {"EQUITY_MARKET", "RATES"} <= {a["value"] for a in o["axes"]}
