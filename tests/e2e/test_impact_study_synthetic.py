"""The study must tell a planted structured effect from no effect, end to end (data -> frames -> chain -> held-out -> battery -> checks).

Two synthetic datasets share everything (volatility-driven severity, noise text features) except one thing: in the first, an earnings-window flag raises
severity inside a given volatility regime; in the second it carries no information. A study that cannot separate them proves nothing about real data.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from eventshock.config import REPO_ROOT
from eventshock.modeling import impact_study as S
from eventshock.modeling.impact_episodes import aggregate
from eventshock.modeling.study_config import load_study_config
from eventshock.pipeline.config import load_impact_model_config
from eventshock.pipeline.impact_features_v2 import feature_names_v2

_FULL, _ = load_study_config(REPO_ROOT / "configs")
# the same learners and rules, a shorter chain, so the test runs in a couple of minutes (the real chain is exercised by `make impact-study`)
SCFG = _FULL.model_copy(update={"impact": _FULL.impact.model_copy(update={"chain": ["R0", "R2-ridge", "R2s-ridge", "R2s-full", "R3s-ridge"],
                                                                         "side_branch": ["R3-ridge"]})})
NAMES = feature_names_v2("ISSUER", "R3s")
TICKERS = [f"T{i}" for i in range(8)]


def sessions():
    d, out = date(2016, 1, 4), []
    while d <= date(2026, 9, 25):
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out[::4]  # every fourth session keeps the table small


def split_p2(d: date) -> str:
    if d <= date(2023, 12, 1):          # gaps are wide because the synthetic sessions are thinned to every third
        return "train"
    if date(2024, 2, 1) <= d <= date(2024, 11, 30):
        return "val"
    if date(2025, 2, 1) <= d <= date(2025, 11, 30):
        return "test"
    if d >= date(2026, 2, 1):
        return "live"
    return "embargo"


def make_rows(effect: float, seed: int = 0):
    rng = np.random.default_rng(seed)
    rows = []
    for s0, d in enumerate(sessions()):
        for t in TICKERS:
            f = {n: float(rng.normal()) for n in NAMES}
            vol = abs(rng.normal(1.0, 0.4)) + 0.15 * int(t[1:]) % 3
            f["f_sigma_60"], f["f_resid_vol_20d_ratio"] = vol, vol * float(rng.uniform(0.8, 1.2))
            flag = float(rng.random() < 0.15)
            f["earn_window"] = float("nan") if rng.random() < 0.2 else flag
            logsev = 0.3 + 0.5 * (vol - 1.0) + effect * flag + rng.normal(0, 0.45)
            absz = math.expm1(max(logsev, 0.01))
            rows.append({"scope": "ISSUER", "episode": f"{t}|{d}", "id": f"{t}|{d}", "s0": s0, "s0_date": d.isoformat(), "ticker": t, "sector": "S", "z": absz,
                         "abs_z": absz, "score": 1 + int(absz > 1) + int(absz > 2), "placebo_abs_z": math.expm1(max(0.3 + 0.5 * (vol - 1.0) + rng.normal(0, 0.45), 0.01)),
                         "abs_z_w1": absz, "abs_z_w3": absz, "factor_model": "market", "adapter": "gdelt-gkg", "timing": "OFF_HOURS", "event_top": "NONE",
                         "event_status": "NO_EVENT", "origin": "SOURCE", "source_type": "NEWS", "text": "x", "split_P1_legacy": "gap",
                         "split_P2_extended": split_p2(d), **f})
    return rows


@pytest.fixture(scope="module")
def cfg():
    base = load_impact_model_config(REPO_ROOT / "configs")
    c = S.study_cfg(base, SCFG)
    small = c.fit.hgb.model_copy(update={"max_depth": [2], "max_iter": [60]})  # speed only: the learners are unchanged
    return c.model_copy(update={"fit": c.fit.model_copy(update={"hgb": small})})


def run(effect, cfg):
    ep = aggregate(make_rows(effect), NAMES, ["split_P1_legacy", "split_P2_extended"])
    return S.run_scope_protocol("ISSUER", "P2_extended", ep, cfg, SCFG, False, lambda *_: None)


@pytest.fixture(scope="module")
def planted(cfg):
    return run(0.8, cfg)


@pytest.fixture(scope="module")
def null(cfg):
    return run(0.0, cfg)


def check(res, cid):
    return next(c for c in res["checks"] if c["id"] == cid)


def test_the_study_runs_end_to_end_and_reports_the_planned_structure(planted):
    assert planted["status"] == "ok" and planted["folds"] >= 8 and planted["episodes"]["test"] > 200
    ids = [c["id"] for c in planted["chain"]]
    assert ids[0] == "R0-constant" and "R2s-ridge" in ids and "R2s-full" in ids and "R3-ridge" in ids
    assert {c["id"] for c in planted["checks"]} == {f"C{i}" for i in range(1, 12)}
    assert check(planted, "C4")["passed"] is None and check(planted, "C5")["passed"] is None   # needs a calibration table: never silently passed
    assert not any("[ERROR]" in x for x in planted["leakage_findings"])


def test_a_planted_structured_effect_is_adopted_and_certified_by_the_pre_registered_checks(planted):
    assert planted["selected"].startswith(("R2s", "R3s")) or planted["best_block_model"].startswith(("R2s", "R3s"))
    cal = planted["increments"]["ridge"]["calendar"]
    assert cal["oof"]["hi"] < 0 and cal["test"]["hi"] < 0 and cal["live"]["hi"] < 0
    assert check(planted, "C10")["passed"] is True
    assert check(planted, "C11")["passed"] is True
    assert planted["battery"]["best_block"]["neutral_skill_test"]["lo"] > 0       # skill that survives removing the regime
    cal_abl = planted["battery"]["ablation"]["blocks"]["calendar"]
    assert cal_abl["model"].startswith(("R2s", "R3s"))
    perm = cal_abl["permutation_within_issuer_month"]
    assert perm["spearman_lost"] > 0.02 and perm["mae_added_lo"] > 0


def test_no_effect_is_not_found_and_the_block_is_not_certified(null):
    cal = null["increments"]["ridge"]["calendar"]
    assert cal["test"]["lo"] < 0.005 and cal["test"]["hi"] > -0.005                # the interval straddles zero
    assert check(null, "C10")["passed"] is not True
    assert not null["selected"].startswith(("R2s", "R3s"))                         # the out-of-fold rule did not step up
    p = null["battery"]["ablation"]["blocks"]["calendar"]["permutation_within_issuer_month"]
    assert abs(p["spearman_lost"]) < 0.03                                          # shuffling an information-free block costs nothing


def test_when_severity_is_pure_volatility_the_real_window_and_the_placebo_window_are_predicted_equally_well(null):
    m = null["sets"]["val+test"]["models"][null["best_state_model"]]
    assert m["spearman"]["value"] > 0.3                                              # market state has real skill ...
    assert abs(m["spearman"]["value"] - m["placebo_spearman"]) < 0.1                 # ... and it is the same skill on the window before the event: regime, not event


def test_the_held_out_sets_are_only_scored_in_a_full_run(cfg):
    ep = aggregate(make_rows(0.8), NAMES, ["split_P1_legacy", "split_P2_extended"])
    dev = S.run_scope_protocol("ISSUER", "P2_extended", ep, cfg, SCFG, True, lambda *_: None)
    assert dev["status"].startswith("dev-only") and "sets" not in dev and "checks" not in dev
