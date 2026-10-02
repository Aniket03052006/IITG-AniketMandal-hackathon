"""The real-source replay profile end to end: pack -> pipeline -> API -> stress engine."""

from __future__ import annotations

from eventshock.domain import UNKNOWN_ENTITY, DataOrigin


class TestMetaAndReport:
    def test_meta_describes_the_replay_profile_honestly(self, replay_client):
        m = replay_client.get("/api/meta").json()
        assert m["profile"] == "replay" and m["data_origin"] == "REAL_SOURCE_MIXED_NLP"
        assert m["replay"]["snapshot_id"] and len(m["replay"]["output_digest"]) == 64
        assert any("trained models" in n and "event type" in n and "impact is a PLACEHOLDER" in n for n in m["notices"])
        so = m["replay"]["stage_origins"]
        assert so["sentiment"].startswith("MODEL") and so["event"].startswith("MODEL") and so["impact"] == "PLACEHOLDER"

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

    def test_download_log_lists_the_current_plan_and_counts_the_abandoned_one(self, replay_client, replay_container):
        r = replay_client.get("/api/pipeline/report").json()
        log = r["fetch_log"]
        plan = set(replay_container.snapshot.manifest.fetch_plan)
        assert log and {e["status"] for e in log} <= {"ok", "error"}
        for e in log:
            assert e["attempts"] >= 1 and (e["status"] == "ok" or e["last_error"])
            assert e["query"] in plan or e["query"].startswith("gkg:"), "a request of an abandoned plan must not be listed"
        assert r["superseded_requests"] > 0, "the abandoned first plan's failed requests are counted, not silently dropped"
        assert {e["query"] for e in log if e["query"] in plan} == plan, "every request of the current plan has a row"

    def test_no_pipeline_report_in_demo_profile(self, client):
        assert client.get("/api/pipeline/report").status_code == 404


class TestSignals:
    def test_two_source_types_and_no_fixture_origin(self, replay_client):
        items = replay_client.get("/api/signals").json()["items"]
        assert {i["source_type"] for i in items} == {"NEWS", "SOCIAL"}
        assert {i["data_origin"] for i in items} == {DataOrigin.REAL_SOURCE_MIXED_NLP.value}

    def test_signal_detail_carries_provenance(self, replay_client):
        sid = replay_client.get("/api/signals").json()["items"][0]["id"]
        s = replay_client.get(f"/api/signals/{sid}").json()
        p = s["provenance"]
        assert p["snapshot_id"] and p["record_ref"] and len(p["content_sha256"]) == 64
        assert p["dedup"]["member_count"] == s["evidence"]["source_count"]
        assert p["stage_origins"] == {"sentiment": "MODEL", "event": "MODEL", "impact": "PLACEHOLDER_RULES"}
        assert s["model_versions"]["impact"].startswith("placeholder") and s["model_versions"]["event"].startswith("tfidf-lr-event-v1+")
        e = p["event"]
        assert e["model_id"] == "tfidf-lr-event-v1" and len(e["artifact_sha256"]) == 64 and e["calibrated"] is True
        assert 0 <= e["confidence"] <= 1 and 0 <= e["no_event_probability"] <= 1 and isinstance(e["seen_in_training"], bool)
        assert s["event"]["status"] in {"CLASSIFIED", "NO_EVENT", "UNCERTAIN"}
        assert s["model_versions"]["sentiment"].startswith("tfidf-lr-v1+")
        a = p["sentiment"]
        assert a["model_id"] == "tfidf-lr-v1" and len(a["artifact_sha256"]) == 64 and a["calibrated"] is True
        assert 0 <= a["confidence"] <= 1 and isinstance(a["seen_in_training"], bool)
        snt = s["sentiment"]
        assert abs(snt["positive"] + snt["neutral"] + snt["negative"] - 1) < 1e-3 and -1 <= snt["score"] <= 1

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
        assert r["audit"]["data_origin"] == "REAL_SOURCE_MIXED_NLP" and r["audit"]["mode"] == "REPLAY"
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


class TestSentimentModelEndpoint:
    def test_card_is_served_with_results_and_limits(self, replay_client):
        c = replay_client.get("/api/models/sentiment").json()
        assert c["id"] == "tfidf-lr-v1" and len(c["artifact_sha256"]) == 64 and c["limitations"]
        sets = {e["id"]: e for e in c["evaluations"]}
        t = sets["tfn_test"]
        assert t["status"] == "ok" and t["model"]["n"] > 1000 and len(t["model"]["confusion"]) == 3
        assert t["model"]["macro_f1"] > t["baselines"]["placeholder_lexicon"]["macro_f1"]
        assert set(t["model"]["per_class"]) == {"negative", "neutral", "positive"}
        assert c["calibration"]["temperature"] > 0 and {x["selected"] for x in c["candidates"]} == {True, False}

    def test_card_matches_the_artifact_that_scored_the_signals(self, replay_client):
        sid = replay_client.get("/api/signals").json()["items"][0]["id"]
        sha = replay_client.get(f"/api/signals/{sid}").json()["provenance"]["sentiment"]["artifact_sha256"]
        assert replay_client.get("/api/models/sentiment").json()["artifact_sha256"] == sha

    def test_no_model_card_in_the_demo_profile(self, client):
        assert client.get("/api/models/sentiment").status_code == 404

    def test_pipeline_report_lists_unscorable_texts(self, replay_client):
        assert replay_client.get("/api/pipeline/report").json()["quarantine_by_code"].get("UNSCORABLE_TEXT", 0) > 0


