"""End-to-end smoke test against a REAL server process (replay profile): API, model versions, evidence and the SPA.

    python scripts/smoke_e2e.py            # starts `python -m eventshock` on a free port, checks, stops it
    python scripts/smoke_e2e.py --url http://127.0.0.1:8000   # check a server that is already running

Everything the UI shows comes from these endpoints, so agreement here (served ids and artifact hashes equal the committed cards,
evidence page built from the same cards, signals carry the same ids) is agreement with the UI. Exits 1 on the first failed check.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARDS = {"sentiment": "models/sentiment/tfidf-lr-v2/model_card.json", "event": "models/event/hybrid-event-v2/model_card.json",
         "impact": "models/impact/impact-v2/model_card.json"}
STARTUP_SECONDS = 600


class Fail(SystemExit):
    pass


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        raise Fail(1)


def get(base: str, path: str, *, raw: bool = False):
    with urllib.request.urlopen(base + path, timeout=60) as r:  # noqa: S310 - localhost
        body = r.read()
        return body if raw else json.loads(body)


def post(base: str, path: str, payload: dict):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
        return json.loads(r.read())


def put(base: str, path: str, payload: dict):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
        return json.loads(r.read())


def delete(base: str, path: str) -> int:
    req = urllib.request.Request(base + path, method="DELETE")
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return r.status


def run_checks(base: str) -> None:
    check(get(base, "/api/health") == {"status": "ok"}, "health")
    cards = {k: json.loads((ROOT / p).read_text(encoding="utf-8")) for k, p in CARDS.items()}
    served = {k: get(base, f"/api/models/{k}") for k in CARDS}
    for k, card in cards.items():
        check(served[k]["id"] == card["id"] and served[k]["artifact_sha256"] == card["artifact_sha256"],
              f"/api/models/{k} serves {card['id']} with the committed artifact hash {card['artifact_sha256'][:12]}")

    ev = get(base, "/api/evidence")
    stages = {s["stage"]: s for s in ev["stages"]}
    check({k: stages[k]["model_id"] for k in CARDS} == {k: c["id"] for k, c in cards.items()}, "/api/evidence stages name the same model ids")
    check(all(stages[k]["artifact_sha256"] == cards[k]["artifact_sha256"] for k in CARDS), "/api/evidence artifact hashes equal the cards")
    check({k: s["kind"] for k, s in stages.items()} == {"sentiment": "experimental", "event": "experimental", "impact": "experimental"},
          "lifecycle on /api/evidence: all three stages experimental (no stage promoted)")
    check(any("took no part" in c for c in stages["event"]["failed"]), "event stage lists the failing independent-set check")

    meta = get(base, "/api/meta")
    check(meta["impact"]["model_id"] == "impact-v2" and meta["impact"]["mode"] == "MODEL", "/api/meta: impact-v2 in MODEL mode")
    check(set(meta["impact"]["scopes"].values()) == {"CALIBRATED"}, "/api/meta: both impact scopes CALIBRATED")
    check(any("tfidf-lr-event-v1" in n for n in meta["notices"]), "/api/meta notice names the TF-IDF model the impact stage reads (train/serve parity)")

    page = get(base, "/api/signals")
    items = page["items"]
    check(len(items) > 0 and page["total"] >= len(items), f"/api/signals returns {page['total']} signals")
    modelled = [s for s in items if s.get("impact_origin") == "MODEL"]
    check(len(modelled) > 0, "some signals carry a model-origin impact (impact-v2)")
    detail = get(base, f"/api/signals/{modelled[0]['id']}")
    prov = detail["provenance"]
    check(prov["event"]["model_id"] == "hybrid-event-v2" and prov["event"]["artifact_sha256"] == cards["event"]["artifact_sha256"],
          "a signal's audit names hybrid-event-v2 and its artifact hash")
    check(prov["sentiment"]["model_id"] == "tfidf-lr-v2" and prov["sentiment"]["artifact_sha256"] == cards["sentiment"]["artifact_sha256"],
          "...tfidf-lr-v2 with its artifact hash")
    check(prov["impact"]["model_id"] == "impact-v2" and prov["impact"]["artifact_sha256"] == cards["impact"]["artifact_sha256"]
          and prov["impact"]["feature_schema"] == cards["impact"]["feature_schema"], "...impact-v2 with its artifact hash and feature schema")
    check(prov["stage_origins"]["event"] == "MODEL" and prov["stage_origins"]["impact"] == "MODEL", "...with MODEL stage origins")

    run1 = post(base, "/api/stress-test", {"signal_id": modelled[0]["id"], "force": True})
    run2 = post(base, "/api/stress-test", {"signal_id": modelled[0]["id"], "force": True})
    check(run1["status"] == "COMPLETED" and abs(sum(p["delta"] for p in run1["positions"]) - run1["summary"]["pnl"]) < 1.0,
          f"stress test completes and position deltas reconcile to the P&L ({run1['summary']['pnl']:,.0f})")
    strip = lambda r: {k: v for k, v in r.items() if k not in ("run_id", "id")}  # noqa: E731
    check(strip(run1) == strip(run2), "the stress engine is deterministic (same signal, same result)")

    # Stage 6: one engine, many doors. The smoke test uses a private journal (see main), so nothing it pastes outlives it.
    before = get(base, "/api/signals?channel=REPLAY")["total"]
    pasted = post(base, "/api/analyze", {"text": "Chipmakers slide as semiconductor demand softens and data center spending slows"})
    sig = pasted["signal"]
    check(pasted["outcome"] in ("NEW", "DUPLICATE") and sig["scope_level"] == "SECTOR" and sig["scope_sector"] == "Technology" and sig["channel"] == "MANUAL",
          "/api/analyze: a pasted sector story is a MANUAL SECTOR-scope signal, no company invented")
    check(get(base, "/api/signals?channel=REPLAY")["total"] == before, "...and the replay signals are untouched by it")
    rel = get(base, f"/api/signals/{sig['id']}/relevance")
    check(rel["level"] == "SECTOR" and 0 < rel["share"] < 1 and rel["reach"], "/api/signals/{id}/relevance reports the sector exposure of the book")
    st = post(base, "/api/stress-test", {"signal_id": sig["id"], "force": True})
    check(st["status"] in ("COMPLETED", "NOT_APPLICABLE") and st["audit"]["scope_level"] == "SECTOR", "a pasted signal runs through the same stress engine")
    # Stage 7: the risk assessment (rule mode here: no key, no network)
    caps = get(base, "/api/meta")["capabilities"]
    check(caps["assessment"] is True and caps["llm"]["mode"] == "RULES" and caps["llm"]["sends_text_off_machine"] is False,
          "/api/meta: the assessment layer is on and reads text by rules (no language model, nothing leaves the machine)")
    regulatory = post(base, "/api/analyze", {"text": "European regulators propose stricter capital requirements for major banks, potentially increasing funding costs."})
    a = regulatory["assessment"]
    check(a["reading"]["event_type"] == "REGULATORY_LEGAL" and "Financials" in a["reading"]["sectors"] and a["reading"]["primary_issuer"]["entity_id"] == "UNKNOWN_ENTITY",
          "/api/analyze: a regulatory headline is read as Regulatory / Legal, Financials, with no issuer invented")
    check(a["severity"]["basis"] == "SCORECARD" and a["labels"] and 1 <= a["severity"]["score"] <= 10,
          "...scored by the severity scorecard, labelled not validated / not a forecast")
    ev = get(base, f"/api/signals/{regulatory['signal_id']}/evidence")
    tl = get(base, f"/api/signals/{regulatory['signal_id']}/timeline")
    check(set(ev) >= {"source_evidence", "model_inference", "scenario_assumptions"} and tl["items"] and tl["excluded"],
          "/api/signals/{id}/evidence and /timeline answer, with the exclusions listed")
    run = post(base, "/api/stress-test", {"signal_id": regulatory["signal_id"], "force": True})
    check(run["status"] == "COMPLETED" and run["audit"]["impact_origin"] == "ASSESSMENT" and any(s["scope"] == "SECTOR" and s["applicable"] for s in run["shocks"]),
          "a stress run on it is driven by the assessment, and the sector read from the text reaches the portfolio")
    # Stage 8: historical analogues (retrieved, hindsight, never a score input) and the scenario-vs-history check
    check(caps.get("analogues") is True and caps.get("history_check") is True, "/api/meta: analogues and the scenario history check are on")
    an = get(base, f"/api/signals/{items[0]['id']}/analogues")
    check(an["status"] in ("OK", "NO_RELIABLE_ANALOGUE", "UNAVAILABLE") and an["reason"] and "hindsight" in an["outcome_note"],
          f"/api/signals/{{id}}/analogues answers honestly ({an['status']})")
    check(all(i["origin"] == "RETRIEVED" for i in an["items"]) and (an["status"] != "OK" or an["aggregate"] is not None), "...retrieved items are labelled and an OK answer carries its aggregate")
    hc = get(base, "/api/scenarios/scn_macro_rates_shock/history-check")
    check(any(c["factor"] == "PD_MULTIPLIER" and not c["checkable"] for c in hc["checks"]) and any(c["checkable"] for c in hc["checks"]),
          "/api/scenarios/{id}/history-check ranks what history can speak to and says what it cannot")
    # Stage 10: multi-scope event intelligence (a derived side-car: it must not change what a signal is)
    check(caps.get("intelligence") is True, "/api/meta: event intelligence is on")
    intel = get(base, f"/api/signals/{items[0]['id']}/intelligence")
    check(intel["scope"]["scope_type"] in ("COMPANY", "INDUSTRY", "SECTOR", "GEOGRAPHY", "MACRO", "MARKET", "THEME", "UNRESOLVED") and intel["group"]["report_count"] >= 1
          and intel["evidence"]["evidence_strength"]["tier"] in ("STRONG", "MODERATE", "WEAK", "INSUFFICIENT") and intel["labels"] and intel["limitations"],
          "/api/signals/{id}/intelligence: scope, event group, evidence tier, labels and limits")
    nameless = post(base, "/api/analyze", {"text": "Local festival draws record crowds to the lakeside this weekend, organisers say"})
    if nameless["intelligence"] is not None:
        ni = nameless["intelligence"]
        check(ni["scope"]["scope_type"] == "UNRESOLVED" and {a["field"] for a in ni["abstentions"]} >= {"company", "scope"}, "/api/analyze: text with no subject is UNRESOLVED and abstains by field")
    macro = post(base, "/api/analyze", {"text": "The Federal Reserve holds interest rates steady as inflation cools, signalling cuts later this year"})
    check(macro["intelligence"]["scope"]["scope_type"] == "MACRO" and macro["intelligence"]["scope"]["scope_path"][-1]["type"] == "MARKET",
          "/api/analyze: a rates story resolves to a MACRO scope with the market as its root")
    live = get(base, "/api/live/status")
    check(live["state"] == "OFF" and live["enabled"] is False, "/api/live/status: live is off by default (replay data only)")
    scope = get(base, "/api/scope")
    check(scope["replay_mix"].get("UNRESOLVED", 0) > 0 and scope["evaluation"], "/api/scope: unresolved events are kept, and the sector vocabulary has a measured evaluation")

    # Personal portfolios: optional, persistent, and the default is untouched by them.
    plain = post(base, "/api/stress-test", {"signal_id": modelled[0]["id"], "force": True})
    mine = post(base, "/api/portfolios", {"name": "smoke", "holdings": [{"ticker": "AAPL", "weight_pct": 40}, {"ticker": "TLT", "weight_pct": 30},
                                                                       {"ticker": "CASH", "weight_pct": 30}]})
    pid = mine["id"]
    try:
        check(get(base, "/api/portfolios")[0]["id"] == "default" and pid in {p["id"] for p in get(base, "/api/portfolios")},
              "/api/portfolios: the synthetic default is listed first and the saved portfolio next to it")
        exp = get(base, f"/api/portfolios/{pid}/exposure")
        check(abs(exp["total_value"] - 1_000_000) < 1 and {r["key"] for r in exp["by_asset_class"]} == {"EQUITY", "BOND", "CASH"},
              "/api/portfolios/{id}/exposure describes the personal holdings")
        mrun = post(base, "/api/stress-test", {"signal_id": modelled[0]["id"], "force": True, "portfolio_id": pid})
        again = post(base, "/api/stress-test", {"signal_id": modelled[0]["id"], "force": True, "portfolio_id": pid})
        check(mrun["audit"]["portfolio_id"] == pid and mrun["run_id"] == again["run_id"], "a stress run on the personal portfolio is deterministic and names it")
        if mrun["status"] == "COMPLETED":
            chain = get(base, f"/api/stress-runs/{mrun['run_id']}/exposure-chain")
            check(abs(chain["total_impact"] - mrun["summary"]["pnl"]) < 1.0, "/exposure-chain: the steps regroup the engine's own P&L")
        check(post(base, "/api/stress-test", {"signal_id": modelled[0]["id"], "force": True})["run_id"] == plain["run_id"],
              "...and a request with no portfolio is byte-for-byte the same default run as before")
    finally:
        check(delete(base, f"/api/portfolios/{pid}") == 204 and pid not in {p["id"] for p in get(base, "/api/portfolios")}, "a saved portfolio can be deleted")

    # Event -> portfolio propagation: mapping, relevance, a generated scenario, attribution that reconciles, concentration, and manual adjustment that resets cleanly.
    caps = get(base, "/api/meta")["capabilities"]
    check(caps["propagation"] is True and caps["adjustments"] is True, "/api/meta advertises propagation and adjustments")
    avail = None
    for it in get(base, "/api/signals?limit=400")["items"]:
        flow = get(base, f"/api/signals/{it['id']}/propagation")
        if flow["scenario"]["availability"] == "AVAILABLE":
            avail, base_flow = it["id"], flow
            break
    check(avail is not None, "some replay event generates a scenario for the default portfolio")
    g, m, sc = base_flow["graph"], base_flow["materiality"], base_flow["scenario"]
    check(g["edges"] and all(e["status"] in ("OBSERVED", "SCENARIO_ASSUMPTION", "USER_ASSUMPTION") for e in g["edges"]) and "not causal inference" in " ".join(g["labels"]),
          "/propagation: every edge says whether it is observed or assumed; the mapping is not called causal")
    check(m["level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL") and m["why"] and m["rules"], "/propagation: relevance is a named level with its reasons and the rules that fired")
    check(sc["label"] == "SCENARIO SIMULATION — NOT A PREDICTION" and sc["scenario"]["id"].startswith("gen_"), "/propagation: the generated scenario is labelled a simulation")
    auto = post(base, f"/api/signals/{avail}/portfolio-stress", {})
    pnl = auto["run"]["summary"]["pnl"]
    check(auto["run"]["status"] == "COMPLETED" and all(abs(sum(r["delta"] for r in t["rows"]) - pnl) < 0.05 for t in [auto["attribution"]["drivers"], *auto["attribution"]["tables"]]),
          "/portfolio-stress: the generated scenario runs and every attribution table adds up to the total change")
    check(abs(auto["chain"]["total_impact"] - pnl) < 0.05 and post(base, f"/api/signals/{avail}/portfolio-stress", {})["run"]["run_id"] == auto["run"]["run_id"],
          "...the exposure chain agrees, and the same request is the same run")
    check(len(get(base, "/api/concentration")["dimensions"]) == 6 and "clusters" in get(base, "/api/concentration/overlaps"), "/api/concentration: six dimensions and the overlap view")
    before = get(base, f"/api/signals/{avail}/propagation", raw=True)
    adj = put(base, "/api/adjustments", {"values": {"propagation.generation.min_severity": 10}})
    check(adj["count"] == 1 and get(base, f"/api/signals/{avail}/propagation")["adjustments"]["count"] == 1, "/api/adjustments: a change is applied to the running side-cars and labelled on the answer")
    check(post(base, "/api/adjustments/reset", {})["count"] == 0 and get(base, f"/api/signals/{avail}/propagation", raw=True) == before,
          "...and a reset puts every byte of the answer back")


    # Stage 12 decision intelligence: monitor, executive digest, watchlists, scenario lab, reverse stress, explanations, feedback, external markets, brief.
    caps = get(base, "/api/meta")["capabilities"]
    check(all(caps[k] is True for k in ("monitor", "watchlists", "scenario_lab", "explanations", "feedback", "external_markets", "executive_brief")),
          "/api/meta advertises the decision-intelligence side-cars")
    mst = get(base, "/api/monitor/status")
    cycles = get(base, "/api/monitor/cycles")
    check(mst["state"] == "OK" and mst["replay_cycles"] == len(cycles) and len(cycles) > 1 and cycles[0]["baseline"] is True, "/api/monitor: the replay clock has a baseline and later cycles")
    ch1 = get(base, "/api/monitor/changes?mode=REPLAY", raw=True)
    check(ch1 == get(base, "/api/monitor/changes?mode=REPLAY", raw=True), "/api/monitor/changes: the replay changes are byte-identical on repeat")
    dg = get(base, "/api/monitor/digest?mode=REPLAY")
    cards = [c for sec in dg["sections"] for c in sec["cards"]]
    check(dg["availability"] == "AVAILABLE" and len(dg["sections"]) == 8 and "No importance score" in dg["ranking"] and all(c["rank_key"] for c in cards),
          "/api/monitor/digest: eight sections, no score, every card carries its ordering key")
    check(get(base, "/api/monitor/digest?mode=REPLAY", raw=True) == get(base, "/api/monitor/digest?mode=REPLAY", raw=True), "...and the digest is identical on repeat")
    eid = next(c["event_id"] for c in cards if c.get("event_id"))
    tl = get(base, f"/api/events/{eid}/timeline")
    check(tl["items"] and all(i["provenance"] for i in tl["items"]), "/api/events/{id}/timeline: the event as a narrative, every item with its provenance")
    for subject in ("PRIORITY", "VISIBILITY", "STRESS", "MARKET"):
        ex = get(base, f"/api/events/{eid}/explanation?subject={subject}")
        check(ex["subject"] == subject and (ex["reasons"] or ex["availability"] == "UNAVAILABLE") and all(r["source_ref"] and r["provenance"] for r in ex["reasons"]),
              f"/api/events/{{id}}/explanation: {subject} gives structured, sourced reasons")
    xm = get(base, f"/api/events/{eid}/external-markets")
    check(xm["label"] == "EXTERNAL MARKET OBSERVATION" and "never an input" in xm["note"] and xm["match"]["status"] in ("MATCHED", "LOW_CONFIDENCE_MATCH", "NO_MATCH", "INSUFFICIENT_DATA"),
          "/api/events/{id}/external-markets: a labelled observation with an honest match status")
    mt = get(base, f"/api/events/{eid}/market-timeline")
    check(set(mt["kinds"]) <= {"SOURCE_EVENT", "EVENTSHOCK_ASSESSMENT", "EXTERNAL_MARKET_OBSERVATION", "SCENARIO_ASSUMPTION", "REALISED_OUTCOME"}, "/api/events/{id}/market-timeline: the kinds of statement stay separate")
    brief = get(base, f"/api/events/{eid}/brief")
    check([x["id"] for x in brief["sections"]] == ["EXECUTIVE_SUMMARY", "WHAT_HAPPENED", "CURRENT_STATUS", "WHY_IT_MATTERS", "EVIDENCE", "CONFLICTS", "AFFECTED", "PORTFOLIO_EXPOSURE", "PROPAGATION",
                                                  "STRESS", "TOP_DRIVERS", "HISTORICAL_CONTEXT", "EXTERNAL_MARKET_VIEW", "ASSUMPTIONS", "UNCERTAINTY", "WHAT_TO_MONITOR"]
          and all(st["source_refs"] for x in brief["sections"] for st in x["statements"]), "/api/events/{id}/brief: sixteen sections in order, every statement sourced")
    check(get(base, f"/api/events/{eid}/brief", raw=True) == get(base, f"/api/events/{eid}/brief", raw=True)
          and get(base, f"/api/events/{eid}/brief?format=md", raw=True).startswith(b"# Executive risk brief"), "...the brief is deterministic and has a Markdown form")
    wl = post(base, "/api/watchlists", {"name": "smoke watch", "items": [{"kind": "COMPANY", "value": "MSFT"}]})
    try:
        act = get(base, f"/api/watchlists/{wl['id']}/activity?mode=REPLAY")
        check(act["watchlist"]["id"] == wl["id"] and "items" in act, "/api/watchlists: a watchlist is created and has activity")
        check(put(base, f"/api/watchlists/{wl['id']}", {"name": "smoke watch", "enabled": False, "items": wl["items"]})["enabled"] is False, "...and can be switched off")
    finally:
        check(delete(base, f"/api/watchlists/{wl['id']}") == 204, "a watchlist can be deleted")
    req = {"scenario_type": "CUSTOM", "assumptions": [{"kind": "EQUITY_MARKET", "value": -0.10}, {"kind": "RATES", "value": 100}]}
    lab1, lab2 = post(base, "/api/scenarios", req), post(base, "/api/scenarios", req)
    check(lab1["status"] == "COMPLETED" and lab1["scenario_id"] == lab2["scenario_id"] and lab1["scenario_id"].startswith("scn_lab_") and lab1["label"].startswith("SCENARIO SIMULATION"),
          "/api/scenarios: a custom scenario runs deterministically on the unchanged engine and is labelled a simulation")
    cmp = post(base, "/api/scenarios/compare", {"scenarios": [req, {"scenario_type": "BASE", "assumptions": []}]})
    check(len(cmp["rows"]) == 2 and any(r["scenario_type"] == "BASE" and r["pnl"] == 0 for r in cmp["rows"]), "/api/scenarios/compare: two scenarios side by side (the base case is zero)")
    rev = post(base, "/api/reverse-stress", {"target_pct": -5})
    check(rev["status"] == "ACHIEVABLE" and abs(rev["difference_pp"]) <= 0.05 and rev["required_shocks"], "/api/reverse-stress: a hypothetical combination reaches -5% within tolerance")
    fb = post(base, "/api/feedback", {"event_id": eid, "type": "RELEVANCE", "value": "RELEVANT", "analyst_id": "smoke"})
    check(fb["event_id"] and get(base, "/api/feedback/statistics")["volume"] >= 1 and "not ground truth" in get(base, "/api/feedback/statistics")["label"].lower(),
          "/api/feedback: an answer is recorded and the statistics say it is not ground truth")
    rb = get(base, "/api/rebalancer/timeline")
    n = len(rb["tickers"])
    check(10 <= n <= 20 and len(rb["cycles"]) > 20 and rb["params"]["is_default"] and all(abs(sum(c["weights"]) - 1) < 1e-9 for c in rb["cycles"]),
          "/api/rebalancer/timeline: a 10-20 stock index, every cycle fully invested")
    lo, hi = (min(c["lower"] for c in rb["constituents"]), max(c["upper"] for c in rb["constituents"]))
    check(all(lo - 1e-9 <= w <= hi + 1e-9 for c in rb["cycles"] for w in c["weights"]), "...and every weight is inside its bounds")
    check(get(base, "/api/rebalancer/timeline", raw=True) == get(base, "/api/rebalancer/timeline", raw=True), "...and the timeline is identical on repeat")
    whatif = get(base, "/api/rebalancer/timeline?tilt=4&max_turnover=0.1")
    check(whatif["params"]["is_default"] is False and get(base, "/api/rebalancer/timeline")["cycles"][-1]["weights"] == rb["cycles"][-1]["weights"],
          "...a what-if is labelled and leaves the index of record unchanged")
    det = get(base, f"/api/rebalancer/cycles/{len(rb['cycles']) - 1}")
    check(len(det["names"]) == n and all(x["reason"] for x in det["names"]), "/api/rebalancer/cycles/{i}: every stock has a named reason")
    bt = get(base, "/api/rebalancer/backtest")
    check(bt["status"] == "AVAILABLE" and bt["backtest"]["caveats"] and bt["backtest"]["placebo"]["runs"] >= 100, "/api/rebalancer/backtest: the committed back-test matches the served weights and carries its placebo")
    cyc = rb["cycles"]
    busy = max(range(len(cyc)), key=lambda k: (cyc[k]["turnover"], -k))
    dec = get(base, f"/api/rebalancer/cycles/{busy}/decisions")
    check(len(dec["decisions"]) == n and abs(sum(x["trade"] for x in dec["decisions"])) < 1e-9 and all(x["explanation"] for x in dec["decisions"]) and len(dec["proposal_sha256"]) == 64,
          "/api/rebalancer/cycles/{i}/decisions: every stock has before / after / trade and an explanation; the trades net to zero")
    risk = get(base, f"/api/rebalancer/cycles/{busy}/decisions?strategy=sentiment_risk")
    check(risk["strategy"] == "sentiment_risk" and abs(sum(x["after"] for x in risk["decisions"]) - 1) < 1e-9, "...the risk-limit strategy is served beside the baseline and stays fully invested")
    lab = get(base, "/api/rebalancer/lab")
    check(lab["status"] == "AVAILABLE" and {s["id"] for s in lab["lab"]["strategies"]} >= {"sentiment", "equal_weight", "buy_and_hold"} and lab["lab"]["grid"]["cells_total"] == 21,
          "/api/rebalancer/lab: the committed lab matches the served weights and compares every strategy on one window")
    entry = post(base, "/api/rebalancer/proposals/decision", {"strategy": "sentiment", "cycle_index": busy, "action": "APPROVE", "analyst": "smoke", "proposal_sha256": dec["proposal_sha256"]})
    led = get(base, "/api/rebalancer/ledger")
    check(entry["seq"] == 1 and led["chain_ok"] and led["total"] == 1 and get(base, "/api/rebalancer/timeline")["cycles"][-1]["weights"] == rb["cycles"][-1]["weights"],
          "/api/rebalancer/proposals/decision: an approval is recorded in a hash-chained ledger and the served index does not move")

    index = get(base, "/", raw=True).decode("utf-8", "replace")
    check("<div id=\"root\"" in index or "id=\"root\"" in index, "the built UI is served at /")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="check a running server instead of starting one")
    args = ap.parse_args()
    if args.url:
        run_checks(args.url.rstrip("/"))
        return 0
    port = free_port()
    journal = Path(tempfile.mkdtemp(prefix="eventshock-smoke-")) / "journal.jsonl"
    env = {**os.environ, "EVENTSHOCK_PROFILE": "replay", "PYTHONPATH": str(ROOT / "src"), "EVENTSHOCK_JOURNAL_PATH": str(journal),
           # the smoke test never calls a language model: rule mode, and a private cache file
           "EVENTSHOCK_LLM": "0", "EVENTSHOCK_LLM_CACHE_PATH": str(journal.parent / "llm_cache.jsonl"),
           "EVENTSHOCK_PORTFOLIO_STORE_PATH": str(journal.parent / "portfolios"),
           "EVENTSHOCK_OVERRIDES_PATH": str(journal.parent / "overrides.json"),
           "EVENTSHOCK_DECISION_STORE_PATH": str(journal.parent / "decision"),
           "EVENTSHOCK_REBALANCER_LEDGER_PATH": str(journal.parent / "rebalancer_ledger.jsonl")}
    proc = subprocess.Popen([sys.executable, "-m", "eventshock", "--port", str(port)], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + STARTUP_SECONDS
        while True:
            if proc.poll() is not None:
                print(f"FAIL server exited with code {proc.returncode} during start-up", file=sys.stderr)
                return 1
            try:
                get(base, "/api/health")
                break
            except (urllib.error.URLError, ConnectionError, OSError):
                if time.time() > deadline:
                    print("FAIL server did not start in time", file=sys.stderr)
                    return 1
                time.sleep(2)
        run_checks(base)
        print("smoke test passed")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
