"""The rebalancer endpoints over the real replay pack (served sentiment model, real trusted clocks)."""

from __future__ import annotations

import pytest

LO, HI = 0.5 / 15 * 1.0, 1.5 / 15


def test_the_capability_is_advertised_in_replay_only(replay_client, client):
    assert replay_client.get("/api/meta").json()["capabilities"]["rebalancer"] is True
    assert client.get("/api/meta").json()["capabilities"]["rebalancer"] is False
    for path in ("/overview", "/timeline", "/cycles/0", "/backtest"):
        assert client.get(f"/api/rebalancer{path}").status_code == 404


def test_the_overview_describes_the_index_and_the_rule(replay_client):
    o = replay_client.get("/api/rebalancer/overview").json()
    assert o["available"] and 10 <= len(o["constituents"]) <= 20 and o["benchmark"] == "Equal weight"
    assert sum(c["benchmark_weight"] for c in o["constituents"]) == pytest.approx(1.0)
    assert all(c["name"] and c["sector"] for c in o["constituents"])
    assert o["cycle_count"] > 20 and o["params"]["is_default"] is True
    assert o["bounds"]["lower"] < o["bounds"]["benchmark"] < o["bounds"]["upper"]
    assert o["labels"] and o["limitations"] and len(o["curve"]) == 21


def test_every_cycle_of_the_timeline_reconciles(replay_client):
    t = replay_client.get("/api/rebalancer/timeline").json()
    n = len(t["tickers"])
    assert t["params"]["is_default"] and t["include_live"] is False
    prev = [1 / n] * n
    for c in t["cycles"]:
        assert len(c["weights"]) == len(c["scores"]) == len(c["reports"]) == n
        assert sum(c["weights"]) == pytest.approx(1.0, abs=1e-9)
        assert all(LO - 1e-9 <= w <= HI + 1e-9 for w in c["weights"])
        assert 0.5 * sum(abs(a - b) for a, b in zip(c["weights"], prev, strict=True)) <= t["params"]["max_turnover"] + 1e-9
        prev = c["weights"]
    assert t["excluded_untrusted_clock"] > 0 and t["reports_used"] > 500 and t["excluded_other"] == 0
    assert any(w > 1 / n + 1e-4 for c in t["cycles"] for w in c["weights"]) and any(w < 1 / n - 1e-4 for c in t["cycles"] for w in c["weights"])


def test_positive_scores_pull_a_weight_above_its_benchmark_somewhere(replay_client):
    t = replay_client.get("/api/rebalancer/timeline", params={"max_turnover": 0.25}).json()
    n = len(t["tickers"])
    last = t["cycles"][-1]
    for j in range(n):
        if last["scores"][j] > 0.1:
            assert last["weights"][j] > 1 / n
        if last["scores"][j] < -0.1:
            assert last["weights"][j] < 1 / n


def test_the_timeline_is_identical_on_every_call(replay_client):
    a = replay_client.get("/api/rebalancer/timeline").json()
    assert replay_client.get("/api/rebalancer/timeline").json() == a


def test_a_what_if_is_labelled_and_changes_nothing_for_the_next_caller(replay_client):
    base = replay_client.get("/api/rebalancer/timeline").json()
    w = replay_client.get("/api/rebalancer/timeline", params={"tilt": 5, "max_turnover": 0.2, "half_life_hours": 12}).json()
    assert w["params"]["is_default"] is False and w["params"]["tilt"] == 5
    assert w["cycles"][-1]["weights"] != base["cycles"][-1]["weights"]
    assert replay_client.get("/api/rebalancer/timeline").json() == base


@pytest.mark.parametrize("params", [{"tilt": -1}, {"tilt": 99}, {"half_life_hours": 0}, {"half_life_hours": 99999}, {"max_turnover": 0}, {"max_turnover": 0.9}, {"max_turnover": 2}])
def test_a_parameter_outside_its_limits_is_a_422(replay_client, params):
    assert replay_client.get("/api/rebalancer/timeline", params=params).status_code == 422


def test_a_cycle_explains_every_stock(replay_client):
    t = replay_client.get("/api/rebalancer/timeline").json()
    i = len(t["cycles"]) - 1
    d = replay_client.get(f"/api/rebalancer/cycles/{i}").json()
    assert d["index"] == i and d["status"] and len(d["names"]) == len(t["tickers"])
    assert sum(n["weight"] for n in d["names"]) == pytest.approx(1.0, abs=1e-9)
    assert sum(n["active"] for n in d["names"]) == pytest.approx(0.0, abs=1e-9)
    for n in d["names"]:
        assert n["reason"] in {"AT_UPPER_BOUND", "AT_LOWER_BOUND", "LIMITED_BY_TURNOVER", "HELD_BELOW_MIN_TRADE", "NO_EVIDENCE", "NO_CLEAR_SENTIMENT", "TILT_UP", "TILT_DOWN"}
        ds = d["drivers"][n["ticker"]]
        assert sum(x["contribution"] for x in ds) == pytest.approx(n["score"], abs=1e-9) or n["reports"] > len(ds)   # all of them listed => exact
        assert all(x["headline"] and x["source"] for x in ds)


