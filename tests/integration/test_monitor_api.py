"""The monitor and event-timeline endpoints over the real replay pack."""

from __future__ import annotations


def test_the_capability_is_advertised_in_replay_only(replay_client, client):
    assert replay_client.get("/api/meta").json()["capabilities"]["monitor"] is True
    assert client.get("/api/meta").json()["capabilities"]["monitor"] is False
    assert client.get("/api/monitor/status").status_code == 404
    assert client.get("/api/events/x/timeline").status_code == 404


def test_status_says_what_each_mode_can_do(replay_client):
    r = replay_client.get("/api/monitor/status").json()
    assert r["mode"] == "REPLAY" and r["state"] == "OK" and r["available"] and r["replay_cycles"] > 5 and r["labels"] and r["limitations"]
    live = replay_client.get("/api/monitor/status", params={"mode": "LIVE"}).json()
    assert live["state"] == "OFF" and not live["available"] and "REPLAY works" in live["reason"]


def test_cycles_are_a_fixed_clock(replay_client):
    cy = replay_client.get("/api/monitor/cycles").json()
    assert cy[0]["baseline"] is True and [c["index"] for c in cy] == list(range(len(cy)))
    assert [c["at"] for c in cy] == sorted(c["at"] for c in cy)
    assert replay_client.get("/api/monitor/cycles").json() == cy


def test_changes_are_structured_and_identical_on_every_call(replay_client):
    a = replay_client.get("/api/monitor/changes", params={"cycle": 8, "window": 2}).json()
    b = replay_client.get("/api/monitor/changes", params={"cycle": 8, "window": 2}).json()
    assert a == b and a["mode"] == "REPLAY" and a["availability"] == "AVAILABLE"
    assert a["tracked_events"] > 0 and a["excluded_untrusted_clock"] > 0
    for ch in a["changes"]:
        assert ch["event_id"].startswith("evt_") and ch["rule"] and ch["provenance"] and ch["current"]["fingerprint"]
        assert ch["cycle"] in (7, 8)
    ids = [c["change_id"] for c in a["changes"]]
    assert len(ids) == len(set(ids))


def test_the_baseline_cycle_has_no_changes(replay_client):
    assert replay_client.get("/api/monitor/changes", params={"cycle": 0}).json()["changes"] == []


def test_types_filter_and_validation(replay_client):
    ok = replay_client.get("/api/monitor/changes", params={"cycle": 8, "types": ["NEW_EVENT"]}).json()
    assert all(c["change_type"] == "NEW_EVENT" for c in ok["changes"])
    assert replay_client.get("/api/monitor/changes", params={"cycle": 999}).status_code == 422
    assert replay_client.get("/api/monitor/changes", params={"types": ["NOPE"]}).status_code == 422
    assert replay_client.get("/api/monitor/changes", params={"mode": "LIVE", "since": "not-a-time"}).status_code == 422


def test_live_mode_is_unavailable_not_an_error_when_the_feed_is_off(replay_client):
    r = replay_client.get("/api/monitor/changes", params={"mode": "LIVE"}).json()
    assert r["mode"] == "LIVE" and r["availability"] == "UNAVAILABLE" and r["changes"] == [] and "live feed is off" in r["reason"]


def test_an_event_timeline_resolves_from_an_event_or_a_signal_id(replay_client):
    ch = next(c for c in replay_client.get("/api/monitor/changes", params={"cycle": 8, "window": 4}).json()["changes"])
    by_event = replay_client.get(f"/api/events/{ch['event_id']}/timeline").json()
    by_signal = replay_client.get(f"/api/events/{ch['current']['anchor_signal_id']}/timeline").json()
    assert by_event == by_signal and by_event["availability"] == "AVAILABLE"
    kinds = {i["kind"] for i in by_event["items"]}
    assert "REPORT" in kinds and by_event["items"][0]["update_kind"] == "NEW_EVENT"
    assert all(i["provenance"] for i in by_event["items"]) and by_event["history"]
    assert replay_client.get("/api/events/evt_doesnotexist/timeline").status_code == 404


def test_refresh_is_a_noop_when_live_is_off(replay_client):
    r = replay_client.post("/api/monitor/refresh")
    assert r.status_code == 200 and r.json()["state"] == "OFF"


