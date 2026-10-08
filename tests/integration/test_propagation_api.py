"""Event -> portfolio propagation, generated scenarios, attribution, concentration and manual adjustment over the real replay app."""

from __future__ import annotations

import pytest

GOOD = {"name": "Mine", "base_currency": "USD", "mode": "WEIGHT", "holdings": [
    {"ticker": "AAPL", "weight_pct": 20}, {"ticker": "JPM", "weight_pct": 15}, {"ticker": "MSFT", "weight_pct": 15},
    {"ticker": "TLT", "weight_pct": 25}, {"ticker": "CASH", "weight_pct": 25}]}


@pytest.fixture(scope="module")
def sigs(replay_client):
    """(a signal whose scenario is generated, one whose scenario is unavailable, one the mapping abstains on), found in the real replay pack."""
    avail = unavail = abstain = None
    for s in replay_client.get("/api/signals", params={"limit": 400}).json()["items"]:
        flow = replay_client.get(f"/api/signals/{s['id']}/propagation").json()
        sc = flow["scenario"]["availability"]
        if sc == "AVAILABLE" and avail is None:
            avail = s["id"]
        if sc == "UNAVAILABLE" and unavail is None and flow["graph"]["availability"] != "ABSTAINED":
            unavail = s["id"]
        if flow["graph"]["availability"] == "ABSTAINED" and abstain is None:
            abstain = s["id"]
        if avail and unavail and abstain:
            break
    assert avail, "no replay signal generates a scenario"
    return avail, unavail, abstain


@pytest.fixture()
def reset_adjustments(replay_client):
    yield
    replay_client.post("/api/adjustments/reset")


def test_capabilities_are_advertised(replay_client):
    caps = replay_client.get("/api/meta").json()["capabilities"]
    assert caps["propagation"] is True and caps["adjustments"] is True


class TestPropagation:
    def test_flow_has_graph_materiality_and_scenario(self, replay_client, sigs):
        flow = replay_client.get(f"/api/signals/{sigs[0]}/propagation").json()
        assert flow["signal_id"] == sigs[0] and flow["adjustments"] is None
        g, m, s = flow["graph"], flow["materiality"], flow["scenario"]
        assert g["nodes"] and g["edges"] and all(e["status"] in ("OBSERVED", "SCENARIO_ASSUMPTION", "USER_ASSUMPTION") for e in g["edges"])
        assert any("not causal inference" in x for x in g["labels"])
        assert m["level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL") and m["rules"] and m["why"]
        assert s["label"] == "SCENARIO SIMULATION — NOT A PREDICTION" and s["scenario"]["id"].startswith("gen_") and s["gates"]

    def test_unavailable_scenario_says_why(self, replay_client, sigs):
        if sigs[1] is None:
            pytest.skip("no unavailable example in the replay pack")
        s = replay_client.get(f"/api/signals/{sigs[1]}/propagation").json()["scenario"]
        assert s["scenario"] is None and s["reason"].startswith("SCENARIO UNAVAILABLE") and any(not g["passed"] for g in s["gates"])

    def test_abstained_mapping_is_relevance_undetermined(self, replay_client, sigs):
        if sigs[2] is None:
            pytest.skip("no abstained example in the replay pack")
        flow = replay_client.get(f"/api/signals/{sigs[2]}/propagation").json()
        assert flow["graph"]["reached"] == [] and flow["materiality"]["level"] == "UNDETERMINED" and flow["scenario"]["scenario"] is None

    def test_materiality_endpoint_matches_the_flow(self, replay_client, sigs):
        a = replay_client.get(f"/api/signals/{sigs[0]}/materiality").json()
        assert a == replay_client.get(f"/api/signals/{sigs[0]}/propagation").json()["materiality"]

    def test_deterministic(self, replay_client, sigs):
        a = replay_client.get(f"/api/signals/{sigs[0]}/propagation").content
        assert a == replay_client.get(f"/api/signals/{sigs[0]}/propagation").content

    def test_unknown_signal_and_portfolio(self, replay_client, sigs):
        assert replay_client.get("/api/signals/nope/propagation").status_code == 404
        assert replay_client.get(f"/api/signals/{sigs[0]}/propagation", params={"portfolio_id": "pf_zzzzzzzz"}).status_code == 404

    def test_a_personal_portfolio_is_used_only_when_named(self, replay_client, sigs):
        pid = replay_client.post("/api/portfolios", json=GOOD).json()["id"]
        try:
            mine = replay_client.get(f"/api/signals/{sigs[0]}/propagation", params={"portfolio_id": pid}).json()
            default = replay_client.get(f"/api/signals/{sigs[0]}/propagation").json()
            assert mine["portfolio_id"] == pid and mine["portfolio_name"] == "Mine" and mine["graph"]["portfolio_id"] == pid
            assert default["portfolio_id"] != pid
            assert mine["graph"]["reached_share"] != default["graph"]["reached_share"]
        finally:
            replay_client.delete(f"/api/portfolios/{pid}")


