"""Score calibration, attribution and the evaluation protocol of the impact model (the pieces that make its numbers trustworthy)."""

from __future__ import annotations

import numpy as np
import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.modeling import impact_train as T
from eventshock.modeling.impact_stats import make_view, spearman
from eventshock.pipeline.config import load_impact_model_config
from eventshock.pipeline.impact_model import (
    attribute_row,
    calibrate_value,
    interp,
    score_knots,
    to_score,
)
from tests.modeling_helpers import base_config

CFG = load_impact_model_config(REPO_ROOT / "configs")
CUTS = list(base_config().impact.score_cutpoints)


def _cal(pred, absz, score):
    return T.build_calibration(CFG, np.asarray(pred, float), np.asarray(absz, float), np.asarray(score, int), CUTS)


class TestScoreMapping:
    def test_knots_and_integer_convention(self):
        xs, ys = score_knots(CUTS, 14.0)
        assert xs[0] == 0.0 and xs[-1] == 14.0 and ys == [float(i) for i in range(11)]
        # the integer score is ceil(value), min 1: the same convention as ImpactAssessment.raw
        assert [to_score(v) for v in (0.0, 0.2, 1.0, 1.0001, 6.5, 10.0, 12.0)] == [1, 1, 1, 2, 7, 10, 10]

    def test_interp_is_clamped_and_monotone(self):
        xs, ys = [0.0, 1.0, 1.0, 3.0], [0.0, 1.0, 2.0, 4.0]
        assert interp(-5, xs, ys) == 0.0 and interp(9, xs, ys) == 4.0
        vals = [interp(x, xs, ys) for x in np.linspace(0, 3, 50)]
        assert all(b >= a for a, b in zip(vals, vals[1:], strict=False))

    def test_calibration_is_monotone_and_covers_the_range(self):
        rng = np.random.default_rng(0)
        absz = np.abs(rng.standard_t(4, 3000)) * 0.9
        score = np.array([1 + sum(a >= c for c in CUTS) for a in absz])
        pred = np.log1p(absz) * 0.3 + rng.normal(0, 0.05, 3000)  # an imperfect but informative predictor
        cal = _cal(pred, absz, score)
        grid = np.linspace(pred.min() - 1, pred.max() + 1, 400)
        vals = [calibrate_value(cal, g)[0] for g in grid]
        assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:], strict=False))
        assert calibrate_value(cal, pred.min() - 5)[1] == 1 and calibrate_value(cal, pred.max() + 5)[1] >= 8

    def test_the_reference_distribution_is_the_one_it_was_given(self):
        """Fit-invariance in miniature: the calibration is a pure function of the reference predictions it is handed."""
        rng = np.random.default_rng(1)
        absz = np.abs(rng.normal(0, 1, 1000))
        score = np.array([1 + sum(a >= c for c in CUTS) for a in absz])
        pred = np.log1p(absz) + rng.normal(0, 0.2, 1000)
        a, b = _cal(pred, absz, score), _cal(pred.copy(), absz.copy(), score.copy())
        assert a == b

    def test_bins_report_what_comparable_events_realised(self):
        rng = np.random.default_rng(2)
        absz = np.abs(rng.standard_t(3, 4000))
        score = np.array([1 + sum(x >= c for c in CUTS) for x in absz])
        pred = np.log1p(absz) + rng.normal(0, 0.3, 4000)
        cal = _cal(pred, absz, score)
        meds = [b["severity_q50"] for b in cal["bins"]]
        assert meds == sorted(meds)  # higher predicted score, higher realised severity (the informative-predictor case)
        assert all(b["n_episodes"] >= 1 for b in cal["bins"])
        assert cal["bins"][0]["score_low"] == 1 and cal["bins"][-1]["score_high"] == 10


class TestAttribution:
    def _fit(self, additive: bool):
        rng = np.random.default_rng(3)
        X = rng.normal(size=(1500, 5))
        y = 0.4 * X[:, 0] + 0.2 * np.abs(X[:, 1]) + (0.3 * X[:, 2] * X[:, 3] if not additive else 0.0) + rng.normal(0, 0.05, 1500)
        est = T._hgb(additive, 3, 120, 0.1, 20, 1.0, 0)
        est.fit(X, y)
        return est, X

    def test_additive_model_attributions_sum_to_the_prediction_exactly(self):
        est, X = self._fit(True)
        ref = [float(v) for v in np.median(X, axis=0)]
        for row in X[:40]:
            contrib, base, full = attribute_row(est, ref, [float(v) for v in row])
            assert base + sum(contrib) == pytest.approx(full, abs=1e-9)

    def test_an_interacting_model_does_not_claim_exactness(self):
        est, X = self._fit(False)
        ref = [float(v) for v in np.median(X, axis=0)]
        errs = [abs(b + sum(c) - f) for c, b, f in (attribute_row(est, ref, [float(v) for v in r]) for r in X[:60])]
        assert max(errs) > 1e-3  # which is why the card says `exact: false` for it and the UI says so

    def test_a_feature_equal_to_the_reference_contributes_nothing(self):
        est, X = self._fit(True)
        ref = [float(v) for v in np.median(X, axis=0)]
        contrib, _b, _f = attribute_row(est, ref, ref)
        assert all(abs(c) < 1e-12 for c in contrib)


