"""Feedback endpoints over the real replay pack, and the guarantee that recording feedback changes nothing that is served."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def ev(replay_container):  # noqa: ANN001, ANN201
    _, states = replay_container.monitor.replay_states(None)
    st = sorted(states.states.values(), key=lambda s: (-(s.severity or 0), s.event_id))[0]
    return st.event_id, st.lead_signal_id


def test_the_capability_is_advertised_in_replay_only(replay_client, client):
    assert replay_client.get("/api/meta").json()["capabilities"]["feedback"] is True
    assert client.get("/api/meta").json()["capabilities"]["feedback"] is False
    assert client.post("/api/feedback", json={"event_id": "x", "type": "SCOPE", "value": "CORRECT"}).status_code == 404


def test_post_records_and_returns_every_required_field(replay_client, ev):
    eid, sid = ev
    r = replay_client.post("/api/feedback", json={"event_id": sid, "type": "RELEVANCE", "value": "PARTIALLY_RELEVANT", "comment": "only the energy leg matters to us"}, headers={"X-Analyst-Id": "priya"})
    assert r.status_code == 201, r.text
    fb = r.json()
    assert fb["feedback_id"].startswith("fb_") and fb["event_id"] == eid and fb["analyst_id"] == "priya" and fb["type"] == "RELEVANCE" and fb["value"] == "PARTIALLY_RELEVANT"
    assert fb["created_at"] and fb["comment"] == "only the energy leg matters to us" and "not ground truth" in fb["label"]
    listed = replay_client.get("/api/feedback", params={"event_id": eid}).json()
    assert listed["total"] >= 1 and listed["items"][0]["feedback_id"] == fb["feedback_id"] and "not ground truth" in listed["label"]


def test_validation_unknown_events_and_the_comment_cap(replay_client, ev):
    eid, _ = ev
    assert replay_client.post("/api/feedback", json={"event_id": eid, "type": "SCOPE", "value": "RELEVANT"}).status_code == 422
    assert replay_client.post("/api/feedback", json={"event_id": eid, "type": "NOPE", "value": "CORRECT"}).status_code == 422
    assert replay_client.post("/api/feedback", json={"event_id": "evt_nope", "type": "SCOPE", "value": "CORRECT"}).status_code == 404
    assert replay_client.post("/api/feedback", json={"event_id": eid, "type": "SCOPE", "value": "CORRECT", "comment": "x" * 501}).status_code == 422
    assert replay_client.post("/api/feedback", json={"type": "SCOPE", "value": "CORRECT"}).status_code == 422


def test_statistics_are_labelled_and_move_with_the_log(replay_client, ev):
    eid, _ = ev
    before = replay_client.get("/api/feedback/statistics").json()
    replay_client.post("/api/feedback", json={"event_id": eid, "type": "EVENT", "value": "INCORRECT", "analyst_id": "stats-a"})
    replay_client.post("/api/feedback", json={"event_id": eid, "type": "EVENT", "value": "CORRECT", "analyst_id": "stats-b"})
    after = replay_client.get("/api/feedback/statistics").json()
    assert after["volume"] == before["volume"] + 2 and after["event"]["total"] == before["event"]["total"] + 2
    assert "not ground truth" in after["label"] and "does not learn" in after["note"] and after["limitations"]
    assert after["disagreements"] >= 1 and after["needs_review"] >= 1


def test_recording_feedback_changes_nothing_that_is_served(replay_client, ev):
    eid, sid = ev
    probes = [("/api/signals/" + sid, {}), ("/api/signals/" + sid + "/assessment", {}), ("/api/signals/" + sid + "/propagation", {}), (f"/api/events/{eid}/explanation", {}),
              ("/api/monitor/digest", {"window": 4}), (f"/api/events/{eid}/timeline", {}), ("/api/monitor/changes", {"window": 3}), ("/api/models/event", {}), ("/api/models/impact", {})]
    before = [replay_client.get(p, params=q).json() for p, q in probes]
    for t, v in (("RELEVANCE", "IRRELEVANT"), ("SCOPE", "INCORRECT"), ("EVENT", "INCORRECT")):
        assert replay_client.post("/api/feedback", json={"event_id": eid, "type": t, "value": v, "analyst_id": "mutation-test"}).status_code == 201
    assert [replay_client.get(p, params=q).json() for p, q in probes] == before


def test_the_log_lives_outside_every_frozen_artifact(replay_container):
    from eventshock.config import REPO_ROOT
    path = replay_container.feedback._store.path  # noqa: SLF001
    assert path is not None and "feedback" in str(path)
    for frozen in ("models", "configs", "data/replay", "data/gold", "docs/evidence"):
        assert not str(path).startswith(str(REPO_ROOT / frozen))