def test_a_cycle_that_does_not_exist_is_a_404(replay_client):
    assert replay_client.get("/api/rebalancer/cycles/99999").status_code == 404
    assert replay_client.get("/api/rebalancer/cycles/-1").status_code == 404


def test_the_backtest_endpoint_answers_in_every_state(replay_client):
    r = replay_client.get("/api/rebalancer/backtest")
    assert r.status_code == 200
    b = r.json()
    assert b["status"] in {"AVAILABLE", "STALE", "UNAVAILABLE"}
    if b["status"] == "UNAVAILABLE":
        assert b["reason"] and b["backtest"] is None
    else:
        assert b["backtest"]["caveats"] and len(b["backtest"]["dates"]) == len(b["backtest"]["rebalanced"])


# ---------------------------------------------------------------------------------------------------------------------- strategies, decisions, lab, ledger
def _busiest(replay_client, **params):
    t = replay_client.get("/api/rebalancer/timeline", params=params).json()
    return max(range(len(t["cycles"])), key=lambda k: (t["cycles"][k]["turnover"], -k))


def test_the_overview_lists_the_strategies_and_says_which_can_be_served(replay_client):
    o = replay_client.get("/api/rebalancer/overview").json()
    ids = {s["id"]: s for s in o["strategies"]}
    assert set(ids) == {"sentiment", "sentiment_risk", "sentiment_impact"} and ids["sentiment"]["experimental"] is False
    assert all(s["experimental"] for k, s in ids.items() if k != "sentiment")
    assert ids["sentiment"]["available"] is True


def test_the_default_strategy_is_the_baseline_and_an_unknown_one_is_a_422(replay_client):
    a = replay_client.get("/api/rebalancer/timeline").json()
    b = replay_client.get("/api/rebalancer/timeline", params={"strategy": "sentiment"}).json()
    assert a == b and a["strategy"] == "sentiment"
    assert replay_client.get("/api/rebalancer/timeline", params={"strategy": "nope"}).status_code == 422
    assert replay_client.get("/api/rebalancer/cycles/0", params={"strategy": "nope"}).status_code == 422
    assert replay_client.get("/api/rebalancer/cycles/0/decisions", params={"strategy": "nope"}).status_code == 422


def test_other_strategies_keep_the_index_a_fully_invested_bounded_one(replay_client):
    for sid in ("sentiment_risk", "sentiment_impact"):
        t = replay_client.get("/api/rebalancer/timeline", params={"strategy": sid}).json()
        assert t["strategy"] == sid
        for c in t["cycles"]:
            assert sum(c["weights"]) == pytest.approx(1.0, abs=1e-9)
        sec = {}
        for con, w in zip(t["constituents"], t["cycles"][-1]["weights"], strict=True):
            sec[con["sector"]] = sec.get(con["sector"], 0.0) + w
        if sid == "sentiment_risk":
            n_by = {}
            for con in t["constituents"]:
                n_by[con["sector"]] = n_by.get(con["sector"], 0) + 1
            assert all(sec[k] <= min(1.0, n_by[k] / len(t["tickers"]) * 1.25) + 1e-9 for k in sec)


def test_a_decision_proposal_reconciles_and_every_trade_names_its_evidence(replay_client):
    i = _busiest(replay_client)
    d = replay_client.get(f"/api/rebalancer/cycles/{i}/decisions").json()
    assert d["index"] == i and d["strategy"] == "sentiment" and len(d["decisions"]) == len(d["tickers"]) and len(d["proposal_sha256"]) == 64
    assert sum(x["after"] for x in d["decisions"]) == pytest.approx(1.0, abs=1e-9) and sum(x["trade"] for x in d["decisions"]) == pytest.approx(0.0, abs=1e-9)
    assert d["buys"] + d["sells"] + d["holds"] == len(d["decisions"]) and d["buys"] and d["sells"]
    for x in d["decisions"]:
        assert x["trade"] == pytest.approx(x["after"] - x["before"], abs=1e-12)
        assert x["explanation"] and x["side"] in {"BUY", "SELL", "HOLD"} and x["evidence_quality"] in {"NONE", "THIN", "OK"}
        if x["reports"]:
            assert x["drivers"] and all(r["headline"] and r["published_at"] and r["source"] for r in x["drivers"])
    traded = [x for x in d["decisions"] if x["side"] != "HOLD"]
    assert any(any(b["code"] == "TURNOVER_CAP" for b in x["binding"]) for x in traded) or d["status"] == "TRADED"
    assert replay_client.get(f"/api/rebalancer/cycles/{i}/decisions").json() == d
    assert replay_client.get("/api/rebalancer/cycles/99999/decisions").status_code == 404


