"""Stage 8 through the real application (replay profile): analogues and the scenario history check are read-only side-cars.

Needs the committed analogue pack (``data/replay/analogues``), the committed floor evidence and the committed shock history.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eventshock.api.main import create_app
from eventshock.config import Settings

ALLOWED = {"OK", "NO_RELIABLE_ANALOGUE", "UNAVAILABLE"}


@pytest.fixture(scope="module")
def own_client(tmp_path_factory):
    """Pasting text switches the (shared) engine to the TF-IDF event model when no encoder is installed, so tests that paste use their own app, never the session-scoped one."""
    d = tmp_path_factory.mktemp("analogues")
    return TestClient(create_app(Settings(profile="replay", journal_path=d / "journal.jsonl", llm_cache_path=d / "llm.jsonl", llm=False)))


def sample_ids(client, n=12):
    page = client.get("/api/signals", params={"limit": 200}).json()
    return [s["id"] for s in page["items"]][:n]


def test_capabilities_announce_both_features(replay_client):
    caps = replay_client.get("/api/meta").json()["capabilities"]
    assert caps["analogues"] is True and caps["history_check"] is True


def test_every_replay_signal_gets_an_honest_answer_never_a_server_error(replay_client):
    statuses = set()
    for sid in sample_ids(replay_client):
        r = replay_client.get(f"/api/signals/{sid}/analogues")
        assert r.status_code == 200, r.text
        a = r.json()
        assert a["status"] in ALLOWED and a["outcome_note"] and a["reason"]
        statuses.add(a["status"])
        if a["status"] == "OK":
            assert 1 <= len(a["items"]) <= 5 and a["aggregate"] is not None
            published = replay_client.get(f"/api/signals/{sid}").json()["document"]["published_at"][:10]
            for it in a["items"]:
                assert it["origin"] == "RETRIEVED" and it["reaction_session"] < published       # strictly earlier than the report
                assert it["similarity"] >= a["similarity_floor"]
        else:
            assert a["items"] == [] and a["aggregate"] is None
    assert statuses <= ALLOWED


def test_answers_are_deterministic(replay_client):
    sid = sample_ids(replay_client, 1)[0]
    assert replay_client.get(f"/api/signals/{sid}/analogues").json() == replay_client.get(f"/api/signals/{sid}/analogues").json()


def test_analogues_never_change_the_assessment_or_the_signal(replay_client):
    sid = sample_ids(replay_client, 1)[0]
    before = (replay_client.get(f"/api/signals/{sid}/assessment").json()["severity"], replay_client.get(f"/api/signals/{sid}").json())
    replay_client.get(f"/api/signals/{sid}/analogues")
    after = (replay_client.get(f"/api/signals/{sid}/assessment").json()["severity"], replay_client.get(f"/api/signals/{sid}").json())
    assert before == after and "analogues" not in after[1]


def test_unknown_signal_is_a_404(replay_client):
    assert replay_client.get("/api/signals/does_not_exist/analogues").status_code == 404


def test_scenario_history_check_covers_every_shock_and_flags_the_unchecked(replay_client):
    sc = replay_client.get("/api/scenarios/scn_macro_rates_shock").json()
    r = replay_client.get("/api/scenarios/scn_macro_rates_shock/history-check")
    assert r.status_code == 200
    body = r.json()
    assert len(body["checks"]) == len(sc["shocks"]) and body["severity_scale"] == 1.0
    by = {(c["factor"], c["scope"]): c for c in body["checks"]}
    assert by[("PD_MULTIPLIER", "MARKET")]["checkable"] is False and "unvalidated assumption" in by[("PD_MULTIPLIER", "MARKET")]["reading"]
    rates = by[("RATES_BPS", "MARKET")]
    assert rates["checkable"] and [h["horizon_sessions"] for h in rates["horizons"]] == [1, 5, 21]
    assert any("probability" in c for c in body["caveats"])


def test_history_check_scales_with_severity_and_validates_input(replay_client):
    big = replay_client.get("/api/scenarios/scn_macro_rates_shock/history-check", params={"severity_scale": 1.5}).json()
    base = replay_client.get("/api/scenarios/scn_macro_rates_shock/history-check").json()
    v = lambda b: next(c["value"] for c in b["checks"] if c["factor"] == "RATES_BPS")  # noqa: E731
    assert v(big) == pytest.approx(1.5 * v(base))
    assert replay_client.get("/api/scenarios/nope/history-check").status_code == 404
    assert replay_client.get("/api/scenarios/scn_macro_rates_shock/history-check", params={"severity_scale": 0}).status_code == 422


def test_text_the_pack_has_not_embedded_is_unavailable_without_an_encoder_not_empty(own_client):
    r = own_client.post("/api/analyze", json={"text": "Quantum Dynamics announces a surprise restructuring after weak demand, shares seen lower"})
    assert r.status_code == 200
    a = own_client.get(f"/api/signals/{r.json()['signal_id']}/analogues").json()
    assert a["status"] in ALLOWED
    if a["status"] == "UNAVAILABLE":
        assert "encoder" in a["reason"]


def test_an_unresolved_report_is_refused_not_matched_to_unrelated_market_history(replay_client):
    page = replay_client.get("/api/signals", params={"limit": 200, "scope_level": "UNRESOLVED"}).json()
    assert page["items"], "the replay pack should hold unresolved reports"
    for s in page["items"][:5]:
        a = replay_client.get(f"/api/signals/{s['id']}/analogues").json()
        assert a["status"] == "NO_RELIABLE_ANALOGUE" and a["items"] == [] and "could not be tied" in a["reason"]
