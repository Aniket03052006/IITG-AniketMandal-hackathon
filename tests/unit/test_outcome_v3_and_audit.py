"""Stage 8: outcome-v3 (EWMA sigma) and the building blocks of the outcome audit. Synthetic prices only (the real audit needs git-ignored data)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.modeling.evidence_v3 import load_evidence_v3
from eventshock.modeling.outcome_audit import (
    auc,
    clean,
    decide_ewma,
    has_session_in,
    icc_design_effect,
    moments,
    regime_gap,
    sample_quiet,
    sibling_share,
    stratified_auc,
    tercile_cuts,
    tercile_of,
)
from eventshock.modeling.outcome_v3 import LAMBDA, ewma_sigma, outcome_v3
from tests.modeling_helpers import make_store

CONFIG = REPO_ROOT / "configs"


class TestOutcomeV3:
    def test_car_and_market_model_are_identical_to_v2_and_only_sigma_differs(self):
        store = make_store(400)
        v2, _ = store.target("AAA", 300)
        v3, why = outcome_v3(store, "AAA", 300)
        assert why == "" and v3 is not None and v2 is not None
        assert v3.car == v2.car and v3.sigma60 == v2.fit.sigma and v3.z60 == v2.z
        assert v3.z == pytest.approx(v3.car / (v3.sigma_ewma * math.sqrt(v3.window_sessions)))
        assert v3.abs_z == abs(v3.z)

    def test_reasons_are_the_same_as_v2(self):
        store = make_store(400)
        assert outcome_v3(store, "AAA", 399) == (None, "CENSORED")
        assert outcome_v3(store, "AAA", 50) == (None, "INSUFFICIENT_HISTORY")

    def test_ewma_is_point_in_time(self):
        store = make_store(400)
        a, _ = outcome_v3(store, "AAA", 300)
        # prices from the report session on are replaced by noise: the sigma (a function of the past) must not move; the car may
        b, _ = outcome_v3(store.scrambled_from(300), "AAA", 300)
        assert a is not None and b is not None
        assert a.sigma_ewma == b.sigma_ewma and a.sigma60 == b.sigma60

    def test_ewma_weights_recent_residuals_more(self):
        calm_then_wild = ewma_sigma(0.01, [0.0] * 50 + [0.05] * 10)
        wild_then_calm = ewma_sigma(0.01, [0.05] * 10 + [0.0] * 50)
        assert calm_then_wild > wild_then_calm
        assert ewma_sigma(0.01, []) == pytest.approx(0.01)
        assert LAMBDA == 0.94

    def test_the_audit_sampler_and_the_shared_function_give_the_same_z(self):
        from eventshock.modeling.outcome_audit import sample_quiet

        store = make_store(520)
        for r in sample_quiet(store, {}, {}, n=25, first_idx=150, seed=11, lam=LAMBDA, exclude_within=2):
            v3, _ = outcome_v3(store, r["ticker"], r["s0"])
            assert v3 is not None and r["z_ewma"] == pytest.approx(v3.z) and r["z60"] == pytest.approx(v3.z60)


class TestStatistics:
    def test_moments_of_a_standard_normal_sample(self):
        z = np.random.default_rng(0).standard_normal(50_000)
        m = moments(z)
        assert abs(m["var"] - 1) < 0.03 and abs(m["excess_kurtosis"]) < 0.15 and abs(m["p_abs_gt_2"] - 0.0455) < 0.006

    def test_moments_ignore_nan_and_handle_tiny_samples(self):
        assert moments([float("nan"), 1.0])["n"] == 1 and moments([float("nan")])["var"] != moments([float("nan")])["var"]

    def test_auc_extremes_and_ties(self):
        assert auc(np.array([3.0, 4.0]), np.array([1.0, 2.0])) == 1.0
        assert auc(np.array([1.0, 2.0]), np.array([3.0, 4.0])) == 0.0
        assert auc(np.array([1.0]), np.array([1.0])) == 0.5
        assert auc(np.array([]), np.array([1.0])) != auc(np.array([]), np.array([1.0]))  # NaN

    def test_regime_gap_is_zero_for_regime_neutral_and_positive_otherwise(self):
        rng = np.random.default_rng(1)
        regime = np.repeat([0, 1, 2], 4000)
        neutral = rng.standard_normal(12000)
        heteroskedastic = neutral * np.where(regime == 2, 2.0, 1.0)
        assert regime_gap(neutral, regime) < 0.1
        assert regime_gap(heteroskedastic, regime) > 1.0
        assert regime_gap(neutral[:50], regime[:50]) != regime_gap(neutral[:50], regime[:50])  # too few -> NaN

    def test_terciles_split_roughly_in_thirds(self):
        vals = list(range(300))
        cuts = tercile_cuts(vals)
        assert [tercile_of(v, cuts) for v in (0, 150, 299)] == [0, 1, 2]
        with pytest.raises(ConfigError):
            tercile_cuts(vals[:10])

    def test_icc_detects_a_common_date_effect(self):
        rng = np.random.default_rng(2)
        groups, values = [], []
        for g in range(200):
            shock = rng.standard_normal() * 2
            for _ in range(5):
                groups.append(f"d{g}")
                values.append(shock + rng.standard_normal() * 0.5)
        r = icc_design_effect(values, groups)
        assert r["icc"] > 0.8 and r["design_effect"] > 3 and r["effective_n"] < 1000 / 3
        indep = icc_design_effect(list(rng.standard_normal(1000)), [f"d{i // 5}" for i in range(1000)])
        assert indep["icc"] < 0.1

    def test_has_session_in(self):
        s = [3, 10, 40]
        assert has_session_in(s, 10, 11) and has_session_in(s, 0, 3) and not has_session_in(s, 11, 39) and not has_session_in([], 0, 9)

    def test_sibling_share_finds_same_ticker_near_duplicates_only(self):
        eps = [
            {"ticker": "AAA", "s0": 10, "text": "Apple unveils new iphone lineup today", "split": "train"},
            {"ticker": "AAA", "s0": 12, "text": "Apple unveils new iphone lineup", "split": "val"},
            {"ticker": "BBB", "s0": 11, "text": "Apple unveils new iphone lineup today", "split": "train"},
            {"ticker": "AAA", "s0": 90, "text": "Apple unveils new iphone lineup today", "split": "train"},
        ]
        r = sibling_share(eps, jaccard=0.5, within_sessions=10)
        assert r["with_sibling"] == 2 and r["split_straddling_pairs"] == 1 and r["share"] == 0.5

    def test_stratified_auc_cannot_be_driven_by_composition(self):
        # event tickers have larger |z| than quiet days overall only because they are more volatile names: within ticker there is no lift
        null = [{"ticker": t, "year": 2024, "z60": z} for t, s in (("A", 1.0), ("B", 3.0)) for z in np.random.default_rng(3).standard_normal(200) * s]
        events = [{"ticker": "B", "s0_date": f"2024-01-{d:02d}", "abs_z": abs(z)} for d, z in enumerate(np.random.default_rng(4).standard_normal(40) * 3.0, 1)
                  for _ in [0]][:28]
        pooled = auc(np.array([e["abs_z"] for e in events]), np.array([abs(r["z60"]) for r in null]))
        strat = stratified_auc(events, null)["auc"]
        assert pooled > 0.6 and abs(strat - 0.5) < 0.12


class TestQuietSample:
    def test_sample_is_seeded_and_avoids_blocked_sessions(self):
        store = make_store(520)
        kwargs = {"n": 200, "first_idx": 150, "seed": 5, "lam": 0.94, "exclude_within": 2}
        taken = {"AAA": {300}}
        a = sample_quiet(store, taken, {}, **kwargs)
        b = sample_quiet(store, taken, {}, **kwargs)
        assert a == b and len(a) == 200
        assert not any(r["ticker"] == "AAA" and 298 <= r["s0"] <= 302 for r in a)
        assert all(r["s0"] >= 150 for r in a)

    def test_earnings_flags(self):
        store = make_store(520)
        earn = {t: list(range(160, 500, 63)) for t in store.sectors}
        rows = sample_quiet(store, {}, earn, n=300, first_idx=150, seed=6, lam=0.94, exclude_within=2)
        for r in rows:
            es = earn[r["ticker"]]
            assert r["earn_in_target"] == any(r["s0"] <= e <= r["s0"] + 1 for e in es)
            assert r["earn_in_window"] == any(r["s0"] - 60 <= e < r["s0"] for e in es)
        assert any(r["earn_in_window"] for r in rows) and any(r["z_ex"] is not None for r in rows)

    def test_a_degenerate_request_fails_loudly(self):
        store = make_store(100)  # fewer sessions than the 120 of history a fit needs: no pair is eligible
        with pytest.raises(ConfigError, match="quiet-day sampler"):
            sample_quiet(store, {}, {}, n=50, first_idx=10, seed=1, lam=0.94, exclude_within=2)


class TestDecisionRule:
    RULE = {"regime_log_variance_gap_reduction_at_least": 0.25, "must_hold_in_both_halves": [["2016-01-04", "2020-12-31"], ["2021-01-01", "2026-12-31"]],
            "overall_null_variance_within": [0.6, 1.6]}

    def _sample(self, ewma_scale_in_high: float, sigma_scale_in_high: float, n: int = 6000):
        rng = np.random.default_rng(9)
        rows = []
        for i in range(n):
            high = i % 3 == 2
            date = "2018-06-01" if i % 2 else "2023-06-01"
            rows.append({"date": date, "vix": 30.0 if high else (10.0 if i % 3 == 0 else 17.0),
                         "z60": float(rng.standard_normal() * (sigma_scale_in_high if high else 1.0)),
                         "z_ewma": float(rng.standard_normal() * (ewma_scale_in_high if high else 1.0))})
        return rows

    def test_adopts_when_ewma_removes_the_regime_dependence(self):
        d = decide_ewma(self._sample(1.0, 1.8), (14.0, 20.0), self.RULE)
        assert d["adopt_ewma"] and d["outcome_version"] == "outcome-v3"

    def test_keeps_v2_when_ewma_is_no_better(self):
        d = decide_ewma(self._sample(1.8, 1.8), (14.0, 20.0), self.RULE)
        assert not d["adopt_ewma"] and d["outcome_version"] == "outcome-v2"

    def test_keeps_v2_when_ewma_is_wildly_mis_scaled(self):
        rows = self._sample(1.0, 1.8)
        for r in rows:
            r["z_ewma"] *= 3.0
        assert not decide_ewma(rows, (14.0, 20.0), self.RULE)["checks"]["overall_ewma_variance_in_range"]


class TestPreregistrationAndOutput:
    def test_the_preregistration_loads_and_is_hashed(self):
        doc, sha = load_evidence_v3(CONFIG)
        assert doc["version"] == "evidence-v3" and len(sha) == 64
        assert doc["outcome_audit"]["adopt_ewma_if"]["regime_log_variance_gap_reduction_at_least"] == 0.25

    def test_a_missing_section_stops_the_run(self, tmp_path):
        (tmp_path / "evidence_v3.yaml").write_text('version: "evidence-v3"\nseed: 1\n')
        with pytest.raises(ConfigError, match="missing"):
            load_evidence_v3(tmp_path)

    def test_wrong_version_is_refused(self, tmp_path):
        (tmp_path / "evidence_v3.yaml").write_text('version: "evidence-v2"\n')
        with pytest.raises(ConfigError, match="version"):
            load_evidence_v3(tmp_path)

    def test_clean_makes_strict_json(self):
        import json

        out = clean({"a": float("nan"), "b": [float("inf"), 1.5], "c": {"d": 2}})
        assert json.dumps(out, allow_nan=False) == '{"a": null, "b": [null, 1.5], "c": {"d": 2}}'
