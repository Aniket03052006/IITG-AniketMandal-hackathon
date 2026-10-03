"""The frozen market-context pack: serving must agree with training on anchoring and on features, and cannot see the future."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from eventshock.config import ConfigError
from eventshock.modeling.market_pack import build_context_payload
from eventshock.pipeline.market_context import NEXT, MarketContext, anchor_session, quantize
from tests.modeling_helpers import make_store

STORE = make_store(300)
RATES = None


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def _payload():
    return build_context_payload(STORE, sorted(STORE.sectors), RATES, date.fromisoformat(STORE.dates[-12]))


class TestAnchorParity:
    @pytest.mark.parametrize("ts,origin", [
        (utc(2020, 3, 3, 15), "SOURCE"), (utc(2020, 3, 3, 12), "SOURCE"), (utc(2020, 3, 3, 21, 30), "SOURCE"),
        (utc(2020, 7, 1, 20, 30), "SOURCE"), (utc(2020, 2, 4, 20, 30), "SOURCE"), (utc(2020, 3, 7, 15), "SOURCE"),
        (utc(2020, 3, 3), "SOURCE_DATE_ONLY"), (utc(2020, 3, 7), "SOURCE_DATE_ONLY"), (utc(2020, 3, 3, 15), "GDELT_FIRST_SEEN"),
    ])
    def test_training_and_serving_use_one_anchor(self, ts, origin):
        assert STORE.anchor(ts, origin) == anchor_session(STORE.dates, ts, origin, STORE.session_rules())

    def test_beyond_the_calendar_has_no_anchor_unless_next_is_allowed(self):
        last = STORE.dates[-1]
        y, m, d = (int(x) for x in last.split("-"))
        ts = utc(y, m, d, 22)  # after the last close
        assert anchor_session(STORE.dates, ts, "SOURCE", STORE.session_rules()) == (None, "OFF_HOURS")
        s0, timing = anchor_session(STORE.dates, ts, "SOURCE", STORE.session_rules(), allow_next=True)
        assert (s0, timing) == (len(STORE.dates), "OFF_HOURS")


class TestPack:
    def test_deterministic_and_self_digesting(self):
        a, b = _payload(), _payload()
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        assert a["digest"]

    def test_pack_features_equal_the_training_features_to_the_quantisation(self):
        ctx = MarketContext(_payload())
        t = "AAA"
        for key in (STORE.dates[-8], STORE.dates[-1]):
            raw = STORE.features_asof(t, STORE.dates.index(key))
            got = ctx.issuer_features(t, key)
            assert raw is not None and got is not None
            for k, v in raw.items():
                want = quantize(v)
                assert (got[k] != got[k]) if want != want else got[k] == want

    def test_next_session_exists_and_reads_only_existing_sessions(self):
        ctx = MarketContext(_payload())
        assert ctx.issuer_features("AAA", NEXT) is not None
        raw = STORE.features_asof("AAA", len(STORE.dates))
        assert raw is not None and ctx.issuer_features("AAA", NEXT)["ret_1d"] == quantize(raw["ret_1d"])

    def test_features_do_not_change_when_the_future_is_scrambled(self):
        """The future-invariance check, through the serving path: a pack built from prices that are noise from s0 on, read at
        s0, must be identical to the pack built from the real prices."""
        idx = len(STORE.dates) - 6
        p_real = build_context_payload(STORE, ["AAA", "BBB"], RATES, date.fromisoformat(STORE.dates[idx]))
        p_scr = build_context_payload(STORE.scrambled_from(idx), ["AAA", "BBB"], RATES, date.fromisoformat(STORE.dates[idx]))
        key = STORE.dates[idx]
        assert p_real["issuer"]["AAA"][key] == p_scr["issuer"]["AAA"][key]
        assert p_real["market"][key] == p_scr["market"][key]
        later = STORE.dates[idx + 2]  # a later session reads sessions >= idx: it MAY differ (it has seen the scrambled prices)
        assert p_real["issuer"]["AAA"][later] != p_scr["issuer"]["AAA"][later]

    def test_anchor_next_and_gap(self):
        ctx = MarketContext(_payload())
        y, m, d = (int(x) for x in ctx.last_session.split("-"))
        key, timing, why = ctx.anchor(utc(y, m, d, 22), "SOURCE")
        assert (key, timing, why) == (NEXT, "OFF_HOURS", None)
        key, _t, why = ctx.anchor(utc(y + 1, m, 1, 15), "SOURCE")
        assert key is None and "days after the last known session" in why

    def test_a_hand_edited_pack_is_refused(self):
        payload = _payload()
        payload["issuer"]["AAA"][STORE.dates[-1]]["sigma_60"] = 0.5
        with pytest.raises(ConfigError, match="digest"):
            MarketContext(payload)

    def test_missing_pieces_fail_loudly(self):
        payload = _payload()
        del payload["calendar"]
        with pytest.raises(ConfigError, match="missing"):
            MarketContext(payload)


class TestMarketScopeTarget:
    def test_market_target_matches_a_hand_computation(self):
        s0 = 250
        fit = STORE.market_fit_before(s0)
        assert fit is not None
        mu, sigma = fit
        m = STORE.ret[STORE.market]
        tgt, why = STORE.market_target(s0)
        assert why == "" and tgt is not None
        car = (m[s0] - mu) + (m[s0 + 1] - mu)
        assert tgt.car == pytest.approx(car)
        assert tgt.z == pytest.approx(car / (sigma * 2 ** 0.5))

    def test_censored_and_short_history_are_reasons_not_fills(self):
        assert STORE.market_target(len(STORE.dates) - 1)[1] == "CENSORED"
        assert STORE.market_target(10)[1] == "INSUFFICIENT_HISTORY"

    def test_market_features_unchanged_when_the_future_is_scrambled(self):
        s0 = 200
        base = STORE.market_features_asof(s0, None)
        scr = STORE.scrambled_from(s0).market_features_asof(s0, None)
        assert base is not None and scr is not None
        assert {k: (v if v == v else None) for k, v in base.items()} == {k: (v if v == v else None) for k, v in scr.items()}
