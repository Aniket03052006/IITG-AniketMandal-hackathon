"""Event intelligence through the real application (replay profile, real trained models, rule mode: the language model is never called)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eventshock.api.main import create_app
from eventshock.config import Settings
from tests.fakes import GEOPOLITICAL, MNA, MONETARY, UNKNOWN


@pytest.fixture(scope="module")
def app_client(tmp_path_factory):
    d = tmp_path_factory.mktemp("intel")
    return TestClient(create_app(Settings(profile="replay", journal_path=d / "journal.jsonl", llm_cache_path=d / "llm.jsonl", llm=False)))


def analyze(c: TestClient, text: str, **kw) -> dict:
    r = c.post("/api/analyze", json={"text": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_capability_is_announced(app_client) -> None:
    assert app_client.get("/api/meta").json()["capabilities"]["intelligence"] is True


def test_pasted_text_gets_the_same_intelligence_as_any_signal(app_client) -> None:
    r = analyze(app_client, "Goldman Sachs fined $50 million over trading violations, regulators say")
    i = r["intelligence"]
    assert i is not None and i["signal_id"] == r["signal_id"]
    assert i["scope"]["scope_type"] == "COMPANY" and "Goldman" in i["scope"]["scope_value"]
    assert [n["type"] for n in i["scope"]["scope_path"]][:1] == ["COMPANY"] and i["scope"]["scope_path"][-1]["type"] == "MARKET"
    assert i["provenance"]["channel"] == "MANUAL" and i["provenance"]["clock_trusted"] is True
    assert i["group"]["report_count"] >= 1 and i["evidence"]["evidence_strength"]["tier"] in {"INSUFFICIENT", "WEAK", "MODERATE", "STRONG"}
    assert i["novelty"]["label"] in {"NEW", "CONTINUATION", "UPDATE", "RECURRING", "UNKNOWN"}
    assert i["lifecycle"]["state"] in {"DEVELOPING", "CONFIRMED"} and i["lifecycle"]["as_of_basis"] == "NOW"
    assert i["stress"]["status"] is not None and i["event"]["severity_score"] == r["assessment"]["severity"]["score"]
    ids = [m["stage"] for m in i["evidence"]["model_confidence"]]
    assert ids == ["event", "sentiment", "impact"]  # model confidence is its own list, never folded into the evidence tier


@pytest.mark.parametrize("text,types", [(MONETARY, {"MACRO", "MARKET", "THEME"}), (GEOPOLITICAL, {"SECTOR", "INDUSTRY", "MARKET", "GEOGRAPHY", "THEME", "MACRO"}),
                                        (MNA, {"INDUSTRY", "SECTOR", "MARKET", "MACRO", "THEME", "UNRESOLVED"})])
def test_non_company_text_resolves_to_a_non_company_scope(app_client, text: str, types: set) -> None:
    i = analyze(app_client, text)["intelligence"]
    assert i["scope"]["scope_type"] in types and i["scope"]["scope_type"] != "COMPANY"
    assert i["scope"]["scope_confidence"]["tier"] in {"HIGH", "MEDIUM", "LOW", "NONE"}


def test_an_unnamed_company_stays_unknown_and_says_so(app_client) -> None:
    i = analyze(app_client, UNKNOWN)["intelligence"]
    fields = {a["field"]: a for a in i["abstentions"]}
    assert fields["company"]["state"] == "UNKNOWN"
    assert i["affected"]["entities"] == [] or all(e["resolved"] is False for e in i["affected"]["entities"])


def test_text_that_is_not_a_market_event_is_unresolved_with_every_abstention_stated(app_client) -> None:
    r = analyze(app_client, "Lovely weather this weekend, going for a long walk by the lake with the dog")
    i = r["intelligence"]
    if i is None:  # quarantined as unscorable: nothing is invented
        assert r["outcome"] == "QUARANTINED"
        return
    assert i["scope"]["scope_type"] == "UNRESOLVED" and i["scope"]["resolution_status"] in {"UNRESOLVED", "AMBIGUOUS"}
    fields = {a["field"]: a for a in i["abstentions"]}
    assert "scope" in fields and "company" in fields and "impact" in fields or "severity" in fields


def test_headline_and_url_are_used_for_attribution_and_never_fetched(app_client, monkeypatch) -> None:
    import socket

    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("the server must not make a network call for pasted text")

    monkeypatch.setattr(socket, "create_connection", boom)
    r = analyze(app_client, "Shares fell after the filing; analysts expect more disclosure next week.", headline="Acme Corp discloses probe",
                url="https://www.example-news.com/a/b?utm_source=x")
    assert r["headline"] == "Acme Corp discloses probe"
    refs = r["intelligence"]["group"]["reports"]
    assert refs[0]["domain"] == "example-news.com" and refs[0]["url"].startswith("https://example-news.com/")
    bad = app_client.post("/api/analyze", json={"text": "Acme fined $5 million over disclosures", "url": "javascript:alert(1)"})
    assert bad.status_code == 422 and "http" in bad.json()["detail"]


def test_a_replayed_signal_has_a_labelled_as_of_and_a_lifecycle_timeline(replay_client) -> None:
    items = replay_client.get("/api/signals").json()["items"]
    sid = next(s["id"] for s in items if s["source_count"] >= 2 and s["channel"] == "REPLAY")
    i = replay_client.get(f"/api/signals/{sid}/intelligence").json()
    assert i["as_of_basis"] == "LAST_REPORT" and i["group"]["report_count"] >= 2
    if i["provenance"]["clock_trusted"]:
        assert i["lifecycle"]["transitions"][0]["rule"] == "FIRST_REPORT"
    first = i["group"]["first_seen"]
    early = replay_client.get(f"/api/signals/{sid}/intelligence", params={"as_of": first})
    assert early.status_code == 200 and early.json()["group"]["report_count"] <= i["group"]["report_count"]
    before = replay_client.get(f"/api/signals/{sid}/intelligence", params={"as_of": "2000-01-01T00:00:00Z"})
    assert before.status_code == 422 and "precedes" in before.json()["detail"]


def test_unknown_signal_is_404(replay_client) -> None:
    assert replay_client.get("/api/signals/nope/intelligence").status_code == 404


def test_the_feed_carries_scope_type_and_filters_on_it(replay_client) -> None:
    rows = replay_client.get("/api/signals").json()["items"]
    assert all(r["scope_type"] is not None for r in rows[:50])
    some = replay_client.get("/api/signals", params={"scope_type": "COMPANY"}).json()["items"]
    assert some and all(r["scope_type"] == "COMPANY" for r in some)
    assert replay_client.get("/api/signals", params={"scope_type": "BOGUS"}).status_code == 422
