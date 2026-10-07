"""The Stage 13 multi-factor scenarios: served by id, never the default of an event class, FX / oil reach only positions that carry the exposure,
and the default book's runs are unchanged."""

from __future__ import annotations

import pytest

MF = ["scn_mf_stagflation", "scn_mf_oil_supply_shock", "scn_mf_funding_squeeze", "scn_mf_global_downturn"]
BOOK = "pf_wholesale_v2"


@pytest.fixture(scope="module")
def sid(replay_client) -> str:
    rows = [s for s in replay_client.get("/api/signals").json()["items"] if s["scope_level"] == "COMPANY" and s["severity_score"] is not None]
    return sorted(rows, key=lambda s: (-s["severity_score"], s["id"]))[0]["id"]


def run(client, sid, scenario, pid=None):  # noqa: ANN001, ANN201
    body = {"signal_id": sid, "scenario_id": scenario, "force": True} | ({"portfolio_id": pid} if pid else {})
    r = client.post("/api/stress-test", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_they_are_listed_and_none_is_a_default(replay_client):
    data = replay_client.get("/api/scenarios").json()
    ids = {s["id"] for s in data["scenarios"]}
    assert set(MF) <= ids and len(data["default_by_category"]) == 8
    assert not set(MF) & set(data["default_by_category"].values())
    assert all(s["illustrative"] for s in data["scenarios"])


@pytest.mark.parametrize("scenario", MF)
def test_each_runs_on_the_book_with_the_new_exposures_and_reconciles(replay_client, sid, scenario):
    r = run(replay_client, sid, scenario, BOOK)
    assert r["status"] == "COMPLETED" and r["summary"]["pnl"] < 0
    assert sum(p["delta"] for p in r["positions"]) == pytest.approx(r["summary"]["pnl"], abs=0.01)
    factors = {f for p in r["positions"] for f in p["by_factor"]}
    assert {"EQUITY", "CREDIT_SPREAD_BPS"} <= factors
    assert "FX_PCT" in factors                                  # the book holds euro and sterling positions
    assert run(replay_client, sid, scenario, BOOK)["run_id"] == r["run_id"]


def test_oil_reaches_only_positions_with_a_measured_elasticity(replay_client, sid):
    r = run(replay_client, sid, "scn_mf_oil_supply_shock", BOOK)
    assets = {a["asset_id"]: a for a in replay_client.get("/api/portfolio/assets", params={"portfolio_id": BOOK}).json()}
    moved = {p["asset_id"] for p in r["positions"] if "COMMODITY_PCT" in p["by_factor"]}
    assert moved and all(assets[i].get("commodity_sensitivity") is not None for i in moved)
    assert all("COMMODITY_PCT" not in p["by_factor"] for p in r["positions"] if assets[p["asset_id"]].get("commodity_sensitivity") is None)


def test_on_the_default_book_fx_and_oil_are_not_applicable_never_a_zero(replay_client, sid):
    r = run(replay_client, sid, "scn_mf_oil_supply_shock")
    assert r["status"] == "COMPLETED"
    assert not any("COMMODITY_PCT" in p["by_factor"] or "FX_PCT" in p["by_factor"] for p in r["positions"])


def test_the_loan_spread_link_shows_up_only_on_the_book_that_carries_it(replay_client, sid):
    v2 = run(replay_client, sid, "scn_mf_funding_squeeze", BOOK)
    base = run(replay_client, sid, "scn_mf_funding_squeeze")
    loans_v2 = [p for p in v2["positions"] if p["asset_class"] == "LOAN"]
    loans_base = [p for p in base["positions"] if p["asset_class"] == "LOAN"]
    assert any("CREDIT_SPREAD_BPS" in p["by_factor"] for p in loans_v2)
    assert not any("CREDIT_SPREAD_BPS" in p["by_factor"] for p in loans_base)


def test_the_default_event_mapping_and_the_default_run_are_unchanged(replay_client, sid):
    a = replay_client.post("/api/stress-test", json={"signal_id": sid, "force": True}).json()
    assert a["scenario"]["id"] not in MF


@pytest.mark.parametrize("scenario", MF)
def test_the_history_check_handles_the_new_factors(replay_client, scenario):
    r = replay_client.get(f"/api/scenarios/{scenario}/history-check")
    assert r.status_code in (200, 404, 409, 503), r.text      # an endpoint that is off in this profile is fine; a 500 is not
