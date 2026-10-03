"""The battery must report ~zero for information-free text and detect a planted effect: otherwise its verdicts mean nothing."""

from __future__ import annotations

import numpy as np

from eventshock.modeling import impact_regime as R
from eventshock.modeling.impact_stats import spearman


def synthetic(n=6000, text_effect=0.0, seed=0):
    rng = np.random.default_rng(seed)
    issuer = rng.integers(0, 20, n)
    vol = np.abs(rng.normal(0, 1, n)) + 0.3 * (issuer % 5)
    text = rng.normal(0, 1, n)                      # a "text" feature: random unless it carries signal
    y = 0.8 * vol + text_effect * text + rng.normal(0, 0.5, n)
    return issuer, vol, text, y


def fit_predict(vol, text, y, tr, use_text):
    X = np.column_stack([vol, text]) if use_text else vol[:, None]
    A = np.column_stack([X[tr], np.ones(len(tr))])
    beta = np.linalg.lstsq(A, y[tr], rcond=None)[0]
    return lambda Z: np.column_stack([Z, np.ones(len(Z))]) @ beta, X


def run(text_effect):
    issuer, vol, text, y = synthetic(text_effect=text_effect)
    tr, te = np.arange(0, 4000), np.arange(4000, 6000)
    pw, Xw = fit_predict(vol, text, y, tr, True)
    po, Xo = fit_predict(vol, text, y, tr, False)
    return issuer, vol, y, tr, te, pw, Xw, po, Xo


def test_no_information_in_text_means_no_increment_and_no_permutation_effect():
    _, _, y, _, te, pw, Xw, po, Xo = run(0.0)
    inc = R.block_increment(pw(Xw[te]), po(Xo[te]), y[te])
    assert inc["lo"] < 0.01 and inc["hi"] > -0.01                  # the interval straddles ~0: nothing to find
    eff = R.permutation_effect(pw, Xw[te], [1], np.zeros(len(te), int), y[te], y[te], repeats=50, seed=1)
    assert abs(eff["spearman_lost"]) < 0.02 and abs(eff["mae_added"]) < 0.02


def test_a_planted_text_effect_is_detected_by_every_tool():
    _, _, y, _, te, pw, Xw, po, Xo = run(0.6)
    inc = R.block_increment(pw(Xw[te]), po(Xo[te]), y[te])
    assert inc["hi"] < 0                                            # the block helps, with an interval below zero
    eff = R.permutation_effect(pw, Xw[te], [1], np.zeros(len(te), int), y[te], y[te], repeats=50, seed=1)
    assert eff["spearman_lost"] > 0.1 and eff["mae_added"] > 0.05 and eff["mae_added_lo"] > 0
    lbo = R.leave_block_out(pw, Xw[te], [1], np.array([0.0]), y[te], y[te])
    assert lbo["spearman_lost"] > 0.1 and lbo["mae_added"] > 0.05


def neutral(text_effect, buckets):
    issuer, vol, y, tr, te, pw, Xw, po, Xo = run(text_effect)
    keys = R.cell_keys(issuer, R.bucketize(vol, R.bucket_edges(vol[tr], buckets)))
    kw = dict(keys_train=keys[tr], y_train=y[tr], keys_eval=keys[te], y_eval=y[te])
    state = R.neutral_skill(pred_train_oof=po(Xo[tr]), pred_eval=po(Xo[te]), **kw)
    full = R.neutral_skill(pred_train_oof=pw(Xw[tr]), pred_eval=pw(Xw[te]), **kw)
    return state, full


def test_finer_regime_cells_remove_more_of_a_volatility_model_s_skill():
    coarse, _ = neutral(0.0, 2)
    fine, _ = neutral(0.0, 20)
    assert fine["value"] < coarse["value"] - 0.1                    # conditioning on the regime strips what a pure-volatility model knew


