"""The analyze door and the live overlay through the real application (replay profile, real models), on a private app instance."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eventshock.api.main import create_app
from eventshock.config import Settings

COMPANY = "Goldman Sachs fined $50 million over trading violations, regulators say"
SECTOR = "Chipmakers slide as semiconductor demand softens and data center spending slows"
MACRO = "Federal Reserve signals rate cuts as inflation cools; Treasury yields drop"
UNRESOLVED = "Shares of the company tumbled after a surprise announcement"


@pytest.fixture(scope="module")
def app_client(tmp_path_factory):
    """Its own app and its own journal: pasting text mutates the live overlay, which the shared session container must never see."""
    return TestClient(create_app(Settings(profile="replay", journal_path=tmp_path_factory.mktemp("live") / "journal.jsonl")))


def analyze(c: TestClient, text: str, **kw) -> dict:
    r = c.post("/api/analyze", json={"text": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_capabilities_and_live_are_off_by_default(app_client) -> None:
    meta = app_client.get("/api/meta").json()
    caps = meta["capabilities"]
    assert caps["analyze"] is True and caps["live_enabled"] is False and caps["assessment"] is True and caps["llm"]["mode"] == "RULES"
    st = app_client.get("/api/live/status").json()
    assert st["state"] == "OFF" and st["enabled"] is False and st["market_context_through"]
    assert app_client.post("/api/live/refresh").status_code == 409


def test_the_live_switch_turns_the_feed_on_and_off_without_a_restart(app_client) -> None:
    """PUT /live/state: no request is made by switching (the poll loop is not running under TestClient); the capture choice is refused
    with its reason while no capture file exists; the feed is off again at the end so the other tests keep their premise."""
    st = app_client.get("/api/live/status").json()
    assert st["state"] == "OFF" and [c["kind"] for c in st["source_choices"]] == ["both", "gdelt", "edgar", "capture"]
    net = {c["kind"]: c["network"] for c in st["source_choices"]}
    assert net == {"both": True, "gdelt": True, "edgar": True, "capture": False}
    try:
        on = app_client.put("/api/live/state", json={"enabled": True, "source": "gdelt"})
        assert on.status_code == 200 and on.json()["enabled"] is True and on.json()["source_kind"] == "gdelt" and on.json()["state"] == "IDLE"
        assert app_client.get("/api/meta").json()["capabilities"]["live_enabled"] is True
    finally:
        off = app_client.put("/api/live/state", json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False and off.json()["state"] == "OFF"
    assert app_client.get("/api/meta").json()["capabilities"]["live_enabled"] is False
    assert app_client.post("/api/live/refresh").status_code == 409


def test_the_live_switch_refuses_an_unavailable_source_and_a_malformed_body(app_client) -> None:
    capture = next(c for c in app_client.get("/api/live/status").json()["source_choices"] if c["kind"] == "capture")
    if not capture["available"]:
        r = app_client.put("/api/live/state", json={"enabled": True, "source": "capture"})
        assert r.status_code == 409 and "capture" in r.json()["detail"]
        assert app_client.get("/api/live/status").json()["state"] == "OFF"
    edgar = next(c for c in app_client.get("/api/live/status").json()["source_choices"] if c["kind"] == "edgar")
    if not edgar["available"]:  # no declared SEC contact in this environment: an anonymous request is never sent
        r = app_client.put("/api/live/state", json={"enabled": True, "source": "edgar"})
        assert r.status_code == 409 and "EVENTSHOCK_SEC_CONTACT" in r.json()["detail"]
        assert app_client.get("/api/live/status").json()["state"] == "OFF"
    assert app_client.put("/api/live/state", json={"enabled": True, "source": "rss"}).status_code == 422
    assert app_client.put("/api/live/state", json={"source": "gdelt"}).status_code == 422
    assert app_client.put("/api/live/state", json={"enabled": True, "surprise": 1}).status_code == 422


@pytest.fixture(scope="module")
def capture_client(tmp_path_factory):
    """A private app for playing the committed capture: it adds hundreds of signals to the live overlay."""
    return TestClient(create_app(Settings(profile="replay", journal_path=tmp_path_factory.mktemp("cap") / "journal.jsonl")))


def test_the_simulated_live_capture_plays_through_the_switch_without_touching_replay(capture_client) -> None:
    c = capture_client
    before = c.get("/api/signals").json()
    replay_ids = {s["id"] for s in before["items"]}
    choices = {x["kind"]: x for x in c.get("/api/live/status").json()["source_choices"]}
    assert choices["capture"]["available"] is True and choices["capture"]["network"] is False
    on = c.put("/api/live/state", json={"enabled": True, "source": "capture"}).json()
    assert on["simulated"] is True and on["source_kind"] == "capture" and on["source_mode"] == "CAPTURE"
    st = on
    for _ in range(60):  # 216 records in batches of 20
        st = c.post("/api/live/refresh").json()
        if st["state"] == "IDLE":
            break
    assert st["state"] == "IDLE" and st["fetched_total"] >= 100 and st["live_signal_count"] > 0 and st["last_error"] is None
    after = c.get("/api/signals").json()
    live = [s for s in after["items"] if s["channel"] == "LIVE"]
    assert live and not ({s["id"] for s in live} & replay_ids)  # no live signal shadows a replay one
    assert replay_ids <= {s["id"] for s in after["items"]}  # every replay signal is still served
    again = c.put("/api/live/state", json={"enabled": True, "source": "capture"}).json()  # a finished capture can be started over
    assert again["state"] == "IDLE" and again["live_signal_count"] == st["live_signal_count"]
    off = c.put("/api/live/state", json={"enabled": False}).json()
    assert off["state"] == "OFF" and off["live_signal_count"] == st["live_signal_count"]  # off keeps what arrived


def test_a_company_paste_is_company_scope_and_reaches_the_book_directly(app_client) -> None:
    r = analyze(app_client, COMPANY)
    s = r["signal"]
    assert r["outcome"] == "NEW" and s["scope_level"] == "COMPANY" and s["ticker"] == "GS" and s["channel"] == "MANUAL"
    assert s["relevance_level"] == "DIRECT" and 0 < s["relevance_share"] < 0.2
    full = app_client.get(f"/api/signals/{s['id']}").json()
    assert full["provenance"]["adapter"] == "manual-paste" and full["scope"]["sector"] == "Financials"
    assert full["model_versions"]["event"].startswith("tfidf-lr-event-v1")  # no encoder installed: the reference model, labelled
    rel = app_client.get(f"/api/signals/{s['id']}/relevance").json()
    assert rel["level"] == "DIRECT" and any(x["kind"] == "ISSUER" for x in rel["slices"])


def test_a_sector_paste_has_no_company_but_a_sector_scope_and_a_stress_that_runs(app_client) -> None:
    s = analyze(app_client, SECTOR)["signal"]
    assert s["scope_level"] == "SECTOR" and s["scope_sector"] == "Technology" and s["ticker"] is None
    assert s["scope_strength"] == "STRONG" and s["relevance_level"] == "SECTOR"
    st = app_client.post("/api/stress-test", json={"signal_id": s["id"], "force": True}).json()
    assert st["status"] == "COMPLETED" and st["audit"]["scope_level"] == "SECTOR"
    assert any(sh["scope"] == "SECTOR" and sh["applicable"] for sh in st["shocks"]) or st["summary"]["pnl"] != 0


def test_a_macro_paste_is_market_scope_and_stays_unresolved_about_companies(app_client) -> None:
    s = analyze(app_client, MACRO)["signal"]
    assert s["scope_level"] == "MARKET" and s["scope_themes"] and s["relevance_level"] == "MARKET_WIDE" and s["relevance_share"] == 1.0
    assert s["entity_id"] == "UNKNOWN_ENTITY"
    full = app_client.get(f"/api/signals/{s['id']}").json()
    assert full["evidence"]["novelty_measured"] is False  # nothing to compare against: not presented as a measurement


def test_nothing_identifiable_is_kept_as_unresolved_with_its_reason_not_discarded(app_client) -> None:
    r = analyze(app_client, UNRESOLVED)
    s = r["signal"]
    assert r["outcome"] == "NEW" and s["scope_level"] == "UNRESOLVED" and s["relevance_level"] == "UNDETERMINED"
    assert s["relevance_share"] is None
    note = app_client.get(f"/api/signals/{s['id']}").json()["scope"]["note"]
    assert "not guessed about" in note


def test_an_unscorable_paste_is_rejected_with_the_reason_and_creates_nothing(app_client) -> None:
    before = app_client.get("/api/signals?channel=MANUAL").json()["total"]
    r = analyze(app_client, "ok")
    assert r["outcome"] == "QUARANTINED" and r["signal"] is None and r["rejection"]["code"] == "TOO_SHORT"
    assert app_client.get("/api/signals?channel=MANUAL").json()["total"] == before


def test_the_same_paste_twice_is_one_signal(app_client) -> None:
    a = analyze(app_client, "Boeing faces a new federal probe after a mid-air door panel failure")
    b = analyze(app_client, "Boeing faces a new federal probe after a mid-air door panel failure")
    assert b["outcome"] == "DUPLICATE" and b["signal_id"] == a["signal_id"]


def test_bad_requests_are_422_not_500(app_client) -> None:
    assert app_client.post("/api/analyze", json={"text": ""}).status_code == 422
    assert app_client.post("/api/analyze", json={"text": "x" * 20001}).status_code == 422
    r = app_client.post("/api/analyze", json={"text": COMPANY, "published_at": "2099-01-01T00:00:00Z"})
    assert r.status_code == 422 and "future" in r.json()["detail"]
    r = app_client.post("/api/analyze", json={"text": COMPANY, "published_at": "2026-10-01T10:00:00"})
    assert r.status_code == 422 and "time zone" in r.json()["detail"]


def test_a_long_article_is_truncated_and_says_so(app_client) -> None:
    r = analyze(app_client, "Fed day in review\n" + "Policymakers discussed inflation and rate cuts at length. " * 80)
    assert r["truncated"] is True and any("first 2000 characters" in n for n in r["notes"])


def test_feed_filters_channel_scope_and_since_seq(app_client) -> None:
    allp = app_client.get("/api/signals").json()
    manual = app_client.get("/api/signals?channel=MANUAL").json()
    replay = app_client.get("/api/signals?channel=REPLAY").json()
    assert manual["total"] >= 4 and replay["total"] == 2330 and allp["total"] == manual["total"] + replay["total"]
    assert all(i["channel"] == "MANUAL" for i in manual["items"]) and all(i["channel"] == "REPLAY" for i in replay["items"])
    sectors = app_client.get("/api/signals?scope_level=SECTOR").json()
    assert sectors["total"] > 0 and all(i["scope_level"] == "SECTOR" for i in sectors["items"])
    assert app_client.get("/api/signals?scope_level=NOPE").status_code == 422
    seq = allp["seq"]
    assert app_client.get(f"/api/signals?since_seq={seq}").json()["total"] == 0
    analyze(app_client, "Pfizer wins approval for a new obesity drug, shares rise in early trading")
    changed = app_client.get(f"/api/signals?since_seq={seq}").json()
    assert changed["total"] == 1 and changed["seq"] > seq and changed["items"][0]["first_seq"] > seq


def test_replay_signals_are_untouched_by_everything_above(app_client) -> None:
    from eventshock.api.deps import get_container  # noqa: F401

    meta = app_client.get("/api/meta").json()
    from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST

    assert meta["replay"]["output_digest"] == GOLDEN_SERVED_DIGEST


def test_demo_profile_has_no_engine_and_says_so(client) -> None:
    r = client.post("/api/analyze", json={"text": COMPANY})
    assert r.status_code == 503 and "replay profile" in r.json()["detail"]
    caps = client.get("/api/meta").json()["capabilities"]
    older = {"analyze": False, "live_enabled": False, "assessment": False, "llm": None, "analogues": False, "history_check": True, "intelligence": False, "propagation": False, "adjustments": True, "custom_portfolios": True}
    assert {k: caps[k] for k in older} == older
    assert not any(v for k, v in caps.items() if k not in older)           # the demo profile serves none of the decision side-cars (monitor, watchlists, scenario lab, explanations, feedback, brief, markets)
    assert client.get("/api/live/status").status_code == 404
    page = client.get("/api/signals").json()
    assert page["seq"] == 0 and all(i["channel"] == "REPLAY" for i in page["items"])
    assert all(i["scope_level"] in {"COMPANY", "UNRESOLVED"} for i in page["items"])
