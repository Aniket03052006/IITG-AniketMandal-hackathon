"""Does retrieval add information about the realised move beyond what the model already has? (Stage 8, Phase 5; pre-registered.)

Baseline ``B0``: ridge on the registered ``R2s`` features (market state + timing + structured calendar), issuer scope, target ``log1p |z|`` (outcome-v3).
Candidates: ``C_knn`` (B0 + point-in-time neighbour-outcome features) and ``G_reference_class`` (B0 + the shrunk mean outcome of the report's
event-class x VIX-tercile cell). Each candidate is compared with B0 by a paired MAE difference with a clustered (by reaction date) bootstrap on the
2025 test and 2026 live episodes, and by whether it widens the gap between predicting the real window and the placebo window. An analogue-derived
quantity may enter the severity score only if the pre-registered rule is met on BOTH test and live; otherwise it is display evidence.

The neighbour features of an episode use only index rows that pass the point-in-time rule at that episode's publication date (``search.collect``), so a
row's own outcome, and any outcome whose window overlaps its own, can never reach its features.

The module also applies the pre-registered similarity-floor rule (dev data only): see ``choose_floor``.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..modeling.evidence_v3 import load_evidence_v3
from ..modeling.outcome_audit import build_store, clean, regime_cutpoints, tercile_of
from ..modeling.outcome_v3 import outcome_v3
from ..modeling.severity_validity import cluster_bootstrap, spearman
from ..pipeline.impact_features_v2 import feature_names_v2
from .build import build_index
from .corpus import load_corpus
from .index import AnalogueIndex
from .relevance_eval import K, lift_at_threshold, load_vectors
from .search import SearchParams, collect, search

SCHEMA = "analogue-outcome-value-v1"
NAN = float("nan")
KNN_NAMES = ("knn_mean_log1p_absz", "knn_n_eff", "knn_max_sim", "knn_available")
SHRINK_K = 20


# ------------------------------------------------------------------------------------------------ the floor rule
def choose_floor(grid: list[float], lifts: dict[float, float | None], answerable: dict[float, float], *, min_lift: float, min_answerable: float) -> dict[str, Any]:
    """The smallest grid value whose dev event-type precision lift >= ``min_lift`` and whose dev answerable share >= ``min_answerable``; else NOT_VIABLE."""
    rows = [{"floor": t, "precision_lift": lifts.get(t), "answerable_share": answerable.get(t),
             "ok": bool(lifts.get(t) is not None and lifts[t] >= min_lift and answerable.get(t, 0.0) >= min_answerable)} for t in sorted(grid)]
    chosen = next((r["floor"] for r in rows if r["ok"]), None)
    return {"rule": f"smallest floor with precision lift >= {min_lift} and answerable share >= {min_answerable}", "curve": rows, "chosen": chosen,
            "viable": chosen is not None}


def knn_features(index: AnalogueIndex, vectors: np.ndarray, rows: list[dict[str, Any]], params: SearchParams) -> np.ndarray:
    """(n, 4) neighbour features per query row, point-in-time. Columns follow ``KNN_NAMES``; the mean is NaN when nothing is above the floor."""
    out = np.full((len(rows), 4), NAN, dtype=float)
    for j, r in enumerate(rows):
        c = collect(index, vectors[j], query_date=r["published_at"][:10], scope="ISSUER", params=params, exclude_ids=frozenset({r["id"]}))
        reps = c.reps[: params.aggregate_over]
        if reps:
            w = np.asarray([s for _, s in reps])
            y = np.asarray([np.log1p(index.rows[i]["abs_z"]) for i, _ in reps])
            out[j] = [float((w * y).sum() / w.sum()), len(reps), float(w.max()), 1.0]
        else:
            out[j] = [NAN, 0.0, 0.0, 0.0]
    return out


def reference_class_feature(rows: list[dict[str, Any]], y: np.ndarray, train: np.ndarray, tercile: np.ndarray) -> np.ndarray:
    """Shrunk mean of y in each (model event class x VIX tercile) cell. Train rows use leave-one-out so a row never sees its own outcome."""
    glob = float(y[train].mean())
    sums: dict[tuple[str, int], float] = {}
    cnts: dict[tuple[str, int], int] = {}
    keys = [(str(r.get("event_top")), int(t)) for r, t in zip(rows, tercile, strict=True)]
    for k, yy, tr in zip(keys, y, train, strict=True):
        if tr:
            sums[k] = sums.get(k, 0.0) + float(yy)
            cnts[k] = cnts.get(k, 0) + 1
    out = np.empty(len(rows))
    for i, k in enumerate(keys):
        s, n = sums.get(k, 0.0), cnts.get(k, 0)
        if train[i]:
            s, n = s - float(y[i]), n - 1
        out[i] = (s + SHRINK_K * glob) / (n + SHRINK_K)
    return out


# ------------------------------------------------------------------------------------------------ models
def fit_ridge(x: np.ndarray, y: np.ndarray, train: np.ndarray, val: np.ndarray, grid: list[float]) -> tuple[np.ndarray, float]:
    """Predictions for every row from a ridge fitted on train (median-imputed, standardised); alpha chosen by validation MAE."""
    med = np.nanmedian(x[train], axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    xi = np.where(np.isnan(x), med, x)
    sc = StandardScaler().fit(xi[train])
    xs = sc.transform(xi)
    best = (float("inf"), grid[0], None)
    for a in grid:
        m = Ridge(alpha=a).fit(xs[train], y[train])
        mae = float(np.abs(m.predict(xs[val]) - y[val]).mean())
        if mae < best[0]:
            best = (mae, a, m)
    return best[2].predict(xs), float(best[1])  # type: ignore[union-attr]


def compare(pred: dict[str, np.ndarray], y: np.ndarray, yp: np.ndarray, dates: np.ndarray, idx: np.ndarray, *, resamples: int, seed: int, ci: float) -> dict[str, Any]:
    """Each candidate against B0 on the rows ``idx``: paired MAE difference and the change in (rank skill on the real window - on the placebo window)."""
    yy, pp, dd = y[idx], yp[idx], dates[idx]
    out: dict[str, Any] = {"n": int(idx.size)}
    p0 = pred["B0"][idx]
    for name, p in pred.items():
        q = p[idx]
        stats = {"mae": lambda i, q=q: float(np.abs(q[i] - yy[i]).mean()), "rho_real": lambda i, q=q: spearman(q[i], yy[i]),
                 "rho_placebo": lambda i, q=q: spearman(q[i], pp[i])}
        if name != "B0":
            stats["delta_mae_vs_B0"] = lambda i, q=q: float(np.abs(q[i] - yy[i]).mean() - np.abs(p0[i] - yy[i]).mean())
            stats["delta_real_minus_placebo_vs_B0"] = lambda i, q=q: (spearman(q[i], yy[i]) - spearman(q[i], pp[i])) - (spearman(p0[i], yy[i]) - spearman(p0[i], pp[i]))
        out[name] = cluster_bootstrap(stats, dd, resamples=resamples, seed=seed, ci=ci)
    return out


def enter_score(res: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    """Apply ``enter_score_if`` to one candidate on test and live. Missing or undefined intervals fail."""
    verdict: dict[str, Any] = {}
    for cand in ("C_knn", "G_reference_class"):
        checks = {}
        for split in rule["delta_mae_upper_ci_below_zero"]:
            d = res.get(split, {}).get(cand, {}).get("delta_mae_vs_B0")
            checks[f"{split}:mae_improves"] = bool(d and d["hi"] is not None and d["hi"] < 0)
            if rule.get("real_minus_placebo_improves"):
                r = res.get(split, {}).get(cand, {}).get("delta_real_minus_placebo_vs_B0")
                checks[f"{split}:real_minus_placebo_improves"] = bool(r and r["lo"] is not None and r["lo"] > 0)
        verdict[cand] = {"checks": checks, "may_enter_score": all(checks.values()) and bool(checks)}
    return verdict


# ------------------------------------------------------------------------------------------------ the study
def _table_features(table: Path, ids: set[str], names: list[str]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    with table.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["id"] in ids:
                out[r["id"]] = [NAN if r.get(n) is None else float(r[n]) for n in names]
    return out


def run_outcome_value(repo_root: Path, config_dir: Path, floor: float | None, out_path: Path, *, log=print) -> dict[str, Any]:
    pre, pre_sha = load_evidence_v3(config_dir)
    rcfg = pre["retrieval"]
    table = repo_root / pre["data"]["impact_table"]
    cache = repo_root / "data" / "modeling" / "embeddings" / "intfloat__multilingual-e5-large.npz"
    corpus = load_corpus(repo_root / "data" / "modeling" / "analogue_corpus.jsonl")
    issuer = [r for r in corpus if r["scope"] == "ISSUER"]
    vecs = load_vectors(cache, [r["text"] for r in corpus])
    vec_of = {r["id"]: vecs[i] for i, r in enumerate(corpus)}
    index = build_index(repo_root, config_dir)
    log(f"index: {len(index)} trusted rows")
    params = SearchParams.from_config(pre, floor if floor is not None else 0.84)

    names = feature_names_v2("ISSUER", "R2s")
    feats = _table_features(table, {r["id"] for r in issuer}, names)
    rows = [r for r in issuer if r["id"] in feats]
    x0 = np.asarray([feats[r["id"]] for r in rows], dtype=float)
    split = np.asarray([r["split"] for r in rows])
    dates = np.asarray([r["s0_date"] for r in rows])
    y = np.asarray([np.log1p(r["abs_z"]) for r in rows])
    store = build_store(repo_root, config_dir)
    yp = np.empty(len(rows))
    for i, r in enumerate(rows):
        o, _ = outcome_v3(store, r["ticker"], int(r["s0"]) + int(store.cfg.placebo_offset_sessions))
        yp[i] = np.log1p(o.abs_z) if o else NAN
    ok = np.isfinite(yp)
    log(f"issuer rows {len(rows)}, placebo available {int(ok.sum())}; computing neighbour features ...")
    rows_v = np.stack([vec_of[r["id"]] for r in rows])
    knn = knn_features(index, rows_v, rows, params)
    cuts = regime_cutpoints(store, pre)
    terc = np.asarray([tercile_of(float(r["vix_level"]), cuts) if r["vix_level"] is not None else 1 for r in rows])
    train, val = split == "train", split == "val"
    g = reference_class_feature(rows, y, train, terc)
    grid = [0.1, 1.0, 10.0, 100.0]
    knn_f = knn.copy()
    knn_f[:, 0] = np.where(np.isnan(knn_f[:, 0]), np.nanmean(knn_f[train, 0]), knn_f[:, 0])
    preds, alphas = {}, {}
    for name, x in (("B0", x0), ("C_knn", np.hstack([x0, knn_f])), ("G_reference_class", np.hstack([x0, g[:, None]]))):
        preds[name], alphas[name] = fit_ridge(x, y, train, val, grid)
    preds["G_standalone"] = g
    preds["constant"] = np.full(len(rows), float(y[train].mean()))
    boot = pre["bootstrap"]
    resamples, seed, ci = int(boot["resamples"]), int(pre["seed"]), float(boot["ci"])
    res = {}
    for name in ("val", "test", "live"):
        idx = np.flatnonzero((split == name) & ok)
        res[name] = compare(preds, y, yp, dates, idx, resamples=resamples, seed=seed, ci=ci)
    verdict = enter_score(res, rcfg["outcome_value"]["enter_score_if"])
    avail = {n: float(knn[split == n, 3].mean()) for n in ("train", "val", "test", "live")}
    result = {"schema": SCHEMA, "evidence_version": pre["version"], "preregistration_sha256": pre_sha, "seed": seed,
              "inputs": {"corpus_rows": len(corpus), "issuer_rows": len(rows), "index_rows": len(index), "similarity_floor": params.similarity_floor,
                         "features": names, "alphas": alphas, "table_sha256": sha256_file(table), "corpus_sha256": sha256_file(repo_root / "data" / "modeling" / "analogue_corpus.jsonl"),
                         "embedding_cache_sha256": sha256_file(cache)},
              "knn_available_share": avail, "results": res, "enter_score": verdict,
              "decision": ("An analogue-derived quantity may enter the severity score" if any(v["may_enter_score"] for v in verdict.values())
                           else "No analogue-derived quantity enters the severity score: retrieval is display evidence only")}
    atomic_write_text(out_path, json.dumps(clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n")
    log(f"wrote {out_path}")
    return result


def run_floor(repo_root: Path, config_dir: Path, out_path: Path, *, sample: int = 4000, log=print) -> dict[str, Any]:
    """The pre-registered similarity-floor rule on dev data only (labelled dev split for precision; train+val episodes for answerability)."""
    pre, pre_sha = load_evidence_v3(config_dir)
    rcfg = pre["retrieval"]
    rule = rcfg["similarity_floor_rule"]
    cache = repo_root / "data" / "modeling" / "embeddings" / "intfloat__multilingual-e5-large.npz"
    labelled = [json.loads(line) for line in (repo_root / pre["data"]["event_train"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    ann = [r for r in labelled if r["kind"] == "annotated"]
    dev_q, corp = [r for r in ann if r["split"] == "dev" and r["label"] != "NONE"], [r for r in ann if r["split"] == "train"]
    vq, vc = load_vectors(cache, [r["text"] for r in dev_q]), load_vectors(cache, [r["text"] for r in corp])
    sim = vq @ vc.T
    q_lab, c_lab = np.asarray([r["label"] for r in dev_q]), np.asarray([r["label"] for r in corp])
    lifts = {t: lift_at_threshold(sim, q_lab, c_lab, t, K)["lift"] for t in rule["grid"]}
    lift_detail = {str(t): lift_at_threshold(sim, q_lab, c_lab, t, K) for t in rule["grid"]}

    corpus = load_corpus(repo_root / "data" / "modeling" / "analogue_corpus.jsonl")
    vecs = load_vectors(cache, [r["text"] for r in corpus])
    vec_of = {r["id"]: vecs[i] for i, r in enumerate(corpus)}
    index = build_index(repo_root, config_dir)
    dev_eps = [r for r in corpus if r["scope"] == "ISSUER" and r["split"] in ("train", "val")]
    rng = random.Random(int(pre["seed"]))
    picked = rng.sample(dev_eps, min(sample, len(dev_eps)))
    answerable = {}
    for t in rule["grid"]:
        p = SearchParams.from_config(pre, t)
        ok = sum(1 for r in picked if search(index, vec_of[r["id"]], query_date=r["published_at"][:10], scope="ISSUER", params=p,
                                             exclude_ids=frozenset({r["id"]})).status == "OK")
        answerable[t] = ok / len(picked)
        log(f"  floor {t}: answerable {answerable[t]:.3f}, precision lift {lifts[t]}")
    out = choose_floor(list(rule["grid"]), lifts, answerable, min_lift=float(rule["min_lift"]), min_answerable=float(rule["min_answerable_share"]))
    result = {"schema": "analogue-floor-v1", "evidence_version": pre["version"], "preregistration_sha256": pre_sha, "dev_queries_labelled": len(dev_q),
              "labelled_corpus": len(corp), "dev_episodes_sampled": len(picked), "precision_detail": lift_detail, **out}
    atomic_write_text(out_path, json.dumps(clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n")
    log(f"wrote {out_path}")
    return result
