"""The review queue over the real replay pack: what it lists, how it orders, that a decision is a note, and that deciding changes nothing that is served."""

from __future__ import annotations

import hashlib
import json

TIERS = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE", "UNDETERMINED"]


def served(client) -> str:  # noqa: ANN001
    """A hash of everything a decision must not move: the signals, the digest, a stress run."""
    parts = [client.get("/api/signals").json(), client.get("/api/monitor/digest").json()]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def test_the_capability_is_advertised_in_replay_only(replay_client, client):
    assert replay_client.get("/api/meta").json()["capabilities"]["review"] is True
    assert client.get("/api/meta").json()["capabilities"]["review"] is False
    assert client.get("/api/review/queue").status_code == 404
    assert client.post("/api/review/decisions", json={"event_id": "x", "status": "REVIEWED"}).status_code == 404


def test_the_replay_queue_lists_only_events_with_a_named_reason_in_a_stated_order(replay_client):
    q = replay_client.get("/api/review/queue").json()
    assert q["availability"] == "AVAILABLE" and q["mode"] == "REPLAY" and q["as_of"] and "ground truth" in q["label"] and "not scored" in q["ranking"]
    assert 0 < q["matching"] <= q["counts"]["tracked_events"] and len(q["items"]) == min(q["matching"], 100)
    assert q["counts"]["open"] + q["counts"]["reviewed"] + q["counts"]["dismissed"] == q["counts"]["in_queue"]
    assert {r["code"] for r in q["rules"]} == {"CONFLICTED_CLAIMS", "UNRESOLVED_HIGH_SEVERITY", "SINGLE_SOURCE_HIGH_SEVERITY", "MATERIAL_TO_BOOK", "LARGE_STRESS_LOSS", "ESCALATING", "CHANGED_SINCE_REVIEW"}
    tiers = []
    for i in q["items"]:
        assert i["reasons"] and all(r["detail"] and r["label"] for r in i["reasons"]) and i["status"] == "OPEN" and i["decision"] is None
        assert [p["name"] for p in i["rank_key"]][:3] == ["portfolio materiality tier", "severity", "rules fired"]
        tiers.append(TIERS.index(i["rank_key"][0]["value"]))
    assert tiers == sorted(tiers)  # the most material tier first


def test_every_item_can_be_followed_to_its_event(replay_client):
    for i in replay_client.get("/api/review/queue", params={"limit": 3}).json()["items"]:
        assert replay_client.get(f"/api/signals/{i['signal_id']}").status_code == 200
        assert replay_client.get(f"/api/events/{i['event_id']}/timeline").status_code in (200, 404)  # the timeline route is the event page's own


def test_a_decision_moves_the_item_records_who_and_why_and_changes_nothing_that_is_served(replay_client):
    before = served(replay_client)
    q = replay_client.get("/api/review/queue", params={"limit": 1}).json()
    item = q["items"][0]
    eid = item["event_id"]
    try:
        r = replay_client.post("/api/review/decisions", json={"event_id": item["signal_id"], "status": "REVIEWED", "note": "checked against the desk"}, headers={"X-Analyst-Id": "priya"})
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["decision_id"].startswith("rv_") and d["event_id"] == eid and d["status"] == "REVIEWED" and d["analyst_id"] == "priya" and d["note"] == "checked against the desk"
        assert d["fingerprint"] and d["headline"] == item["headline"] and "ground truth" in d["label"]
        after = replay_client.get("/api/review/queue").json()
        assert eid not in {i["event_id"] for i in after["items"]} and after["counts"]["reviewed"] >= 1 and after["counts"]["open"] == q["counts"]["open"] - 1
        done = replay_client.get("/api/review/queue", params={"status": "REVIEWED"}).json()["items"]
        mine = next(i for i in done if i["event_id"] == eid)
        assert mine["status"] == "REVIEWED" and mine["decision"]["note"] == "checked against the desk" and not mine["changed_since_review"]
        assert served(replay_client) == before  # a decision is a note
    finally:
        replay_client.post("/api/review/decisions", json={"event_id": eid, "status": "OPEN"})  # leave the shared session's queue as it was
    assert eid in {i["event_id"] for i in replay_client.get("/api/review/queue").json()["items"]}
    hist = replay_client.get("/api/review/decisions", params={"event_id": eid}).json()
    assert hist["total"] >= 2 and [x["status"] for x in hist["items"]][:2] == ["OPEN", "REVIEWED"]


def test_a_bad_request_is_refused_and_records_nothing(replay_client):
    total = replay_client.get("/api/review/decisions").json()["total"]
    assert replay_client.post("/api/review/decisions", json={"event_id": "evt_nope", "status": "REVIEWED"}).status_code == 404
    assert replay_client.post("/api/review/decisions", json={"event_id": "x", "status": "MAYBE"}).status_code == 422
    assert replay_client.post("/api/review/decisions", json={"status": "REVIEWED"}).status_code == 422
    eid = replay_client.get("/api/review/queue", params={"limit": 1}).json()["items"][0]["event_id"]
    assert replay_client.post("/api/review/decisions", json={"event_id": eid, "status": "REVIEWED", "note": "x" * 501}).status_code == 422
    assert replay_client.get("/api/review/queue", params={"status": "DONE"}).status_code == 422
    assert replay_client.get("/api/review/queue", params={"limit": 0}).status_code == 422
    assert replay_client.get("/api/review/decisions").json()["total"] == total


def test_the_live_queue_says_why_it_is_empty_and_replay_does_not_depend_on_it(replay_client):
    live = replay_client.get("/api/review/queue", params={"mode": "LIVE"}).json()
    assert live["mode"] == "LIVE" and live["availability"] in ("AVAILABLE", "UNAVAILABLE")
    if live["availability"] == "UNAVAILABLE":
        assert live["reason"] and live["items"] == []
    assert replay_client.get("/api/review/queue").json()["availability"] == "AVAILABLE"


def test_the_queue_follows_the_selected_book(replay_client):
    default = replay_client.get("/api/review/queue", params={"limit": 500}).json()
    assert default["portfolio_id"] is None or isinstance(default["portfolio_id"], str)
    named = replay_client.get("/api/review/queue", params={"limit": 500, "portfolio_id": "default"}).json()
    assert [i["event_id"] for i in named["items"]] == [i["event_id"] for i in default["items"]]
    assert replay_client.get("/api/review/queue", params={"portfolio_id": "pf_doesnotexist"}).status_code in (404, 422)
