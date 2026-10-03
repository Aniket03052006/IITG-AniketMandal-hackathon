from __future__ import annotations

import json

import numpy as np
import pytest

from eventshock.config import REPO_ROOT
from eventshock.modeling import impact_study as S
from eventshock.modeling.impact_episodes import aggregate
from eventshock.modeling.impact_train import load_frame
from eventshock.modeling.study_config import load_study_config
from eventshock.pipeline.config import load_impact_model_config
from eventshock.pipeline.impact_features_v2 import feature_names_v2

SCFG, SHA = load_study_config(REPO_ROOT / "configs")


def row(ep, i, **kw):
    base = {"scope": "ISSUER", "episode": ep, "id": f"{ep}#{i}", "s0": 100, "s0_date": "2024-02-01", "ticker": "AAA", "sector": "Tech", "z": 1.0, "abs_z": 1.0,
            "score": 3, "placebo_abs_z": 0.4, "abs_z_w1": 0.5, "abs_z_w3": 1.2, "factor_model": "market", "adapter": "gdelt-gkg", "timing": "OFF_HOURS",
            "event_top": "NONE", "event_status": "NO_EVENT", "origin": "SOURCE", "source_type": "NEWS", "text": "t", "split_P1_legacy": "gap",
            "split_P2_extended": "val", "f_sigma_60": 0.02, "earn_window": float("nan"), "fomc_s0": 0.0}
    return {**base, **kw}


def test_aggregate_averages_features_nan_aware_and_keeps_episodes_whole():
    rows = [row("A|1", 0, f_sigma_60=0.02, fomc_s0=1.0), row("A|1", 1, f_sigma_60=0.04, fomc_s0=0.0, earn_window=1.0), row("B|1", 0, origin="GDELT_FIRST_SEEN")]
    ep = aggregate(rows, ["f_sigma_60", "earn_window", "fomc_s0"], ["split_P2_extended"])
    a = next(e for e in ep if e["episode"] == "A|1")
    assert len(ep) == 2 and a["n_docs"] == 2 and a["f_sigma_60"] == pytest.approx(0.03) and a["fomc_s0"] == 0.5 and a["earn_window"] == 1.0
    b = next(e for e in ep if e["episode"] == "B|1")
    assert b["earn_window"] != b["earn_window"] and b["origin"] == "GDELT_FIRST_SEEN"      # unknown stays unknown; any non-publisher clock demotes the episode
    assert a["origin"] == "SOURCE" and a["weight"] == 1.0


def test_an_episode_split_across_protocol_splits_is_refused():
    with pytest.raises(ValueError, match="different split_P2_extended"):
        aggregate([row("A|1", 0), row("A|1", 1, split_P2_extended="test")], ["f_sigma_60"], ["split_P2_extended"])


def test_study_config_narrows_the_grid_but_keeps_the_v1_learners_and_gates():
    base = load_impact_model_config(REPO_ROOT / "configs")
    cfg = S.study_cfg(base, SCFG)
    assert cfg.folds.step_months == 6 and cfg.fit.hgb.max_depth == [2, 3] and cfg.fit.hgb.l2_regularization == [10.0]
    assert cfg.acceptance == base.acceptance and cfg.calibration == base.calibration  # nothing about the bar changed


def test_chain_ids_map_to_the_v1_families_and_rungs():
    steps = S.make_steps(SCFG.impact.chain + SCFG.impact.side_branch)
    assert steps[0].family == "constant" and [s.rung for s in steps[1:4]] == ["R2", "R2", "R2"]
    assert {s.family for s in steps[1:]} == {"ridge", "hgb_additive", "hgb_full"} and steps[-1].id == "R3-full"


def test_frames_use_the_protocol_split_column_and_the_requested_names():
    rows = [row(f"A|{i}", 0, split_P2_extended=sp, s0=100 + i) for i, sp in enumerate(["train"] * 3 + ["val", "test"])]
    ep = aggregate(rows, ["f_sigma_60"], ["split_P1_legacy", "split_P2_extended"])
    names = ["f_sigma_60"]
    fr = load_frame(ep, "ISSUER", names, "split_P2_extended")
    assert fr.names == names and sorted(set(fr.split)) == ["test", "train", "val"] and len(fr.idx("train")) == 3
    assert load_frame(ep, "ISSUER", names, "split_P1_legacy").idx("train").size == 0


def test_checks_c9_to_c11_are_defined_pre_registered_and_n_a_when_unevaluable():
    add = SCFG.impact.acceptance_added
    assert add.c9_regime_neutral_spearman_ci_lower_above == 0.0 and add.c10_block_increment_mae_ci_upper_below == 0.0
    assert add.c11_positive_year_share_at_least == 0.75
    assert {"R2", "R2s", "R3", "R3s", "R3h"} == set(SCFG.impact.rungs)


def test_p1_regression_gate_passes_on_identical_tables_and_fails_on_a_changed_feature(tmp_path):
    names = sorted({n for sc in ("ISSUER", "MARKET") for n in feature_names_v2(sc, "R3")})
    v1 = [{"scope": "ISSUER", "id": f"d{i}", "split": "test", "s0": 10 + i, "abs_z": 1.0, "z": 1.0, "placebo_abs_z": 0.1, **{n: 0.5 for n in names}} for i in range(5)]
    table = tmp_path / "v1.jsonl"
    table.write_text("\n".join(json.dumps(r) for r in v1) + "\n")
    card = tmp_path / "card.json"
    card.write_text(json.dumps({"scopes": [{"scope": "ISSUER", "selected_id": "R3-full", "evaluations": [
        {"id": "val+test", "models": [{"id": "R3-full", "spearman": {"value": 0.119}}]}]}]}))
    res = S.p1_regression([dict(r) for r in v1], table, card, 0.03, SCFG)
    assert res["status"] == "ok" and res["v1_rows_checked"] == 5 and res["v1_pooled_spearman_issuer"] == 0.119
    changed = [dict(r) for r in v1]
    changed[2]["f_sigma_60"] = 0.51
    bad = S.p1_regression(changed, table, card, 0.03, SCFG)
    assert bad["status"] == "FAILED" and bad["rows_with_a_different_feature_or_target"] == 1
    assert S.p1_regression([], tmp_path / "absent.jsonl", card, 0.03, SCFG)["status"] == "skipped"


def test_eval_sets_define_reliable_live_news_as_publisher_clock_outside_trading_hours():
    rows = [row(f"A|{i}", 0, split_P2_extended="live", s0=i, timing=t, origin=o)
            for i, (t, o) in enumerate([("OFF_HOURS", "SOURCE"), ("IN_SESSION", "SOURCE"), ("FIRST_SEEN", "GDELT_FIRST_SEEN"), ("PRE_OPEN", "SOURCE")])]
    fr = load_frame(aggregate(rows, ["f_sigma_60"], ["split_P2_extended"]), "ISSUER", ["f_sigma_60"], "split_P2_extended")
    sets = S.eval_sets(fr)
    assert len(sets["live"]) == 4 and sorted(fr.timing[sets["live_reliable"]].tolist()) == ["OFF_HOURS", "PRE_OPEN"]
    assert np.array_equal(sets["val+test"], np.array([], dtype=int))
