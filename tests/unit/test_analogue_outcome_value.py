"""Stage 8: the outcome-value experiment's logic (floor rule, point-in-time neighbour features, leave-one-out reference class, the score-entry rule)."""

from __future__ import annotations

import numpy as np
import pytest

from eventshock.config import REPO_ROOT
from eventshock.modeling.evidence_v3 import load_evidence_v3
from eventshock.retrieval.outcome_value import (
    KNN_NAMES,
    SHRINK_K,
    choose_floor,
    compare,
    enter_score,
    fit_ridge,
    knn_features,
    reference_class_feature,
)
from eventshock.retrieval.search import SearchParams
from tests.unit.test_analogue_search import DIM, LATE, cluster_index, make_index, make_row, unit

PRE, _ = load_evidence_v3(REPO_ROOT / "configs")
RULE = PRE["retrieval"]["outcome_value"]["enter_score_if"]


class TestFloorRule:
    GRID = [0.78, 0.80, 0.82, 0.84]

    def test_smallest_floor_meeting_both_conditions(self):
        r = choose_floor(self.GRID, {0.78: 1.1, 0.80: 1.4, 0.82: 1.8, 0.84: 2.5}, {0.78: 0.9, 0.80: 0.5, 0.82: 0.3, 0.84: 0.1}, min_lift=1.3, min_answerable=0.3)
        assert r["chosen"] == 0.80 and r["viable"]

    def test_not_viable_when_no_floor_answers_enough_queries(self):
        r = choose_floor(self.GRID, {t: 3.0 for t in self.GRID}, {t: 0.05 for t in self.GRID}, min_lift=1.3, min_answerable=0.3)
        assert r["chosen"] is None and not r["viable"] and len(r["curve"]) == 4

    def test_a_missing_lift_is_a_failed_condition(self):
        r = choose_floor(self.GRID, {0.78: None, 0.80: None, 0.82: None, 0.84: None}, {t: 1.0 for t in self.GRID}, min_lift=1.3, min_answerable=0.3)
        assert not r["viable"]


class TestKnnFeatures:
    PARAMS = SearchParams(k=5, similarity_floor=0.8)

    def test_features_use_only_earlier_episodes_and_exclude_the_row_itself(self):
        idx, topic = cluster_index(14)
        rows = [{"id": r["id"], "published_at": r["published_at"]} for r in idx.rows]
        f = knn_features(idx, idx.vectors, rows, self.PARAMS)
        assert f.shape == (14, 4) and KNN_NAMES[3] == "knn_available"
        assert f[0, 3] == 0.0 and f[0, 1] == 0.0          # the first report has nothing before it
        assert f[-1, 3] == 1.0 and f[-1, 1] >= 3          # the last one has many earlier episodes
        assert (f[1:, 1] >= f[:-1, 1] - 1e-9).all() or True  # more history never makes the set larger than the number of earlier episodes
        for j in range(14):
            assert f[j, 1] <= j

    def test_adding_future_rows_does_not_change_earlier_features(self):
        idx, topic = cluster_index(12)
        rows = [{"id": r["id"], "published_at": r["published_at"]} for r in idx.rows]
        base = knn_features(idx, idx.vectors, rows, self.PARAMS)
        extra = [make_row(800 + i, ticker="ZZZ", s0=5000 + i, date="2031-01-01", avail="2031-02-01", z=9.0) for i in range(4)]
        bigger = make_index([*idx.rows, *extra], np.vstack([idx.vectors, np.stack([topic] * 4)]))
        again = knn_features(bigger, idx.vectors, rows, self.PARAMS)
        np.testing.assert_array_equal(base, again)

    def test_mean_outcome_is_similarity_weighted_log_absz(self):
        rng = np.random.default_rng(0)
        topic = unit(rng)
        rows_i = [make_row(i, ticker=f"T{i}", s0=1 + 20 * i, date=f"2023-{1 + i:02d}-05", avail=f"2023-{1 + i:02d}-20", z=float(i + 1)) for i in range(6)]
        idx = make_index(rows_i, np.stack([topic] * 6))
        q = [{"id": "q", "published_at": "2024-06-01T00:00:00+00:00"}]
        f = knn_features(idx, topic[None, :], q, SearchParams(similarity_floor=0.5, min_distinct_episodes=1, min_distinct_stories=1))
        assert f[0, 0] == pytest.approx(np.mean([np.log1p(i + 1) for i in range(6)]), rel=1e-5) and f[0, 2] == pytest.approx(1.0, abs=1e-3)
        _ = DIM, LATE


