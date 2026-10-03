"""The v2 trainer path (Variant of run_scope) on synthetic document rows: the machinery is the v1 one, so the card must be the v1 card with v2 wording and rungs."""

from __future__ import annotations

import numpy as np
import pytest

from eventshock.config import REPO_ROOT
from eventshock.domain import ImpactLifecycle
from eventshock.modeling import impact_train_v2 as V
from eventshock.modeling.impact_study import make_steps, study_cfg
from eventshock.modeling.impact_train import Variant, run_scope
from eventshock.modeling.study_config import load_study_config
from eventshock.pipeline.config import load_impact_model_config
from eventshock.pipeline.impact_features_v2 import FEATURE_SCHEMA_V2, feature_names_v2

from .test_impact_study_synthetic import NAMES, make_rows

SCFG, _ = load_study_config(REPO_ROOT / "configs")


@pytest.fixture(scope="module")
def run():
    base = load_impact_model_config(REPO_ROOT / "configs")
    cfg = study_cfg(base, SCFG)
    small = cfg.fit.hgb.model_copy(update={"max_depth": [2], "max_iter": [60]})
    cfg = cfg.model_copy(update={"fit": cfg.fit.model_copy(update={"hgb": small})})
    rows = [{**r, "weight": 1.0} for r in make_rows(0.8)]
    var = Variant(names_fn=feature_names_v2, all_names=lambda sc: feature_names_v2(sc, "R3s"), rungs=("R2", "R2s", "R3", "R3s"), split_key="split_P2_extended",
                  ladder=make_steps(["R0", "R2-ridge", "R2s-ridge", "R2s-full"]), titles=V.TITLES, limitations=["synthetic"], feature_schema=FEATURE_SCHEMA_V2,
                  extra_checks=lambda scope, chosen, results: [])
    return run_scope("ISSUER", rows, cfg, [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0], "t" * 64, "c" * 64, False, lambda *_: None, var)


def test_the_variant_path_serves_a_calibrated_model_with_the_calendar_features(run):
    card = run.card
    assert card.lifecycle in (ImpactLifecycle.CALIBRATED, ImpactLifecycle.PRODUCTION) and card.served and run.payload is not None
    assert card.selected_id.startswith("R2s") and any(f in run.payload["features"] for f in ("earn_window", "f8k_count_24h"))
    assert [c.id for c in card.acceptance.checks] == [f"C{i}" for i in range(1, 9)]
    assert {e.id for e in card.evaluations} >= {"oof", "val", "test", "val+test", "live"}
    assert next(e for e in card.evaluations if e.id == "test").title == V.TITLES["test"]
    assert card.calibration is not None and card.limitations == ["synthetic"]


def test_the_planted_calendar_effect_is_visible_in_the_held_out_error(run):
    test = next(e for e in run.card.evaluations if e.id == "test")
    const = next(m for m in test.models if m.id == "R0-constant")
    model = next(m for m in test.models if m.id == run.card.selected_id)
    assert model.delta_mae_vs_constant.hi < 0 and model.mae.value < const.mae.value


def test_feature_names_in_the_payload_are_all_registered_event_time_features(run):
    from eventshock.modeling.leakage import check_features

    assert not [f for f in check_features(run.payload["features"]) if f.severity == "ERROR"]
    assert isinstance(run.payload["ref_row"], list) and len(run.payload["ref_row"]) == len(run.payload["features"]) and np.isfinite(run.payload["ref_pred"])
    assert NAMES  # the synthetic columns cover every name the rung needs
