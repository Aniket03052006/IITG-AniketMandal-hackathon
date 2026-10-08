"""Personal portfolios over the real replay app: optional, persistent, and wired through relevance, stress, the exposure chain and comparison."""

from __future__ import annotations

import pytest

GOOD = {"name": "Mine", "base_currency": "USD", "mode": "WEIGHT", "holdings": [
    {"ticker": "AAPL", "weight_pct": 20}, {"ticker": "JPM", "weight_pct": 15}, {"ticker": "MSFT", "weight_pct": 15},
    {"ticker": "TLT", "weight_pct": 25}, {"ticker": "CASH", "weight_pct": 25}]}
CASH_ONLY = {"name": "Cash only", "holdings": [{"ticker": "CASH", "weight_pct": 100}]}
ALL_EQUITY = {"name": "All SPY", "holdings": [{"ticker": "SPY", "weight_pct": 100}]}


@pytest.fixture()
def made(replay_client):
    ids: list[str] = []

    def make(body):
        r = replay_client.post("/api/portfolios", json=body)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
        return r.json()["id"]

    yield make
    for i in ids:
        replay_client.delete(f"/api/portfolios/{i}")


def pick(client, level):
    items = client.get("/api/signals").json()["items"]
    rows = [s for s in items if s["scope_level"] == level and s["severity_score"] is not None]
    assert rows, level
    return sorted(rows, key=lambda s: (-(s["severity_score"] or 0), s["id"]))[0]["id"]


def stress(client, sid, pid=None, **kw):
    body = {"signal_id": sid, "force": True, **kw}
    if pid is not None:
        body["portfolio_id"] = pid
    return client.post("/api/stress-test", json=body)


def test_the_default_is_always_listed_first_and_read_only(replay_client) -> None:
    items = replay_client.get("/api/portfolios").json()
    assert items[0]["id"] == "default" and items[0]["kind"] == "DEFAULT"
    v = replay_client.get("/api/portfolios/default").json()
    assert v["kind"] == "DEFAULT" and v["stored"] is None
    assert replay_client.put("/api/portfolios/default", json=GOOD).status_code == 405
    assert replay_client.delete("/api/portfolios/default").status_code == 405
    assert replay_client.post("/api/portfolios/default/duplicate").status_code == 405
    assert replay_client.get("/api/meta").json()["capabilities"]["custom_portfolios"] is True


def test_create_view_edit_duplicate_delete(replay_client) -> None:
    created = replay_client.post("/api/portfolios", json=GOOD)
    assert created.status_code == 201
    v = created.json()
    pid = v["id"]
    assert v["kind"] == "USER" and v["resolved"]["ok"] and len(v["resolved"]["holdings"]) == 5
    assert [i["id"] for i in replay_client.get("/api/portfolios").json()][:2] == ["default", pid]
    edited = {**GOOD, "name": "Renamed", "holdings": [{"ticker": "AAPL", "weight_pct": 100}]}
    assert replay_client.put(f"/api/portfolios/{pid}", json=edited).json()["stored"]["name"] == "Renamed"
    dup = replay_client.post(f"/api/portfolios/{pid}/duplicate")
    assert dup.status_code == 201 and dup.json()["stored"]["name"] == "Renamed (copy)"
    assert replay_client.delete(f"/api/portfolios/{pid}").status_code == 204
    assert replay_client.delete(f"/api/portfolios/{dup.json()['id']}").status_code == 204
    assert replay_client.get(f"/api/portfolios/{pid}").status_code == 404


def test_invalid_input_is_a_422_that_names_the_problem_and_saves_nothing(replay_client) -> None:
    before = len(replay_client.get("/api/portfolios").json())
    bad = {**GOOD, "holdings": [{"ticker": "AAPL", "weight_pct": 60}, {"ticker": "AAPL", "weight_pct": 10}]}
    r = replay_client.post("/api/portfolios", json=bad)
    assert r.status_code == 422
    msgs = " ".join(d["msg"] for d in r.json()["detail"])
    assert "appears twice" in msgs and "add up to 70" in msgs
    assert replay_client.post("/api/portfolios", json={"name": "x", "holdings": [], "bogus": 1}).status_code == 422
    assert len(replay_client.get("/api/portfolios").json()) == before


