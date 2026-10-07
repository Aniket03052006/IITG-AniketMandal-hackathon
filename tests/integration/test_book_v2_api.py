"""Wholesale Book v2 served as a read-only preset: it is addressable wherever a portfolio id is, never listed among the user's portfolios,
and a stress run on it is an ordinary deterministic run that uses the Stage 13 mechanics. The default book is untouched."""

from __future__ import annotations

import pytest

BOOK = "pf_wholesale_v2"


@pytest.fixture(scope="module")
def sid(replay_client) -> str:
    """A company-scope event with the highest severity: it triggers the stress test and reaches the book's issuers."""
    rows = [s for s in replay_client.get("/api/signals").json()["items"] if s["scope_level"] == "COMPANY" and s["severity_score"] is not None]
    return sorted(rows, key=lambda s: (-s["severity_score"], s["id"]))[0]["id"]


def stress(client, sid, pid=None):  # noqa: ANN001, ANN201
    body = {"signal_id": sid, "force": True} | ({"portfolio_id": pid} if pid else {})
    return client.post("/api/stress-test", json=body).json()


def test_the_preset_is_listed_apart_from_the_users_portfolios(replay_client):
    presets = replay_client.get("/api/portfolios/presets").json()
    assert [p["id"] for p in presets] == [BOOK] and presets[0]["kind"] == "PRESET" and presets[0]["holding_count"] > 100
    assert all(p["kind"] != "PRESET" for p in replay_client.get("/api/portfolios").json())
    assert replay_client.get(f"/api/portfolios/{BOOK}").json()["kind"] == "PRESET"
    assert replay_client.delete(f"/api/portfolios/{BOOK}").status_code == 404                        # read-only: it is not a stored portfolio


def test_summary_and_exposure_name_it_a_synthetic_preset(replay_client):
    s = replay_client.get("/api/portfolio/summary", params={"portfolio_id": BOOK}).json()
    assert s["kind"] == "PRESET" and s["synthetic"] is True and s["portfolio_id"] == BOOK
    assert replay_client.get(f"/api/portfolios/{BOOK}/exposure").json()["kind"] == "PRESET"
    default = replay_client.get("/api/portfolio/summary").json()
    assert default["kind"] == "DEFAULT" and s["asset_count"] == default["asset_count"] + 5      # the default book plus the government and cash sleeves


def test_the_assets_carry_the_new_mechanics(replay_client):
    assets = replay_client.get("/api/portfolio/assets", params={"portfolio_id": BOOK}).json()
    kinds = {a["asset_type"] for a in assets}
    assert {"EQUITY", "BOND", "LOAN", "DERIVATIVE", "CASH"} <= kinds
    assert any("convexity" in a for a in assets if a["asset_type"] == "BOND") and any("spread_passthrough" in a for a in assets if a["asset_type"] == "LOAN")
    assert any("counterparty_pd" in a for a in assets if a["asset_type"] == "DERIVATIVE") and any(a.get("currency") for a in assets)
    default = replay_client.get("/api/portfolio/assets").json()
    assert not any({"convexity", "gamma", "rating"} & a.keys() for a in default)                 # the default book carries none of it


def test_a_stress_run_on_the_preset_is_deterministic_and_reconciles(replay_client, sid):
    a, b = stress(replay_client, sid, BOOK), stress(replay_client, sid, BOOK)
    assert a["status"] == "COMPLETED" and a["run_id"] == b["run_id"] and a["audit"]["portfolio_id"] == BOOK
    assert a["summary"]["pnl"] == b["summary"]["pnl"] and a["summary"]["baseline_value"] != stress(replay_client, sid)["summary"]["baseline_value"]
    assert sum(p["delta"] for p in a["positions"]) == pytest.approx(a["summary"]["pnl"], abs=0.01)
    for p in a["positions"]:
        assert sum(p["by_factor"].values()) == pytest.approx(p["delta"], abs=0.01), p["asset_id"]


def test_the_default_run_does_not_depend_on_the_preset_existing(replay_client, sid):
    before = stress(replay_client, sid)
    stress(replay_client, sid, BOOK)
    after = stress(replay_client, sid)
    assert before["run_id"] == after["run_id"] and before["summary"] == after["summary"]


def test_an_unknown_id_is_still_404(replay_client, sid):
    assert replay_client.get("/api/portfolio/summary", params={"portfolio_id": "pf_nope"}).status_code == 404
