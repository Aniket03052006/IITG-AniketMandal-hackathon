"""Providers: deterministic observations from recorded points (a snapshot or a synthetic fixture), no look-ahead, a hash-pinned snapshot, honest state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.markets.models import MarketStatus
from eventshock.markets.provider import PointProvider, load_point_provider, load_records, sha256_of, status_of
from tests.markets_helpers import FIXTURE, fixture_provider

T = datetime(2026, 9, 24, 12, tzinfo=UTC)


def records():  # noqa: ANN201
    return load_records({"schema": "market-points-v1", "markets": [{
        "market_id": "M1", "series_id": "S", "question": "Will X?", "status": "active", "open_time": "2026-09-01T00:00:00Z", "close_time": "2026-12-31T00:00:00Z",
        "points": [{"at": "2026-09-22T12:00:00Z", "p": 0.40, "oi": 100, "vol": 10}, {"at": "2026-09-23T12:00:00Z", "p": 0.45, "oi": 110, "vol": 20},
                   {"at": "2026-09-24T12:00:00Z", "p": 0.60, "oi": 120, "vol": 30}, {"at": "2026-09-26T12:00:00Z", "p": 0.90, "oi": 130, "vol": 40}]}]})


def prov(**kw):  # noqa: ANN003, ANN201
    return PointProvider(name="kalshi", source="kalshi-snapshot", synthetic=False, records=records(), previous_gap_hours=24, mode="snapshot", **kw)


def test_an_observation_is_the_latest_point_at_or_before_the_moment_with_the_previous_one_a_day_earlier():
    (o,) = prov().markets("S", T)
    assert o.probability == 0.60 and o.previous_probability == 0.45 and o.probability_change_pp == pytest.approx(15.0)
    assert o.observed_at == T and o.previous_observed_at == T - timedelta(days=1) and o.market_status is MarketStatus.OPEN and not o.synthetic
    assert o.volume == 60 and o.volume_24h == 30 and o.open_interest == 120 and o.provenance[0].kind.value == "EXTERNAL_MARKET_OBSERVATION" and o.provenance[0].source == "kalshi-snapshot"


def test_replay_never_looks_ahead():
    p = prov()
    assert p.markets("S", datetime(2026, 9, 21, tzinfo=UTC)) == []                               # before the first point: nothing, not a guess
    early = p.markets("S", datetime(2026, 9, 23, 13, tzinfo=UTC))[0]
    assert early.probability == 0.45 and early.previous_probability == 0.40                      # the 09-26 point (0.90) is invisible
    assert p.markets("S", datetime(2026, 8, 30, tzinfo=UTC)) == []                               # before the market opened


def test_no_previous_observation_means_no_change_not_zero():
    o = prov().markets("S", datetime(2026, 9, 22, 13, tzinfo=UTC))[0]
    assert o.previous_probability is None and o.probability_change_pp is None


def test_a_market_after_its_close_time_is_closed():
    assert prov().markets("S", datetime(2027, 1, 5, tzinfo=UTC)) == [] or prov().markets("S", datetime(2027, 1, 5, tzinfo=UTC))[0].market_status is MarketStatus.CLOSED


def test_history_is_the_points_in_a_range_and_unknown_markets_are_empty():
    p = prov()
    assert [(t.day, pr) for t, pr in p.history("M1", datetime(2026, 9, 23, tzinfo=UTC), datetime(2026, 9, 25, tzinfo=UTC))] == [(23, 0.45), (24, 0.60)]
    assert p.history("nope", T - timedelta(days=9), T) == [] and p.markets("OTHER", T) == []


def test_the_state_is_honest_about_what_it_holds():
    s = prov(captured_at=datetime(2026, 10, 5, tzinfo=UTC)).state()
    assert s.state == "AVAILABLE" and s.mode == "snapshot" and not s.synthetic and "captured 2026-10-05" in s.reason and s.observed_through == datetime(2026, 9, 26, 12, tzinfo=UTC)
    f = fixture_provider().state()
    assert f.synthetic and f.mode == "fixture" and "SYNTHETIC FIXTURE" in f.reason
    empty = PointProvider(name="k", source="s", synthetic=False, records=[], previous_gap_hours=24, mode="snapshot").state()
    assert empty.state == "UNAVAILABLE"


def test_a_snapshot_must_match_its_manifest_and_a_fixture_must_be_synthetic(tmp_path):
    f = tmp_path / "snap.json"
    f.write_text(json.dumps({"schema": "market-points-v1", "source": "kalshi-snapshot", "synthetic": False, "markets": []}), encoding="utf-8")
    man = tmp_path / "snap.manifest.json"
    with pytest.raises(ConfigError, match="manifest .* is missing"):
        load_point_provider(f, name="k", previous_gap_hours=24, manifest=man)
    man.write_text(json.dumps({"sha256": sha256_of(f)}), encoding="utf-8")
    assert load_point_provider(f, name="k", previous_gap_hours=24, manifest=man, expect_synthetic=False).state().state == "UNAVAILABLE"       # verified; an empty file says so
    f.write_text(f.read_text(encoding="utf-8").replace("kalshi-snapshot", "tampered"), encoding="utf-8")
    with pytest.raises(ConfigError, match="modified"):
        load_point_provider(f, name="k", previous_gap_hours=24, manifest=man)
    with pytest.raises(ConfigError, match="synthetic"):
        load_point_provider(FIXTURE, name="k", previous_gap_hours=24, expect_synthetic=False)
    with pytest.raises(ConfigError, match="schema"):
        load_records({"schema": "other", "markets": []})


def test_the_committed_snapshot_matches_its_manifest_and_holds_real_probabilities():
    snap = REPO_ROOT / "data" / "external" / "kalshi_snapshot.json"
    if not snap.is_file():
        pytest.skip("no snapshot captured (`make kalshi-snapshot`)")
    p = load_point_provider(snap, name="kalshi", previous_gap_hours=24, manifest=snap.with_suffix(".manifest.json"), expect_synthetic=False)
    s = p.state()
    assert s.state == "AVAILABLE" and not s.synthetic and s.observed_from < s.observed_through
    pts = [pt for r in p._records for pt in r.points if pt.prob is not None]  # noqa: SLF001
    assert pts and all(0.0 <= pt.prob <= 1.0 for pt in pts)


@pytest.mark.parametrize("raw,expected", [("active", MarketStatus.OPEN), ("open", MarketStatus.OPEN), ("closed", MarketStatus.CLOSED), ("finalized", MarketStatus.SETTLED), ("settled", MarketStatus.SETTLED),
                                          ("weird", MarketStatus.UNKNOWN), (None, MarketStatus.UNKNOWN)])
def test_market_status_is_normalised(raw, expected):
    assert status_of(raw) is expected


def test_the_fixture_has_every_scenario_it_promises_and_is_labelled_synthetic_everywhere():
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert d["synthetic"] is True and d["source"] == "fixture" and "SYNTHETIC" in d["note"]
    assert all(m["question"].startswith("[SYNTHETIC FIXTURE]") for m in d["markets"])
    assert {m["status"] for m in d["markets"]} == {"active", "finalized"} and any(all(p["p"] is None for p in m["points"]) for m in d["markets"])