def test_the_proposal_digest_moves_with_a_what_if(replay_client):
    i = _busiest(replay_client)
    a = replay_client.get(f"/api/rebalancer/cycles/{i}/decisions").json()["proposal_sha256"]
    assert replay_client.get(f"/api/rebalancer/cycles/{i}/decisions", params={"tilt": 4}).json()["proposal_sha256"] != a


def _decide(replay_client, i, digest, **over):
    body = {"strategy": "sentiment", "cycle_index": i, "action": "APPROVE", "analyst": "tester", "proposal_sha256": digest, **over}
    return replay_client.post("/api/rebalancer/proposals/decision", json=body)


def test_approving_a_proposal_records_it_in_the_ledger_and_changes_nothing_served(replay_client):
    served = replay_client.get("/api/rebalancer/timeline").json()
    i = _busiest(replay_client)
    d = replay_client.get(f"/api/rebalancer/cycles/{i}/decisions").json()
    r = _decide(replay_client, i, d["proposal_sha256"], note="looks fine")
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["action"] == "APPROVE" and e["tracking_difference"] == pytest.approx(0.0, abs=1e-9) and e["turnover"] == pytest.approx(d["turnover"], abs=1e-9)
    assert e["proposal_sha256"] == d["proposal_sha256"] and len(e["entry_hash"]) == 64
    led = replay_client.get("/api/rebalancer/ledger").json()
    assert led["chain_ok"] and led["total"] >= 1 and led["entries"][0]["id"] == e["id"] and led["entries"][0]["stale"] is False
    assert led["paper_book"]["weights"] == pytest.approx(e["approved"]) and led["labels"]
    latest = replay_client.get(f"/api/rebalancer/cycles/{i}/decisions").json()["latest_decision"]
    assert latest["id"] == e["id"] and latest["stale"] is False
    assert replay_client.get("/api/rebalancer/timeline").json() == served   # a decision is a note: the served index did not move


def test_a_stale_digest_is_refused_with_a_409(replay_client):
    i = _busiest(replay_client)
    r = _decide(replay_client, i, "0" * 64)
    assert r.status_code == 409 and "changed" in r.json()["detail"]


def test_rejecting_keeps_the_previous_weights(replay_client):
    i = _busiest(replay_client)
    d = replay_client.get(f"/api/rebalancer/cycles/{i}/decisions").json()
    e = _decide(replay_client, i, d["proposal_sha256"], action="REJECT", note="no").json()
    assert e["action"] == "REJECT" and e["approved"] == pytest.approx(e["before"]) and e["accepted_tickers"] == [] and e["turnover"] == pytest.approx(0.0, abs=1e-12)


def test_a_partial_approval_must_balance_and_unfundable_ones_are_a_422(replay_client):
    i = _busiest(replay_client)
    d = replay_client.get(f"/api/rebalancer/cycles/{i}/decisions").json()
    buys = [x["ticker"] for x in d["decisions"] if x["side"] == "BUY"]
    sells = [x["ticker"] for x in d["decisions"] if x["side"] == "SELL"]
    ok = _decide(replay_client, i, d["proposal_sha256"], accepted_tickers=buys[:1] + sells)
    assert ok.status_code == 200 and sum(ok.json()["approved"]) == pytest.approx(1.0, abs=1e-9) and set(ok.json()["rejected_tickers"]) == set(buys[1:])
    assert _decide(replay_client, i, d["proposal_sha256"], accepted_tickers=buys).status_code == 422
    assert _decide(replay_client, i, d["proposal_sha256"], accepted_tickers=["ZZZZ"]).status_code == 422


def test_an_analyst_name_and_a_known_strategy_are_required(replay_client, client):
    i = _busiest(replay_client)
    d = replay_client.get(f"/api/rebalancer/cycles/{i}/decisions").json()
    assert _decide(replay_client, i, d["proposal_sha256"], analyst="").status_code == 422
    assert _decide(replay_client, i, d["proposal_sha256"], strategy="nope").status_code == 422
    assert client.get("/api/rebalancer/ledger").status_code == 404 and client.get("/api/rebalancer/lab").status_code == 404


def test_the_lab_endpoint_answers_in_every_state(replay_client):
    b = replay_client.get("/api/rebalancer/lab").json()
    assert b["status"] in {"AVAILABLE", "STALE", "UNAVAILABLE"}
    if b["status"] == "UNAVAILABLE":
        assert b["reason"] and b["lab"] is None
    else:
        lab = b["lab"]
        assert lab["caveats"] and {s["id"] for s in lab["strategies"]} >= {"sentiment", "equal_weight", "buy_and_hold"}
        assert all(len(s["daily_net"]) == len(lab["dates"]) for s in lab["strategies"])
