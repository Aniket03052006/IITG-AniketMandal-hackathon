from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eventshock.modeling.market import eligibility_reason, impact_rows, score_from_abs_z
from tests.modeling_helpers import base_config, make_doc, make_store

CFG = base_config()
CUTS = CFG.impact.score_cutpoints


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=UTC)


class TestScore:
    @pytest.mark.parametrize("z,score", [(0.0, 1), (0.49, 1), (0.5, 2), (0.99, 2), (1.0, 3), (2.99, 6), (3.0, 7), (6.99, 9), (7.0, 10), (99, 10)])
    def test_cutpoints_edges(self, z, score):
        assert score_from_abs_z(z, CUTS) == score


class TestAnchoring:
    store = make_store(300)

    def idx(self, iso):
        return self.store.dates.index(iso)

    def test_in_session_report_reacts_in_the_same_session(self):
        # 2020-03-03 is a Tuesday; 15:00 UTC = 10:00 EST
        s0, timing = self.store.anchor(utc(2020, 3, 3, 15), "SOURCE")
        assert (self.store.dates[s0], timing) == ("2020-03-03", "IN_SESSION")

    def test_pre_open_report_is_same_session_but_flagged(self):
        s0, timing = self.store.anchor(utc(2020, 3, 3, 12), "SOURCE")  # 07:00 EST
        assert (self.store.dates[s0], timing) == ("2020-03-03", "PRE_OPEN")

    def test_after_close_goes_to_next_session(self):
        s0, timing = self.store.anchor(utc(2020, 3, 3, 21, 30), "SOURCE")  # 16:30 EST
        assert (self.store.dates[s0], timing) == ("2020-03-04", "OFF_HOURS")

    def test_dst_moves_the_close_by_an_hour_in_utc(self):
        # 2020-07-01: EDT, close is 20:00 UTC, so 20:30 UTC is after the close. In winter 20:30 UTC is 15:30 EST.
        summer, t1 = self.store.anchor(utc(2020, 7, 1, 20, 30), "SOURCE")
        winter, t2 = self.store.anchor(utc(2020, 2, 4, 20, 30), "SOURCE")
        assert (self.store.dates[summer], t1) == ("2020-07-02", "OFF_HOURS")
        assert (self.store.dates[winter], t2) == ("2020-02-04", "IN_SESSION")

    def test_weekend_goes_to_monday(self):
        s0, timing = self.store.anchor(utc(2020, 3, 7, 15), "SOURCE")  # Saturday
        assert (self.store.dates[s0], timing) == ("2020-03-09", "OFF_HOURS")

    def test_date_only_uses_that_date_or_the_next_session(self):
        s0, timing = self.store.anchor(utc(2020, 3, 3), "SOURCE_DATE_ONLY")
        assert (self.store.dates[s0], timing) == ("2020-03-03", "DATE_ONLY")
        s0, _ = self.store.anchor(utc(2020, 3, 7), "SOURCE_DATE_ONLY")  # Saturday -> Monday
        assert self.store.dates[s0] == "2020-03-09"

    def test_gdelt_first_seen_is_flagged_whatever_the_time(self):
        assert self.store.anchor(utc(2020, 3, 3, 15), "GDELT_FIRST_SEEN")[1] == "FIRST_SEEN"

    def test_beyond_the_calendar_has_no_session(self):
        assert self.store.anchor(utc(2030, 1, 1), "SOURCE")[0] is None


