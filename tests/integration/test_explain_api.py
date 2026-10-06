"""Explanation endpoints over the real replay pack."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def tracked(replay_container):  # noqa: ANN001, ANN201
    """A few tracked events (with their lead signal id) at the last cycle."""
    m = replay_container.monitor
    _, states = m.replay_states(None)
    top = sorted(states.states.values(), key=lambda s: (-(s.severity or 0), s.event_id))[:6]
    assert top
    return top


def test_the_capability_is_advertised_in_replay_only(replay_client, client):
    assert replay_client.get("/api/meta").json()["capabilities"]["explanations"] is True
    assert client.get("/api/meta").json()["capabilities"]["explanations"] is False
    assert client.get("/api/events/x/explanation").status_code == 404


@pytest.mark.parametrize("subject", ["PRIORITY", "VISIBILITY"])
def test_every_tracked_event_has_reasons_with_kind_source_and_provenance(replay_client, tracked, subject):
    for st in tracked:
        r = replay_client.get(f"/api/events/{st.event_id}/explanation", params={"subject": subject})
        assert r.status_code == 200, r.text
        e = r.json()
        assert e["subject"] == subject and e["availability"] == "AVAILABLE" and e["reasons"] and e["headline"]
        for x in e["reasons"]:
            assert x["code"] and x["text"] and x["source_ref"] and x["provenance"] and x["kind"] in {"MODEL_OUTPUT", "PRODUCT_RULE", "SCENARIO_ASSUMPTION", "HISTORICAL_OBSERVATION", "EXTERNAL_MARKET_OBSERVATION"}
        assert sum(e["kinds"].values()) == len(e["reasons"]) and e["labels"] and not any("ai determined" in x["text"].lower() for x in e["reasons"])


def test_priority_names_the_components_in_the_rankings_order(replay_client, tracked):
    e = replay_client.get(f"/api/events/{tracked[0].event_id}/explanation").json()
    codes = [x["code"] for x in e["reasons"]]
    assert "SEVERITY" in codes and "EVIDENCE_TIER" in codes and "INDEPENDENT_SOURCES" in codes
    assert codes.index("INDEPENDENT_SOURCES") < codes.index("EVIDENCE_TIER")


def test_the_event_can_be_named_by_a_signal_and_a_cycle_and_the_answer_is_stable(replay_client, tracked):
    sig = tracked[0].lead_signal_id
    a = replay_client.get(f"/api/events/{sig}/explanation", params={"subject": "PRIORITY"}).json()
    assert a == replay_client.get(f"/api/events/{tracked[0].event_id}/explanation", params={"subject": "PRIORITY"}).json()
    assert replay_client.get(f"/api/events/{sig}/explanation", params={"cycle": 99999}).status_code == 422
    assert replay_client.get("/api/events/evt_nope/explanation").status_code == 404
    assert replay_client.get(f"/api/events/{sig}/explanation", params={"subject": "NOPE"}).status_code == 422
    assert replay_client.get(f"/api/events/{sig}/explanation", params={"subject": "LAB"}).status_code == 422


def test_a_generated_scenario_explains_its_stress_with_assumptions_and_historical_context(replay_client, replay_container):
    thr = replay_container.assessments.threshold
    sid = next(s.id for s in replay_container.signals.list() if (a := replay_container.assessments.assess(s)).severity and a.severity.score >= thr
               and replay_container.propagation.scenario(s).availability.value == "AVAILABLE")
    e = replay_client.get(f"/api/events/{sid}/explanation", params={"subject": "STRESS"}).json()
    kinds = {x["kind"] for x in e["reasons"]}
    assert {"SCENARIO_ASSUMPTION", "PRODUCT_RULE"} <= kinds and "STRESS_TOTAL" in {x["code"] for x in e["reasons"]}
    assert "not a prediction" in e["headline"].lower()
    assert any(x["kind"] == "HISTORICAL_OBSERVATION" and "not a probability" in x["text"] for x in e["reasons"])


def test_an_event_without_a_scenario_says_why_instead_of_inventing_a_stress(replay_client, replay_container):
    sid = next(s.id for s in replay_container.signals.list() if replay_container.propagation.scenario(s).availability.value == "UNAVAILABLE")
    e = replay_client.get(f"/api/events/{sid}/explanation", params={"subject": "STRESS"}).json()
    assert e["availability"] == "PARTIAL" and e["reasons"] and e["reasons"][0]["code"] == "STRESS_NOT_RUN" and "SCENARIO UNAVAILABLE" in e["headline"]


def test_change_explanations_carry_the_rule_and_a_missing_change_is_a_404_or_unavailable(replay_client, replay_container):
    cs = replay_container.monitor.replay_changes(cycle=len(replay_container.monitor.cycles()) - 1, window=6)
    ch = cs.changes[0]
    e = replay_client.get(f"/api/events/{ch.event_id}/explanation", params={"subject": "CHANGE", "change_id": ch.change_id}).json()
    assert e["subject"] == "CHANGE" and e["reasons"][0]["code"] == "CHANGE_RULE" and e["level"] == ch.change_type.value
    assert replay_client.get(f"/api/events/{ch.event_id}/explanation", params={"subject": "CHANGE", "change_id": "chg_nope"}).status_code == 404


def test_scenario_and_reverse_explanations(replay_client):
    s = replay_client.post("/api/scenarios/explanation", json={"assumptions": [{"kind": "EQUITY_MARKET", "value": -0.1}]}).json()
    assert s["subject"] == "LAB" and s["reasons"] and {"SCENARIO_ASSUMPTION", "PRODUCT_RULE"} <= {x["kind"] for x in s["reasons"]}
    rv = replay_client.post("/api/reverse-stress/explanation", json={"target_pct": -5}).json()
    assert rv["subject"] == "REVERSE" and [x["code"] for x in rv["reasons"]][:2] == ["REVERSE_TARGET", "REVERSE_METHOD"]
    assert replay_client.post("/api/scenarios/explanation", json={"assumptions": [{"kind": "EQUITY_MARKET", "value": -0.99}]}).status_code == 422
    assert replay_client.post("/api/reverse-stress/explanation", json={"target_pct": 5}).status_code == 422
