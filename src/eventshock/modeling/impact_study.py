"""The Stage 4 impact study: does event or structured information add predictive value *beyond market state*, and does it survive other periods?

Everything that decides the answer is fixed in ``configs/evidence_v2.yaml`` before any v2 number existed (its sha256 is stamped into the output).
Per scope and per protocol (P1 legacy = impact-v1's 2022 hold-out, P2 extended = val 2024, test 2025, live 2026 news) the study

* builds episode-level frames from the v2 table (``impact_episodes``), checks the leakage invariants again (feature registry, rolling folds, group straddle);
* runs the pre-registered nested chain R0 -> R2 (market state) -> R2s (+ calendar) -> R3s (+ text-model outputs), plus R3 (text without calendar) as a side branch,
  over ridge, additive boosting and full boosting, choosing among rungs only by a paired out-of-fold interval below zero (the impact-v1 rule);
* scores every fitted rung once on val, test and live, and reports the paired error difference of each block, by period, event type, issuer group and timestamp quality;
* runs the regime-versus-event battery (``impact_regime``): placebo window, regime-neutral skill, within-issuer skill, permutation and leave-block-out of each block;
* repeats the event question on filing events (Track F): event versus matched quiet session, and whether the filing's own item codes predict the reaction;
* evaluates the pre-registered checks C1-C3, C6-C11 for the selected model. C4 and C5 need a calibration table, so they exist only if an artifact is trained.

Nothing here writes a served artifact; ``--dev-only`` never scores val/test/live.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from ..config import REPO_ROOT, ConfigError
from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..pipeline.config import (
    ImpactFit,
    ImpactFolds,
    ImpactHgbGrid,
    ImpactLadderStep,
    ImpactModelConfig,
    load_impact_model_config,
)
from ..pipeline.impact_features import ISSUER, MARKET, SCOPES, TEXT
from ..pipeline.impact_features_v2 import CALENDAR, FILING_ITEMS, feature_names_v2, filing_feature_names
from . import impact_regime as R
from .impact_dataset import load_table
from .impact_episodes import aggregate
from .impact_stats import (
    boot_indices,
    delta_mae_estimate,
    estimate,
    mae_estimate,
    make_view,
    spearman,
    spearman_estimate,
)
from .impact_train import (
    Frame,
    check_rolling_folds,
    fit_step,
    load_frame,
    oof_predictions,
    rolling_folds,
)
from .leakage import Finding, check_features, group_straddle, require_clean, time_order
from .study_config import StudyConfig, load_study_config

FAMILY = {"ridge": "ridge", "additive": "hgb_additive", "full": "hgb_full"}
BLOCK_STEPS = ("R2s", "R3s", "R3")
HELD = ("val", "test", "val+test", "live", "live_reliable")


# ----------------------------------------------------------------------------------------------------------- setup
def study_cfg(base: ImpactModelConfig, scfg: StudyConfig) -> ImpactModelConfig:
    f = scfg.impact.fit
    return base.model_copy(update={
        "fit": ImpactFit(issuer_weight_cap=f["issuer_weight_cap"], hgb=ImpactHgbGrid(**f["hgb"]), ridge_alpha=f["ridge_alpha"]),
        "folds": ImpactFolds(**scfg.impact.folds)})


def make_steps(ids: list[str]) -> list[ImpactLadderStep]:
    out = []
    for sid in ids:
        if sid == "R0":
            out.append(ImpactLadderStep(id="R0-constant", family="constant"))
            continue
        rung, fam = sid.split("-")
        out.append(ImpactLadderStep(id=sid, family=FAMILY[fam], rung=rung))
    return out


def eval_sets(fr: Frame) -> dict[str, np.ndarray]:
    val, test, live = fr.idx("val"), fr.idx("test"), fr.idx("live")
    rel = live[(fr.timing[live] != "FIRST_SEEN") & (fr.origin[live] == "SOURCE") & (fr.timing[live] != "IN_SESSION")]
    return {"val": val, "test": test, "val+test": np.concatenate([val, test]), "live": live, "live_reliable": rel}


def _d(e: Any) -> dict[str, Any]:
    return e.model_dump() if hasattr(e, "model_dump") else e


def _period(fr: Frame, idx: np.ndarray) -> str:
    return f"{min(fr.date[idx].tolist())}..{max(fr.date[idx].tolist())}" if len(idx) else "empty"


# ----------------------------------------------------------------------------------------------------------- one scope, one protocol
def run_scope_protocol(scope: str, proto: str, ep_rows: list[dict], cfg: ImpactModelConfig, scfg: StudyConfig, dev_only: bool, log) -> dict[str, Any]:
    names = feature_names_v2(scope, "R3s")
    fr = load_frame(ep_rows, scope, names, f"split_{proto}")
    rung_cols = {r: fr.cols(feature_names_v2(scope, r)) for r in ("R2", "R2s", "R3", "R3s")}
    chain = make_steps(scfg.impact.chain)
    side = make_steps(scfg.impact.side_branch)
    steps = [*chain, *side]
    train_idx = fr.idx("train")
    n_ep = {s: int(len(fr.idx(s))) for s in ("train", "val", "test", "live")}
    findings: list[Finding] = check_features(fr.names)
    meta = [{"split": sp, "episode": e, "s0": int(s0)} for sp, e, s0 in zip(fr.split, fr.ep, fr.s0, strict=True)]
    dates = ["?"] * (int(fr.s0.max()) + 1)
    for s0, d in zip(fr.s0, fr.date, strict=True):
        dates[int(s0)] = str(d)
    findings += group_straddle(meta, "episode")
    findings += time_order(meta, dates, scfg.protocol(proto).embargo_sessions)
    folds = rolling_folds(fr, cfg)
    findings += check_rolling_folds(fr, folds, cfg.folds.embargo_sessions)
    require_clean(findings)
    t0 = time.time()
    out: dict[str, Any] = {"scope": scope, "protocol": proto, "episodes": n_ep, "folds": len(folds), "features": fr.names,
                           "train_period": _period(fr, train_idx), "leakage_findings": [str(f) for f in findings]}
    if len(folds) < 3 or n_ep["train"] < 800:
        out["status"] = f"not evaluable: {len(folds)} folds, {n_ep['train']} training episodes"
        return out

    # ---- out-of-fold selection (the impact-v1 rule: step up only on a paired interval entirely below zero)
    oof_rows = np.unique(np.concatenate([f[1] for f in folds]))
    oof_view = make_view(fr.ep[oof_rows], fr.y[oof_rows], fr.absz[oof_rows], fr.score[oof_rows], fr.placebo[oof_rows])
    ib = boot_indices(oof_view.n_ep, scfg.impact.bootstrap_resamples, scfg.impact.bootstrap_seed)
    params: dict[str, dict[str, Any]] = {}
    oof: dict[str, np.ndarray] = {}
    for step in steps:
        grid = oof_predictions(fr, folds, step, cfg, rung_cols)
        best, best_mae = None, float("inf")
        for k, pr in grid.items():
            mae = float(np.abs(oof_view.aggregate(pr[oof_rows]) - oof_view.y).mean())
            if mae < best_mae:
                best, best_mae = k, mae
        params[step.id], oof[step.id] = json.loads(best), grid[best]  # type: ignore[arg-type]
        log(f"  [{scope}/{proto}] OOF {step.id:14s} {best_mae:.4f} {params[step.id]}  ({time.time() - t0:.0f}s)")
    ep_oof = {sid: oof_view.aggregate(p[oof_rows]) for sid, p in oof.items()}
    chosen = chain[0].id
    verdicts = []
    for step in chain:
        d = delta_mae_estimate(ep_oof[step.id], ep_oof[chosen], oof_view, ib) if step.id != chosen else estimate(0.0)
        if step.id == chain[0].id:
            v = "baseline: the training mean"
        elif d.hi is not None and d.hi < 0:
            v, chosen = f"adopted: beats {chosen} out of fold, interval below zero", step.id
        else:
            v = f"not adopted: no significant out-of-fold gain over {chosen}"
        verdicts.append({"id": step.id, "oof_mae": _d(mae_estimate(ep_oof[step.id], oof_view, ib)),
                         "oof_spearman": _d(spearman_estimate(ep_oof[step.id], oof_view.absz, ib)),
                         "delta_vs_previous_choice": _d(d), "verdict": v})
    for step in side:
        verdicts.append({"id": step.id, "side_branch": True, "oof_mae": _d(mae_estimate(ep_oof[step.id], oof_view, ib)),
                         "oof_spearman": _d(spearman_estimate(ep_oof[step.id], oof_view.absz, ib))})
    out.update({"oof_period": _period(fr, oof_rows), "oof_episodes": int(oof_view.n_ep), "chain": verdicts, "selected": chosen, "params": params})

    def oof_mae(sid: str) -> float:
        return float(np.abs(ep_oof[sid] - oof_view.y).mean())

    state_ids = [s.id for s in steps if s.rung == "R2"]
    block_ids = [s.id for s in steps if s.rung in BLOCK_STEPS]
    best_state, best_block = min(state_ids, key=oof_mae), min(block_ids, key=oof_mae)
    out["best_state_model"], out["best_block_model"] = best_state, best_block
    if dev_only:
        out["status"] = "dev-only: val/test/live were not scored"
        return out

    # ---- held-out scoring: every step fitted once on all training episodes, scored on each held-out set
    fitted = {s.id: fit_step(s, params[s.id], fr, train_idx, cfg, rung_cols) for s in steps}
    sets = eval_sets(fr)
    preds = {sid: {name: (ft.predict(fr, idx) if len(idx) else np.array([])) for name, idx in sets.items()} for sid, ft in fitted.items()}
    base_id = "R2-ridge"
    results: dict[str, Any] = {}
    for name, idx in sets.items():
        if len(idx) < 5:
            continue
        v = make_view(fr.ep[idx], fr.y[idx], fr.absz[idx], fr.score[idx], fr.placebo[idx])
        ib2 = boot_indices(v.n_ep, scfg.impact.bootstrap_resamples, scfg.impact.bootstrap_seed)
        const = v.aggregate(preds["R0-constant"][name])
        base = v.aggregate(preds[base_id][name])
        ms = {}
        for s in steps:
            p = v.aggregate(preds[s.id][name])
            ok = ~np.isnan(v.placebo)
            plc = spearman(p[ok], v.placebo[ok]) if ok.sum() >= 20 else float("nan")
            ms[s.id] = {"mae": _d(mae_estimate(p, v, ib2)), "spearman": _d(spearman_estimate(p, v.absz, ib2)), "placebo_spearman": None if plc != plc else round(plc, 4),
                        "delta_vs_constant": _d(delta_mae_estimate(p, const, v, ib2)), "delta_vs_r2_ridge": _d(delta_mae_estimate(p, base, v, ib2))}
        results[name] = {"episodes": int(v.n_ep), "period": _period(fr, idx), "models": ms}
    out["sets"] = results
    log(f"  [{scope}/{proto}] held-out scored ({time.time() - t0:.0f}s)")

    # ---- increments by block (paired), pooled and by period / event type / issuer group / timestamp quality
    def deltas(with_id: str, without_id: str) -> dict[str, Any]:
        d = {"oof": _d(delta_mae_estimate(ep_oof[with_id], ep_oof[without_id], oof_view, ib))}
        for name in ("val+test", "test", "live", "live_reliable"):
            if name in sets and len(sets[name]) >= 20:
                v = make_view(fr.ep[sets[name]], fr.y[sets[name]], fr.absz[sets[name]], fr.score[sets[name]], fr.placebo[sets[name]])
                ib3 = boot_indices(v.n_ep, scfg.impact.bootstrap_resamples, scfg.impact.bootstrap_seed)
                d[name] = _d(delta_mae_estimate(v.aggregate(preds[with_id][name]), v.aggregate(preds[without_id][name]), v, ib3))
        return d

    inc: dict[str, Any] = {}
    for fam in ("ridge", "additive", "full"):
        pairs = {"calendar": (f"R2s-{fam}", f"R2-{fam}"), "text_given_calendar": (f"R3s-{fam}", f"R2s-{fam}"),
                 "text_alone": (f"R3-{fam}", f"R2-{fam}"), "calendar_and_text": (f"R3s-{fam}", f"R2-{fam}")}
        inc[fam] = {k: deltas(a, b) for k, (a, b) in pairs.items() if a in preds and b in preds}
    out["increments"] = inc

    pool = np.concatenate([fr.idx("val"), fr.idx("test"), fr.idx("live")])
    pooled_pred = {sid: np.full(fr.n, np.nan) for sid in (best_state, best_block)}
    for sid in pooled_pred:
        pooled_pred[sid][oof_rows] = oof[sid][oof_rows]
        for name in ("val", "test", "live"):
            if len(sets[name]):
                pooled_pred[sid][sets[name]] = preds[sid][name]
    have = np.concatenate([oof_rows, pool])
    have = have[~np.isnan(pooled_pred[best_block][have])]
    years = np.array([d[:4] for d in fr.date[have]])
    pw, po = pooled_pred[best_block][have], pooled_pred[best_state][have]
    per_year = R.by_period(pw, po, fr.y[have], years, scfg.impact.battery.min_year_episodes)
    out["by_year"] = {"block": best_block, "state": best_state, "years": per_year, "helpful": R.helpful_share(per_year)}
    strata: dict[str, Any] = {}
    held_idx = np.concatenate([sets["val+test"], sets["live"]])
    hp = {sid: np.concatenate([preds[sid]["val+test"], preds[sid]["live"]]) for sid in (best_state, best_block)}
    for dim, arr in (("event type", fr.event_top[held_idx]), ("sector", np.array([_sector(ep_rows, e) for e in fr.ep[held_idx]])),
                     ("timestamp quality", fr.timing[held_idx]), ("source", fr.adapter[held_idx])):
        cell = {}
        for val in sorted(set(arr.tolist())):
            m = arr == val
            if m.sum() >= scfg.impact.battery.min_episodes_per_cell * 2:
                cell[str(val)] = {"episodes": int(m.sum()), **R.block_increment(hp[best_block][m], hp[best_state][m], fr.y[held_idx][m], resamples=500)}
        strata[dim] = cell
    out["increment_strata"] = {"block": best_block, "state": best_state, "cells": strata}

    # ---- regime-versus-event battery
    bat = scfg.impact.battery
    vol_col = fr.cols(["f_resid_vol_20d_ratio" if scope == ISSUER else "m_dev_vol_20d_ratio"])[0]
    edges = R.bucket_edges(fr.X[train_idx, vol_col], bat.vol_buckets)
    grp = fr.ticker if scope == ISSUER else np.array(["MKT"] * fr.n)
    keys = R.cell_keys(grp, R.bucketize(fr.X[:, vol_col], edges))
    battery: dict[str, Any] = {"vol_proxy": fr.names[vol_col], "bucket_edges": [round(float(x), 5) for x in edges]}
    for label, sid in (("selected", chosen), ("best_state", best_state), ("best_block", best_block)):
        entry: dict[str, Any] = {"model": sid}
        for name in ("test", "val+test", "live"):
            idx = sets[name]
            if len(idx) < 30:
                continue
            ns = R.neutral_skill(keys_train=keys[train_idx], y_train=fr.y[train_idx], pred_train_oof=oof[sid][train_idx], keys_eval=keys[idx],
                                 y_eval=fr.y[idx], pred_eval=preds[sid][name], resamples=scfg.impact.bootstrap_resamples, seed=scfg.impact.bootstrap_seed)
            entry[f"neutral_skill_{name}"] = ns
            if scope == ISSUER:
                entry[f"within_issuer_skill_{name}"] = R.within_group_skill(preds[sid][name], fr.absz[idx], fr.ticker[idx], bat.min_episodes_per_cell)
            vb = R.bucketize(fr.X[idx, vol_col], edges)
            entry[f"within_volatility_bucket_skill_{name}"] = R.within_group_skill(preds[sid][name], fr.absz[idx], vb.astype(str), bat.min_episodes_per_cell * 4)
        battery[label] = entry
    # block ablations on the held-out episodes (no refit): each block is ablated on the best model, by out-of-fold error, that actually contains it
    block_cols = {"calendar": (("R2s", "R3s"), CALENDAR[scope]), "text_model_outputs": (("R3", "R3s"), TEXT)}
    idx = sets["val+test"]
    Xh = fr.X[idx]
    month = np.array([f"{t}|{m}" for t, m in zip(fr.ticker[idx], fr.month[idx], strict=True)]) if scope == ISSUER else fr.month[idx]
    abl: dict[str, Any] = {}
    for block, (rungs, names_) in block_cols.items():
        holders = [s_.id for s_ in steps if s_.rung in rungs and fitted[s_.id].kind != "constant"]
        if not holders:
            continue
        sid = min(holders, key=oof_mae)
        ft = fitted[sid]
        cols = [c for c in fr.cols(names_) if c in ft.cols]
        if not cols:
            continue
        predict = lambda Z, _f=ft: _f.est.predict(Z[:, _f.cols])  # noqa: E731
        med = np.nanmedian(fr.X[train_idx][:, cols], axis=0)
        abl[block] = {"model": sid, "permutation_within_issuer_month": R.permutation_effect(predict, Xh, cols, month, fr.absz[idx], fr.y[idx],
                                                                                            repeats=bat.permutation_repeats, seed=scfg.seed),
                      "leave_block_out": R.leave_block_out(predict, Xh, cols, med, fr.absz[idx], fr.y[idx])}
    battery["ablation"] = {"set": "val+test", "blocks": abl}
    out["battery"] = battery
    out["checks"] = acceptance_checks(out, scfg, chosen, best_state, best_block, fr, sets, preds, oof, train_idx, keys, scope)
    out["status"] = "ok"
    return out


def _sector(ep_rows: list[dict], episode: str, _cache: dict[str, dict[str, str]] = {}) -> str:  # noqa: B006 (a deliberate per-process cache)
    cache = _cache.setdefault(str(id(ep_rows)), {r["episode"]: (r.get("sector") or "market") for r in ep_rows})
    return cache.get(episode, "market")


# ----------------------------------------------------------------------------------------------------------- the pre-registered checks
def acceptance_checks(out: dict[str, Any], scfg: StudyConfig, chosen: str, best_state: str, best_block: str, fr: Frame, sets: dict[str, np.ndarray],
                      preds: dict[str, dict[str, np.ndarray]], oof: dict[str, np.ndarray], train_idx: np.ndarray, keys: np.ndarray, scope: str) -> list[dict]:
    """C1-C3 and C6-C8 as in configs/impact_model.yaml; C9-C11 as added in configs/evidence_v2.yaml. C4 and C5 need an artifact's calibration."""
    add = scfg.impact.acceptance_added
    sets_res = out["sets"]
    sel = lambda name: sets_res.get(name, {}).get("models", {}).get(chosen)  # noqa: E731
    pooled, test, val, live = sel("val+test"), sel("test"), sel("val"), sel("live_reliable")
    checks: list[dict] = []

    def add_check(cid: str, label: str, value: str, passed: bool | None, detail: str) -> None:
        checks.append({"id": cid, "label": label, "value": value, "passed": passed, "detail": detail})

    def ci(e: dict | None) -> str:
        return "n/a" if not e or e["value"] is None else (f"{e['value']:+.3f} [{e['lo']:+.3f}, {e['hi']:+.3f}]" if e["lo"] is not None else f"{e['value']:+.3f}")

    c1 = pooled["spearman"] if pooled else None
    add_check("C1", "Rank skill on held-out episodes (val+test)", ci(c1), None if not c1 or c1["lo"] is None else c1["lo"] > 0.0,
              "Spearman of prediction vs realised |z|; pass if the 95% interval's lower bound > 0")
    c2 = pooled["delta_vs_constant"] if pooled else None
    add_check("C2", "Error vs the constant baseline (val+test)", ci(c2), None if not c2 or c2["hi"] is None else c2["hi"] < 0.0,
              "paired difference in log-severity MAE; pass if the 95% interval's upper bound < 0")
    dv, dt = (val["delta_vs_r2_ridge"] if val else None), (test["delta_vs_r2_ridge"] if test else None)
    ok3 = None if not dv or not dt or dv["value"] is None or dt["value"] is None else (dv["value"] <= 0.002 and dt["value"] <= 0.002)
    add_check("C3", "Not worse than the market-state linear model", f"val {ci(dv)}; test {ci(dt)}", ok3, "point difference in log-severity MAE <= 0.002 on each of val and test")
    add_check("C4", "Score buckets ordered by realised severity", "n/a", None, "needs a trained artifact's calibration table (not part of the study)")
    add_check("C5", "Realised-score interval coverage", "n/a", None, "needs a trained artifact's calibration table (not part of the study)")
    add_check("C6", "Leakage suite clean", f"{len(out['leakage_findings'])} checks", not any("[ERROR]" in x for x in out["leakage_findings"]),
              "feature registry, group straddle, time order + embargo, rolling folds (plus the table's own price and calendar invariance in its manifest)")
    gap = None
    if pooled and pooled["spearman"]["value"] is not None and pooled["placebo_spearman"] is not None:
        gap = pooled["spearman"]["value"] - pooled["placebo_spearman"]
    add_check("C7", "More skill on the real window than on the pre-event placebo (val+test)",
              "n/a" if gap is None else f"{gap:+.3f} (real {pooled['spearman']['value']:+.3f}, placebo {pooled['placebo_spearman']:+.3f})",
              None if gap is None else gap > 0.0, "skill that also predicts the window before the event is market state, not the event")
    n_live = sets_res.get("live_reliable", {}).get("episodes", 0)
    c8 = live["spearman"] if live else None
    add_check("C8", "Rank skill on 2026 news with publisher timestamps", ci(c8) if n_live >= 100 else f"n/a ({n_live} episodes, need 100)",
              None if not c8 or c8["lo"] is None or n_live < 100 else c8["lo"] > 0.0, "the served documents are news with first-seen or publisher clocks")
    nsk = out["battery"].get("selected", {}).get("neutral_skill_test")
    add_check("C9", "Regime-neutral rank skill (test)", "n/a" if not nsk else f"{nsk['value']:+.3f} [{nsk['lo']:+.3f}, {nsk['hi']:+.3f}] (n={nsk['n']})",
              None if not nsk or nsk["lo"] != nsk["lo"] else nsk["lo"] > add.c9_regime_neutral_spearman_ci_lower_above,
              "Spearman after removing the issuer x volatility-bucket regime from prediction and outcome; pass if the lower bound > 0")
    inc_test = _block_vs_state(sets, preds, fr, best_block, best_state, "test", scfg)
    inc_live = _block_vs_state(sets, preds, fr, best_block, best_state, "live", scfg)
    ok10 = None if not inc_test or not inc_live or inc_test["hi"] != inc_test["hi"] or inc_live["hi"] != inc_live["hi"] else (
        inc_test["hi"] < add.c10_block_increment_mae_ci_upper_below and inc_live["hi"] < add.c10_block_increment_mae_ci_upper_below)
    fmt = lambda e: "n/a" if not e else f"{e['value']:+.4f} [{e['lo']:+.4f}, {e['hi']:+.4f}]"  # noqa: E731
    add_check("C10", f"Block increment over market state ({best_block} vs {best_state})", f"test {fmt(inc_test)}; live {fmt(inc_live)}", ok10,
              "paired log-severity MAE difference; pass if the upper bound is below 0 on test and on live")
    yh = out.get("by_year", {}).get("helpful", {})
    share = yh.get("share")
    add_check("C11", "The block helps in most calendar years", "n/a" if share is None or share != share else f"{yh['helpful']}/{yh['periods']} years ({share:.2f})",
              None if share is None or share != share or yh.get("periods", 0) < 3 else share >= add.c11_positive_year_share_at_least,
              f"share of years (>= {scfg.impact.battery.min_year_episodes} episodes) where the block's point difference is below zero; pass if >= {add.c11_positive_year_share_at_least}")
    return checks


