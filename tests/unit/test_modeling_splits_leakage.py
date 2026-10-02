from __future__ import annotations

import random
from datetime import date

import pytest

from eventshock.modeling.leakage import (
    FEATURE_REGISTRY,
    LeakageError,
    bootstrap_ci,
    check_features,
    duplicate_rate,
    future_invariance,
    group_straddle,
    metadata_baseline,
    require_clean,
    spearman,
    time_order,
)
from eventshock.modeling.splits import assign_impact_splits, impact_split
from tests.modeling_helpers import base_config, business_days, make_store

SCFG = base_config().splits.impact
DATES = business_days(date(2022, 1, 3), 400)  # 2022-01-03 .. mid 2023


def idx(iso):
    return DATES.index(iso)


class TestImpactSplit:
    def test_periods_follow_the_config_dates(self):
        assert impact_split(idx("2022-02-01"), DATES, SCFG) == "train"
        assert impact_split(idx("2022-05-02"), DATES, SCFG) == "val"
        assert impact_split(idx("2022-08-01"), DATES, SCFG) == "test"
        assert impact_split(idx("2023-01-03"), DATES, SCFG) == "gap"

    def test_embargo_drops_the_last_sessions_before_the_next_period(self):
        first_val = idx("2022-04-01")
        assert impact_split(first_val - 6, DATES, SCFG) == "train"
        assert impact_split(first_val - 5, DATES, SCFG) == "embargo"
        assert impact_split(first_val - 1, DATES, SCFG) == "embargo"
        first_test = idx("2022-07-01")
        assert impact_split(first_test - 1, DATES, SCFG) == "embargo"

    def test_live_period_is_never_mixed_with_the_others(self):
        dates = [*DATES, "2026-03-02"]
        assert impact_split(len(dates) - 1, dates, SCFG) == "live"

    def test_assign_stamps_rows_and_counts(self):
        rows = [{"s0": idx("2022-02-01")}, {"s0": idx("2022-05-02")}]
        counts = assign_impact_splits(rows, DATES, SCFG)
        assert [r["split"] for r in rows] == ["train", "val"] and counts == {"train": 1, "val": 1}


class TestTimeAndGroups:
    def test_time_order_is_clean_after_assignment(self):
        rows = [{"s0": i} for i in range(0, 400, 7)]
        assign_impact_splits(rows, DATES, SCFG)
        assert not [f for f in time_order(rows, DATES, 5) if f.severity == "ERROR"]

    def test_time_order_catches_overlapping_periods(self):
        rows = [{"s0": 100, "split": "train"}, {"s0": 102, "split": "val"}]
        errs = [f for f in time_order(rows, DATES, 5) if f.severity == "ERROR"]
        assert errs and "embargo" in errs[0].detail

    def test_group_straddle_fires_on_an_injected_leak_and_is_silent_on_clean_data(self):
        clean = [{"episode": "A", "split": "train"}, {"episode": "B", "split": "val"}]
        assert group_straddle(clean, "episode")[0].severity == "INFO"
        leaky = [*clean, {"episode": "A", "split": "test"}]
        f = group_straddle(leaky, "episode")[0]
        assert f.severity == "ERROR" and "A" in f.detail

    def test_require_clean_raises_on_error_only(self):
        ok = group_straddle([{"g": 1, "split": "train"}], "g")
        assert require_clean(ok) == ok
        with pytest.raises(LeakageError):
            require_clean(group_straddle([{"g": 1, "split": "train"}, {"g": 1, "split": "val"}], "g"))


