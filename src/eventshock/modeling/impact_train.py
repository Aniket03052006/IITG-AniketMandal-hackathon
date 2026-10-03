"""Train, select, calibrate and evaluate the impact model, scope by scope, and write ``models/impact/<id>/``.

The question this answers, with evidence: *does information available when a report appears predict the size of the market's
subsequent response better than a simple baseline?* Everything is chronological:

* rolling-origin folds over the TRAIN period (a fold's model sees only sessions at least ``embargo_sessions`` before the fold)
  select the model and give the out-of-fold predictions that define the calibration;
* val is a checkpoint, test is scored once, live (news, 2026) once; none of them is ever fitted on or tuned against;
* the ladder (constant, metadata, market-state ridge, additive/full boosting, + text-model outputs, + n-grams) is tried in order and a
  more complex rung replaces the current choice only if its paired out-of-fold improvement has a bootstrap interval entirely
  below zero;
* the acceptance bar (``configs/impact_model.yaml``, pre-registered) decides the lifecycle; failing it is reported, never hidden.

Serving imports the same ``pipeline.impact_model`` functions that evaluation uses (``calibrate_value``, ``attribute_row``), and the
finished artifact is reloaded through the real loader and checked against the in-memory fit before the card is written.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..config import REPO_ROOT, ConfigError
from ..domain import ImpactLifecycle
from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..pipeline.config import ImpactLadderStep, ImpactModelConfig, load_impact_model_config
from ..pipeline.impact_card import (
    ARTIFACT_FILE,
    CARD_FILE,
    Acceptance,
    AcceptanceCheck,
    Attribution,
    CalibrationBin,
    CalibrationCard,
    DirectionCheck,
    HorizonCheck,
    ImpactModelCard,
    LadderEntry,
    ModelScore,
    ScopeCard,
    SetResult,
    Stratum,
    TrainingInfo,
)
from ..pipeline.impact_features import FEATURE_SCHEMA, ISSUER, SCOPES, feature_names
from ..pipeline.impact_model import PAYLOAD_SCHEMA, ImpactModel, attribute_row, calibrate_value
from .config import load_modeling_config
from .impact_dataset import load_table
from .impact_stats import (
    EpisodeView,
    boot_indices,
    delta_mae_estimate,
    estimate,
    mae_estimate,
    make_view,
    monotone,
    rmse,
    spearman,
    spearman_estimate,
    top_decile_lift,
    weighted_median,
    wilson,
)
from .leakage import (
    Finding,
    check_features,
    group_straddle,
    require_clean,
    time_order,
)

EVAL_SETS = ("val", "test", "val+test", "live", "live_reliable")
RELIABLE_ORIGINS = {"SOURCE"}


# ------------------------------------------------------------------------------------------------------------ data
@dataclass
class Frame:
    scope: str
    n: int
    names: list[str]  # columns of X (the R3 feature set of the scope)
    X: np.ndarray
    split: np.ndarray
    ep: np.ndarray
    s0: np.ndarray
    date: np.ndarray
    ticker: np.ndarray
    adapter: np.ndarray
    timing: np.ndarray
    origin: np.ndarray
    event_top: np.ndarray
    event_status: np.ndarray
    y: np.ndarray
    absz: np.ndarray
    z: np.ndarray
    score: np.ndarray
    placebo: np.ndarray
    absz_w1: np.ndarray
    absz_w3: np.ndarray
    weight: np.ndarray
    texts: list[str]
    sent: np.ndarray  # P(pos) - P(neg)
    p_none: np.ndarray
    month: np.ndarray = field(default_factory=lambda: np.array([]))

    def idx(self, *splits: str) -> np.ndarray:
        return np.flatnonzero(np.isin(self.split, splits))

    def cols(self, names: list[str]) -> list[int]:
        pos = {n: i for i, n in enumerate(self.names)}
        return [pos[n] for n in names]


def _lo(a: np.ndarray) -> str:
    return min(a.tolist())


def _hi(a: np.ndarray) -> str:
    return max(a.tolist())


def _f(v: Any) -> float:
    return float("nan") if v is None else float(v)


def load_frame(rows: list[dict], scope: str, names: list[str] | None = None, split_key: str = "split") -> Frame:
    part = [r for r in rows if r["scope"] == scope]
    names = feature_names(scope, "R3") if names is None else names
    return Frame(
        scope=scope, n=len(part), names=names,
        X=np.array([[_f(r.get(c)) for c in names] for r in part], dtype=float).reshape(len(part), len(names)),
        split=np.array([r[split_key] for r in part]), ep=np.array([r["episode"] for r in part]),
        s0=np.array([r["s0"] for r in part], dtype=int), date=np.array([r["s0_date"] for r in part]),
        ticker=np.array([r.get("ticker") or "" for r in part]), adapter=np.array([r["adapter"] for r in part]),
        timing=np.array([r["timing"] for r in part]), origin=np.array([r["origin"] for r in part]),
        event_top=np.array([r["event_top"] for r in part]), event_status=np.array([r["event_status"] for r in part]),
        y=np.log1p(np.array([r["abs_z"] for r in part], dtype=float)), absz=np.array([r["abs_z"] for r in part], dtype=float),
        z=np.array([r["z"] for r in part], dtype=float), score=np.array([r["score"] for r in part], dtype=int),
        placebo=np.array([_f(r.get("placebo_abs_z")) for r in part], dtype=float),
        absz_w1=np.array([_f(r.get("abs_z_w1")) for r in part], dtype=float),
        absz_w3=np.array([_f(r.get("abs_z_w3")) for r in part], dtype=float),
        weight=np.array([r["weight"] for r in part], dtype=float), texts=[r.get("text", "") for r in part],
        sent=np.array([_f(r.get("sent_pos")) - _f(r.get("sent_neg")) for r in part], dtype=float),
        p_none=np.array([_f(r.get("ev_p_none")) for r in part], dtype=float),
        month=np.array([r["s0_date"][5:7] for r in part]))


def view_of(fr: Frame, idx: np.ndarray, extra: dict[str, np.ndarray] | None = None) -> EpisodeView:
    return make_view(fr.ep[idx], fr.y[idx], fr.absz[idx], fr.score[idx], fr.placebo[idx], extra)


# ------------------------------------------------------------------------------------------------------------ fitting
def fit_weights(fr: Frame, idx: np.ndarray, cap: float) -> np.ndarray:
    """Episode weight (1/episode size) with each issuer's share of the mass capped (water-filling), normalised to mean 1.

    A cap below 1/(number of issuers) cannot be met and is skipped; it never raises, never drops rows.
    """
    w = fr.weight[idx].copy()
    if fr.scope == ISSUER and cap < 1:
        tick = fr.ticker[idx]
        names = np.unique(tick)
        if len(names) * cap >= 1:
            for _ in range(50):
                tot = w.sum()
                over = [t for t in names if w[tick == t].sum() > cap * tot * (1 + 1e-9)]
                if not over:
                    break
                for t in over:
                    m = tick == t
                    rest = tot - w[m].sum()
                    w[m] *= (cap * rest / (1 - cap)) / w[m].sum()
    return w * (len(w) / w.sum())


class Fitted:
    """A fitted ladder step: ``predict(frame, idx)`` returns log1p(|z|) for the rows."""

    def __init__(self, kind: str, est: Any, cols: list[int], extra: dict[str, Any] | None = None) -> None:
        self.kind, self.est, self.cols, self.extra = kind, est, cols, extra or {}

    def predict(self, fr: Frame, idx: np.ndarray) -> np.ndarray:
        if self.kind == "constant":
            return np.full(len(idx), self.est)
        if self.kind == "metadata":
            return self.extra["predict"](fr, idx)
        if self.kind == "ridge_tfidf":
            from scipy.sparse import csr_matrix, hstack

            tab = self.extra["tab"].transform(fr.X[np.ix_(idx, self.cols)])
            txt = self.extra["vec"].transform([fr.texts[i] for i in idx])
            return self.est.predict(hstack([csr_matrix(tab), txt]).tocsr())
        return self.est.predict(fr.X[np.ix_(idx, self.cols)])


def _hgb(additive: bool, depth: int, it: int, lr: float, leaf: int, l2: float, seed: int):
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(
        loss="squared_error", max_depth=depth, max_iter=it, learning_rate=lr, min_samples_leaf=leaf, l2_regularization=l2,
        early_stopping=False, random_state=seed, interaction_cst="no_interactions" if additive else None)


def _ridge(alpha: float):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(), Ridge(alpha=alpha))


def _metadata_fitter(fr: Frame, idx: np.ndarray, w: np.ndarray) -> Fitted:
    """Additive shrunken group means on issuer, source and calendar month only: no text, no prices. Diagnostic, never served."""
    gm = float(np.average(fr.y[idx], weights=w))
    keys = (["ticker", "adapter", "month"] if fr.scope == ISSUER else ["adapter", "month"])
    effects: list[dict[str, float]] = []
    for k in keys:
        col = getattr(fr, k)[idx]
        eff: dict[str, float] = {}
        for g in np.unique(col):
            m = col == g
            eff[str(g)] = float(np.sum((fr.y[idx][m] - gm) * w[m]) / (w[m].sum() + 5.0))
        effects.append(eff)

    def predict(frame: Frame, ii: np.ndarray) -> np.ndarray:
        out = np.full(len(ii), gm)
        for k, eff in zip(keys, effects, strict=True):
            out += np.array([eff.get(str(v), 0.0) for v in getattr(frame, k)[ii]])
        return out

    return Fitted("metadata", None, [], {"predict": predict})


def fit_step(step: ImpactLadderStep, params: dict[str, Any], fr: Frame, idx: np.ndarray, cfg: ImpactModelConfig,
             rung_cols: dict[str, list[int]]) -> Fitted:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    if np.any(fr.split[idx] != "train") and not params.get("_allow_nontrain"):
        raise AssertionError("fit_step received rows outside the train split: the held-out sets must never be fitted on")
    w = fit_weights(fr, idx, cfg.fit.issuer_weight_cap)
    y = fr.y[idx]
    if step.family == "constant":
        return Fitted("constant", float(np.average(y, weights=w)), [])
    if step.family == "metadata":
        return _metadata_fitter(fr, idx, w)
    cols = rung_cols[step.rung or "R2"]
    X = fr.X[np.ix_(idx, cols)]
    if step.family == "ridge":
        est = _ridge(params["alpha"])
        est.fit(X, y, ridge__sample_weight=w)
        return Fitted("ridge", est, cols)
    if step.family in ("hgb_additive", "hgb_full"):
        est = _hgb(step.family == "hgb_additive", params["max_depth"], params["max_iter"], params["learning_rate"],
                   params["min_samples_leaf"], params["l2_regularization"], cfg.seed)
        est.fit(X, y, sample_weight=w)
        return Fitted(step.family, est, cols)
    if step.family == "ridge_tfidf":
        from scipy.sparse import csr_matrix, hstack

        imp, sc = SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler()
        tab = sc.fit_transform(imp.fit_transform(X))

        class _Tab:
            def transform(self, a: np.ndarray) -> np.ndarray:
                return sc.transform(imp.transform(a))

        tf = cfg.fit.tfidf
        vec = TfidfVectorizer(ngram_range=tf.ngram_range, min_df=tf.min_df, max_features=tf.max_features, sublinear_tf=True,
                              lowercase=True, dtype=np.float64)
        txt = vec.fit_transform([fr.texts[i] for i in idx])
        est = Ridge(alpha=params["alpha"])
        est.fit(hstack([csr_matrix(tab), txt]).tocsr(), y, sample_weight=w)
        return Fitted("ridge_tfidf", est, cols, {"tab": _Tab(), "vec": vec})
    raise ValueError(f"unknown family {step.family}")


def param_grid(step: ImpactLadderStep, cfg: ImpactModelConfig) -> list[dict[str, Any]]:
    if step.family in ("constant", "metadata"):
        return [{}]
    if step.family in ("ridge", "ridge_tfidf"):
        return [{"alpha": a} for a in cfg.fit.ridge_alpha]
    g = cfg.fit.hgb
    return [{"max_depth": d, "max_iter": it, "learning_rate": lr, "min_samples_leaf": leaf, "l2_regularization": l2}
            for d in g.max_depth for it in g.max_iter for lr in g.learning_rate for leaf in g.min_samples_leaf
            for l2 in g.l2_regularization]


def pkey(p: dict[str, Any]) -> str:
    return json.dumps(p, sort_keys=True)


# ------------------------------------------------------------------------------------------------------------ folds
def rolling_folds(fr: Frame, cfg: ImpactModelConfig) -> list[tuple[np.ndarray, np.ndarray, str]]:
    """(train rows, test rows, label) for each fold. Test rows are TRAIN-split rows in [start, start+step); the fold's training rows
    are train-split rows at least ``embargo_sessions`` before the first test session. No row is in both; no episode straddles."""
    tr = fr.idx("train")
    fc = cfg.folds
    y, m = (int(v) for v in fc.first_fold_start.split("-")[:2])
    last = _hi(fr.date[tr])
    folds = []
    while True:
        start = f"{y:04d}-{m:02d}-01"
        if start > last:
            break
        m2, y2 = m + fc.step_months, y
        while m2 > 12:
            m2, y2 = m2 - 12, y2 + 1
        end = f"{y2:04d}-{m2:02d}-01"
        test = tr[(fr.date[tr] >= start) & (fr.date[tr] < end)]
        if len(test):
            cutoff = fr.s0[test].min() - fc.embargo_sessions
            train = tr[fr.s0[tr] <= cutoff]
            if len(np.unique(fr.ep[train])) >= fc.min_train_episodes:
                folds.append((train, test, f"{start}..{end}"))
        y, m = y2, m2
    return folds


def check_rolling_folds(fr: Frame, folds: list[tuple[np.ndarray, np.ndarray, str]], embargo: int) -> list[Finding]:
    for train, test, label in folds:
        if fr.s0[train].max() + embargo > fr.s0[test].min():
            return [Finding("rolling_folds", "ERROR", f"fold {label}: training reaches within {embargo} sessions of the test period")]
        if set(fr.ep[train]) & set(fr.ep[test]):
            return [Finding("rolling_folds", "ERROR", f"fold {label}: an episode is in both training and test")]
    return [Finding("rolling_folds", "INFO", f"{len(folds)} rolling-origin folds: every fold trains >= {embargo} sessions before its test period; no episode straddles")]


def oof_predictions(fr: Frame, folds, step: ImpactLadderStep, cfg: ImpactModelConfig, rung_cols: dict[str, list[int]]
                    ) -> dict[str, np.ndarray]:
    """Out-of-fold row predictions for every parameter setting of a step (NaN on rows no fold tested)."""
    grid = param_grid(step, cfg)
    out = {pkey(p): np.full(fr.n, np.nan) for p in grid}
    staged = step.family in ("hgb_additive", "hgb_full")
    for train, test, _label in folds:
        if staged:  # one fit per (depth, l2, ...) at the largest iteration count; the smaller counts are read off the stages
            groups: dict[str, list[dict[str, Any]]] = {}
            for p in grid:
                groups.setdefault(pkey({k: v for k, v in p.items() if k != "max_iter"}), []).append(p)
            w = fit_weights(fr, train, cfg.fit.issuer_weight_cap)
            cols = rung_cols[step.rung or "R2"]
            for plist in groups.values():
                top = max(plist, key=lambda p: p["max_iter"])
                est = _hgb(step.family == "hgb_additive", top["max_depth"], top["max_iter"], top["learning_rate"],
                           top["min_samples_leaf"], top["l2_regularization"], cfg.seed)
                est.fit(fr.X[np.ix_(train, cols)], fr.y[train], sample_weight=w)
                want = {p["max_iter"]: p for p in plist}
                for i, pred in enumerate(est.staged_predict(fr.X[np.ix_(test, cols)]), start=1):
                    if i in want:
                        out[pkey(want[i])][test] = pred
        else:
            for p in grid:
                out[pkey(p)][test] = fit_step(step, p, fr, train, cfg, rung_cols).predict(fr, test)
    return out


# ------------------------------------------------------------------------------------------------------------ scoring
@dataclass
class Evalset:
    id: str
    title: str
    role: str
    idx: np.ndarray
    view: EpisodeView
    period: str


V1_TITLES = {"val": "2022 Q2, tweets (checkpoint)", "test": "2022 Q3, tweets (read once)", "val+test": "2022 Q2+Q3 pooled",
             "live": "2026 news, all timestamps (read once)", "live_reliable": "2026 news, publisher timestamps outside trading hours"}


def build_sets(fr: Frame, dev_only: bool, titles: dict[str, str] | None = None) -> dict[str, Evalset]:
    titles = titles or V1_TITLES
    def mk(i: str, title: str, role: str, idx: np.ndarray) -> Evalset:
        v = view_of(fr, idx)
        per = f"{_lo(fr.date[idx])}..{_hi(fr.date[idx])}" if len(idx) else "empty"
        return Evalset(i, title, role, idx, v, per)

    val, test, live = fr.idx("val"), fr.idx("test"), fr.idx("live")
    sets = {"val": mk("val", titles["val"], "checkpoint: read to choose nothing", val)}
    if not dev_only:
        sets["test"] = mk("test", titles["test"], "held-out test, scored once", test)
        sets["val+test"] = mk("val+test", titles["val+test"], "pooled for the acceptance checks", np.concatenate([val, test]))
        sets["live"] = mk("live", titles["live"], "live-like news, noisy clocks", live)
        rel = live[(fr.timing[live] != "FIRST_SEEN") & np.isin(fr.origin[live], list(RELIABLE_ORIGINS))
                   & (fr.timing[live] != "IN_SESSION")]
        sets["live_reliable"] = mk("live_reliable", titles["live_reliable"], "the news acceptance check", rel)
    return sets


def _placebo(pred: np.ndarray, v: EpisodeView, ib: np.ndarray):
    ok = ~np.isnan(v.placebo)
    if ok.sum() < 20:
        return estimate(None)
    p, b = pred[ok], v.placebo[ok]
    sub = boot_indices(len(p), ib.shape[0], 13)
    vals = np.array([spearman(p[i], b[i]) for i in sub])
    vals = vals[~np.isnan(vals)]
    lo, hi = (np.percentile(vals, 2.5), np.percentile(vals, 97.5)) if len(vals) >= 20 else (None, None)
    return estimate(spearman(p, b), lo, hi)


# ------------------------------------------------------------------------------------------------------------ calibration
def build_calibration(cfg: ImpactModelConfig, pred_ep: np.ndarray, absz_ep: np.ndarray, score_ep: np.ndarray, cutpoints: list[float]
                      ) -> dict[str, Any]:
    cc = cfg.calibration
    grid = np.linspace(0.0, 1.0, cc.percentile_points)
    pred_q = np.quantile(pred_ep, grid)
    sev_q = np.quantile(absz_ep, grid)
    cal: dict[str, Any] = {"grid": [float(g) for g in grid], "pred_q": [float(v) for v in pred_q], "sev_q": [float(v) for v in sev_q],
                           "cut": list(cutpoints), "cap": cc.severity_cap, "extreme_score": cc.extreme_score}
    cal["bins"] = bins_from(cfg, cal, pred_ep, absz_ep, score_ep)
    return cal


def predicted_scores(cal: dict[str, Any], pred_ep: np.ndarray) -> np.ndarray:
    return np.array([calibrate_value(cal, float(p))[1] for p in pred_ep], dtype=int)


def _bin_stats(cfg: ImpactModelConfig, lo: int, hi: int, absz: np.ndarray, score: np.ndarray) -> dict[str, Any]:
    q10, q90 = cfg.calibration.interval
    k = int(np.sum(score >= cfg.calibration.extreme_score))
    p_lo, p_hi = wilson(k, len(score))
    return {"score_low": lo, "score_high": hi, "n_episodes": int(len(score)),
            "severity_q10": float(np.quantile(absz, q10)), "severity_q50": float(np.quantile(absz, 0.5)),
            "severity_q90": float(np.quantile(absz, q90)),
            "realised_score_q10": int(np.quantile(score, q10, method="nearest")),
            "realised_score_q90": int(np.quantile(score, q90, method="nearest")),
            "p_extreme": round(k / len(score), 4), "p_extreme_lo": round(p_lo, 4), "p_extreme_hi": round(p_hi, 4)}


def bins_from(cfg: ImpactModelConfig, cal: dict[str, Any], pred_ep: np.ndarray, absz_ep: np.ndarray, score_ep: np.ndarray) -> list[dict]:
    """Reference table: episodes grouped by the score the model gave them (out of fold); thin top buckets merge downwards."""
    pscore = predicted_scores(cal, pred_ep)
    edges: list[tuple[int, int]] = []
    hi, count = 10, 0
    for s in range(10, 0, -1):
        count += int(np.sum(pscore == s))
        if count >= cfg.calibration.min_bin_episodes:
            edges.append((s, hi))
            hi, count = s - 1, 0
    if hi >= 1:  # a thin remainder at the bottom merges into the lowest bucket that exists
        if edges:
            edges[-1] = (1, edges[-1][1])
        else:
            edges.append((1, 10))
    out = []
    for lo, hi in sorted(edges):
        m = (pscore >= lo) & (pscore <= hi)
        if m.sum():
            out.append(_bin_stats(cfg, lo, hi, absz_ep[m], score_ep[m]))
    return out


def bins_apply(cfg: ImpactModelConfig, cal: dict[str, Any], edges: list[dict], pred_ep: np.ndarray, absz_ep: np.ndarray,
               score_ep: np.ndarray) -> list[dict]:
    pscore = predicted_scores(cal, pred_ep)
    out = []
    for b in edges:
        m = (pscore >= b["score_low"]) & (pscore <= b["score_high"])
        if m.sum() >= 1:
            out.append(_bin_stats(cfg, b["score_low"], b["score_high"], absz_ep[m], score_ep[m]))
    return out


def _bin_card(b: dict) -> CalibrationBin:
    return CalibrationBin(
        score_low=b["score_low"], score_high=b["score_high"], n_episodes=b["n_episodes"], severity_q10=round(b["severity_q10"], 3),
        severity_q50=round(b["severity_q50"], 3), severity_q90=round(b["severity_q90"], 3), realised_score_q10=b["realised_score_q10"],
        realised_score_q90=b["realised_score_q90"], p_extreme=estimate(b["p_extreme"], b["p_extreme_lo"], b["p_extreme_hi"]))


# ------------------------------------------------------------------------------------------------------------ the scope run
def _ci_str(e) -> str:
    if e.value is None:
        return "n/a"
    return f"{e.value:+.3f} [{e.lo:+.3f}, {e.hi:+.3f}]" if e.lo is not None else f"{e.value:+.3f}"


@dataclass
class ScopeRun:
    card: ScopeCard
    payload: dict[str, Any] | None
    dev: dict[str, Any] = field(default_factory=dict)


@dataclass
class Variant:
    """What differs between impact-v1 and the Stage 4 refit: the feature names per rung, the split column, the ladder and the wording that names the periods."""

    names_fn: Any = feature_names
    all_names: Any = None                 # scope -> every column the frame needs (default: the R3 set of names_fn)
    rungs: tuple[str, ...] = ("R2", "R3")
    split_key: str = "split"
    ladder: list[ImpactLadderStep] | None = None
    titles: dict[str, str] | None = None
    limitations: list[str] | None = None
    extra_checks: Any = None              # (scope, chosen_id, results) -> list[AcceptanceCheck] appended to C1-C8
    feature_schema: str = FEATURE_SCHEMA


def run_scope(scope: str, rows: list[dict], cfg: ImpactModelConfig, cutpoints: list[float], table_sha: str, cfg_sha: str,
              dev_only: bool, log, variant: Variant | None = None) -> ScopeRun:
    var = variant or Variant()
    fr = load_frame(rows, scope, (var.all_names(scope) if var.all_names else None), var.split_key)
    gate = cfg.scopes[scope]
    sets = build_sets(fr, dev_only, var.titles)
    rung_cols = {r: fr.cols(var.names_fn(scope, r)) for r in var.rungs}
    train_idx = fr.idx("train")
    n_ep = {s: len(np.unique(fr.ep[fr.idx(s)])) for s in ("train", "val", "test", "live")}
    heldout_ep = n_ep["val"] + n_ep["test"]
    excluded: dict[str, int] = {}
    limitations: list[str] = []
    findings: list[Finding] = []
    findings += check_features(fr.names)
    meta_rows = [{"split": sp, "episode": e, "s0": int(s0)} for sp, e, s0 in zip(fr.split, fr.ep, fr.s0, strict=True)]
    dates = ["?"] * (int(fr.s0.max()) + 1)
    for s0, d in zip(fr.s0, fr.date, strict=True):
        dates[int(s0)] = str(d)
    findings += group_straddle(meta_rows, "episode")
    findings += time_order(meta_rows, dates, 5)
    folds = rolling_folds(fr, cfg)
    findings += check_rolling_folds(fr, folds, cfg.folds.embargo_sessions)
    require_clean(findings)  # a leakage ERROR aborts the whole run
    leak_lines = [str(f) for f in findings]

    train_info = TrainingInfo(
        table_sha256=table_sha, rows={s: int(len(fr.idx(s))) for s in ("train", "val", "test", "live")}, episodes=n_ep,
        train_period=f"{_lo(fr.date[train_idx])}..{_hi(fr.date[train_idx])}" if len(train_idx) else "empty",
        folds=f"{len(folds)} rolling-origin folds of {cfg.folds.step_months} months from {cfg.folds.first_fold_start}, "
              f"embargo {cfg.folds.embargo_sessions} sessions", excluded=excluded, seed=cfg.seed, config_sha256=cfg_sha)
    target = ("log1p(|z|): two-session abnormal return over its trailing sigma" if scope == ISSUER
              else "log1p(|z|): two-session S&P 500 excess return over its trailing sigma")

    if heldout_ep < gate.min_heldout_episodes or len(folds) < 3:
        why = (f"only {heldout_ep} held-out episodes (val {n_ep['val']} + test {n_ep['test']}); the gate is {gate.min_heldout_episodes}"
               if heldout_ep < gate.min_heldout_episodes else f"only {len(folds)} usable folds")
        card = ScopeCard(
            scope=scope, lifecycle=ImpactLifecycle.DATASET, served=False, summary=f"Not evaluable: {why}. No model is fitted.",
            target=target, selected_id=None, algorithm="none", features=fr.names, training=train_info, ladder=[], evaluations=[],
            calibration=None, strata=[], attribution=None, horizon=[], direction=None, leakage_findings=leak_lines,
            acceptance=Acceptance(rule=ACCEPT_RULE, met=False, checks=[]), limitations=[f"scope gate failed: {why}"])
        return ScopeRun(card, None)

    t0 = time.time()
    oof_rows = np.unique(np.concatenate([f[1] for f in folds]))
    oof_view = view_of(fr, oof_rows)
    ib_oof = boot_indices(oof_view.n_ep, cfg.evaluation.bootstrap_resamples, cfg.evaluation.bootstrap_seed)
    ladder = var.ladder or cfg.ladder
    ladder_params: dict[str, dict[str, Any]] = {}
    oof_pred: dict[str, np.ndarray] = {}  # step id -> row predictions (NaN outside OOF) for the chosen params
    for step in ladder:
        grid_preds = oof_predictions(fr, folds, step, cfg, rung_cols)
        best, best_mae = None, float("inf")
        for k, pr in grid_preds.items():
            ep = oof_view.aggregate(pr[oof_rows])
            mae = float(np.abs(ep - oof_view.y).mean())
            if mae < best_mae:
                best, best_mae = k, mae
        assert best is not None
        ladder_params[step.id] = json.loads(best)
        oof_pred[step.id] = grid_preds[best]
        log(f"  [{scope}] OOF {step.id:13s} best {best_mae:.4f}  {ladder_params[step.id]}  ({time.time() - t0:.0f}s)")

    # ---- the ladder rule: step up only on a paired out-of-fold improvement whose interval is entirely below zero
    ep_pred = {sid: oof_view.aggregate(p[oof_rows]) for sid, p in oof_pred.items()}
    chosen_id = ladder[0].id
    entries: list[LadderEntry] = []
    for step in ladder:
        p = ep_pred[step.id]
        d = delta_mae_estimate(p, ep_pred[chosen_id], oof_view, ib_oof) if step.id != chosen_id else estimate(0.0)
        servable = step.family not in ("metadata", "ridge_tfidf", "constant")
        if step.id == ladder[0].id:
            verdict = "baseline: the training mean"
        elif not servable:
            verdict = "diagnostic only (never served): " + ("uses issuer identity, a banned shortcut" if step.family == "metadata"
                                                          else "needs raw text at serving time")
        elif d.hi is not None and d.hi < 0:
            verdict = f"adopted: beats {chosen_id} out of fold, interval entirely below zero"
            chosen_id = step.id
        else:
            verdict = f"not adopted: no significant out-of-fold gain over {chosen_id}"
        entries.append(LadderEntry(
            id=step.id, family=step.family, rung=step.rung, servable=servable and step.family != "constant",
            params={k: v for k, v in ladder_params[step.id].items()}, n_features=len(rung_cols.get(step.rung or "", [])),
            oof_mae=mae_estimate(p, oof_view, ib_oof), oof_spearman=spearman_estimate(p, oof_view.absz, ib_oof), delta_mae_vs_previous_choice=d,
            chosen=False, verdict=verdict))
    selected_step = next(s for s in ladder if s.id == chosen_id)
    for e in entries:
        e.chosen = e.id == chosen_id
    log(f"  [{scope}] selected {chosen_id}  ({time.time() - t0:.0f}s)")

    # ---- fit every step on all training rows (for the baseline-vs-model table) and score the held-out sets
    fitted = {s.id: fit_step(s, ladder_params[s.id], fr, train_idx, cfg, rung_cols) for s in ladder}
    base_id = next((s.id for s in ladder if s.family == "ridge" and s.rung == "R2"), ladder[0].id)
    results: list[SetResult] = []
    oof_models = []
    const_ep = ep_pred[ladder[0].id]
    for s in ladder:
        oof_models.append(ModelScore(
            id=s.id, mae=mae_estimate(ep_pred[s.id], oof_view, ib_oof), rmse=round(rmse(ep_pred[s.id], oof_view), 4),
            spearman=spearman_estimate(ep_pred[s.id], oof_view.absz, ib_oof), top_decile_lift=_r(top_decile_lift(ep_pred[s.id], oof_view.absz)),
            placebo_spearman=_placebo(ep_pred[s.id], oof_view, ib_oof),
            delta_mae_vs_constant=delta_mae_estimate(ep_pred[s.id], const_ep, oof_view, ib_oof),
            delta_mae_vs_market_state=delta_mae_estimate(ep_pred[s.id], ep_pred[base_id], oof_view, ib_oof)))
    results.append(SetResult(id="oof", title="Rolling-origin out-of-fold, training period", role="selection and calibration reference",
                             n_episodes=oof_view.n_ep, n_rows=len(oof_rows), period=f"{_lo(fr.date[oof_rows])}..{_hi(fr.date[oof_rows])}",
                             models=oof_models))
    preds: dict[str, dict[str, np.ndarray]] = {sid: {} for sid in fitted}  # step -> set -> row predictions
    for sid, ft in fitted.items():
        for set_id, es in sets.items():
            preds[sid][set_id] = ft.predict(fr, es.idx) if len(es.idx) else np.array([])
    for set_id, es in sets.items():
        if es.view.n_ep == 0:
            continue
        ib = boot_indices(es.view.n_ep, cfg.evaluation.bootstrap_resamples, cfg.evaluation.bootstrap_seed)
        const_s = es.view.aggregate(preds[ladder[0].id][set_id])
        base_s = es.view.aggregate(preds[base_id][set_id])
        ms = []
        for s in ladder:
            pe = es.view.aggregate(preds[s.id][set_id])
            ms.append(ModelScore(
                id=s.id, mae=mae_estimate(pe, es.view, ib), rmse=round(rmse(pe, es.view), 4), spearman=spearman_estimate(pe, es.view.absz, ib),
                top_decile_lift=_r(top_decile_lift(pe, es.view.absz)), placebo_spearman=_placebo(pe, es.view, ib),
                delta_mae_vs_constant=delta_mae_estimate(pe, const_s, es.view, ib),
                delta_mae_vs_market_state=delta_mae_estimate(pe, base_s, es.view, ib)))
        results.append(SetResult(id=set_id, title=es.title, role=es.role, n_episodes=es.view.n_ep, n_rows=len(es.idx),
                                 period=es.period, models=ms))
    log(f"  [{scope}] held-out scored ({time.time() - t0:.0f}s)")

    if selected_step.family == "constant":
        card = ScopeCard(
            scope=scope, lifecycle=ImpactLifecycle.BASELINE, served=False, selected_id=chosen_id, algorithm="none (no candidate beat the constant)",
            summary="No candidate beat the training-mean baseline out of fold, so nothing is served for this scope; the labelled heuristic stays.",
            target=target, features=fr.names, training=train_info, ladder=entries, evaluations=results, calibration=None, strata=[],
            attribution=None, horizon=[], direction=None, leakage_findings=leak_lines,
            acceptance=Acceptance(rule=ACCEPT_RULE, met=False, checks=[]), limitations=["no learned model beat the baseline"])
        return ScopeRun(card, None)

    # ---- calibration of the selected model from its out-of-fold predictions
    sel_ep_oof = ep_pred[chosen_id]
    cal = build_calibration(cfg, sel_ep_oof, oof_view.absz, oof_view.score, cutpoints)
    fit_sel = fitted[chosen_id]
    # ---- fit invariance: refit with the held-out labels scrambled; nothing about the artifact may change
    rng = np.random.default_rng(3)
    saved = (fr.y.copy(), fr.absz.copy())
    held = np.flatnonzero(fr.split != "train")
    fr.y[held], fr.absz[held] = rng.permutation(fr.y[held]), rng.permutation(fr.absz[held])
    fit_sel2 = fit_step(selected_step, ladder_params[chosen_id], fr, train_idx, cfg, rung_cols)
    fr.y, fr.absz = saved
    probe_idx = fr.idx("val")[:400] if dev_only else fr.idx("val", "test")[:400]
    if not np.array_equal(fit_sel.predict(fr, probe_idx), fit_sel2.predict(fr, probe_idx)):
        raise ConfigError("fit-invariance violated: the fitted model changed when the held-out labels were scrambled")
    findings.append(Finding("fit_invariance", "INFO", "refit with val/test/live labels scrambled gives bit-identical predictions"))

    # ---- held-out calibration: same bin edges, independent episodes
    pool = sets["val+test"] if "val+test" in sets else sets["val"]
    pool_pred = pool.view.aggregate(preds[chosen_id]["val+test" if "val+test" in sets else "val"])
    held_bins = bins_apply(cfg, cal, cal["bins"], pool_pred, pool.view.absz, pool.view.score)
    nominal = cfg.calibration.interval[1] - cfg.calibration.interval[0]
    pscore = predicted_scores(cal, pool_pred)
    inside = []
    for ps, rs in zip(pscore, pool.view.score, strict=True):
        b = next((b for b in cal["bins"] if b["score_low"] <= ps <= b["score_high"]), None)
        if b:
            inside.append(b["realised_score_q10"] <= rs <= b["realised_score_q90"])
    cov = float(np.mean(inside)) if inside else float("nan")
    cov_lo, cov_hi = wilson(int(np.sum(inside)), len(inside))
    mono = monotone([b["severity_q50"] for b in held_bins if b["n_episodes"] >= 10])
    ext_pred = np.array([next((b["p_extreme"] for b in cal["bins"] if b["score_low"] <= s <= b["score_high"]), np.nan) for s in pscore])
    ext_true = (pool.view.score >= cfg.calibration.extreme_score).astype(float)
    base_rate = float(np.mean(sel_ep_oof * 0 + (oof_view.score >= cfg.calibration.extreme_score)))
    brier = float(np.nanmean((ext_pred - ext_true) ** 2))
    brier_base = float(np.mean((base_rate - ext_true) ** 2))
    calib_card = CalibrationCard(
        method=("rank-calibrated: prediction -> percentile of the out-of-fold training predictions -> |z| at the same percentile of the "
                "realised severity distribution -> the target's own fixed cut points; interval = what comparable out-of-fold events realised"),
        reference_episodes=int(oof_view.n_ep), reference_period=f"{_lo(fr.date[oof_rows])}..{_hi(fr.date[oof_rows])}",
        extreme_score=cfg.calibration.extreme_score, base_rate_extreme=round(base_rate, 4),
        bins_reference=[_bin_card(b) for b in cal["bins"]], bins_heldout=[_bin_card(b) for b in held_bins], nominal_coverage=round(nominal, 3),
        heldout_coverage=estimate(cov, cov_lo, cov_hi, 3), monotonicity_spearman=_r(mono, 3), extreme_brier=_r(brier, 5),
        extreme_brier_base_rate=_r(brier_base, 5))

    # ---- attribution exactness
    cols = fit_sel.cols
    ref = [float(weighted_median(fr.X[train_idx, c], np.ones(len(train_idx)))) for c in cols]
    x_probe = fr.X[np.ix_(probe_idx, cols)]
    err = 0.0
    for xr in x_probe[:200]:
        contrib, base, full = attribute_row(fit_sel.est, ref, [float(v) for v in xr])
        err = max(err, abs(base + sum(contrib) - full))
    exact = selected_step.family in ("hgb_additive", "ridge")
    attribution = Attribution(kind="additive" if selected_step.family == "hgb_additive" else "linear" if selected_step.family == "ridge" else "sensitivity",
                              exact=exact and err < 1e-6, max_abs_error=float(f"{err:.3g}"), units="ln(1 + |z|): baseline + contributions = prediction")

    # ---- strata, horizon, direction on val+test
    pool_idx = pool.idx
    sel_rows = preds[chosen_id]["val+test" if "val+test" in sets else "val"]
    strata = _strata(fr, pool_idx, sel_rows, ladder[0], preds[ladder[0].id]["val+test" if "val+test" in sets else "val"], cfg)
    horizon = []
    pe = pool.view.aggregate(sel_rows)
    ibp = boot_indices(pool.view.n_ep, cfg.evaluation.bootstrap_resamples, 9)
    for w, arr in ((1, fr.absz_w1), (2, fr.absz), (3, fr.absz_w3)):
        v = make_view(fr.ep[pool_idx], fr.y[pool_idx], arr[pool_idx], fr.score[pool_idx], fr.placebo[pool_idx])
        horizon.append(HorizonCheck(window_sessions=w, spearman=spearman_estimate(pe, v.absz, ibp)))
    direction = _direction(fr, pool_idx, cfg) if scope == ISSUER else None

    # ---- acceptance (pre-registered)
    live_rel = sets.get("live_reliable")
    checks = _acceptance(cfg, results, chosen_id, base_id, calib_card, live_rel, gate.live_min_episodes, leak_lines)
    if var.extra_checks is not None:
        checks = [*checks, *var.extra_checks(scope, chosen_id, results)]
    met = all(c.passed is True for c in checks)
    lifecycle = ImpactLifecycle.PRODUCTION if (met and not dev_only) else ImpactLifecycle.CALIBRATED
    if dev_only:
        lifecycle = ImpactLifecycle.TRAINED  # held-out sets were not scored: never claims calibration or acceptance
    summary = _summary(scope, lifecycle, chosen_id, results, checks)
    limitations = var.limitations if var.limitations is not None else _limitations(scope, fr, n_ep, checks)

    payload = {
        "kind": selected_step.family, "features": [fr.names[c] for c in cols], "model": fit_sel.est, "ref_row": ref,
        "ref_pred": float(attribute_row(fit_sel.est, ref, ref)[1]), "cal": cal, "lifecycle": lifecycle.value,
    }
    algo = {"hgb_additive": "additive gradient boosting (one feature per interaction group) on log1p(|z|)",
            "hgb_full": "gradient boosting (interactions allowed) on log1p(|z|)", "ridge": "ridge regression on log1p(|z|)"}[selected_step.family]
    card = ScopeCard(
        scope=scope, lifecycle=lifecycle, served=True, summary=summary, target=target, selected_id=chosen_id,
        algorithm=f"{algo}; params {ladder_params[chosen_id]}", features=[fr.names[c] for c in cols], training=train_info, ladder=entries,
        evaluations=results, calibration=calib_card, strata=strata, attribution=attribution, horizon=horizon, direction=direction,
        leakage_findings=[*leak_lines, str(findings[-1])], acceptance=Acceptance(rule=ACCEPT_RULE, met=met, checks=checks),
        limitations=limitations)
    dev = {"selected": chosen_id, "params": ladder_params[chosen_id]}
    return ScopeRun(card, payload, dev)


def _r(x: float | None, d: int = 4) -> float | None:
    return None if x is None or x != x else round(float(x), d)


ACCEPT_RULE = (
    "Pre-registered in configs/impact_model.yaml before the first held-out run. PRODUCTION needs every check to pass: "
    "C1 rank skill above zero (val+test, 95% interval); C2 lower log-severity error than the constant (paired interval below zero); "
    "C3 not worse than the market-state-only linear model on val and on test; C4 predicted-score buckets ordered by realised severity; "
    "C5 the served realised-score interval covers close to its nominal share; C6 the leakage suite is clean; "
    "C7 more skill on the real window than on the pre-event placebo window; C8 skill on news (2026, publisher timestamps). "
    "A check that cannot be evaluated is not a pass.")


def _acceptance(cfg: ImpactModelConfig, results: list[SetResult], chosen_id: str, base_id: str, cal: CalibrationCard,
                live_rel: Evalset | None, live_min: int, leak: list[str]) -> list[AcceptanceCheck]:
    ac = cfg.acceptance

    def ms(set_id: str) -> ModelScore | None:
        r = next((x for x in results if x.id == set_id), None)
        return next((m for m in r.models if m.id == chosen_id), None) if r else None

    pooled, val, test, live = ms("val+test"), ms("val"), ms("test"), ms("live_reliable")
    out: list[AcceptanceCheck] = []
    c1 = pooled.spearman if pooled else None
    out.append(AcceptanceCheck(id="C1", label="Rank skill on held-out episodes (val+test)", value=_ci_str(c1) if c1 else "n/a",
                               passed=(None if not c1 or c1.lo is None else c1.lo > ac.c1_spearman_ci_lower_above),
                               detail=f"Spearman of prediction vs realised |z|; pass if the 95% interval's lower bound > {ac.c1_spearman_ci_lower_above}"))
    c2 = pooled.delta_mae_vs_constant if pooled else None
    out.append(AcceptanceCheck(id="C2", label="Error vs the constant baseline (val+test)", value=_ci_str(c2) if c2 else "n/a",
                               passed=(None if not c2 or c2.hi is None else c2.hi < ac.c2_mae_improvement_vs_constant_ci_upper_below),
                               detail="paired difference in log-severity MAE; pass if the 95% interval's upper bound < 0"))
    d_val, d_test = (val.delta_mae_vs_market_state if val else None), (test.delta_mae_vs_market_state if test else None)
    ok3 = None if not d_val or not d_test or d_val.value is None or d_test.value is None else (
        d_val.value <= ac.c3_not_worse_than_market_state_baseline_by and d_test.value <= ac.c3_not_worse_than_market_state_baseline_by)
    out.append(AcceptanceCheck(id="C3", label="Not worse than the market-state linear model", passed=ok3,
                               value=f"val {_ci_str(d_val) if d_val else 'n/a'}; test {_ci_str(d_test) if d_test else 'n/a'}",
                               detail=f"point difference in log-severity MAE <= {ac.c3_not_worse_than_market_state_baseline_by} on each of val and test ({base_id})"))
    mono = cal.monotonicity_spearman
    out.append(AcceptanceCheck(id="C4", label="Score buckets ordered by realised severity (val+test)", value="n/a" if mono is None else f"{mono:+.2f}",
                               passed=None if mono is None else mono >= ac.c4_bucket_monotonicity_spearman_min,
                               detail=f"Spearman of bucket order vs bucket median |z| >= {ac.c4_bucket_monotonicity_spearman_min} (needs >= 4 buckets of >= 10 episodes)"))
    cv = cal.heldout_coverage
    out.append(AcceptanceCheck(id="C5", label="Realised-score interval coverage (val+test)", passed=None if cv.value is None else abs(cv.value - cal.nominal_coverage) <= ac.c5_interval_coverage_tolerance,
                               value="n/a" if cv.value is None else f"{cv.value:.2f} (nominal {cal.nominal_coverage:.2f})",
                               detail=f"covered share within {ac.c5_interval_coverage_tolerance} of nominal"))
    out.append(AcceptanceCheck(id="C6", label="Leakage suite clean", passed=not any("[ERROR]" in x for x in leak),
                               value=f"{len(leak)} checks", detail="feature registry, group straddle, time order + embargo, rolling folds, fit invariance"))
    plc = pooled.placebo_spearman if pooled else None
    gap = (pooled.spearman.value - plc.value) if pooled and pooled.spearman.value is not None and plc and plc.value is not None else None
    out.append(AcceptanceCheck(id="C7", label="More skill on the real window than on the pre-event placebo (val+test)",
                               value="n/a" if gap is None else f"{gap:+.3f} (real {pooled.spearman.value:+.3f}, placebo {plc.value:+.3f})",
                               passed=None if gap is None else gap > ac.c7_real_minus_placebo_spearman_above,
                               detail="skill that also predicts the window before the event is market state, not the event"))
    n_live = live_rel.view.n_ep if live_rel else 0
    c8 = live.spearman if live else None
    out.append(AcceptanceCheck(id="C8", label="Rank skill on 2026 news with publisher timestamps", value=_ci_str(c8) if (c8 and n_live >= live_min) else f"n/a ({n_live} episodes, need {live_min})",
                               passed=None if (not c8 or c8.lo is None or n_live < live_min) else c8.lo > ac.c8_live_spearman_ci_lower_above,
                               detail="the served documents are news with first-seen or publisher clocks, unlike the 2022 tweets"))
    return out


def _summary(scope: str, lifecycle: ImpactLifecycle, chosen: str, results: list[SetResult], checks: list[AcceptanceCheck]) -> str:
    ok = [c.id for c in checks if c.passed is True]
    bad = [c.id for c in checks if c.passed is False]
    na = [c.id for c in checks if c.passed is None]
    pooled = next((r for r in results if r.id == "val+test"), None)
    m = next((x for x in pooled.models if x.id == chosen), None) if pooled else None
    skill = f" Held-out rank skill {m.spearman.value:+.2f} (95% interval {m.spearman.lo:+.2f} to {m.spearman.hi:+.2f})." if m and m.spearman.lo is not None else ""
    return (f"{lifecycle.value}: {chosen} selected out of fold.{skill} Acceptance: passed {', '.join(ok) or 'none'}; "
            f"failed {', '.join(bad) or 'none'}; not evaluable {', '.join(na) or 'none'}.")


def _limitations(scope: str, fr: Frame, n_ep: dict[str, int], checks: list[AcceptanceCheck]) -> list[str]:
    out = [f"Held-out evidence is {n_ep['val'] + n_ep['test']} episodes (val {n_ep['val']}, test {n_ep['test']}): intervals are wide.",
           "Validation and test are 2022 tweets; training is mostly 2015-2019 tweets and headlines. News (2026) is the served domain and is scored separately.",
           "The target is a coincident market-response proxy: coverage is partly a reaction to a move, so this is not a clean forecast."]
    if scope == ISSUER:
        out.append("34 current large caps: severity is calibrated for them and does not transfer to small or distressed issuers.")
    else:
        out.append("Market scope: documents without a listed issuer are often not market news at all; the target is the S&P 500's own move on that session.")
    if any(c.passed is None for c in checks):
        out.append("At least one acceptance check could not be evaluated for lack of data; that keeps the scope below PRODUCTION.")
    return out


def _strata(fr: Frame, idx: np.ndarray, row_pred: np.ndarray, const_step, const_row_pred: np.ndarray, cfg: ImpactModelConfig) -> list[Stratum]:
    out: list[Stratum] = []
    minn = cfg.evaluation.min_stratum_episodes
    ibn = cfg.evaluation.bootstrap_resamples

    def one(dim: str, val: str, m: np.ndarray) -> None:
        if m.sum() == 0:
            return
        sub = idx[m]
        v = make_view(fr.ep[sub], fr.y[sub], fr.absz[sub], fr.score[sub], fr.placebo[sub])
        if v.n_ep < minn:
            return
        pe, ce = v.aggregate(row_pred[m]), v.aggregate(const_row_pred[m])
        ib = boot_indices(v.n_ep, ibn, 21)
        out.append(Stratum(dimension=dim, value=val, n_episodes=v.n_ep, spearman=spearman_estimate(pe, v.absz, ib),
                           mae_model=_r(float(np.abs(pe - v.y).mean())), mae_constant=_r(float(np.abs(ce - v.y).mean()))))

    for dim, arr in (("event type", fr.event_top[idx]), ("event status", fr.event_status[idx]), ("timestamp quality", fr.timing[idx]),
                     ("source", fr.adapter[idx])):
        for val in sorted(set(arr)):
            one(dim, str(val), arr == val)
    sc = fr.score[idx]
    for lo, hi, lab in ((1, 2, "realised score 1-2"), (3, 4, "realised score 3-4"), (5, 6, "realised score 5-6"), (7, 10, "realised score 7-10")):
        m = (sc >= lo) & (sc <= hi)
        if m.sum() >= minn:
            sub = idx[m]
            v = make_view(fr.ep[sub], fr.y[sub], fr.absz[sub], fr.score[sub], fr.placebo[sub])
            pe, ce = v.aggregate(row_pred[m]), v.aggregate(const_row_pred[m])
            out.append(Stratum(dimension="magnitude (by outcome)", value=lab, n_episodes=v.n_ep, spearman=estimate(None),
                               mae_model=_r(float(np.abs(pe - v.y).mean())), mae_constant=_r(float(np.abs(ce - v.y).mean()))))
    if fr.scope == ISSUER:
        rhos, n = [], 0
        for t in sorted(set(fr.ticker[idx])):
            m = fr.ticker[idx] == t
            sub = idx[m]
            v = make_view(fr.ep[sub], fr.y[sub], fr.absz[sub], fr.score[sub], fr.placebo[sub])
            if v.n_ep >= cfg.evaluation.per_issuer_min_episodes:
                r = spearman(v.aggregate(row_pred[m]), v.absz)
                if r == r:
                    rhos.append(r)
                    n += 1
        if rhos:
            out.append(Stratum(dimension="issuer (macro average)", value=f"mean of {n} issuers", n_episodes=n,
                               spearman=estimate(float(np.mean(rhos))), mae_model=None, mae_constant=None))
    return out


def _direction(fr: Frame, idx: np.ndarray, cfg: ImpactModelConfig) -> DirectionCheck:
    """Diagnostic only (never part of the score): does confident, non-neutral sentiment point the way the stock then moved?"""
    m = (np.abs(fr.sent[idx]) >= 0.5) & (fr.p_none[idx] < 0.5)
    sub = idx[m]
    if len(sub) < 30:
        return DirectionCheck(n=int(len(sub)), hit_rate=estimate(None), note="too few confident, event-like, non-neutral documents to say anything")
    hit = (np.sign(fr.sent[sub]) == np.sign(fr.z[sub])).astype(float)
    eps = fr.ep[sub]
    uniq = np.unique(eps)
    per = np.array([hit[eps == e].mean() for e in uniq])
    ib = boot_indices(len(per), cfg.evaluation.bootstrap_resamples, 31)
    vals = per[ib].mean(axis=1)
    return DirectionCheck(n=int(len(sub)), hit_rate=estimate(float(per.mean()), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))),
                          note="sign of (P(pos) - P(neg)) vs sign of the realised abnormal return; 0.5 is a coin flip. Reported, not used by the score.")


# ------------------------------------------------------------------------------------------------------------ orchestration
def run(config_dir: Path, repo_root: Path, dev_only: Path | None, log=print) -> int:
    cfg = load_impact_model_config(config_dir)
    mcfg = load_modeling_config(config_dir)
    table = repo_root / cfg.table
    manifest_path = repo_root / cfg.manifest_file
    for p in (table, manifest_path):
        if not p.is_file():
            raise ConfigError(f"missing {p}: run `make impact-table` first (needs data/raw and data/processed/history)")
    table_sha = sha256_file(table)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["table_sha256"] != table_sha:
        raise ConfigError("the impact table does not match its manifest: rebuild it with `make impact-table`")
    if manifest["feature_schema"] != FEATURE_SCHEMA or cfg.feature_schema != FEATURE_SCHEMA:
        raise ConfigError("feature schema mismatch between the table, the config and the code")
    cfg_sha = sha256_file(config_dir / "impact_model.yaml")
    rows = load_table(table)
    log(f"impact table: {len(rows)} rows, sha256 {table_sha[:12]}")
    cut = list(mcfg.impact.score_cutpoints)
    runs = {}
    for scope in SCOPES:
        log(f"scope {scope}")
        runs[scope] = run_scope(scope, rows, cfg, cut, table_sha, cfg_sha, dev_only is not None, log)
        log(f"  [{scope}] {runs[scope].card.lifecycle.value}: {runs[scope].card.summary}")
    if dev_only is not None:
        dev_only.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dev_only / "dev_report.json",
                          json.dumps({s: r.card.model_dump(mode="json") for s, r in runs.items()}, indent=1, sort_keys=True) + "\n")
        log(f"--dev-only: wrote {dev_only / 'dev_report.json'}; test and live were not scored, nothing was promoted")
        return 0
    return write_artifact(cfg, repo_root, runs, manifest, table_sha, log)


def write_artifact(cfg: ImpactModelConfig, repo_root: Path, runs: dict[str, ScopeRun], manifest: dict, table_sha: str, log) -> int:
    import importlib.metadata as md

    import joblib

    out = repo_root / cfg.model_dir
    out.mkdir(parents=True, exist_ok=True)
    payload = {"schema": PAYLOAD_SCHEMA, "feature_schema": FEATURE_SCHEMA,
               "scopes": {s: r.payload for s, r in runs.items() if r.payload is not None}}
    art = out / ARTIFACT_FILE
    joblib.dump(payload, art, compress=3)
    sha = sha256_file(art)
    libs = {k: md.version(k) for k in ("scikit-learn", "numpy", "scipy")}
    card = ImpactModelCard(
        id=cfg.version, version=cfg.version, feature_schema=FEATURE_SCHEMA,
        output_definition=("Per scope: predicted log1p(|z|) of the two-session market response (z = abnormal return / trailing sigma), "
                           "rank-calibrated to a 1-10 EventShock score with an empirical uncertainty interval; attributions are exact for the additive model."),
        artifact_file=ARTIFACT_FILE, artifact_sha256=sha, artifact_bytes=art.stat().st_size, libraries=libs,
        dataset={"table_sha256": table_sha, "rows": int(manifest["rows"]), "feature_schema": manifest["feature_schema"],
                 "history_signals_sha256": manifest["inputs"]["history_signals"]["sha256"],
                 "modeling_config_digest": manifest["inputs"]["modeling_config_digest"]},
        selection_rule="rolling-origin out-of-fold log-severity MAE; a more complex rung is adopted only if its paired improvement interval is entirely below zero",
        scopes=[runs[s].card for s in SCOPES])
    (out / CARD_FILE).write_text(json.dumps(card.model_dump(mode="json"), indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    # the artifact must load through the real serving class and reproduce the in-memory numbers
    model = ImpactModel.load(out, cfg.min_link_confidence)
    log(f"wrote {out}  sha256 {sha[:12]}  ({art.stat().st_size / 1e6:.2f} MB); reloaded: served scopes {model.served_scopes}, "
        f"lifecycle { {s: v.value for s, v in model.lifecycle.items()} }")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eventshock.modeling train-impact")
    ap.add_argument("--dev-only", metavar="OUT_DIR", type=Path)
    args = ap.parse_args(argv)
    return run(REPO_ROOT / "configs", REPO_ROOT, args.dev_only)


if __name__ == "__main__":
    sys.exit(main())
