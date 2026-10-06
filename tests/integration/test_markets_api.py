"""External-market endpoints over the real replay pack and the synthetic fixture provider (tests never call Kalshi)."""

from __future__ import annotations

import pytest

STATUSES = {"MATCHED", "LOW_CONFIDENCE_MATCH", "NO_MATCH", "INSUFFICIENT_DATA"}


@pytest.fixture(scope="module")
def events(replay_container):  # noqa: ANN001, ANN201
    _, states = replay_container.monitor.replay_states(None)
    top = sorted(states.states.values(), key=lambda s: (-(s.severity or 0), s.event_id))[:8]
    assert top
    return top


def test_capability_is_advertised_in_replay_only(replay_client, client):
    assert replay_client.get("/api/meta").json()["capabilities"]["external_markets"] is True
    assert client.get("/api/meta").json()["capabilities"]["external_markets"] is False
    assert client.get("/api/events/x/external-markets").status_code == 404
    assert client.get("/api/events/x/market-timeline").status_code == 404


def test_every_event_answers_a_well_formed_view_labelled_and_never_an_input(replay_client, events):
    for st in events:
        r = replay_client.get(f"/api/events/{st.event_id}/external-markets")
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["label"] == "EXTERNAL MARKET OBSERVATION" and "never an input" in v["note"] and v["match"]["status"] in STATUSES and v["provenance"]
        assert v["provider"]["synthetic"] is True and "SYNTHETIC FIXTURE" in v["provider"]["reason"]
        if v["match"]["status"] in ("NO_MATCH", "INSUFFICIENT_DATA"):
            assert v["match"]["market"] is None and v["match"]["reason"]
        if v["match"]["market"]:
            assert v["match"]["market"]["provenance"] and v["interpretation"] is not None


def test_unknown_event_is_404_and_a_bad_cycle_is_422(replay_client, events):
    assert replay_client.get("/api/events/evt_nope/external-markets").status_code == 404
    assert replay_client.get(f"/api/events/{events[0].event_id}/external-markets", params={"cycle": 9999}).status_code == 422


def test_the_view_is_byte_identical_on_repeat(replay_client, events):
    a = replay_client.get(f"/api/events/{events[0].event_id}/external-markets").content
    b = replay_client.get(f"/api/events/{events[0].event_id}/external-markets").content
    assert a == b


def test_timeline_items_are_typed_and_sorted(replay_client, events):
    allowed = {"SOURCE_EVENT", "EVENTSHOCK_ASSESSMENT", "EXTERNAL_MARKET_OBSERVATION", "SCENARIO_ASSUMPTION", "REALISED_OUTCOME"}
    for st in events:
        r = replay_client.get(f"/api/events/{st.event_id}/market-timeline")
        assert r.status_code == 200, r.text
        t = r.json()
        assert set(t["kinds"]) <= allowed and [i["at"] for i in t["items"]] == sorted(i["at"] for i in t["items"]) and all(i["provenance"] for i in t["items"])


def test_the_analogues_alias_matches_the_signal_endpoint_or_says_unavailable(replay_client, events):
    st = events[0]
    r = replay_client.get(f"/api/events/{st.event_id}/analogues")
    assert r.status_code in (200, 404), r.text
    if r.status_code == 200:
        direct = replay_client.get(f"/api/signals/{st.anchor_signal_id}/analogues")
        assert direct.status_code == 200 and r.json() == direct.json()


def test_the_market_explanation_gives_reasons_of_the_right_kind_for_every_event(replay_client, events):
    for st in events:
        r = replay_client.get(f"/api/events/{st.event_id}/explanation", params={"subject": "MARKET"})
        assert r.status_code == 200, r.text
        e = r.json()
        assert e["subject"] == "MARKET"
        if e["availability"] == "AVAILABLE":
            assert e["reasons"] and all(x["source_ref"] and x["provenance"] for x in e["reasons"])
            assert {x["kind"] for x in e["reasons"]} <= {"PRODUCT_RULE", "EXTERNAL_MARKET_OBSERVATION"}
            assert not any("confirms" in x["text"].lower() for x in e["reasons"])