def test_validate_and_parse_never_save(replay_client) -> None:
    before = len(replay_client.get("/api/portfolios").json())
    v = replay_client.post("/api/portfolios/validate", json={**GOOD, "holdings": GOOD["holdings"][:2]})
    assert v.status_code == 200 and v.json()["ok"] is False and v.json()["portfolio"] is None
    p = replay_client.post("/api/portfolios/parse", json={"text": "AAPL 20%\nJPM 15%\nMSFT 15%\nTLT 25%\nCash 25%"}).json()
    assert p["draft"]["mode"] == "WEIGHT" and p["resolved"]["ok"] is True
    assert replay_client.post("/api/portfolios/parse", json={"text": "AAPL 20%\nJPM 100 @ 5"}).json()["draft"] is None
    assert len(replay_client.get("/api/portfolios").json()) == before


def test_exposure_for_default_and_personal(replay_client, made) -> None:
    pid = made(GOOD)
    mine = replay_client.get(f"/api/portfolios/{pid}/exposure").json()
    assert mine["kind"] == "USER" and mine["total_value"] == pytest.approx(1_000_000)
    assert {r["key"]: r["share"] for r in mine["by_asset_class"]} == pytest.approx({"EQUITY": 0.5, "BOND": 0.25, "CASH": 0.25})
    assert next(m for m in mine["metrics"] if m["key"] == "bond_duration")["value"] == 17.0
    default = replay_client.get("/api/portfolios/default/exposure").json()
    assert default["kind"] == "DEFAULT" and default["position_count"] > 50
    for d in (mine, default):  # the sector-by-asset-class table regroups the whole book
        mx = d["matrix"]
        assert mx["unit"] == "market_value" and mx["reconciled"] and sum(c["value"] for c in mx["cells"]) == pytest.approx(d["total_value"])
        assert {r["key"]: r["total"] for r in mx["cols"]} == pytest.approx({r["key"]: r["market_value"] for r in d["by_asset_class"]})
    assert replay_client.get("/api/portfolios/pf_doesnotexist/exposure").status_code == 404
    legacy = replay_client.get("/api/portfolio/summary", params={"portfolio_id": pid}).json()
    assert legacy["kind"] == "USER" and legacy["synthetic"] is False and legacy["asset_count"] == 5
    assert replay_client.get("/api/portfolio/summary").json()["synthetic"] is True


def test_no_portfolio_id_means_the_default_exactly_as_before(replay_client) -> None:
    sid = pick(replay_client, "COMPANY")
    plain = stress(replay_client, sid).json()
    named = stress(replay_client, sid, "default").json()
    assert plain["run_id"] == named["run_id"] and plain["audit"]["portfolio_id"] == named["audit"]["portfolio_id"]
    assert plain["summary"] == named["summary"]


@pytest.mark.parametrize("level", ["COMPANY", "SECTOR", "MARKET"])
def test_event_to_exposure_to_scenario_to_stress_to_chain(replay_client, made, level) -> None:
    pid = made(GOOD)
    sid = pick(replay_client, level)
    rel = replay_client.get(f"/api/signals/{sid}/relevance", params={"portfolio_id": pid}).json()
    assert rel["portfolio_id"] == pid and rel["band"] in {"NONE", "LOW", "MEDIUM", "HIGH"}
    r = stress(replay_client, sid, pid)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["audit"]["portfolio_id"] == pid and run["audit"]["portfolio_hash"]
    if run["status"] != "COMPLETED":
        assert run["status"] == "NOT_APPLICABLE"   # a sector the portfolio does not name is reported, not zeroed
        return
    assert run["summary"]["baseline_value"] == pytest.approx(1_000_000)
    assert stress(replay_client, sid, pid).json()["run_id"] == run["run_id"]       # deterministic
    chain = replay_client.get(f"/api/stress-runs/{run['run_id']}/exposure-chain").json()
    assert chain["portfolio_id"] == pid and chain["total_impact"] == pytest.approx(run["summary"]["pnl"])
    assert sum(s["impact"] for s in chain["steps"]) == pytest.approx(run["summary"]["pnl"])
    assert "forecast" in chain["note"]
    assert run["run_id"] in {x["run_id"] for x in replay_client.get("/api/stress-runs", params={"signal_id": sid, "portfolio_id": pid}).json()}