def test_neutral_skill_separates_event_information_from_regime_information():
    state0, full0 = neutral(0.0, 10)
    state1, full1 = neutral(0.6, 10)
    assert abs(full0["value"] - state0["value"]) < 0.05             # information-free text adds no within-regime skill
    assert full1["value"] - state1["value"] > 0.2 and full1["lo"] > state1["hi"]  # a planted effect does, with separated intervals


def test_buckets_never_merge_unknown_volatility_into_a_regime():
    edges = R.bucket_edges(np.array([1.0, 2.0, 3.0, 4.0, 5.0]), 2)
    b = R.bucketize(np.array([0.5, 4.5, np.nan]), edges)
    assert b.tolist() == [0, 1, -1]


def test_within_group_skill_ignores_small_groups_and_macro_averages():
    rng = np.random.default_rng(3)
    g = np.array(["a"] * 60 + ["b"] * 60 + ["c"] * 3)
    y = rng.normal(size=len(g))
    pred = np.where(g == "a", y, rng.normal(size=len(g)))          # perfect inside a, random inside b
    res = R.within_group_skill(pred, y, g, min_n=20)
    assert res["groups"] == 2 and 0.3 < res["value"] < 0.7


def test_helpful_share_and_by_period_skip_thin_years():
    rng = np.random.default_rng(4)
    y = rng.normal(size=600)
    good, bad = y + rng.normal(0, 0.1, 600), y + rng.normal(0, 1.0, 600)
    years = np.array(["2023"] * 300 + ["2024"] * 290 + ["2025"] * 10)
    per = R.by_period(good, bad, y, years, min_n=100)
    assert set(per) == {"2023", "2024"} and R.helpful_share(per) == {"periods": 2, "helpful": 2, "share": 1.0}


def test_event_vs_control_matching_is_one_to_one_deterministic_and_respects_bucket_and_distance():
    events = [{"ticker": "A", "s0": 100, "bucket": 2}, {"ticker": "A", "s0": 101, "bucket": 2}, {"ticker": "B", "s0": 50, "bucket": 1}]
    pool = [{"ticker": "A", "s0": 99, "bucket": 2}, {"ticker": "A", "s0": 103, "bucket": 2}, {"ticker": "A", "s0": 100, "bucket": 3},
            {"ticker": "B", "s0": 300, "bucket": 1}]
    pairs = R.match_controls(events, pool, max_distance=60)
    assert pairs == [(0, 0), (1, 1)]                                # B has no control within 60 sessions; bucket 3 is never used for bucket 2
    assert R.match_controls(events, pool, max_distance=60) == pairs


def test_event_vs_control_detects_lift_and_auc_is_half_without_one():
    rng = np.random.default_rng(5)
    ctl = np.abs(rng.normal(0, 1, 800))
    lifted = R.event_vs_control(ctl + 0.5 + rng.normal(0, 0.3, 800), ctl)
    flat = R.event_vs_control(ctl + rng.normal(0, 0.3, 800), ctl)
    assert lifted["lo"] > 0.4 and lifted["auc"] > 0.6
    assert flat["lo"] < 0.05 < flat["hi"] + 0.1 and abs(flat["auc"] - 0.5) < 0.06
    assert R.auc(np.array([1.0, 2.0]), np.array([1.0, 2.0])) == 0.5


def test_permute_within_keeps_rows_whole_and_only_moves_the_block():
    X = np.arange(40, dtype=float).reshape(10, 4)
    groups = np.array([0] * 5 + [1] * 5)
    out = R.permute_within(X, [2, 3], groups, np.random.default_rng(0))
    assert np.array_equal(out[:, :2], X[:, :2])
    assert sorted(out[:5, 2].tolist()) == sorted(X[:5, 2].tolist()) and np.array_equal(out[:, 2] - 2, out[:, 3] - 3)  # block columns move together
    assert spearman(np.arange(10.0), np.arange(10.0)) == 1.0
