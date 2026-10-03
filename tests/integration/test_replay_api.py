"""The real-source replay profile end to end: pack -> pipeline -> API -> stress engine."""

from __future__ import annotations

from eventshock.domain import UNKNOWN_ENTITY, DataOrigin


class TestMetaAndReport:
    def test_meta_describes_the_replay_profile_honestly(self, replay_client):
        m = replay_client.get("/api/meta").json()
        assert m["profile"] == "replay" and m["data_origin"] == "REAL_SOURCE_MIXED_NLP"
        assert m["replay"]["snapshot_id"] and len(m["replay"]["output_digest"]) == 64
        assert any("trained models" in n and "event type" in n and "impact is a trained model" in n and "experimental" in n
                   and "PLACEHOLDER rule for any signal the model cannot score" in n for n in m["notices"])
        so = m["replay"]["stage_origins"]
        assert so["sentiment"].startswith("MODEL") and so["event"].startswith("MODEL") and so["impact"].startswith("MODEL (impact-v2")
        assert m["impact"]["mode"] == "MODEL" and m["impact"]["served_scopes"] == ["ISSUER", "MARKET"] and m["impact"]["reason"] is None
        assert set(m["impact"]["scopes"].values()) <= {"TRAINED", "CALIBRATED", "PRODUCTION"}

    def test_demo_profile_meta_is_unchanged(self, client):
        m = client.get("/api/meta").json()
        assert m["profile"] == "demo" and m["data_origin"] == "DEMO_FIXTURE" and m["replay"] is None and m["impact"] is None

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
        assert {k: p["stage_origins"][k] for k in ("sentiment", "event")} == {"sentiment": "MODEL", "event": "MODEL"}
        assert p["stage_origins"]["impact"] in {"MODEL", "PLACEHOLDER_RULES"}
        assert s["model_versions"]["event"].startswith("hybrid-event-v2+")
        e = p["event"]
        assert e["model_id"] == "hybrid-event-v2" and len(e["artifact_sha256"]) == 64 and e["calibrated"] is True
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
        assert c["id"] == "hybrid-event-v2" and len(c["artifact_sha256"]) == 64 and c["limitations"]
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


