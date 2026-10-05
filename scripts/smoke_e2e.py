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
CARDS = {"sentiment": "models/sentiment/tfidf-lr-v1/model_card.json", "event": "models/event/hybrid-event-v2/model_card.json",
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
    check(prov["sentiment"]["model_id"] == "tfidf-lr-v1" and prov["sentiment"]["artifact_sha256"] == cards["sentiment"]["artifact_sha256"],
          "...tfidf-lr-v1 with its artifact hash")
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
    live = get(base, "/api/live/status")
    check(live["state"] == "OFF" and live["enabled"] is False, "/api/live/status: live is off by default (replay data only)")
    scope = get(base, "/api/scope")
    check(scope["replay_mix"].get("UNRESOLVED", 0) > 0 and scope["evaluation"], "/api/scope: unresolved events are kept, and the sector vocabulary has a measured evaluation")

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
           "EVENTSHOCK_LLM": "0", "EVENTSHOCK_LLM_CACHE_PATH": str(journal.parent / "llm_cache.jsonl")}
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
