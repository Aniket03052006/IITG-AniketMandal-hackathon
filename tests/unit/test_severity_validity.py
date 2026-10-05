"""Stage 8: the severity-validity study's statistics and its label rule (synthetic data; the real study needs git-ignored prices)."""

from __future__ import annotations

import numpy as np
import pytest

from eventshock.config import REPO_ROOT
from eventshock.modeling.evidence_v3 import load_evidence_v3
from eventshock.modeling.severity_validity import (
    attach_outcomes,
    band_table,
    cluster_bootstrap,
    decide_label,
    evaluate_split,
    monotone_check,
    regime_baseline,
    spearman,
)
from tests.modeling_helpers import make_store

PRE, _ = load_evidence_v3(REPO_ROOT / "configs")
CFG = PRE["severity_validity"]


class TestSpearman:
    def test_perfect_monotone_and_ties(self):
        assert spearman(np.arange(10.0), np.arange(10.0) ** 3) == pytest.approx(1.0)
        assert spearman(np.arange(10.0), -np.arange(10.0)) == pytest.approx(-1.0)
        assert spearman(np.zeros(10), np.arange(10.0)) != spearman(np.zeros(10), np.arange(10.0))  # constant side -> NaN
        assert spearman(np.arange(3.0), np.arange(3.0)) != spearman(np.arange(3.0), np.arange(3.0))  # too few -> NaN


class TestClusterBootstrap:
    def test_interval_covers_the_truth_and_is_wider_with_date_clustering(self):
        rng = np.random.default_rng(0)
        dates = np.repeat([f"d{i:03d}" for i in range(120)], 6)
        day_shock = np.repeat(rng.standard_normal(120), 6)
        x = rng.standard_normal(dates.size) + day_shock
        y = 0.5 * x + rng.standard_normal(dates.size) + day_shock
        res = cluster_bootstrap({"rho": lambda idx: spearman(x[idx], y[idx])}, dates, resamples=300, seed=1)["rho"]
        assert res["lo"] < res["estimate"] < res["hi"] and res["valid_draws"] > 250
        naive = cluster_bootstrap({"rho": lambda idx: spearman(x[idx], y[idx])}, np.arange(dates.size).astype(str), resamples=300, seed=1)["rho"]
        assert (res["hi"] - res["lo"]) > (naive["hi"] - naive["lo"])  # clustering by date widens the interval

    def test_same_seed_same_answer_and_paired_draws(self):
        dates = np.repeat([f"d{i}" for i in range(60)], 4)
        v = np.random.default_rng(3).standard_normal(dates.size)
        stats = {"a": lambda idx: float(v[idx].mean()), "b": lambda idx: float(v[idx].mean()) + 1.0}
        r1 = cluster_bootstrap(stats, dates, resamples=100, seed=9)
        r2 = cluster_bootstrap(stats, dates, resamples=100, seed=9)
        assert r1 == r2
        assert r1["b"]["lo"] == pytest.approx(r1["a"]["lo"] + 1.0)  # same resamples: a difference of statistics has no extra noise


class TestBands:
    BANDS = {"negligible": [1, 2], "low": [3, 4], "moderate": [5, 6], "high": [7, 8], "extreme": [9, 10]}

    def test_counts_and_wilson_intervals(self):
        score = np.array([0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] * 10)
        tail = np.array([False, False, False, False, False, True, True, True, True, True, True, True] * 10)
        rows = {r["band"]: r for r in band_table(score, tail, self.BANDS)}
        assert rows["abstained"]["n"] == 20 and rows["negligible"]["n"] == 20 and rows["extreme"]["n"] == 20
        assert rows["negligible"]["rate"] == 0.0 and rows["extreme"]["rate"] == 1.0
        assert rows["low"]["wilson_lo"] < rows["low"]["rate"] < rows["low"]["wilson_hi"]
        assert sum(r["n"] for r in rows.values()) == score.size

    def test_empty_band_has_no_rate(self):
        rows = {r["band"]: r for r in band_table(np.array([1, 1, 2]), np.array([False, True, False]), self.BANDS)}
        assert rows["high"]["n"] == 0 and rows["high"]["rate"] is None

    def test_monotonicity_needs_enough_populated_bands(self):
        rows = [{"band": "abstained", "n": 99, "rate": 0.9}, {"band": "a", "n": 40, "rate": 0.05}, {"band": "b", "n": 40, "rate": 0.10},
                {"band": "c", "n": 40, "rate": 0.2}, {"band": "d", "n": 5, "rate": 0.9}]
        m = monotone_check(rows, 30)
        assert m["bands_used"] == 3 and m["spearman"] == pytest.approx(1.0)  # the abstained class and the thin band are not used
        assert monotone_check(rows[:2], 30)["spearman"] is None