class TestImpactModel:
    def test_card_endpoint_matches_the_artifact_and_carries_the_evidence(self, replay_client, replay_container):
        card = replay_client.get("/api/models/impact").json()
        assert card["id"] == "impact-v2" and len(card["artifact_sha256"]) == 64
        assert card["artifact_sha256"] == replay_container.impact_card.artifact_sha256
        assert [s["scope"] for s in card["scopes"]] == ["ISSUER", "MARKET"]
        for sc in card["scopes"]:
            assert sc["lifecycle"] in {"TRAINED", "CALIBRATED", "PRODUCTION"} and sc["served"]
            assert sc["ladder"][0]["id"] == "R0-constant" and any(e["chosen"] for e in sc["ladder"])
            assert {r["id"] for r in sc["evaluations"]} >= {"oof", "val", "test", "val+test", "live"}
            assert [c["id"] for c in sc["acceptance"]["checks"]] == [f"C{i}" for i in range(1, 12)]
            if sc["lifecycle"] != "PRODUCTION":
                assert sc["acceptance"]["met"] is False and any(c["passed"] is not True for c in sc["acceptance"]["checks"])
        # the paired comparison with the model it replaces is on the card, including the scope where it is worse
        vs = {(v["scope"], v["set_id"]): v for v in card["vs_previous"]}
        assert vs[("ISSUER", "val+test")]["delta_mae"]["hi"] < 0 and vs[("MARKET", "val+test")]["delta_mae"]["lo"] > 0
        assert all(v["previous_id"] == "impact-v1" for v in vs.values())

    def test_no_impact_card_in_the_demo_profile(self, client):
        assert client.get("/api/models/impact").status_code == 404

    def test_a_model_scored_signal_carries_a_complete_audit_and_a_calibrated_estimate(self, replay_client):
        items = replay_client.get("/api/signals").json()["items"]
        scored = next(i for i in items if i["impact_origin"] == "MODEL")
        assert scored["impact_lifecycle"] in {"TRAINED", "CALIBRATED", "PRODUCTION"} and 1 <= scored["impact_score"] <= 10
        s = replay_client.get(f"/api/signals/{scored['id']}").json()
        a, i = s["provenance"]["impact"], s["impact"]
        assert a["feature_schema"] == "impact-features-v2" and a["calibrated"] and a["inputs"]
        assert i["scope"] == a["scope"] and i["predicted_severity"] >= 0 and i["drivers"][0]["feature"] == "baseline"
        assert i["comparable_events"] > 0 and 0 <= i["p_extreme"] <= 1 and i["score_low"] <= i["score_high"]
        assert "impact-v2" in s["model_versions"]["impact"]

    def test_placeholder_signals_say_so_and_carry_no_model_fields(self, replay_client):
        items = replay_client.get("/api/signals").json()["items"]
        ph = next(i for i in items if i["impact_origin"] == "PLACEHOLDER" and i["impact_score"] is not None)
        s = replay_client.get(f"/api/signals/{ph['id']}").json()
        assert s["provenance"]["impact"] is None and s["provenance"]["impact_note"]
        assert s["impact"]["predicted_severity"] is None and s["model_versions"]["impact"].startswith("placeholder")
        assert ph["impact_lifecycle"] is None

    def test_a_stress_run_records_which_stage_produced_the_trigger(self, replay_client):
        items = replay_client.get("/api/signals").json()["items"]
        for origin, lifecycle in (("MODEL", True), ("PLACEHOLDER", False)):
            it = next(i for i in items if i["impact_origin"] == origin and i["impact_score"] is not None)
            r = replay_client.post("/api/stress-test", json={"signal_id": it["id"], "force": True}).json()
            assert r["audit"]["impact_origin"] == origin and (r["audit"]["impact_lifecycle"] is not None) is lifecycle


class TestImpactDegradesHonestly:
    def test_a_missing_artifact_serves_the_labelled_heuristic_and_says_why(self, tmp_path):
        from eventshock.api.deps import build_container
        from eventshock.config import Settings

        c = build_container(Settings(profile="replay", impact_model_dir=tmp_path / "nope"))
        assert c.impact_card is None and c.impact_status.mode == "PLACEHOLDER" and "make train-impact" in c.impact_status.reason
        sigs = c.signals.list()
        assert all(s.provenance.impact is None and s.model_versions.impact in (None, "") or s.model_versions.impact.startswith("placeholder")
                   for s in sigs)
        assert all(s.provenance.stage_origins["impact"] == "PLACEHOLDER_RULES" for s in sigs)

    def test_a_tampered_artifact_stops_start_up(self, tmp_path):
        import shutil

        from eventshock.api.deps import build_container
        from eventshock.config import REPO_ROOT, ConfigError, Settings

        d = tmp_path / "impact"
        shutil.copytree(REPO_ROOT / "models" / "impact" / "impact-v1", d)
        with (d / "model.joblib").open("ab") as fh:
            fh.write(b"x")
        import pytest

        with pytest.raises(ConfigError, match="does not match its model card"):
            build_container(Settings(profile="replay", impact_model_dir=d))