def _block_vs_state(sets: dict[str, np.ndarray], preds: dict[str, dict[str, np.ndarray]], fr: Frame, block: str, state: str, name: str,
                    scfg: StudyConfig) -> dict[str, float] | None:
    idx = sets.get(name)
    if idx is None or len(idx) < 30:
        return None
    return R.block_increment(preds[block][name], preds[state][name], fr.y[idx], resamples=scfg.impact.bootstrap_resamples, seed=scfg.impact.bootstrap_seed)


# ----------------------------------------------------------------------------------------------------------- Track F
def run_track_f(rows: list[dict], cfg: ImpactModelConfig, scfg: StudyConfig, dev_only: bool, log) -> dict[str, Any]:
    """Event versus matched control, and the filing's own item codes as predictors of the reaction (events only, chronological)."""
    ev = {r["pair_id"]: r for r in rows if r["kind"] == "event" and r["pair_id"] is not None}
    ct = {r["pair_id"]: r for r in rows if r["kind"] == "control"}
    ids = sorted(set(ev) & set(ct))
    out: dict[str, Any] = {"pairs": len(ids)}
    bat = scfg.impact.battery
    sec = scfg.impact.bootstrap_seed

    def contrast(sel: list[int]) -> dict[str, Any] | None:
        if len(sel) < 20:
            return None
        e = np.array([np.log1p(ev[i]["abs_z"]) for i in sel])
        c = np.array([np.log1p(ct[i]["abs_z"]) for i in sel])
        return R.event_vs_control(e, c, resamples=scfg.impact.bootstrap_resamples, seed=sec)

    clean = [i for i in ids if ev[i]["timing"] != "IN_SESSION"]
    out["all_pairs"] = contrast(ids)
    out["excluding_in_session_filings"] = contrast(clean)
    out["by_item_group"] = {g: contrast([i for i in clean if ev[i].get(g) == 1.0]) for g in FILING_ITEMS}
    out["by_item_group"] = {k: v for k, v in out["by_item_group"].items() if v}
    out["by_year"] = {y: c for y in sorted({ev[i]["s0_date"][:4] for i in clean}) if (c := contrast([i for i in clean if ev[i]["s0_date"][:4] == y]))}
    out["earnings_by_year"] = {y: c for y in sorted({ev[i]["s0_date"][:4] for i in clean}) if (c := contrast(
        [i for i in clean if ev[i]["s0_date"][:4] == y and ev[i].get("item_earnings") == 1.0]))}
    out["non_earnings_by_year"] = {y: c for y in sorted({ev[i]["s0_date"][:4] for i in clean}) if (c := contrast(
        [i for i in clean if ev[i]["s0_date"][:4] == y and ev[i].get("item_earnings") != 1.0]))}
    out["by_protocol_split"] = {n: {sp: c for sp in ("train", "val", "test", "live") if (c := contrast([i for i in clean if ev[i][f"split_{n}"] == sp]))}
                                for n in ("P1_legacy", "P2_extended")}
    # a model of the reaction among events only: state -> + calendar -> + the filing's own item codes (published at event time)
    events = [r for r in rows if r["kind"] == "event"]
    models: dict[str, Any] = {}
    for proto in ("P1_legacy", "P2_extended"):
        names = filing_feature_names("F2")
        findings = check_features(names)
        require_clean(findings)
        fr = load_frame(events, ISSUER, names, f"split_{proto}")
        rung_cols = {r: fr.cols(filing_feature_names(r)) for r in ("F0", "F1", "F2")}
        steps = [ImpactLadderStep(id="F-constant", family="constant")] + [
            ImpactLadderStep(id=f"{r}-{fam}", family=FAMILY[fam], rung=r) for r in ("F0", "F1", "F2") for fam in ("ridge", "additive")]
        folds = rolling_folds(fr, cfg)
        if len(folds) < 3:
            models[proto] = {"status": "not evaluable"}
            continue
        oof_rows = np.unique(np.concatenate([f[1] for f in folds]))
        view = make_view(fr.ep[oof_rows], fr.y[oof_rows], fr.absz[oof_rows], fr.score[oof_rows], fr.placebo[oof_rows])
        ibo = boot_indices(view.n_ep, scfg.impact.bootstrap_resamples, sec)
        params, oofp = {}, {}
        for step in steps:
            grid = oof_predictions(fr, folds, step, cfg, rung_cols)
            best = min(grid, key=lambda k: float(np.abs(view.aggregate(grid[k][oof_rows]) - view.y).mean()))
            params[step.id], oofp[step.id] = json.loads(best), grid[best]
        epo = {sid: view.aggregate(p[oof_rows]) for sid, p in oofp.items()}
        entry: dict[str, Any] = {"episodes": {s: int(len(fr.idx(s))) for s in ("train", "val", "test", "live")}, "oof_episodes": int(view.n_ep),
                                 "oof": {sid: {"mae": _d(mae_estimate(p, view, ibo)), "spearman": _d(spearman_estimate(p, view.absz, ibo))} for sid, p in epo.items()}}
        entry["oof_increments"] = {f"{a}_vs_{b}-{fam}": _d(delta_mae_estimate(epo[f"{a}-{fam}"], epo[f"{b}-{fam}"], view, ibo))
                                   for fam in ("ridge", "additive") for a, b in (("F1", "F0"), ("F2", "F1"), ("F2", "F0"))}
        if not dev_only:
            train = fr.idx("train")
            fitted = {s.id: fit_step(s, params[s.id], fr, train, cfg, rung_cols) for s in steps}
            held = {}
            for name, idx in eval_sets(fr).items():
                if len(idx) < 20:
                    continue
                v = make_view(fr.ep[idx], fr.y[idx], fr.absz[idx], fr.score[idx], fr.placebo[idx])
                ib2 = boot_indices(v.n_ep, scfg.impact.bootstrap_resamples, sec)
                pr = {sid: v.aggregate(ft.predict(fr, idx)) for sid, ft in fitted.items()}
                held[name] = {"episodes": int(v.n_ep), "period": _period(fr, idx),
                              "models": {sid: {"mae": _d(mae_estimate(p, v, ib2)), "spearman": _d(spearman_estimate(p, v.absz, ib2)),
                                               "delta_vs_constant": _d(delta_mae_estimate(p, pr["F-constant"], v, ib2))} for sid, p in pr.items()},
                              "increments": {f"{a}_vs_{b}-{fam}": _d(delta_mae_estimate(pr[f"{a}-{fam}"], pr[f"{b}-{fam}"], v, ib2))
                                             for fam in ("ridge", "additive") for a, b in (("F1", "F0"), ("F2", "F1"), ("F2", "F0"))}}
            entry["sets"] = held
        models[proto] = entry
        log(f"  [track F/{proto}] done")
    out["models"] = models
    out["note"] = (f"controls: same issuer and volatility bucket, no 8-K event within {bat.control['exclusion_sessions']} sessions, one to one; "
                   "filings accepted during the session are excluded from the headline contrast")
    return out


