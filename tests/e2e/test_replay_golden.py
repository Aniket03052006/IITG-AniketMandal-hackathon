"""Deterministic replay: a fixed event must always produce the same signal -> scenario -> result.

If this fails after an intentional change to fixtures, scenarios or engine formulas, review the diff
and update the pinned values deliberately (they are the regression anchor for the demo).
"""

from __future__ import annotations

import pytest

GOLDEN_RUN_ID = "run_10e9dc8e3b9a"


def run(client, **payload):
    return client.post("/api/stress-test", json={"signal_id": "sig_0001", **payload}).json()


def test_golden_stress_result_for_headline_demo_signal(client):
    sig = client.get("/api/signals/sig_0001").json()
    assert (sig["event"]["category"], sig["impact"]["score"], sig["sentiment"]["score"]) == (
        "CREDIT_FUNDING", 9, -0.72)

    r = run(client)
    assert r["run_id"] == GOLDEN_RUN_ID
    assert r["scenario"]["id"] == "scn_credit_funding_stress"
    assert r["severity"]["scale"] == pytest.approx(9 / 7)
    s = r["summary"]
    assert s["baseline_value"] == pytest.approx(558_798_258.0, abs=1.0)
    assert s["pnl"] == pytest.approx(-10_173_459.37, abs=1.0)
    assert s["pnl_pct"] == pytest.approx(-0.018205, abs=1e-5)
    worst = r["contributions"]["by_entity"][0]
    assert worst["key"] == "ENT_MRDN"  # the issuer itself drives the loss
    assert r["audit"]["calculated_at"].startswith("2026-10-01T12:00:00")


def test_replay_is_reproducible_across_app_instances(settings):
    from fastapi.testclient import TestClient

    from eventshock.api.main import create_app

    a = TestClient(create_app(settings)).post("/api/stress-test", json={"signal_id": "sig_0003"}).json()
    b = TestClient(create_app(settings)).post("/api/stress-test", json={"signal_id": "sig_0003"}).json()
    assert a == b


def test_every_triggering_fixture_signal_completes_and_reconciles(client):
    feed = client.get("/api/signals", params={"min_impact": 7}).json()["items"]
    assert feed
    for item in feed:
        r = client.post("/api/stress-test", json={"signal_id": item["id"]}).json()
        assert r["status"] == "COMPLETED", item["id"]
        assert r["summary"]["pnl"] == pytest.approx(sum(p["delta"] for p in r["positions"]))
        assert r["audit"]["data_origin"] == "DEMO_FIXTURE"


def test_demo_pipeline_covers_defensibility_cases(client):
    """Showable failure handling: duplicate/contradiction, unknown entity, partial signal."""
    assert client.get("/api/signals/sig_0005").json()["evidence"]["contradicted_by"] == ["sig_0006"]
    assert client.get("/api/signals/sig_0013").json()["entity"]["entity_id"] == "UNKNOWN_ENTITY"
    assert client.post("/api/stress-test", json={"signal_id": "sig_0014"}).json()["status"] == "UNAVAILABLE"