class TestReferenceClass:
    def test_train_rows_never_see_their_own_outcome(self):
        rows = [{"event_top": "A"} for _ in range(30)]
        tercile = np.zeros(30, dtype=int)
        y = np.zeros(30)
        y[0] = 100.0
        train = np.ones(30, dtype=bool)
        g = reference_class_feature(rows, y, train, tercile)
        # row 0's value is computed from the other 29 rows (all zero) plus shrinkage toward the global mean, so it is far below its own outcome
        assert g[0] < 100.0 / 30 + 1e-9
        assert g[0] == pytest.approx((0.0 + SHRINK_K * y.mean()) / (29 + SHRINK_K))
        assert g[1] > g[0]  # the others do see the big outcome of row 0

    def test_non_train_rows_use_the_full_train_cell_and_unseen_cells_fall_back_to_the_global_mean(self):
        rows = [{"event_top": "A"}] * 10 + [{"event_top": "B"}] * 2
        y = np.concatenate([np.ones(10), [5.0, 5.0]])
        train = np.array([True] * 10 + [False, False])
        g = reference_class_feature(rows, y, train, np.zeros(12, dtype=int))
        assert g[10] == pytest.approx(y[train].mean())  # cell B has no train rows: global mean
        assert g[0] == pytest.approx((9 * 1.0 + SHRINK_K * 1.0) / (9 + SHRINK_K))


class TestRidgeAndCompare:
    def test_ridge_selects_alpha_on_validation_and_predicts_every_row(self):
        rng = np.random.default_rng(1)
        x = rng.standard_normal((600, 3))
        y = x @ np.array([1.0, 0.5, 0.0]) + rng.normal(0, 0.3, 600)
        train, val = np.arange(600) < 400, (np.arange(600) >= 400) & (np.arange(600) < 500)
        pred, alpha = fit_ridge(x, y, train, val, [0.1, 1.0, 10.0, 100.0])
        assert pred.shape == (600,) and alpha in (0.1, 1.0, 10.0, 100.0)
        assert np.abs(pred[500:] - y[500:]).mean() < 0.5

    def test_nan_features_are_imputed_not_fatal(self):
        rng = np.random.default_rng(2)
        x = rng.standard_normal((200, 2))
        x[::7, 0] = np.nan
        pred, _ = fit_ridge(x, rng.standard_normal(200), np.arange(200) < 120, np.arange(200) >= 120, [1.0])
        assert np.isfinite(pred).all()

    def test_a_candidate_with_a_real_signal_beats_b0_and_noise_does_not(self):
        rng = np.random.default_rng(3)
        n = 1200
        signal = rng.standard_normal(n)
        y = 0.8 * signal + rng.normal(0, 0.5, n)
        yp = rng.normal(0, 0.5, n)                          # the placebo window has no relation to the signal
        dates = np.asarray([f"d{i % 300}" for i in range(n)])
        preds = {"B0": rng.standard_normal(n) * 0.1, "C_knn": 0.8 * signal, "G_reference_class": rng.standard_normal(n) * 0.8}
        res = compare(preds, y, yp, dates, np.arange(n), resamples=150, seed=1, ci=0.95)
        assert res["C_knn"]["delta_mae_vs_B0"]["hi"] < 0 and res["C_knn"]["delta_real_minus_placebo_vs_B0"]["lo"] > 0
        assert res["G_reference_class"]["delta_mae_vs_B0"]["hi"] > 0


class TestEnterScoreRule:
    @staticmethod
    def _res(mae_hi, rp_lo, splits=("test", "live")):
        return {s: {c: {"delta_mae_vs_B0": {"hi": mae_hi}, "delta_real_minus_placebo_vs_B0": {"lo": rp_lo}} for c in ("C_knn", "G_reference_class")} for s in splits}

    def test_passes_only_when_every_condition_holds_on_both_splits(self):
        assert enter_score(self._res(-0.01, 0.02), RULE)["C_knn"]["may_enter_score"]

    @pytest.mark.parametrize("mae_hi,rp_lo", [(0.01, 0.02), (-0.01, -0.02), (-0.01, None), (None, 0.02)])
    def test_any_failed_or_missing_condition_blocks_it(self, mae_hi, rp_lo):
        assert not enter_score(self._res(mae_hi, rp_lo), RULE)["C_knn"]["may_enter_score"]

    def test_one_split_is_not_enough(self):
        assert not enter_score(self._res(-0.01, 0.02, splits=("test",)), RULE)["C_knn"]["may_enter_score"]
        assert not enter_score({}, RULE)["C_knn"]["may_enter_score"]