# ------------------------------------------------------------------------------------------------------------------------------------ digest
def test_the_digest_has_every_configured_section_in_order_with_a_ranked_drillable_card(replay_client):
    d = replay_client.get("/api/monitor/digest", params={"window": 6}).json()
    assert d["availability"] == "AVAILABLE" and d["mode"] == "REPLAY" and d["ranking"].startswith("Ordered by relevance to the portfolio")
    assert [s["id"] for s in d["sections"]] == ["NEW_RISKS", "ESCALATIONS", "EXPOSURE_CHANGES", "STRESS_CHANGES", "EVIDENCE_CHANGES", "CONFLICTS", "CONCENTRATION", "WATCHLISTS"]
    cards = [c for s in d["sections"] for c in s["cards"]]
    assert cards
    for s in d["sections"]:
        assert len(s["cards"]) <= 5 and s["total"] >= len(s["cards"]) and s["truncated"] == (s["total"] > len(s["cards"]))
        assert [c["rank"] for c in s["cards"]] == list(range(1, len(s["cards"]) + 1))
    for c in cards:
        if c["kind"] == "EVENT":
            assert [p["name"] for p in c["rank_key"]] == ["materiality", "severity", "size of change", "recency", "id"]
            assert [x["step"] for x in c["drill"]] == ["EVENT", "EVIDENCE", "SCOPE", "EXPOSURE", "PROPAGATION", "STRESS", "ATTRIBUTION"] and c["event_id"].startswith("evt_") and c["provenance"]
        assert not [k for k in c if "score" in k]
    assert not [k for k in d if "score" in k]


def test_the_digest_order_follows_its_shown_key_and_is_the_same_every_call(replay_client):
    d = replay_client.get("/api/monitor/digest", params={"window": 6}).json()
    assert d == replay_client.get("/api/monitor/digest", params={"window": 6}).json()
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE", "UNDETERMINED"]
    for s in d["sections"]:
        if s["id"] in ("CONCENTRATION", "WATCHLISTS"):
            continue
        keys = [(order.index(c["rank_key"][0]["value"]), -float(c["rank_key"][1]["value"] if c["rank_key"][1]["value"] != "n/a" else 0)) for c in s["cards"]]
        assert keys == sorted(keys), s["id"]                                              # materiality tier then severity never goes the wrong way


def test_digest_validation_and_modes(replay_client):
    assert replay_client.get("/api/monitor/digest", params={"cycle": 99999}).status_code == 422
    assert replay_client.get("/api/monitor/digest", params={"window": 0}).status_code == 422
    live = replay_client.get("/api/monitor/digest", params={"mode": "LIVE"}).json()
    assert live["mode"] == "LIVE" and live["availability"] == "UNAVAILABLE" and "live feed is off" in live["reason"] and live["sections"] == []
    early = replay_client.get("/api/monitor/digest", params={"cycle": 0}).json()
    assert early["availability"] == "AVAILABLE" and all(s["total"] == 0 for s in early["sections"] if s["id"] not in ("CONCENTRATION", "WATCHLISTS"))     # the baseline reports no change


def test_a_watched_subject_appears_in_the_watchlist_section(replay_client):
    v = replay_client.get("/api/watchlists/vocabulary").json()
    w = replay_client.post("/api/watchlists", json={"name": "digest test", "items": [{"kind": "EVENT_TYPE", "value": v["event_types"][0]["value"]}]}).json()
    try:
        d = replay_client.get("/api/monitor/digest", params={"window": 12}).json()
        sec = next(s for s in d["sections"] if s["id"] == "WATCHLISTS")
        assert any(c["watch"]["watchlist_id"] == w["id"] and c["watch"]["matched_events"] > 0 for c in sec["cards"])
        card = next(c for c in sec["cards"] if c["watch"]["watchlist_id"] == w["id"])
        assert card["headline"] == "digest test" and [p["name"] for p in card["rank_key"]][0] == "new events"
    finally:
        replay_client.delete(f"/api/watchlists/{w['id']}")


def test_the_digest_is_unavailable_outside_the_replay_profile(client):
    assert client.get("/api/monitor/digest").status_code == 404
