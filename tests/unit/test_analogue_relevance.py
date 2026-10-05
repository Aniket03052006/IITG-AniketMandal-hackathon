"""Stage 8: the retrieval relevance metrics (pure numpy, no encoder)."""

from __future__ import annotations

import numpy as np
import pytest

from eventshock.config import ConfigError
from eventshock.retrieval.relevance_eval import (
    base_rate,
    lift_at_threshold,
    load_vectors,
    paired_bootstrap,
    precision_and_rr,
    topk,
)


class TestTopK:
    def test_largest_first_and_ties_break_by_lower_index(self):
        sim = np.array([[0.5, 0.9, 0.9, 0.1], [0.3, 0.3, 0.3, 0.3]])
        assert topk(sim, 3).tolist() == [[1, 2, 0], [0, 1, 2]]

    def test_deterministic_across_calls(self):
        sim = np.random.default_rng(0).random((20, 50))
        assert (topk(sim, 5) == topk(sim, 5)).all()


class TestPrecision:
    def test_precision_and_reciprocal_rank(self):
        c_lab = np.array(["A", "B", "B", "A", "B", "B", "B", "B"])
        q_lab = np.array(["A"])
        sim = np.array([[0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2]])      # neighbours in order: A B B A B ...
        p, rr = precision_and_rr(sim, q_lab, c_lab, k=5)
        assert p[0] == pytest.approx(2 / 5) and rr[0] == 1.0
        p2, rr2 = precision_and_rr(sim, np.array(["B"]), c_lab, k=5)
        assert p2[0] == pytest.approx(3 / 5) and rr2[0] == pytest.approx(1 / 2)

    def test_no_relevant_neighbour_scores_zero(self):
        _, rr = precision_and_rr(np.array([[0.9, 0.8, 0.7]]), np.array(["Z"]), np.array(["A", "B", "A"]), k=3)
        assert rr[0] == 0.0

    def test_base_rate_is_the_label_share_of_the_corpus(self):
        assert base_rate(np.array(["A", "B", "C"]), np.array(["A", "A", "B", "B"])).tolist() == [0.5, 0.5, 0.0]


class TestLift:
    def test_a_perfect_retriever_has_lift_over_base_rate(self):
        c_lab = np.array(["A"] * 10 + ["B"] * 90)
        q_lab = np.array(["A"])
        sim = np.array([[0.95] * 5 + [0.1] * 95])  # the five closest are A
        out = lift_at_threshold(sim, q_lab, c_lab, 0.5)
        assert out["neighbours"] == 5 and out["precision"] == 1.0 and out["base_rate"] == pytest.approx(0.1) and out["lift"] == pytest.approx(10.0)

    def test_nothing_above_the_threshold_is_unanswered_not_zero(self):
        out = lift_at_threshold(np.array([[0.2, 0.1, 0.05]]), np.array(["A"]), np.array(["A", "B", "A"]), 0.9)
        assert out["neighbours"] == 0 and out["lift"] is None and out["queries_with_a_neighbour"] == 0


class TestBootstrap:
    def test_interval_contains_the_difference_and_is_reproducible(self):
        rng = np.random.default_rng(1)
        a, b = rng.random(200) + 0.1, rng.random(200)
        r1 = paired_bootstrap(a, b, resamples=400, seed=3)
        assert r1["lo"] < r1["estimate"] < r1["hi"] and r1["lo"] > 0
        assert r1 == paired_bootstrap(a, b, resamples=400, seed=3)

    def test_no_difference_has_an_interval_around_zero(self):
        x = np.random.default_rng(2).random(300)
        r = paired_bootstrap(x, x.copy(), resamples=200, seed=1)
        assert r["lo"] == r["hi"] == r["estimate"] == 0.0


class TestLoadVectors:
    def test_missing_cache_or_text_fails_loudly(self, tmp_path):
        with pytest.raises(ConfigError, match="analogue-embed"):
            load_vectors(tmp_path / "nope.npz", ["x"])
        from eventshock.pipeline.embeddings import text_key

        np.savez(tmp_path / "c.npz", keys=np.array([text_key("known")]), vectors=np.ones((1, 4), dtype=np.float32))
        v = load_vectors(tmp_path / "c.npz", ["known"])
        assert v.shape == (1, 4) and abs(np.linalg.norm(v[0]) - 1) < 1e-3
        with pytest.raises(ConfigError, match="not in the embedding cache"):
            load_vectors(tmp_path / "c.npz", ["unknown"])