def test_an_event_with_no_exposure_and_an_all_equity_book(replay_client, made) -> None:
    sid = pick(replay_client, "MARKET")
    cash = made(CASH_ONLY)
    rel = replay_client.get(f"/api/signals/{sid}/relevance", params={"portfolio_id": cash}).json()
    assert rel["share"] == 0 and rel["band"] == "NONE"
    run = stress(replay_client, sid, cash).json()
    assert run["status"] == "COMPLETED" and run["summary"]["pnl"] == 0
    chain = replay_client.get(f"/api/stress-runs/{run['run_id']}/exposure-chain").json()
    assert chain["steps"] == [] and chain["not_reached"]["share"] == pytest.approx(1.0)
    eq = made(ALL_EQUITY)
    assert stress(replay_client, sid, eq).json()["summary"]["pnl"] < 0                  # a market-wide sell-off reaches an all-equity book
    assert replay_client.get(f"/api/signals/{sid}/relevance", params={"portfolio_id": eq}).json()["band"] == "HIGH"


def test_an_unresolved_event_is_reported_not_guessed(replay_client, made) -> None:
    items = replay_client.get("/api/signals").json()["items"]
    unresolved = [s for s in items if s["scope_level"] == "UNRESOLVED"]
    if not unresolved:
        pytest.skip("the replay pack has no unresolved signal")
    pid = made(GOOD)
    rel = replay_client.get(f"/api/signals/{unresolved[0]['id']}/relevance", params={"portfolio_id": pid}).json()
    assert rel["level"] == "UNDETERMINED" and rel["band"] == "UNDETERMINED"


def test_feed_relevance_follows_the_chosen_portfolio(replay_client, made) -> None:
    pid = made(CASH_ONLY)
    default = replay_client.get("/api/signals").json()["items"]
    mine = replay_client.get("/api/signals", params={"portfolio_id": pid}).json()["items"]
    d = {s["id"]: s for s in default}
    market = [s for s in mine if s["scope_level"] == "MARKET"]
    assert market and all(s["relevance_share"] == 0 and s["relevance_band"] == "NONE" for s in market)
    assert any(d[s["id"]]["relevance_share"] > 0 for s in market)


def test_compare_two_portfolios_on_one_event(replay_client, made) -> None:
    sid = pick(replay_client, "MARKET")
    eq, cash = made(ALL_EQUITY), made(CASH_ONLY)
    r = replay_client.post("/api/portfolios/compare", json={"signal_id": sid, "portfolio_ids": [eq, cash], "force": True})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["pnl_pct_a"] < 0 and c["pnl_pct_b"] == 0 and c["difference"].startswith("All SPY shows the larger modeled loss")
    assert replay_client.post("/api/portfolios/compare", json={"signal_id": sid, "portfolio_ids": [eq, "default"], "force": True}).status_code == 200
    assert replay_client.post("/api/portfolios/compare", json={"signal_id": sid, "portfolio_ids": [eq, "pf_nope000"]}).status_code == 404
    assert replay_client.post("/api/portfolios/compare", json={"signal_id": sid, "portfolio_ids": [eq]}).status_code == 422


def test_the_chain_refuses_a_run_made_on_an_edited_portfolio(replay_client, made) -> None:
    pid = made(ALL_EQUITY)
    sid = pick(replay_client, "MARKET")
    run = stress(replay_client, sid, pid).json()
    replay_client.put(f"/api/portfolios/{pid}", json={**ALL_EQUITY, "holdings": [{"ticker": "SPY", "weight_pct": 50}, {"ticker": "CASH", "weight_pct": 50}]})
    assert replay_client.get(f"/api/stress-runs/{run['run_id']}/exposure-chain").status_code == 409


def test_unknown_portfolio_ids_are_404_everywhere(replay_client) -> None:
    sid = pick(replay_client, "MARKET")
    assert stress(replay_client, sid, "pf_nope0000").status_code == 404
    assert replay_client.get(f"/api/signals/{sid}/relevance", params={"portfolio_id": "pf_nope0000"}).status_code == 404
    assert replay_client.get("/api/portfolio/exposure", params={"portfolio_id": "../etc"}).status_code == 404