# ----------------------------------------------------------------------------------------------------------- P1 regression gate
def p1_regression(doc_rows: list[dict], v1_table: Path, v1_card: Path, tol: float, scfg: StudyConfig) -> dict[str, Any]:
    """The v2 table must reproduce the v1 table on every v1 row (features and target), and so impact-v1's held-out skill."""
    if not v1_table.is_file():
        return {"status": "skipped", "reason": f"{v1_table} is not present (it is git-ignored; run `make impact-table`)"}
    v2 = {(r["scope"], r["id"]): r for r in doc_rows}
    feats = sorted({n for sc in SCOPES for n in feature_names_v2(sc, "R3")})
    mism, missing, checked = 0, 0, 0
    for r1 in load_table(v1_table):
        r2 = v2.get((r1["scope"], r1["id"]))
        if r2 is None:
            if r1["split"] in ("val", "test", "live", "train"):
                missing += 1
            continue
        checked += 1
        for k in (*feats, "abs_z", "z", "s0", "placebo_abs_z"):
            a, b = r1.get(k), r2.get(k)
            if not (a == b or (a is not None and b is not None and a != a and b != b)):
                mism += 1
                break
    card = json.loads(v1_card.read_text(encoding="utf-8"))
    iss = next(s for s in card["scopes"] if s["scope"] == ISSUER)
    pooled = next(e for e in iss["evaluations"] if e["id"] == "val+test")
    v1_sp = next(m for m in pooled["models"] if m["id"] == iss["selected_id"])["spearman"]["value"]
    return {"status": "ok" if (mism == 0 and missing == 0) else "FAILED", "v1_rows_checked": checked, "rows_missing_in_v2": missing,
            "rows_with_a_different_feature_or_target": mism, "v1_pooled_spearman_issuer": v1_sp, "tolerance": tol,
            "statement": "every v1 row is reproduced exactly in the v2 table, so the legacy protocol sees the same data as impact-v1"
            if (mism == 0 and missing == 0) else "the v2 table differs from the v1 table on rows both contain: investigate before trusting any v2 number"}


