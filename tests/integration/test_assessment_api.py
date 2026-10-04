"""The risk-assessment layer through the real application (replay profile, real trained models, rule mode: the language model is never called)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eventshock.api.main import create_app
from eventshock.config import Settings
from tests.fakes import CASES, EARNINGS, GEOPOLITICAL, MONETARY, REGULATORY, UNKNOWN

GS = "Goldman Sachs fined $50 million over trading violations, regulators say"
GS_REWORDED = ["Regulators say Goldman Sachs was fined $50 million for trading violations",
               "Goldman Sachs hit with $50 million fine for trading violations, say regulators"]


@pytest.fixture(scope="module")
def app_client(tmp_path_factory):
    d = tmp_path_factory.mktemp("assess")
    return TestClient(create_app(Settings(profile="replay", journal_path=d / "journal.jsonl", llm_cache_path=d / "llm.jsonl", llm=False)))


def analyze(c: TestClient, text: str, **kw) -> dict:
    r = c.post("/api/analyze", json={"text": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_meta_says_how_text_is_read(app_client) -> None:
    caps = app_client.get("/api/meta").json()["capabilities"]
    assert caps["assessment"] is True and caps["llm"]["mode"] == "RULES" and caps["llm"]["sends_text_off_machine"] is False
    assert "switched off" in caps["llm"]["reason"]


@pytest.mark.parametrize("name", ["regulatory", "monetary", "geopolitical", "earnings", "mna", "unknown"])
def test_each_required_case_gets_a_full_assessment(app_client, name: str) -> None:
    case = CASES[name]
    r = analyze(app_client, case["text"])
    a = r["assessment"]
    assert a is not None and a["signal_id"] == r["signal_id"]
    rd = a["reading"]
    assert rd["event_type"] == case["event"]
    assert set(case["sectors"]) <= set(rd["sectors"]) and set(case["regions"]) <= set(rd["regions"])
    assert rd["primary_issuer"]["entity_id"] == "UNKNOWN_ENTITY"  # none of the seven names a company in the entity master
    assert a["extraction"]["mode"] == "RULES" and a["severity"]["basis"] == "TRANSPARENT_HYBRID"
    assert 1 <= a["severity"]["score"] <= 10 and a["severity"]["low"] <= a["severity"]["score"] <= a["severity"]["high"]
    assert any("not a forecast" in label.lower() for label in a["labels"])
    for s in rd["evidence"]:
        assert rd["text"][s["start"]:s["end"]] == s["quote"]
    assert r["signal"]["severity_score"] == a["severity"]["score"]  # the feed row and the assessment agree


def test_an_unknown_company_is_never_an_issuer_and_no_issuer_shock_binds(app_client) -> None:
    r = analyze(app_client, UNKNOWN)
    rd = r["assessment"]["reading"]
    qd = next(e for e in rd["entities"] if e["name"] == "Quantum Dynamics")
    assert qd["resolved"] is False and qd["ticker"] is None and rd["sectors"] == []
    run = app_client.post("/api/stress-test", json={"signal_id": r["signal_id"], "force": True}).json()
    assert run["status"] in {"COMPLETED", "NOT_APPLICABLE"}
    assert all(s["applicable"] is False for s in run["shocks"] if s["scope"] == "ISSUER")


def test_the_threshold_is_explicit_and_drives_the_stress(app_client) -> None:
    hot = analyze(app_client, GEOPOLITICAL)
    cold = analyze(app_client, MONETARY)
    h, c = hot["assessment"]["threshold"], cold["assessment"]["threshold"]
    assert h["crosses"] and h["status"] == "ABOVE_TRIGGER" and not c["crosses"] and c["status"] == "BELOW_TRIGGER"
    ran = app_client.post("/api/stress-test", json={"signal_id": hot["signal_id"]}).json()
    assert ran["status"] == "COMPLETED" and ran["audit"]["impact_origin"] == "ASSESSMENT" and ran["audit"]["severity_basis"] == "TRANSPARENT_HYBRID"
    assert ran["severity"]["impact_used"] == hot["assessment"]["severity"]["score"] and ran["summary"]["pnl"] < 0
    held = app_client.post("/api/stress-test", json={"signal_id": cold["signal_id"]}).json()
    assert held["status"] == "NOT_TRIGGERED" and "Severity" in held["reason"] and "what-if" in held["reason"]
    what_if = app_client.post("/api/stress-test", json={"signal_id": cold["signal_id"], "force": True}).json()
    assert what_if["status"] == "COMPLETED" and what_if["audit"]["forced"]
    runs = app_client.get("/api/stress-runs", params={"signal_id": cold["signal_id"]}).json()
    assert {r["run_id"] for r in runs} >= {held["run_id"], what_if["run_id"]}
    assert app_client.get(f"/api/stress-runs/{what_if['run_id']}").json()["run_id"] == what_if["run_id"]


def test_a_text_read_as_a_sector_binds_sector_shocks_in_the_portfolio(app_client) -> None:
    r = analyze(app_client, REGULATORY)
    run = app_client.post("/api/stress-test", json={"signal_id": r["signal_id"], "force": True}).json()
    assert run["status"] == "COMPLETED"
    sector = next((s for s in run["shocks"] if s["scope"] == "SECTOR"), None)
    assert sector is not None and sector["applicable"], "the Financials sector read from the text must reach the portfolio"
    assert run["audit"]["assessed_sector"] in {None, "Financials"}


def test_reworded_reports_of_one_story_are_one_signal_and_do_not_inflate_severity(app_client) -> None:
    first = analyze(app_client, GS)
    sid, base = first["signal_id"], first["assessment"]["severity"]["points"]
    for text in GS_REWORDED:
        r = analyze(app_client, text, source="Second Wire")
        assert r["outcome"] == "UPDATED" and r["signal_id"] == sid
    now = app_client.get(f"/api/signals/{sid}/assessment").json()
    assert now["severity"]["points"] == base, "later coverage is shown, never scored"
    assert now["later_reports_excluded"] >= 2 and now["corroborating_at_event_time"] == 0
    feed = app_client.get("/api/signals", params={"channel": "MANUAL"}).json()["items"]
    assert sum(1 for s in feed if s["entity_id"] != "UNKNOWN_ENTITY" and s["ticker"] == "GS") == 1  # one signal, not three
    plain = app_client.post("/api/stress-test", json={"signal_id": sid, "force": True}).json()
    assert plain["status"] == "COMPLETED"
    ev = app_client.get(f"/api/signals/{sid}/evidence").json()
    assert len([r for r in ev["source_evidence"]["reports"] if r["phase"] == "AFTER_REPORT"]) >= 2
    assert all(r["used_in_score"] is False for r in ev["source_evidence"]["reports"] if r["phase"] == "AFTER_REPORT")


def test_evidence_keeps_source_inference_and_assumption_apart(app_client) -> None:
    sid = analyze(app_client, EARNINGS)["signal_id"]
    ev = app_client.get(f"/api/signals/{sid}/evidence").json()
    assert set(ev) == {"signal_id", "source_evidence", "model_inference", "scenario_assumptions"}
    assert ev["source_evidence"]["text"] == EARNINGS and ev["source_evidence"]["spans"]
    kinds = {line["kind"] for line in ev["model_inference"]["lines"]}
    assert "EXTRACTION" in kinds and "JUDGEMENT_PRIOR" in kinds and "SOURCE" not in {line["kind"] for line in ev["model_inference"]["lines"] if line["label"] == "Event"}
    sa = ev["scenario_assumptions"]
    assert sa["illustrative"] is True and sa["shocks"] and "clamp" in sa["severity_scaling"]


def test_the_timeline_marks_everything_after_the_report_as_unused(app_client) -> None:
    sid = analyze(app_client, MONETARY)["signal_id"]
    tl = app_client.get(f"/api/signals/{sid}/timeline").json()
    kinds = [i["kind"] for i in tl["items"]]
    assert "REPORT" in kinds and "ASSESSED" in kinds
    for i in tl["items"]:
        if i["phase"] == "AFTER_REPORT":
            assert i["used_in_severity"] is False
    assert any("later coverage" in e.lower() for e in tl["excluded"])


def test_a_replay_signal_has_the_same_endpoints_and_a_consistent_headline(app_client) -> None:
    items = app_client.get("/api/signals", params={"channel": "REPLAY", "min_impact": 5}).json()["items"]
    assert items and all((s["severity_score"] or 0) >= 5 for s in items)
    s = items[0]
    a = app_client.get(f"/api/signals/{s['id']}/assessment").json()
    assert a["severity"]["score"] == s["severity_score"] and a["extraction"]["mode"] == "RULES"
    assert a["reference"]["note"]
    assert app_client.get(f"/api/signals/{s['id']}/evidence").status_code == 200
    assert app_client.get(f"/api/signals/{s['id']}/timeline").status_code == 200


def test_unknown_ids_are_404_and_bad_input_is_422(app_client) -> None:
    for path in ("assessment", "evidence", "timeline"):
        assert app_client.get(f"/api/signals/nope/{path}").status_code == 404
    assert app_client.get("/api/stress-runs", params={"signal_id": "nope"}).status_code == 404
    assert app_client.post("/api/analyze", json={"text": ""}).status_code == 422
    assert app_client.post("/api/analyze", json={"text": "   \n  "}).status_code == 422


def test_odd_but_usable_input_degrades_instead_of_crashing(app_client) -> None:
    short = app_client.post("/api/analyze", json={"text": "ok"}).json()
    assert short["outcome"] == "QUARANTINED" and short["assessment"] is None and short["rejection"]["code"]
    noise = analyze(app_client, "Lovely weather in the city this weekend, enjoy the sunshine everyone")
    assert noise["assessment"]["severity"] is None or noise["assessment"]["reading"]["event_type"] != "NO_EVENT"
    named = analyze(app_client, "Quarterly update from the desk: nothing to report today, markets calm.", source="Desk note")
    assert named["signal"]["source"] == "Desk note"
