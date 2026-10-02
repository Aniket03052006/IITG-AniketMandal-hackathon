"""The real-source replay profile end to end: pack -> pipeline -> API -> stress engine."""

from __future__ import annotations

from eventshock.domain import UNKNOWN_ENTITY, DataOrigin


class TestMetaAndReport:
    def test_meta_describes_the_replay_profile_honestly(self, replay_client):
        m = replay_client.get("/api/meta").json()
        assert m["profile"] == "replay" and m["data_origin"] == "REAL_SOURCE_PLACEHOLDER_NLP"
        assert m["replay"]["snapshot_id"] and len(m["replay"]["output_digest"]) == 64
        assert any("PLACEHOLDER" in n for n in m["notices"])
        assert m["replay"]["stage_origins"]["impact"].startswith("PLACEHOLDER")

    def test_demo_profile_meta_is_unchanged(self, client):
        m = client.get("/api/meta").json()
        assert m["profile"] == "demo" and m["data_origin"] == "DEMO_FIXTURE" and m["replay"] is None

    def test_pipeline_report_accounts_for_every_record(self, replay_client):
        r = replay_client.get("/api/pipeline/report").json()
        c = r["counts"]
        assert c["records_read"] == c["quarantined"] + c["exact_duplicates_folded"] + c["reports_in_signals"]
        assert c["signals"] == c["entity_resolved"] + c["entity_unknown"]
        assert {s["source_type"] for s in r["sources"]} == {"NEWS", "SOCIAL"}
        assert all(s["license"] and s["attribution"] for s in r["sources"])

    def test_failed_downloads_are_reported_not_hidden(self, replay_client):
        log = replay_client.get("/api/pipeline/report").json()["fetch_log"]
        assert log and {e["status"] for e in log} <= {"ok", "error"}
        for e in log:
            assert e["attempts"] >= 1 and (e["status"] == "ok" or e["last_error"])
        assert any(e["status"] == "error" for e in log), "the shipped pack is partial and must say so"

    def test_no_pipeline_report_in_demo_profile(self, client):
        assert client.get("/api/pipeline/report").status_code == 404


class TestSignals:
    def test_two_source_types_and_no_fixture_origin(self, replay_client):
        items = replay_client.get("/api/signals").json()["items"]
        assert {i["source_type"] for i in items} == {"NEWS", "SOCIAL"}
        assert {i["data_origin"] for i in items} == {DataOrigin.REAL_SOURCE_PLACEHOLDER_NLP.value}

    def test_signal_detail_carries_provenance(self, replay_client):
        sid = replay_client.get("/api/signals").json()["items"][0]["id"]
        s = replay_client.get(f"/api/signals/{sid}").json()
        p = s["provenance"]
        assert p["snapshot_id"] and p["record_ref"] and len(p["content_sha256"]) == 64
        assert p["dedup"]["member_count"] == s["evidence"]["source_count"]
        assert set(p["stage_origins"]) == {"sentiment", "event", "impact"}
        assert s["model_versions"]["impact"].startswith("placeholder")

    def test_search_finds_a_real_company(self, replay_client):
        hits = replay_client.get("/api/signals", params={"q": "Goldman"}).json()
        assert hits["total"] > 0


class TestRealSignalsDriveTheStressEngine:
    def pick(self, container, *, known: bool, min_impact: int = 7):
        for s in container.signals.list(min_impact=min_impact):
            if (s.entity.entity_id != UNKNOWN_ENTITY) == known:
                return s
        return None

    def test_real_signal_runs_a_completed_stress_test_that_reconciles(self, replay_client, replay_container):
        s = self.pick(replay_container, known=True)
        assert s is not None, "the pack must contain at least one triggering real signal on a known issuer"
        r = replay_client.post("/api/stress-test", json={"signal_id": s.id}).json()
        assert r["status"] == "COMPLETED"
        assert r["audit"]["data_origin"] == "REAL_SOURCE_PLACEHOLDER_NLP" and r["audit"]["mode"] == "REPLAY"
        total = sum(p["delta"] for p in r["positions"])
        assert abs(total - r["summary"]["pnl"]) < 1.0
        issuer_hits = [p for p in r["positions"] if p["entity_id"] == s.entity.entity_id and p["delta"] != 0]
        assert issuer_hits, "the signal's issuer must actually be in the synthetic book and be shocked"

    def test_replay_is_deterministic_across_app_instances(self, replay_client, replay_settings, replay_container):
        from fastapi.testclient import TestClient

        from eventshock.api.main import create_app

        s = self.pick(replay_container, known=True)
        a = replay_client.post("/api/stress-test", json={"signal_id": s.id}).json()
        b = TestClient(create_app(replay_settings)).post("/api/stress-test", json={"signal_id": s.id}).json()
        assert a == b and a["audit"]["calculated_at"].startswith("2026-10-01")

    def test_unresolved_real_signal_only_gets_market_wide_shocks(self, replay_client, replay_container):
        s = self.pick(replay_container, known=False, min_impact=1)
        assert s is not None and s.entity.entity_id == UNKNOWN_ENTITY
        r = replay_client.post("/api/stress-test", json={"signal_id": s.id, "force": True}).json()
        assert r["status"] == "COMPLETED"
        assert all(sh["scope"] == "MARKET" or not sh["applicable"] for sh in r["shocks"])


def test_demo_profile_still_serves_the_golden_fixtures(client):
    assert client.get("/api/signals/sig_0001").status_code == 200