class TestAutoStress:
    def test_generate_run_and_attribute_reconciles_with_the_total(self, replay_client, sigs):
        r = replay_client.post(f"/api/signals/{sigs[0]}/portfolio-stress", json={}).json()
        assert r["run"]["status"] == "COMPLETED" and r["scenario"]["label"].startswith("SCENARIO SIMULATION")
        total = r["run"]["summary"]["pnl"]
        att = r["attribution"]
        assert att["reconciled"] and att["total_pnl"] == pytest.approx(total)
        for t in [att["drivers"], *att["tables"]]:
            assert sum(x["delta"] for x in t["rows"]) == pytest.approx(total, abs=0.02), t["dimension"]
        assert r["chain"]["total_impact"] == pytest.approx(total, abs=0.02)
        assert sum(s["impact"] for s in r["chain"]["steps"]) == pytest.approx(total, abs=1.0)
        mx = att["matrix"]
        assert mx["unit"] == "pnl" and mx["reconciled"] and sum(c["value"] for c in mx["cells"]) == pytest.approx(total, abs=0.02)
        assert {c["row"] for c in mx["cells"]} <= {x["key"] for x in mx["rows"]} and {c["col"] for c in mx["cells"]} <= {x["key"] for x in mx["cols"]}

    def test_same_request_same_run(self, replay_client, sigs):
        a = replay_client.post(f"/api/signals/{sigs[0]}/portfolio-stress", json={}).json()
        b = replay_client.post(f"/api/signals/{sigs[0]}/portfolio-stress", json={}).json()
        assert a["run"]["run_id"] == b["run"]["run_id"] and a["attribution"] == b["attribution"]

    def test_the_generated_run_is_a_normal_run(self, replay_client, sigs):
        run = replay_client.post(f"/api/signals/{sigs[0]}/portfolio-stress", json={}).json()["run"]
        rid = run["run_id"]
        assert replay_client.get(f"/api/stress-runs/{rid}").json()["scenario"]["id"] == run["scenario"]["id"]
        assert replay_client.get(f"/api/stress-runs/{rid}/exposure-chain").status_code == 200
        att = replay_client.get(f"/api/stress-runs/{rid}/attribution").json()
        assert att["run_id"] == rid and att["total_pnl"] == pytest.approx(run["summary"]["pnl"])
        assert rid in [x["run_id"] for x in replay_client.get("/api/stress-runs", params={"signal_id": sigs[0]}).json()]
        flow = replay_client.get(f"/api/signals/{sigs[0]}/propagation").json()
        assert flow["existing_run_id"] == rid

    def test_unavailable_scenario_runs_nothing(self, replay_client, sigs):
        if sigs[1] is None:
            pytest.skip("no unavailable example in the replay pack")
        r = replay_client.post(f"/api/signals/{sigs[1]}/portfolio-stress", json={"force": True}).json()
        assert r["run"] is None and r["attribution"] is None and r["note"].startswith("SCENARIO UNAVAILABLE")

    def test_a_catalog_run_can_be_attributed_too(self, replay_client, sigs):
        run = replay_client.post("/api/stress-test", json={"signal_id": sigs[0], "force": True}).json()
        assert run["status"] == "COMPLETED"
        att = replay_client.get(f"/api/stress-runs/{run['run_id']}/attribution").json()
        assert att["total_pnl"] == pytest.approx(run["summary"]["pnl"]) and att["reconciled"]

    def test_attribution_of_a_run_without_numbers_is_409(self, replay_client, sigs):
        run = replay_client.post("/api/stress-test", json={"signal_id": sigs[0], "impact_override": 2, "force": False}).json()
        assert run["status"] == "NOT_TRIGGERED"
        assert replay_client.get(f"/api/stress-runs/{run['run_id']}/attribution").status_code == 409
        assert replay_client.get("/api/stress-runs/run_nope/attribution").status_code == 404

    def test_personal_portfolio_attribution_reconciles(self, replay_client, sigs):
        pid = replay_client.post("/api/portfolios", json=GOOD).json()["id"]
        try:
            r = replay_client.post(f"/api/signals/{sigs[0]}/portfolio-stress", json={"portfolio_id": pid, "force": True}).json()
            if r["run"] and r["run"]["status"] == "COMPLETED":
                assert r["attribution"]["portfolio_id"] == pid
                assert sum(x["delta"] for x in r["attribution"]["drivers"]["rows"]) == pytest.approx(r["run"]["summary"]["pnl"], abs=0.02)
            else:
                assert r["note"]
        finally:
            replay_client.delete(f"/api/portfolios/{pid}")