def _split(m1, m2, m3, m4, *, mono=(0.9, 4)):
    def est(lo):
        return {"estimate": lo + 0.05, "lo": lo, "hi": lo + 0.1, "valid_draws": 1000}
    return {"metrics": {"M1_overall_rank": est(m1), "M2_within_regime_rank": est(m2), "M3_real_minus_placebo": est(m3), "M4_increment_over_regime": est(m4)},
            "monotone": {"spearman": mono[0], "bands_used": mono[1]}}


class TestLabelRule:
    def test_validated_needs_every_condition_on_both_splits(self):
        ok = {"test": _split(0.05, 0.04, 0.03, 0.02), "live": _split(0.05, 0.04, 0.03, 0.02)}
        assert decide_label(ok, CFG)["label"] == "OUTCOME_VALIDATED"

    def test_one_failing_regime_neutral_check_downgrades_to_directional(self):
        by = {"test": _split(0.05, 0.04, 0.03, -0.01), "live": _split(0.05, 0.04, 0.03, 0.02)}
        assert decide_label(by, CFG)["label"] == "DIRECTIONALLY_INFORMATIVE"

    def test_non_monotone_or_thin_bands_cannot_validate(self):
        by = {"test": _split(0.05, 0.04, 0.03, 0.02, mono=(0.5, 4)), "live": _split(0.05, 0.04, 0.03, 0.02)}
        assert decide_label(by, CFG)["label"] == "DIRECTIONALLY_INFORMATIVE"
        by = {"test": _split(0.05, 0.04, 0.03, 0.02, mono=(0.9, 3)), "live": _split(0.05, 0.04, 0.03, 0.02)}
        assert decide_label(by, CFG)["label"] == "DIRECTIONALLY_INFORMATIVE"

    def test_a_pass_on_test_alone_is_not_enough(self):
        by = {"test": _split(0.05, 0.04, 0.03, 0.02), "live": _split(-0.02, -0.02, -0.02, -0.02)}
        assert decide_label(by, CFG)["label"] == "HEURISTIC_UNCALIBRATED"

    def test_missing_intervals_or_splits_fail_closed(self):
        assert decide_label({}, CFG)["label"] == "HEURISTIC_UNCALIBRATED"
        thin = {"test": {"n": 10, "note": "too few"}, "live": {"n": 10, "note": "too few"}}
        assert decide_label(thin, CFG)["label"] == "HEURISTIC_UNCALIBRATED"
        no_ci = _split(0.05, 0.04, 0.03, 0.02)
        no_ci["metrics"]["M3_real_minus_placebo"]["lo"] = None  # an interval that could not be computed is a failed condition, never a pass
        assert decide_label({"test": no_ci, "live": _split(0.05, 0.04, 0.03, 0.02)}, CFG)["label"] == "DIRECTIONALLY_INFORMATIVE"
        no_m1 = _split(0.05, 0.04, 0.03, 0.02)
        no_m1["metrics"]["M1_overall_rank"]["lo"] = None
        assert decide_label({"test": no_m1, "live": no_m1}, CFG)["label"] == "OUTCOME_VALIDATED"  # M1 is not part of the strong condition