class TestProtocol:
    def _frame(self, n=4000):
        rng = np.random.default_rng(5)
        s0 = np.sort(rng.integers(300, 1900, n))
        dates = np.array([f"{2015 + int(s // 250):04d}-{1 + int((s % 250) // 21):02d}-{1 + int(s % 21):02d}" for s in s0])
        split = np.where(dates <= "2019-12-31", "train", np.where(dates <= "2020-12-31", "val", "test"))
        ep = np.array([f"E{int(s)}-{int(i % 5)}" for i, s in enumerate(s0)])
        X = rng.normal(size=(n, len(T.feature_names("ISSUER", "R3"))))
        absz = np.abs(rng.normal(0, 1, n)) * np.exp(0.3 * X[:, 0])
        return T.Frame(
            scope="ISSUER", n=n, names=T.feature_names("ISSUER", "R3"), X=X, split=split, ep=ep, s0=s0, date=dates,
            ticker=np.array(["AAA"] * n), adapter=np.array(["top-tweets"] * n), timing=np.array(["OFF_HOURS"] * n),
            origin=np.array(["SOURCE"] * n), event_top=np.array(["MARKET_VALUATION"] * n), event_status=np.array(["CLASSIFIED"] * n),
            y=np.log1p(absz), absz=absz, z=absz, score=np.array([1 + sum(a >= c for c in CUTS) for a in absz]),
            placebo=absz, absz_w1=absz, absz_w3=absz, weight=np.ones(n), texts=[""] * n, sent=np.zeros(n), p_none=np.zeros(n),
            month=np.array(["01"] * n))

    def test_rolling_folds_are_chronological_purged_and_disjoint(self):
        fr = self._frame()
        folds = T.rolling_folds(fr, CFG)
        assert len(folds) >= 3
        for train, test, _label in folds:
            assert fr.s0[train].max() + CFG.folds.embargo_sessions <= fr.s0[test].min()
            assert not set(fr.ep[train]) & set(fr.ep[test])
            assert set(fr.split[train]) == {"train"} and set(fr.split[test]) == {"train"}  # val/test/live never enter a fold
        assert T.check_rolling_folds(fr, folds, CFG.folds.embargo_sessions)[0].severity == "INFO"

    def test_an_injected_overlap_is_caught(self):
        fr = self._frame()
        train, test, label = T.rolling_folds(fr, CFG)[2]
        bad = np.concatenate([train, test[:5]])
        assert T.check_rolling_folds(fr, [(bad, test, label)], CFG.folds.embargo_sessions)[0].severity == "ERROR"

    def test_fitting_on_held_out_rows_is_refused(self):
        fr = self._frame()
        step = next(s for s in CFG.ladder if s.id == "R2-ridge")
        cols = {r: fr.cols(T.feature_names("ISSUER", r)) for r in ("R2", "R3")}
        with pytest.raises(AssertionError, match="held-out"):
            T.fit_step(step, {"alpha": 10.0}, fr, fr.idx("train", "val"), CFG, cols)

    def test_issuer_weight_cap_limits_any_single_issuer(self):
        fr = self._frame()
        k = np.arange(fr.n) % 20
        fr.ticker = np.where(k < 14, "BIG", np.array([f"S{i}" for i in range(20)])[k])  # BIG has 70% of the rows, 6 small issuers
        w = T.fit_weights(fr, fr.idx("train"), 0.30)
        tick = fr.ticker[fr.idx("train")]
        assert w[tick == "BIG"].sum() / w.sum() <= 0.30 + 1e-9
        assert w.mean() == pytest.approx(1.0)
        # an unmeetable cap (2 issuers, 15% each) is skipped, not an error
        fr.ticker = np.where(np.arange(fr.n) % 2 == 0, "A", "B")
        assert T.fit_weights(fr, fr.idx("train"), 0.15).mean() == pytest.approx(1.0)

    def test_a_constant_prediction_has_no_rank_skill(self):
        assert spearman(np.full(50, 0.3) + 1e-15 * np.arange(50), np.arange(50.0)) != spearman(np.arange(50.0), np.arange(50.0))
        assert np.isnan(spearman(np.full(50, 0.3), np.arange(50.0)))

    def test_episode_view_collapses_rows_of_one_episode(self):
        ep = np.array(["a", "a", "b", "b", "b", "c"])
        v = make_view(ep, np.arange(6.0), np.arange(6.0), np.ones(6, int), np.full(6, np.nan))
        assert v.n_ep == 3 and v.n_rows == 6
        assert list(v.aggregate(np.array([1.0, 3.0, 2.0, 2.0, 2.0, 9.0]))) == [2.0, 2.0, 9.0]

    def test_unevaluable_checks_never_count_as_passes(self):
        # an empty/short evaluation: every check that needs data returns passed=None, so `met` is False
        class E:
            view = type("V", (), {"n_ep": 0})()

        cal = T.CalibrationCard(method="x", reference_episodes=1, reference_period="-", extreme_score=7, base_rate_extreme=0.04,
                                bins_reference=[], bins_heldout=[], nominal_coverage=0.8, heldout_coverage=T.estimate(None))
        checks = T._acceptance(CFG, [], "R2-additive", "R2-ridge", cal, None, 100, ["[INFO] ok"])
        assert [c.id for c in checks] == [f"C{i}" for i in range(1, 9)]
        assert all(c.passed is not True for c in checks if c.id != "C6")
        assert next(c for c in checks if c.id == "C6").passed is True


def test_the_config_forbids_unknown_keys(tmp_path):
    (tmp_path / "impact_model.yaml").write_text((REPO_ROOT / "configs" / "impact_model.yaml").read_text() + "\nbogus: 1\n")
    with pytest.raises(ConfigError):
        load_impact_model_config(tmp_path)