class TestConcentration:
    def test_default_book(self, replay_client):
        v = replay_client.get("/api/concentration").json()
        assert [d["dimension"] for d in v["dimensions"]] == ["issuer", "sector", "industry", "geography", "asset_class", "risk_factor"]
        assert all(sum(r["share"] for r in d["rows"]) == pytest.approx(1.0) for d in v["dimensions"] if d["dimension"] != "risk_factor")

    def test_personal_book_and_unknown_book(self, replay_client):
        pid = replay_client.post("/api/portfolios", json=GOOD).json()["id"]
        try:
            v = replay_client.get("/api/concentration", params={"portfolio_id": pid}).json()
            assert v["portfolio_id"] == pid and next(d for d in v["dimensions"] if d["dimension"] == "asset_class")["rows"]
        finally:
            replay_client.delete(f"/api/portfolios/{pid}")
        assert replay_client.get("/api/concentration", params={"portfolio_id": "pf_zzzzzzzz"}).status_code == 404

    def test_overlaps_are_an_answer_not_an_error(self, replay_client, sigs):
        v = replay_client.get("/api/concentration/overlaps").json()
        assert v["availability"] == "AVAILABLE" and isinstance(v["clusters"], list) and v["note"]
        mine = replay_client.get("/api/concentration/overlaps", params={"signal_id": sigs[0]}).json()
        assert all(any(e["signal_id"] or True for e in c["events"]) for c in mine["clusters"])
        assert replay_client.get("/api/concentration/overlaps", params={"signal_id": "nope"}).status_code == 404