class TestRegimeBaselineAndEvaluation:
    def _rows(self, n, rng, *, signal):
        rows = []
        for i in range(n):
            vix = float(rng.uniform(10, 40))
            y = 0.02 * vix + rng.normal(0, 0.2)
            score = int(np.clip(round((y - 0.4) * 6 + rng.normal(0, 1.5)), 0, 10)) if signal else int(rng.integers(0, 11))
            rows.append({"s0_date": f"2025-{1 + i % 12:02d}-{1 + (i // 12) % 28:02d}", "f_vix_level": vix, "f_resid_vol_5d_ratio": 1.0, "f_resid_vol_20d_ratio": 1.0,
                         "f_sigma_60": 0.02, "y": y, "y_placebo": 0.02 * vix + rng.normal(0, 0.2), "abs_z": abs(rng.normal(0, 1 + vix / 40)), "score": score})
        return rows

    def test_baseline_is_fitted_on_train_only_and_removes_the_regime(self):
        rng = np.random.default_rng(5)
        train, test = self._rows(800, rng, signal=False), self._rows(400, rng, signal=False)
        predict = regime_baseline(train, 1.0)
        resid = np.asarray([r["y"] for r in test]) - predict(test)
        assert abs(np.corrcoef(resid, [r["f_vix_level"] for r in test])[0, 1]) < 0.15
        assert predict(test).shape == (400,)

    def test_missing_covariates_take_the_train_median_instead_of_crashing(self):
        rng = np.random.default_rng(6)
        train = self._rows(300, rng, signal=False)
        predict = regime_baseline(train, 1.0)
        odd = dict(train[0], f_resid_vol_5d_ratio=None)
        assert np.isfinite(predict([odd])).all()

    def test_a_score_that_only_tracks_the_regime_does_not_pass_the_regime_neutral_metrics(self):
        rng = np.random.default_rng(7)
        train, test = self._rows(800, rng, signal=False), self._rows(900, rng, signal=False)
        for r in test:  # score is a pure function of the regime (VIX): it ranks y overall (the regime drives y) but adds nothing
            r["score"] = int(np.clip((r["f_vix_level"] - 10) / 3, 0, 10))
        predict = regime_baseline(train, 1.0)
        res = evaluate_split(test, predict, (17.0, 25.0), CFG, {"resamples": 120, "ci": 0.95}, 1)
        m = res["metrics"]
        assert m["M1_overall_rank"]["lo"] > 0.2  # looks informative overall
        assert m["M4_increment_over_regime"]["lo"] < 0.05 and m["M4_increment_over_regime"]["estimate"] < 0.1  # but nothing beyond the regime

    def test_a_score_with_event_specific_information_passes(self):
        rng = np.random.default_rng(8)
        train, test = self._rows(800, rng, signal=False), self._rows(900, rng, signal=False)
        for r in test:  # score tracks an event component that is independent of the VIX regime
            event = rng.normal(0, 0.4)
            r["y"] = 0.02 * r["f_vix_level"] + event
            r["score"] = int(np.clip(round(5 + event * 6 + rng.normal(0, 1)), 0, 10))
        res = evaluate_split(test, regime_baseline(train, 1.0), (17.0, 25.0), CFG, {"resamples": 120, "ci": 0.95}, 1)
        assert res["metrics"]["M4_increment_over_regime"]["lo"] > 0.2 and res["metrics"]["M2_within_regime_rank"]["lo"] > 0.2

    def test_tiny_splits_are_reported_not_scored(self):
        assert "note" in evaluate_split(self._rows(20, np.random.default_rng(1), signal=False), lambda r: np.zeros(len(r)), (17.0, 25.0), CFG,
                                        {"resamples": 10, "ci": 0.95}, 1)


class TestOutcomeAttachment:
    def test_episodes_without_a_computable_outcome_are_dropped_by_reason(self):
        store = make_store(400)
        eps = [{"ticker": "AAA", "s0": 300, "text": "x"}, {"ticker": "AAA", "s0": 399, "text": "x"}, {"ticker": "AAA", "s0": 50, "text": "x"}]
        kept, dropped = attach_outcomes(eps, store, {"AAA": [300]}, -3)
        assert len(kept) == 1 and dropped["CENSORED"] == 1 and dropped["INSUFFICIENT_HISTORY"] == 1
        e = kept[0]
        assert e["earn_in_target"] is True and e["y"] == pytest.approx(np.log1p(e["abs_z"])) and e["car"] == store.target("AAA", 300)[0].car