class TestEventModelEndpoint:
    def test_card_is_served_with_results_reliability_and_limits(self, replay_client):
        c = replay_client.get("/api/models/event").json()
        assert c["id"] == "tfidf-lr-event-v1" and len(c["artifact_sha256"]) == 64 and c["limitations"]
        assert c["classes"][-1] == "NONE" and len(c["classes"]) == 9
        assert {r["label"] for r in c["class_reliability"]} == set(c["classes"][:-1])
        assert all(r["status"] in {"ok", "unreliable", "unmeasured"} and r["reason"] for r in c["class_reliability"])
        sets = {e["id"]: e for e in c["evaluations"]}
        assert {"dev_history", "gold_history", "replay_check"} <= set(sets)
        g = sets["gold_history"]
        assert g["status"] == "ok" and g["model"]["n"] > 200 and len(g["model"]["confusion"]) == 9
        assert g["model"]["macro_f1"] > g["baselines"]["placeholder_keywords"]["macro_f1"]
        assert g["model"]["served"]["detection"]["f1"] > g["baselines"]["placeholder_keywords"]["detection_f1"]
        assert c["acceptance"]["rule"] and isinstance(c["acceptance"]["met"], bool) and c["acceptance"]["checks"]
        assert c["abstention"]["commit_threshold"] == 0.5 and 0 < c["abstention"]["dev_coverage"] <= 1

    def test_card_matches_the_artifact_that_classified_the_signals(self, replay_client):
        sid = replay_client.get("/api/signals").json()["items"][0]["id"]
        sha = replay_client.get(f"/api/signals/{sid}").json()["provenance"]["event"]["artifact_sha256"]
        assert replay_client.get("/api/models/event").json()["artifact_sha256"] == sha

    def test_no_event_card_in_the_demo_profile(self, client):
        assert client.get("/api/models/event").status_code == 404


class TestEventStatusInTheFeed:
    def test_summaries_carry_the_status_and_the_filter_works(self, replay_client):
        allp = replay_client.get("/api/signals").json()
        assert {i["event_status"] for i in allp["items"]} == {"CLASSIFIED", "NO_EVENT", "UNCERTAIN"}
        for status in ("CLASSIFIED", "NO_EVENT", "UNCERTAIN"):
            part = replay_client.get("/api/signals", params={"event_status": status}).json()
            assert part["total"] > 0 and {i["event_status"] for i in part["items"]} == {status}
        assert replay_client.get("/api/signals", params={"event_status": "BOGUS"}).status_code == 422

    def test_a_category_filter_matches_only_findings_not_best_guesses(self, replay_client):
        part = replay_client.get("/api/signals", params={"category": "PRODUCT_OPERATIONS"}).json()
        assert part["total"] > 0 and all(i["event_status"] == "CLASSIFIED" and i["category"] == "PRODUCT_OPERATIONS" for i in part["items"])

    def test_non_events_have_no_impact_and_the_stress_engine_reports_them_unavailable(self, replay_client):
        item = replay_client.get("/api/signals", params={"event_status": "NO_EVENT"}).json()["items"][0]
        assert item["impact_score"] is None and item["status"] == "PARTIAL"
        r = replay_client.post("/api/stress-test", json={"signal_id": item["id"], "force": True}).json()
        assert r["status"] == "UNAVAILABLE"


class TestStressEngineIgnoresSentimentValues:
    def test_two_signals_that_differ_only_in_sentiment_give_identical_stress_results(self, replay_container):
        from eventshock.domain import SentimentResult
        from eventshock.services.stress_service import StressService
        from eventshock.store import InMemorySignalRepository

        s = next(x for x in replay_container.signals.list(min_impact=7) if x.entity.entity_id != UNKNOWN_ENTITY)
        flipped = s.model_copy(update={"id": "sig_flipped", "sentiment": SentimentResult(positive=0.0, neutral=0.0, negative=1.0, score=-1.0)})
        c = replay_container
        svc = StressService(InMemorySignalRepository([s, flipped], c.signals.as_of), c.portfolio, c.catalog, c.config)
        a, b = svc.run(s.id), svc.run(flipped.id)
        assert a.summary == b.summary and a.positions == b.positions and a.contributions == b.contributions


def test_demo_profile_still_serves_the_golden_fixtures(client):
    assert client.get("/api/signals/sig_0001").status_code == 200