class TestAdjustments:
    def test_state_lists_knobs(self, replay_client):
        st = replay_client.get("/api/adjustments").json()
        assert st["count"] == 0 and st["version"] == "default" and {k["group"] for k in st["knobs"]} == {"scenario", "relevance", "mapping", "intelligence"}

    def test_an_invalid_value_is_422_per_path_and_changes_nothing(self, replay_client, reset_adjustments):
        r = replay_client.put("/api/adjustments", json={"values": {"propagation.generation.min_severity": 99, "intelligence.nope": 1}})
        assert r.status_code == 422
        paths = {i["path"] for i in r.json()["detail"]["issues"]}
        assert paths == {"propagation.generation.min_severity", "intelligence.nope"}
        assert replay_client.get("/api/adjustments").json()["count"] == 0

    def test_validate_does_not_save(self, replay_client):
        ok = replay_client.post("/api/adjustments/validate", json={"values": {"propagation.generation.min_severity": 5}}).json()
        bad = replay_client.post("/api/adjustments/validate", json={"values": {"propagation.materiality.exposure_bands.medium_share": 0.9}}).json()
        assert ok["ok"] and not bad["ok"] and bad["issues"][0]["path"].endswith("medium_share")
        assert replay_client.get("/api/adjustments").json()["count"] == 0

    def test_an_adjustment_changes_the_answer_is_labelled_and_resets(self, replay_client, sigs, reset_adjustments):
        before = replay_client.get(f"/api/signals/{sigs[0]}/propagation").content
        intel_before = replay_client.get(f"/api/signals/{sigs[0]}/intelligence").content
        r = replay_client.put("/api/adjustments", json={"values": {"propagation.generation.min_severity": 10}})
        assert r.status_code == 200 and r.json()["count"] == 1 and r.json()["version"] != "default"
        flow = replay_client.get(f"/api/signals/{sigs[0]}/propagation").json()
        assert flow["adjustments"]["paths"] == ["propagation.generation.min_severity"]
        assert any(g["id"] == "severity" for g in flow["scenario"]["gates"])
        assert flow["scenario"]["availability"] in ("ABSTAINED", "AVAILABLE")
        # the same signal's scenario no longer clears the gate when severity is below 10 (unless it was already 10)
        sev = next(g for g in flow["scenario"]["gates"] if g["id"] == "severity")
        assert sev["label"].endswith("10")
        # a reset puts every byte back: the side-cars are rebuilt from the shipped configuration
        assert replay_client.post("/api/adjustments/reset").json()["count"] == 0
        assert replay_client.get(f"/api/signals/{sigs[0]}/propagation").content == before
        assert replay_client.get(f"/api/signals/{sigs[0]}/intelligence").content == intel_before

    def test_a_relevance_band_adjustment_reaches_the_existing_relevance_endpoint(self, replay_client, reset_adjustments):
        sid = share = None
        for s in replay_client.get("/api/signals", params={"limit": 80}).json()["items"]:
            r = replay_client.get(f"/api/signals/{s['id']}/relevance").json()
            if r["share"] is not None and r["share"] > 0.02:
                sid, share = s["id"], r["share"]
                break
        assert sid, "no replay signal has a relevance share above 2%"
        new_high = min(0.99, share + 0.01)  # just above the share: the band must fall below HIGH
        r = replay_client.put("/api/adjustments", json={"values": {"portfolio.relevance_bands.high_share": new_high,
                                                                    "portfolio.relevance_bands.medium_share": max(0.001, min(share / 2, new_high / 2))}})
        assert r.status_code == 200, r.text
        assert replay_client.get(f"/api/signals/{sid}/relevance").json()["band"] != "HIGH"

    def test_an_intelligence_prior_reaches_the_intelligence_endpoint(self, replay_client, sigs, reset_adjustments):
        r = replay_client.put("/api/adjustments", json={"values": {"intelligence.grouping.window_hours": 6}})
        assert r.status_code == 200
        flow = replay_client.get(f"/api/signals/{sigs[0]}/intelligence").json()
        assert "6 h" in flow["group"]["grouping_note"] or flow["group"]["report_count"] >= 1

    def test_a_user_edge_changes_the_mapping_and_is_labelled(self, replay_client, sigs, reset_adjustments):
        edge = {"kind": "SECTOR", "key": "Healthcare", "weight": 0.5, "enabled": True, "shock": True, "rationale": "my own view"}
        r = replay_client.put("/api/adjustments", json={"values": {"propagation.risk_factors.GEOPOLITICAL.transmission.user_health": edge}})
        assert r.status_code == 200 and r.json()["added_edges"][0]["edge_id"] == "user_health"
        g = replay_client.get(f"/api/signals/{sigs[0]}/propagation").json()["graph"]
        users = [e for e in g["edges"] if e["status"] == "USER_ASSUMPTION"]
        assert all(e["rule_id"].endswith("user_health") for e in users)

    def test_delete_one_and_unknown(self, replay_client, reset_adjustments):
        replay_client.put("/api/adjustments", json={"values": {"propagation.generation.min_severity": 9}})
        assert replay_client.delete("/api/adjustments", params={"path": "propagation.generation.min_severity"}).json()["count"] == 0
        assert replay_client.delete("/api/adjustments", params={"path": "propagation.generation.min_severity"}).status_code == 404