class TestImpactV2Serving:
    """impact-v2 reads an event calendar: the loader must refuse to run without one or with a modified one, and a missing v2 artifact falls back to v1, labelled."""

    @staticmethod
    def _calendar():
        from eventshock.config import REPO_ROOT
        from eventshock.pipeline.event_context import EventCalendar

        return EventCalendar.load(REPO_ROOT / "data" / "events", REPO_ROOT / "configs" / "sec_items.yaml")

    def test_a_model_that_reads_the_calendar_refuses_to_load_without_one(self):
        import pytest

        from eventshock.config import REPO_ROOT, ConfigError
        from eventshock.pipeline.impact_model import ImpactModel

        with pytest.raises(ConfigError, match="reads the event calendar"):
            ImpactModel.load(REPO_ROOT / "models" / "impact" / "impact-v2", 0.8, None)

    def test_a_modified_calendar_is_refused_by_hash(self):
        import pytest

        from eventshock.config import REPO_ROOT, ConfigError
        from eventshock.pipeline.impact_model import ImpactModel

        cal = self._calendar()
        cal.digests = {**cal.digests, "sec_filings": "0" * 64}
        with pytest.raises(ConfigError, match="do not match the hashes pinned"):
            ImpactModel.load(REPO_ROOT / "models" / "impact" / "impact-v2", 0.8, cal)

    def test_the_committed_calendar_matches_the_hashes_pinned_in_the_card(self, replay_container):
        cal = self._calendar()
        assert replay_container.impact_card.dataset["calendar"] == cal.digests

    def test_the_served_model_uses_calendar_features_and_labels_their_availability(self, replay_client):
        items = replay_client.get("/api/signals").json()["items"]
        names = set()
        for it in [i for i in items if i["impact_origin"] == "MODEL"][:60]:
            s = replay_client.get(f"/api/signals/{it['id']}").json()
            names |= {d["feature"] for d in s["impact"]["drivers"]}
            if s["provenance"]["impact"]["scope"] == "ISSUER":
                assert any(k.startswith("earn_") for k in s["provenance"]["impact"]["inputs"]), "issuer inputs must include the calendar block"
        assert names  # drivers are present on every scored signal

    def test_a_missing_served_artifact_falls_back_to_the_v1_reference(self, tmp_path, monkeypatch):
        from eventshock.api import deps
        from eventshock.config import Settings
        from eventshock.pipeline.config import load_impact_model_config

        real = load_impact_model_config

        def patched(config_dir):
            return real(config_dir).model_copy(update={"served_model_dir": str(tmp_path / "missing-v2")})

        monkeypatch.setattr(deps, "load_impact_model_config", patched)
        c = deps.build_container(Settings(profile="replay"))
        assert c.impact_card is not None and c.impact_card.id == "impact-v1"


class TestEvidenceEndpoint:
    def test_three_stage_statuses_use_the_product_vocabulary_and_nothing_is_called_validated_without_its_bar(self, replay_client):
        b = replay_client.get("/api/evidence").json()
        stages = {s["stage"]: s for s in b["stages"]}
        assert set(stages) == {"sentiment", "event", "impact"}
        assert {s["kind"] for s in stages.values()} <= {"placeholder", "experimental", "validated"}
        assert stages["impact"]["kind"] == "experimental" and stages["impact"]["failed"]          # the served impact-v2 card still fails C5 and C7 (and C10, C11 on the market scope)
        assert stages["event"]["kind"] == "experimental" and stages["event"]["failed"]
        # the hybrid passes its scored bars but has no independent set: the sentence must say exactly that, not "did NOT meet its bar on the gold set"
        assert "passed 3 of 4 checks" in stages["event"]["summary"] and "took no part in adopting" in stages["event"]["summary"]

    def test_feature_table_marks_class_c_as_refused_and_calendar_features_by_availability(self, replay_client):
        feats = {f["name"]: f for f in replay_client.get("/api/evidence").json()["features"]}
        for banned in ("eps_surprise", "filing_at_or_after", "source_count", "ticker"):
            assert feats[banned]["allowed"] is False
        assert feats["earn_window"]["availability"] == "a" and feats["f8k_earnings_24h"]["availability"] == "b" and feats["f_sigma_60"]["allowed"]
        assert all(f["why"] for f in feats.values())

    def test_missing_evidence_files_are_reported_as_unavailable_with_the_command_that_makes_them(self, replay_client):
        b = replay_client.get("/api/evidence").json()
        for view in (b["study"], b["representation"]):
            if not view["available"]:
                assert view["command"].startswith("make ")

    def test_no_evidence_in_the_demo_profile(self, client):
        assert client.get("/api/evidence").status_code == 404