class TestTarget:
    def test_a_planted_shock_is_found_with_the_right_sign_and_score(self):
        probe = make_store(400)
        s0 = 300
        sigma = probe.fit_before("AAA", s0)[0].sigma
        store = make_store(400, shock={("AAA", s0): -12 * sigma})
        t, why = store.target("AAA", s0)
        assert why == "" and t is not None
        assert t.z < -5 and t.score == 10 and t.fit.factor_model == "market+sector"

    def test_a_quiet_session_scores_low(self):
        t, _ = make_store(400).target("AAA", 300)
        assert t is not None and t.abs_z < 3

    def test_sector_factor_removes_a_sector_wide_move_that_a_market_model_keeps(self):
        # shock BBB and CCC (AAA's peers) together: AAA's own return is untouched, so AAA's abnormal return stays small
        probe = make_store(400)
        sig = probe.fit_before("BBB", 300)[0].sigma
        store = make_store(400, shock={("BBB", 300): 8 * sig, ("CCC", 300): 8 * sig})
        t, _ = store.target("AAA", 300)
        assert t is not None and t.abs_z < 3

    def test_censored_when_the_window_runs_past_the_data(self):
        store = make_store(400)
        assert store.target("AAA", 399) == (None, "CENSORED")

    def test_insufficient_history(self):
        store = make_store(400)
        assert store.target("AAA", 50) == (None, "INSUFFICIENT_HISTORY")

    def test_market_only_fallback_when_there_are_too_few_peers(self):
        store = make_store(400, sectors={"AAA": "Tech", "DDD": "Energy"})
        t, _ = store.target("AAA", 300)
        assert t is not None and t.fit.factor_model == "market" and t.fit.c == 0.0


class TestPointInTime:
    def test_the_model_fit_ignores_everything_from_s0_on(self):
        store = make_store(400)
        a = store.fit_before("AAA", 300)[0]
        b = store.scrambled_from(300).fit_before("AAA", 300)[0]
        assert a == b

    def test_features_do_not_change_when_the_future_is_scrambled_but_the_target_does(self):
        store = make_store(400)
        scr = store.scrambled_from(300)
        f1, f2 = store.features_asof("AAA", 300), scr.features_asof("AAA", 300)
        assert f1 is not None and f1.keys() == f2.keys()
        assert all(f1[k] == f2[k] or (f1[k] != f1[k] and f2[k] != f2[k]) for k in f1)
        assert store.target("AAA", 300)[0].z != scr.target("AAA", 300)[0].z

    def test_features_do_change_when_the_past_changes(self):
        # sanity check that the invariance test above is not vacuous
        store = make_store(400)
        scr = store.scrambled_from(250)
        assert store.features_asof("AAA", 300)["ret_20d"] != scr.features_asof("AAA", 300)["ret_20d"]


class TestRows:
    def test_eligibility_reasons(self):
        store = make_store(400)
        c = CFG.impact
        assert eligibility_reason(make_doc(1, ticker=None), store, c) == "NO_ISSUER"
        assert eligibility_reason(make_doc(2, multi=True), store, c) == "MULTI_ENTITY"
        assert eligibility_reason(make_doc(3, link=0.6), store, c) == "LOW_LINK_CONFIDENCE"
        assert eligibility_reason(make_doc(4, ticker="ZZZ"), store, c) == "NO_PRICES"
        assert eligibility_reason(make_doc(5, tags=("TSLA",)), store, c) == "DATASET_TICKER_MISMATCH"
        assert eligibility_reason(make_doc(6, tags=("AAA",)), store, c) is None

    def test_rows_carry_target_features_placebo_and_episode_weights(self):
        store = make_store(520)
        d = store.dates
        docs = [make_doc(i, published_at=datetime.fromisoformat(d[300] + "T21:30:00+00:00")) for i in range(3)]
        docs.append(make_doc(9, ticker="BBB", published_at=datetime.fromisoformat(d[300] + "T21:30:00+00:00")))
        rows, drops = impact_rows(docs, store, CFG.impact)
        assert drops == {} and len(rows) == 4
        a = [r for r in rows if r["ticker"] == "AAA"]
        assert {r["episode"] for r in a} == {f"AAA|{d[301]}"} and all(r["episode_size"] == 3 and r["weight"] == pytest.approx(1 / 3) for r in a)
        assert all(r["placebo_abs_z"] is not None and r["s0_date"] == d[301] and "f_sigma_60" in r for r in rows)
        assert rows[0]["timing"] == "OFF_HOURS"

    def test_drop_census_names_every_reason(self):
        store = make_store(400)
        docs = [make_doc(1, ticker=None), make_doc(2, multi=True), make_doc(3, published_at=datetime(2030, 1, 1, tzinfo=UTC))]
        rows, drops = impact_rows(docs, store, CFG.impact)
        assert rows == [] and drops == {"BEYOND_PRICES": 1, "MULTI_ENTITY": 1, "NO_ISSUER": 1}
