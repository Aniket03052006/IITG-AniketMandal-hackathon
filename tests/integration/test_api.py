from __future__ import annotations

import pytest


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_meta_declares_demo_provenance(client):
    m = client.get("/api/meta").json()
    assert m["mode"] == "REPLAY" and m["data_origin"] == "DEMO_FIXTURE"
    assert m["trigger_threshold"] == 7
    assert len(m["taxonomy"]) == 8
    assert any("fixture" in n.lower() for n in m["notices"])


class TestSignals:
    def test_feed_is_newest_first(self, client):
        items = client.get("/api/signals").json()["items"]
        times = [i["published_at"] for i in items]
        assert times == sorted(times, reverse=True)

    def test_feed_row_contract(self, client):
        row = client.get("/api/signals").json()["items"][0]
        assert {"id", "headline", "source", "source_type", "entity_id", "category",
                "sentiment_score", "impact_score", "status", "source_count"} <= row.keys()

    def test_min_impact_filter(self, client):
        data = client.get("/api/signals", params={"min_impact": 7}).json()
        assert data["total"] == len(data["items"]) >= 4
        assert all(i["impact_score"] >= 7 for i in data["items"])

    def test_category_filter(self, client):
        items = client.get("/api/signals", params={"category": "CREDIT_FUNDING"}).json()["items"]
        assert items and all(i["category"] == "CREDIT_FUNDING" for i in items)

    def test_source_type_filter(self, client):
        items = client.get("/api/signals", params={"source_type": "SOCIAL"}).json()["items"]
        assert items and all(i["source_type"] == "SOCIAL" for i in items)

    def test_text_search(self, client):
        items = client.get("/api/signals", params={"q": "meridian"}).json()["items"]
        assert items and all("meridian" in (i["headline"] + (i["entity_name"] or "")).lower() for i in items)

    @pytest.mark.parametrize("params", [{"min_impact": 0}, {"min_impact": 11}, {"category": "NOPE"}])
    def test_invalid_filters_are_422(self, client, params):
        assert client.get("/api/signals", params=params).status_code == 422

    def test_detail_contains_full_intelligence(self, client):
        s = client.get("/api/signals/sig_0001").json()
        assert s["impact"]["score"] == 9
        assert s["event"]["category"] == "CREDIT_FUNDING"
        assert len(s["event"]["probabilities"]) == 8
        assert s["evidence"]["source_count"] == 5 and s["evidence"]["corroborating"]
        assert s["data_origin"] == "DEMO_FIXTURE"
        assert s["model_versions"]["impact"]

    def test_partial_signal_has_null_impact(self, client):
        s = client.get("/api/signals/sig_0014").json()
        assert s["status"] == "PARTIAL" and s["impact"] is None and s["status_reason"]

    def test_unknown_signal_404(self, client):
        assert client.get("/api/signals/nope").status_code == 404


class TestPortfolio:
    def test_summary(self, client):
        s = client.get("/api/portfolio/summary").json()
        assert s["synthetic"] is True and s["asset_count"] >= 40 and s["total_value"] > 0

    def test_exposure_shares_sum_to_one(self, client):
        e = client.get("/api/portfolio/exposure").json()
        for key in ("by_asset_class", "by_sector", "by_entity", "by_geography"):
            assert sum(r["share"] for r in e[key]) == pytest.approx(1.0)

    def test_assets_listing(self, client):
        assets = client.get("/api/portfolio/assets").json()
        assert len(assets) == client.get("/api/portfolio/summary").json()["asset_count"]


class TestScenarios:
    def test_list_has_defaults_for_all_categories(self, client):
        data = client.get("/api/scenarios").json()
        assert len(data["default_by_category"]) == 8 and len(data["scenarios"]) >= 8
        assert all(s["illustrative"] for s in data["scenarios"])

    def test_detail_and_404(self, client):
        assert client.get("/api/scenarios/scn_macro_rates_shock").status_code == 200
        assert client.get("/api/scenarios/nope").status_code == 404


class TestStressEndpoint:
    def test_high_impact_signal_completes_with_attribution(self, client):
        r = client.post("/api/stress-test", json={"signal_id": "sig_0001"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "COMPLETED"
        s = body["summary"]
        assert s["stressed_value"] < s["baseline_value"] and s["pnl"] < 0
        assert s["stressed_value"] == pytest.approx(s["baseline_value"] + s["pnl"])
        assert body["scenario"]["illustrative"] is True
        assert body["contributions"]["top_positions"]
        assert body["audit"]["mode"] == "REPLAY" and body["audit"]["calculation"].startswith("deterministic")
        assert all(p["formula"] for p in body["positions"])

    def test_below_threshold_is_200_not_triggered(self, client):
        body = client.post("/api/stress-test", json={"signal_id": "sig_0012"}).json()
        assert body["status"] == "NOT_TRIGGERED" and body["summary"] is None

    def test_force_what_if_runs_low_impact_signal(self, client):
        body = client.post("/api/stress-test", json={"signal_id": "sig_0012", "force": True}).json()
        assert body["status"] == "COMPLETED" and body["audit"]["forced"] is True

    def test_partial_signal_is_unavailable(self, client):
        body = client.post("/api/stress-test", json={"signal_id": "sig_0014", "force": True}).json()
        assert body["status"] == "UNAVAILABLE" and body["summary"] is None

    def test_unknown_entity_macro_event_still_stresses_market_wide(self, client):
        body = client.post("/api/stress-test", json={"signal_id": "sig_0004"}).json()
        assert body["status"] == "COMPLETED"
        assert body["scenario"]["id"] == "scn_macro_rates_shock"

    def test_scenario_override(self, client):
        body = client.post("/api/stress-test", json={
            "signal_id": "sig_0001", "scenario_id": "scn_market_drawdown"}).json()
        assert body["scenario"]["id"] == "scn_market_drawdown"

    @pytest.mark.parametrize("payload", [
        {"signal_id": "nope"},
        {"signal_id": "sig_0001", "scenario_id": "nope"},
    ])
    def test_unknown_references_404(self, client, payload):
        assert client.post("/api/stress-test", json=payload).status_code == 404

    @pytest.mark.parametrize("payload", [
        {}, {"signal_id": "sig_0001", "impact_override": 11},
        {"signal_id": "sig_0001", "impact_override": 0}, {"signal_id": "sig_0001", "force": "maybe"},
    ])
    def test_bad_payloads_422(self, client, payload):
        assert client.post("/api/stress-test", json=payload).status_code == 422

    def test_run_is_retrievable(self, client):
        run = client.post("/api/stress-test", json={"signal_id": "sig_0002"}).json()
        again = client.get(f"/api/stress-runs/{run['run_id']}")
        assert again.status_code == 200 and again.json() == run
        assert client.get("/api/stress-runs/run_missing").status_code == 404

    def test_raising_impact_deepens_the_loss(self, client):
        lo = client.post("/api/stress-test", json={"signal_id": "sig_0003", "force": True,
                                                    "impact_override": 4}).json()
        hi = client.post("/api/stress-test", json={"signal_id": "sig_0003", "force": True,
                                                    "impact_override": 10}).json()
        assert hi["summary"]["pnl"] < lo["summary"]["pnl"] < 0
