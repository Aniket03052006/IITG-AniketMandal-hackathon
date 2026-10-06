"""Watchlist endpoints over the real replay pack: CRUD, the closed vocabulary, persistence, matching on resolved scope only, and deterministic activity."""

from __future__ import annotations

import pytest


@pytest.fixture()
def lists(replay_client):  # noqa: ANN001, ANN201
    made: list[str] = []
    yield replay_client, made
    for wid in made:
        replay_client.delete(f"/api/watchlists/{wid}")


def make(c, made, name="Mine", enabled=True, items=None):  # noqa: ANN001, ANN201
    r = c.post("/api/watchlists", json={"name": name, "enabled": enabled, "items": items or []})
    if r.status_code == 201:
        made.append(r.json()["id"])
    return r


def test_the_capability_is_advertised_in_replay_only(replay_client, client):
    assert replay_client.get("/api/meta").json()["capabilities"]["watchlists"] is True
    assert client.get("/api/meta").json()["capabilities"]["watchlists"] is False
    assert client.get("/api/watchlists").status_code == 404


def test_crud_round_trip(lists):
    c, made = lists
    r = make(c, made, items=[{"kind": "SECTOR", "value": "Energy"}, {"kind": "EVENT_TYPE", "value": "GEOPOLITICAL"}])
    assert r.status_code == 201
    w = r.json()
    assert w["id"].startswith("wl_") and [i["value"] for i in w["items"]] == ["Energy", "GEOPOLITICAL"] and all(i["label"] for i in w["items"])
    assert c.get(f"/api/watchlists/{w['id']}").json() == w
    assert w["id"] in [x["id"] for x in c.get("/api/watchlists").json()["watchlists"]]
    u = c.put(f"/api/watchlists/{w['id']}", json={"name": "Renamed", "enabled": False, "items": [{"kind": "RISK_THEME", "value": "rates"}]})
    assert u.status_code == 200 and u.json()["name"] == "Renamed" and u.json()["enabled"] is False and u.json()["created_at"] == w["created_at"]
    assert c.delete(f"/api/watchlists/{w['id']}").status_code == 204
    made.clear()
    assert c.get(f"/api/watchlists/{w['id']}").status_code == 404
    assert c.delete(f"/api/watchlists/{w['id']}").status_code == 404
    assert c.put(f"/api/watchlists/{w['id']}", json={"name": "x", "items": []}).status_code == 404


def test_free_text_is_refused_with_every_reason(lists):
    c, made = lists
    r = make(c, made, items=[{"kind": "COMPANY", "value": "Acme Rocket Co"}, {"kind": "SECTOR", "value": "Moonshots"}])
    assert r.status_code == 422
    msgs = [d["msg"] for d in r.json()["detail"]]
    assert len(msgs) == 2 and all("free text is never turned into a company" in m for m in msgs)
    assert c.get("/api/watchlists/../etc").status_code in (404, 422)
    assert c.get("/api/watchlists/not_an_id").status_code == 404


def test_the_vocabulary_is_the_validator(lists):
    c, made = lists
    v = c.get("/api/watchlists/vocabulary").json()
    assert v["companies"] and v["sectors"] and v["industries"] and v["geographies"] and v["event_types"] and v["risk_themes"]
    pick = v["companies"][0]
    r = make(c, made, items=[{"kind": "COMPANY", "value": pick["value"]}, {"kind": "PORTFOLIO_EXPOSURE", "value": "top:3"}])
    assert r.status_code == 201
    assert make(c, made, items=[{"kind": "COMPANY", "value": pick["detail"]}]).json()["items"][0]["value"] == pick["value"]      # a ticker resolves to the entity id


def test_activity_is_deterministic_and_matches_on_resolved_scope(lists):
    c, made = lists
    v = c.get("/api/watchlists/vocabulary").json()
    w = make(c, made, items=[{"kind": "SECTOR", "value": "Technology"}, {"kind": "COMPANY", "value": v["companies"][0]["value"]}, {"kind": "EVENT_TYPE", "value": "EARNINGS_FINANCIAL_PERFORMANCE"}]).json()
    a = c.get(f"/api/watchlists/{w['id']}/activity").json()
    b = c.get(f"/api/watchlists/{w['id']}/activity").json()
    assert a == b and a["status"] == "OK" and a["mode"] == "REPLAY" and a["provenance"] and a["labels"]
    tech = a["items"][0]
    assert tech["status"] == "MATCHED" and tech["matched_events"] > 0 and tech["events"] and tech["rollup"]["max_severity"] is not None
    for e in tech["events"]:
        assert e["match_reason"] and e["clock_trusted"] is True and e["evidence_tier"] and e["event_id"].startswith("evt_")
    et = a["items"][2]
    assert et["status"] == "MATCHED" and et["scanned"] <= 300


def test_an_unresolved_text_never_matches_a_company(lists, replay_container):
    c, made = lists
    unresolved = {s.id for s in replay_container.signals.list() if s.entity.is_unknown}
    w = make(c, made, items=[{"kind": "COMPANY", "value": e.value} for e in [type("E", (), {"value": x["value"]}) for x in c.get("/api/watchlists/vocabulary").json()["companies"][:8]]]).json()
    a = c.get(f"/api/watchlists/{w['id']}/activity").json()
    seen = {ev["lead_signal_id"] for it in a["items"] for ev in it["events"]}
    assert not (seen & unresolved)


def test_a_disabled_list_is_inert(lists):
    c, made = lists
    w = make(c, made, enabled=False, items=[{"kind": "SECTOR", "value": "Energy"}]).json()
    a = c.get(f"/api/watchlists/{w['id']}/activity").json()
    assert a["status"] == "DISABLED" and a["items"][0]["status"] == "DISABLED" and a["items"][0]["events"] == []


def test_activity_cycle_and_mode_validation(lists):
    c, made = lists
    w = make(c, made, items=[{"kind": "SECTOR", "value": "Energy"}]).json()
    assert c.get(f"/api/watchlists/{w['id']}/activity", params={"cycle": 3}).json()["cycle"] == 3
    assert c.get(f"/api/watchlists/{w['id']}/activity", params={"cycle": 9999}).json()["status"] == "UNAVAILABLE"
    assert c.get(f"/api/watchlists/{w['id']}/activity", params={"mode": "NOPE"}).status_code == 422
    live = c.get(f"/api/watchlists/{w['id']}/activity", params={"mode": "LIVE"}).json()
    assert live["mode"] == "LIVE" and live["items"][0]["status"] == "NO_MATCH"          # nothing live: honest, not an error
    assert c.get("/api/watchlists/wl_nonexistent1/activity").status_code == 404
