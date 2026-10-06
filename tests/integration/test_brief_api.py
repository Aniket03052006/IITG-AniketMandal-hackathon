"""The executive brief over the real replay pack: sixteen sections in a fixed order, every statement sourced and kinded, deterministic bytes, fixed fallback sentences, and nothing mutated."""

from __future__ import annotations

import pytest

from eventshock.brief.models import SECTIONS
from eventshock.pipeline.run import _digest
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST

KINDS = {"SOURCE_EVENT", "EVENTSHOCK_ASSESSMENT", "EXTERNAL_MARKET_OBSERVATION", "SCENARIO_ASSUMPTION", "HISTORICAL_OBSERVATION", "REALISED_OUTCOME", "PRODUCT_RULE"}
BANNED = ("will happen", "is expected to", "forecast that", "prediction that", "confirms", "guaranteed")


@pytest.fixture(scope="module")
def events(replay_container):  # noqa: ANN001, ANN201
    _, states = replay_container.monitor.replay_states(None)
    top = sorted(states.states.values(), key=lambda s: (-(s.severity or 0), s.event_id))[:6]
    assert top
    return top


def test_capability_is_advertised_in_replay_only(replay_client, client):
    assert replay_client.get("/api/meta").json()["capabilities"]["executive_brief"] is True
    assert client.get("/api/meta").json()["capabilities"]["executive_brief"] is False
    assert client.get("/api/events/x/brief").status_code == 404


def test_every_event_has_all_sixteen_sections_in_order_with_sourced_kinded_statements(replay_client, events):
    for st in events:
        r = replay_client.get(f"/api/events/{st.event_id}/brief")
        assert r.status_code == 200, r.text
        b = r.json()
        assert [s["id"] for s in b["sections"]] == [i for i, _ in SECTIONS] and [s["title"] for s in b["sections"]] == [t for _, t in SECTIONS]
        ids = {s["id"] for s in b["sources"]}
        for sec in b["sections"]:
            assert sec["statements"] and sec["availability"] in ("AVAILABLE", "PARTIAL", "UNAVAILABLE")
            for stmt in sec["statements"]:
                assert stmt["text"] and stmt["kind"] in KINDS and stmt["source_refs"] and set(stmt["source_refs"]) <= ids
                assert not any(w in stmt["text"].lower() for w in BANNED), stmt["text"]
        assert b["labels"] and "NOT A PREDICTION" in b["note"]


def test_the_stress_section_is_labelled_a_simulation_and_the_market_section_uses_the_fixed_sentences(replay_client, events):
    seen_market = set()
    for st in events:
        b = replay_client.get(f"/api/events/{st.event_id}/brief").json()
        sec = {s["id"]: s for s in b["sections"]}
        stress = " ".join(x["text"] for x in sec["STRESS"]["statements"])
        assert "NOT A PREDICTION" in stress or "SCENARIO UNAVAILABLE" in stress or "No stress scenario" in stress
        m = " ".join(x["text"] for x in sec["EXTERNAL_MARKET_VIEW"]["statements"])
        assert ("No relevant external prediction market identified." in m or "External market data unavailable." in m or "EXTERNAL MARKET OBSERVATION" in m)
        seen_market.add(sec["EXTERNAL_MARKET_VIEW"]["availability"])
        assert all(x["kind"] in ("EXTERNAL_MARKET_OBSERVATION", "PRODUCT_RULE") for x in sec["EXTERNAL_MARKET_VIEW"]["statements"])
        assert all(x["kind"] in ("HISTORICAL_OBSERVATION", "PRODUCT_RULE") for x in sec["HISTORICAL_CONTEXT"]["statements"])
    assert seen_market


def test_the_brief_is_byte_identical_on_repeat_in_json_and_markdown(replay_client, events):
    eid = events[0].event_id
    assert replay_client.get(f"/api/events/{eid}/brief").content == replay_client.get(f"/api/events/{eid}/brief").content
    a = replay_client.get(f"/api/events/{eid}/brief", params={"format": "md"})
    assert a.status_code == 200 and a.headers["content-type"].startswith("text/markdown") and a.content == replay_client.get(f"/api/events/{eid}/brief", params={"format": "md"}).content
    text = a.text
    for _, title in SECTIONS:
        assert title in text
    assert "## Sources" in text and text.count("## ") == 17


def test_unknown_event_is_404_a_bad_cycle_422_and_an_event_id_or_signal_id_both_resolve(replay_client, events):
    assert replay_client.get("/api/events/evt_nope/brief").status_code == 404
    assert replay_client.get(f"/api/events/{events[0].event_id}/brief", params={"cycle": 9999}).status_code == 422
    by_event = replay_client.get(f"/api/events/{events[0].event_id}/brief").json()
    by_signal = replay_client.get(f"/api/events/{events[0].anchor_signal_id}/brief").json()
    assert by_event["event_id"] == by_signal["event_id"]


def test_the_brief_changes_nothing_that_is_served(replay_client, replay_container, events):
    eid = events[0]
    before = [replay_client.get(f"/api/signals/{eid.lead_signal_id}/{p}").content for p in ("propagation", "relevance")]
    for st in events:
        replay_client.get(f"/api/events/{st.event_id}/brief")
    assert [replay_client.get(f"/api/signals/{eid.lead_signal_id}/{p}").content for p in ("propagation", "relevance")] == before
    assert _digest(replay_container.signals.list()) == GOLDEN_SERVED_DIGEST