# ----------------------------------------------------------------------------------------------------------- orchestration
def run(repo_root: Path, config_dir: Path, dev_only: bool, log=print) -> dict[str, Any]:
    scfg, study_sha = load_study_config(config_dir)
    base = load_impact_model_config(config_dir)
    cfg = study_cfg(base, scfg)
    table, manifest_path = repo_root / "data/modeling/impact_table_v2.jsonl", repo_root / "data/modeling/impact_dataset_v2.json"
    ftable = repo_root / "data/modeling/filing_events.jsonl"
    for p in (table, manifest_path, ftable):
        if not p.is_file():
            raise ConfigError(f"missing {p}: run `make impact-table-v2 filing-events` first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["table_sha256"] != sha256_file(table) or manifest["preregistration"]["sha256"] != study_sha:
        raise ConfigError("the v2 table does not match its manifest or the current pre-registration: rebuild it with `make impact-table-v2`")
    doc_rows = load_table(table)
    log(f"v2 table: {len(doc_rows)} document rows; pre-registration {study_sha[:12]}")
    split_keys = ["split_P1_legacy", "split_P2_extended"]
    feats = sorted({n for sc in SCOPES for n in feature_names_v2(sc, "R3s")})
    ep = aggregate(doc_rows, feats, split_keys)
    log(f"{len(ep)} episodes")
    result: dict[str, Any] = {"study": scfg.version, "preregistration": {"file": "configs/evidence_v2.yaml", "sha256": study_sha},
                              "dataset": {"table_sha256": manifest["table_sha256"], "rows": manifest["rows"], "episodes": len(ep),
                                          "by_scope_protocol_split_episodes": manifest["by_scope_protocol_split_episodes"], "by_scope_year": manifest["by_scope_year"],
                                          "episodes_by_year": {sc: dict(sorted(Counter(r["s0_date"][:4] for r in ep if r["scope"] == sc).items())) for sc in SCOPES},
                                          "by_scope_source": manifest["by_scope_source"],
                                          "exclusions": manifest["exclusions"], "leakage_findings": manifest["leakage_findings"],
                                          "inputs": manifest["inputs"]},
                              "dev_only": dev_only, "runs": {}}
    result["p1_regression"] = p1_regression(doc_rows, repo_root / base.table, repo_root / base.model_dir / "model_card.json", scfg.tolerance, scfg)
    log(f"P1 regression gate: {result['p1_regression']['status']}")
    for proto in ("P1_legacy", "P2_extended"):
        for scope in (ISSUER, MARKET):
            log(f"== {proto} / {scope}")
            result["runs"][f"{proto}/{scope}"] = run_scope_protocol(scope, proto, [r for r in ep if r["scope"] == scope], cfg, scfg, dev_only, log)
    frows = [json.loads(x) for x in ftable.read_text(encoding="utf-8").split("\n") if x.strip()]
    log("== Track F (filing events)")
    result["track_f"] = run_track_f(frows, cfg, scfg, dev_only, log)
    result["track_f"]["table_sha256"] = sha256_file(ftable)
    fman = repo_root / "data/modeling/filing_events.json"
    if fman.is_file():
        fm = json.loads(fman.read_text(encoding="utf-8"))
        result["track_f"].update({"events_by_year": fm["events_by_year"], "events_by_item_group": fm["events_by_item_group"], "event_episodes": fm["event_episodes"],
                                  "control_rule": fm["control_rule"], "exclusions": fm["exclusions"]})
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eventshock.modeling impact-study")
    ap.add_argument("--dev-only", action="store_true")
    args = ap.parse_args(argv)
    res = run(REPO_ROOT, REPO_ROOT / "configs", args.dev_only)
    out = REPO_ROOT / ("data/modeling/impact_study_dev.json" if args.dev_only else "docs/evidence/impact_study.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False, default=lambda o: None if o != o else o) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