class TestDuplicates:
    train = ["Tesla recalls 50,000 vehicles over seat belt defect in the United States today",
             "Fed holds interest rates steady and signals two cuts later this year"]

    def test_detects_a_near_duplicate_across_splits(self):
        ev = ["Tesla recalls 50,000 vehicles over seat belt defect in the United States", "Totally unrelated oil news from Norway"]
        f = duplicate_rate(self.train, ev, 0.7, "x", max_rate=0.1)[0]
        assert f.severity == "ERROR" and "1/2" in f.detail

    def test_clean_when_nothing_overlaps(self):
        assert duplicate_rate(self.train, ["Apple unveils a new phone with a faster chip"], 0.7, "x", 0.0)[0].severity == "INFO"

    def test_exact_duplicate_differing_only_in_case_and_links_is_caught(self):
        ev = ["TESLA RECALLS 50,000 vehicles over seat belt defect in the United States today https://t.co/abc"]
        assert duplicate_rate(self.train, ev, 0.99, "x", 0.0)[0].severity == "ERROR"


class TestFeatureAvailability:
    def test_event_time_features_pass(self):
        assert check_features(["text", "f_sigma_60", "novelty"])[0].severity == "INFO"

    @pytest.mark.parametrize("name", ["source_count", "coverage_velocity", "recent_mention_count", "ticker", "year", "adapter",
                                      "same_day_return", "episode_size", "placeholder_event", "abs_z"])
    def test_post_event_and_shortcut_features_are_rejected(self, name):
        f = check_features(["text", name])
        assert len(f) == 1 and f[0].severity == "ERROR" and name in f[0].detail

    def test_unregistered_features_are_rejected_until_someone_justifies_them(self):
        f = check_features(["brand_new_feature"])
        assert f[0].severity == "ERROR" and "UNREGISTERED" in f[0].detail

    def test_every_feature_the_audit_uses_is_registered_as_event_time(self):
        from eventshock.modeling.audit import IMPACT_FEATURES

        assert all(FEATURE_REGISTRY[f][0] == "AT_EVENT_TIME" for f in IMPACT_FEATURES)


class TestFutureInvariance:
    def test_clean_store_passes(self):
        store = make_store(400)
        assert future_invariance(store, [("AAA", 300), ("BBB", 320)])[0].severity == "INFO"

    def test_a_feature_that_peeks_at_s0_is_caught(self, monkeypatch):
        from eventshock.modeling import market

        real = market.PriceStore.features_asof

        def leaky(self, t, s0):
            out = real(self, t, s0)
            out["ret_same_day"] = self.ret[t][s0]  # the reaction session's own return: a leak
            return out

        monkeypatch.setattr(market.PriceStore, "features_asof", leaky)
        f = future_invariance(make_store(400), [("AAA", 300)])[0]
        assert f.severity == "ERROR" and "ret_same_day" in f.detail


class TestSkillMeasures:
    def test_spearman_known_values(self):
        assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
        assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
        assert spearman([1, 2, 2, 3], [1, 2, 2, 3]) == pytest.approx(1.0)  # ties
        assert spearman([1, 2], [1, 2]) != spearman([1, 2], [1, 2])  # fewer than 3 points -> nan

    def test_metadata_baseline_finds_a_planted_issuer_shortcut_and_none_in_noise(self):
        rng = random.Random(0)
        tickers = ["A", "B", "C", "D"]

        def rows(planted):
            return [{"ticker": t, "adapter": "x", "m": "01", "weight": 1.0,
                     "y": (tickers.index(t) if planted else 0) + rng.gauss(0, 1)} for t in tickers for _ in range(150)]

        keys = [lambda r: r["ticker"], lambda r: r["adapter"], lambda r: r["m"]]
        assert metadata_baseline(rows(True), rows(True), "y", keys)["spearman"] > 0.4
        assert abs(metadata_baseline(rows(False), rows(False), "y", keys)["spearman"]) < 0.15

    def test_bootstrap_interval_brackets_the_estimate(self):
        rng = random.Random(1)
        x = [rng.random() for _ in range(300)]
        y = [a + rng.gauss(0, 0.5) for a in x]
        lo, hi = bootstrap_ci(x, y, n=100)
        assert lo < spearman(x, y) < hi
