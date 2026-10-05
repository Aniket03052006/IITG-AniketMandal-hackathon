"""Phase 3 of Stage 8: does the severity scorecard mean anything against realised market outcomes?

The pre-registered test (``configs/evidence_v3.yaml: severity_validity``) scores the headline of every news episode with the TEXT-ONLY severity-v2
scorecard (rules extractor -> rubric -> matrix; no VIX regime, no novelty, no language model) and asks whether that score ranks the episode's
realised ``outcome-v3`` move (log1p |z|), after removing what a volatility-regime baseline already explains, and by more than it ranks the
placebo window before the report. Nothing here changes a cue, an anchor or a threshold: the scorecard is evaluated as shipped.

Labels (strongest that holds on BOTH test 2025 and live 2026): OUTCOME_VALIDATED, DIRECTIONALLY_INFORMATIVE, HEURISTIC_UNCALIBRATED.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import rankdata
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from ..assessment import benchmark as bm
from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text, sha256_file
from .evidence_v3 import load_evidence_v3
from .impact_stats import wilson
from .market import PriceStore
from .outcome_audit import (
    build_store,
    clean,
    earnings_sessions,
    has_session_in,
    load_issuer_episodes,
    regime_cutpoints,
    tercile_of,
)
from .outcome_v3 import VERSION as OUTCOME_VERSION
from .outcome_v3 import outcome_v3

SCHEMA = "severity-validity-v1"
NAN = float("nan")
COVARIATES = ("f_vix_level", "f_resid_vol_5d_ratio", "f_resid_vol_20d_ratio", "f_sigma_60")
MARKET_COVARIATES = ("m_vix_level", "m_dev_vol_5d_ratio", "m_dev_vol_20d_ratio", "m_sigma_60")


# ------------------------------------------------------------------------------------------------ statistics
def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman correlation with mid-ranks for ties; NaN for fewer than 5 points or a constant side."""
    if a.size < 5:
        return NAN
    ra, rb = rankdata(a), rankdata(b)
    if ra.std() == 0 or rb.std() == 0:
        return NAN
    return float(np.corrcoef(ra, rb)[0, 1])


def cluster_bootstrap(stats: dict[str, Callable[[np.ndarray], float]], dates: np.ndarray, *, resamples: int, seed: int, ci: float = 0.95
                      ) -> dict[str, dict[str, float | int | None]]:
    """Point estimate and percentile interval of each statistic over the SAME resamples of reaction dates (so differences are paired).

    ``stats[name](idx)`` is evaluated on the row indices ``idx``. Issuers that react on one date move together, so dates are the resampling unit.
    """
    by_date: dict[Any, list[int]] = defaultdict(list)
    for i, d in enumerate(dates):
        by_date[d].append(i)
    groups = [np.asarray(v) for v in by_date.values()]
    rng = random.Random(seed)
    all_idx = np.arange(dates.size)
    point = {k: f(all_idx) for k, f in stats.items()}
    draws: dict[str, list[float]] = {k: [] for k in stats}
    for _ in range(resamples):
        idx = np.concatenate([groups[rng.randrange(len(groups))] for _ in groups])
        for k, f in stats.items():
            v = f(idx)
            if v == v:
                draws[k].append(v)
    out: dict[str, dict[str, float | int | None]] = {}
    lo_q, hi_q = (1 - ci) / 2, 1 - (1 - ci) / 2
    for k in stats:
        d = sorted(draws[k])
        out[k] = {"estimate": point[k], "lo": d[int(lo_q * len(d))] if len(d) >= 50 else None,
                  "hi": d[min(len(d) - 1, int(hi_q * len(d)))] if len(d) >= 50 else None, "valid_draws": len(d)}
    return out


def band_table(score: np.ndarray, tail: np.ndarray, bands: dict[str, list[int]]) -> list[dict[str, Any]]:
    """P(tail) per severity band with Wilson intervals; band 'abstained' holds the NO_EVENT readings (score 0)."""
    rows = []
    for name, (lo, hi) in [("abstained", [0, 0]), *bands.items()]:
        m = (score >= lo) & (score <= hi)
        n, k = int(m.sum()), int(tail[m].sum())
        w = wilson(k, n) if n else (None, None)
        rows.append({"band": name, "scores": [lo, hi], "n": n, "tail_events": k, "rate": k / n if n else None, "wilson_lo": w[0], "wilson_hi": w[1]})
    return rows


def monotone_check(rows: list[dict[str, Any]], min_n: int) -> dict[str, Any]:
    """Rank correlation of band order vs band tail rate over the populated bands (abstentions excluded). Needs at least 3 bands.

    Unlike ``spearman`` this has no 5-point floor: the pre-registered rule asks for as few as four populated bands.
    """
    used = [r for r in rows if r["band"] != "abstained" and r["n"] >= min_n and r["rate"] is not None]
    if len(used) < 3:
        return {"bands_used": len(used), "spearman": None}
    order, rate = rankdata(np.arange(len(used), dtype=float)), rankdata(np.asarray([r["rate"] for r in used]))
    if order.std() == 0 or rate.std() == 0:
        return {"bands_used": len(used), "spearman": None}
    return {"bands_used": len(used), "spearman": float(np.corrcoef(order, rate)[0, 1])}


# ------------------------------------------------------------------------------------------------ episodes with scores and outcomes
def attach_scores(episodes: list[dict[str, Any]], rig: bm.Rig, *, log=print) -> None:
    """Text-only rules score (0 = the extractor found no market event) and event type, in place."""
    for i, e in enumerate(episodes):
        r = bm.score_text(rig, str(e["text"]), None, use_llm=False)
        e["score"] = int(r["score"]) if r["score"] is not None else 0
        e["event_type_rules"] = r["event_type"]
        if i and i % 5000 == 0:
            log(f"  scored {i}/{len(episodes)}")


def attach_outcomes(episodes: list[dict[str, Any]], store: PriceStore, earn: dict[str, list[int]], placebo_offset: int) -> tuple[list[dict[str, Any]], Counter]:
    """outcome-v3 (and v2) for the report window and the placebo window. Episodes whose outcome cannot be computed are dropped, by reason."""
    kept, dropped = [], Counter()
    window = store.cfg.window_sessions
    for e in episodes:
        o, why = outcome_v3(store, e["ticker"], int(e["s0"]))
        p, pwhy = outcome_v3(store, e["ticker"], int(e["s0"]) + placebo_offset)
        if o is None or p is None:
            dropped[why or ("PLACEBO_" + pwhy)] += 1
            continue
        e.update(z=o.z, abs_z=o.abs_z, car=o.car, y=math.log1p(o.abs_z), z60=o.z60, y60=math.log1p(abs(o.z60)),
                 y_placebo=math.log1p(p.abs_z), y60_placebo=math.log1p(abs(p.z60)),
                 earn_in_target=has_session_in(earn.get(e["ticker"], []), int(e["s0"]), int(e["s0"]) + window - 1))
        kept.append(e)
    return kept, dropped


def regime_baseline(train: list[dict[str, Any]], alpha: float, covariates: tuple[str, ...] = COVARIATES) -> Callable[[list[dict[str, Any]]], np.ndarray]:
    """Ridge of y on the registered regime covariates, fitted on the train split only. Missing covariates take the train median."""
    def mat(rows: list[dict[str, Any]]) -> np.ndarray:
        return np.asarray([[NAN if r.get(c) is None else float(r[c]) for c in covariates] for r in rows], dtype=float)

    x = mat(train)
    med = np.nanmedian(x, axis=0)
    scaler = StandardScaler().fit(np.where(np.isnan(x), med, x))
    model = Ridge(alpha=alpha).fit(scaler.transform(np.where(np.isnan(x), med, x)), np.asarray([r["y"] for r in train]))

    def predict(rows: list[dict[str, Any]]) -> np.ndarray:
        m = mat(rows)
        return model.predict(scaler.transform(np.where(np.isnan(m), med, m)))

    return predict


# ------------------------------------------------------------------------------------------------ the study
def evaluate_split(rows: list[dict[str, Any]], predict: Callable[[list[dict[str, Any]]], np.ndarray], cuts: tuple[float, float], cfg: dict[str, Any],
                   boot: dict[str, Any], seed: int, *, y_key: str = "y", yp_key: str = "y_placebo", vix_key: str = "f_vix_level") -> dict[str, Any]:
    if len(rows) < 100:
        return {"n": len(rows), "note": "too few episodes to evaluate"}
    score = np.asarray([r["score"] for r in rows], dtype=float)
    y, yp = np.asarray([r[y_key] for r in rows]), np.asarray([r[yp_key] for r in rows])
    resid = y - predict(rows)
    regime = np.asarray([tercile_of(float(r[vix_key]), cuts) if r.get(vix_key) is not None else 1 for r in rows])
    dates = np.asarray([r["s0_date"] for r in rows])

    def m2(idx: np.ndarray) -> float:
        vals = [spearman(score[idx][regime[idx] == t], y[idx][regime[idx] == t]) for t in (0, 1, 2) if (regime[idx] == t).sum() >= 30]
        vals = [v for v in vals if v == v]
        return float(np.mean(vals)) if vals else NAN

    stats = {
        "M1_overall_rank": lambda idx: spearman(score[idx], y[idx]),
        "M2_within_regime_rank": m2,
        "M3_real_minus_placebo": lambda idx: spearman(score[idx], y[idx]) - spearman(score[idx], yp[idx]),
        "M4_increment_over_regime": lambda idx: spearman(score[idx], resid[idx]),
        "placebo_rank": lambda idx: spearman(score[idx], yp[idx]),
    }
    est = cluster_bootstrap(stats, dates, resamples=int(boot["resamples"]), seed=seed, ci=float(boot["ci"]))
    tail = np.asarray([r["abs_z"] >= 2.0 for r in rows])
    bt = band_table(score, tail, cfg["bands"])
    return {"n": len(rows), "abstained_share": float((score == 0).mean()), "score_counts": {str(k): int(v) for k, v in sorted(Counter(score.astype(int)).items())},
            "metrics": est, "band_table": bt, "overall_tail_rate": float(tail.mean()), "monotone": monotone_check(bt, 30)}


def decide_label(by_split: dict[str, dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    """The strongest label whose pre-registered conditions hold on BOTH test and live. Missing intervals fail the condition."""
    def lower(split: str, metric: str) -> float | None:
        m = by_split.get(split, {}).get("metrics", {}).get(metric)
        return None if not m else m["lo"]

    def holds(metrics: list[str]) -> dict[str, bool]:
        return {f"{s}:{m}": (lower(s, m) is not None and lower(s, m) > 0) for s in ("test", "live") for m in metrics}

    spec = cfg["labels"]
    strong = holds(spec["OUTCOME_VALIDATED"]["require_lower_ci_above_zero"])
    mono_spec = spec["OUTCOME_VALIDATED"]["require_monotone_bands"]
    mono = {}
    for s in ("test", "live"):
        mo = by_split.get(s, {}).get("monotone", {})
        mono[s] = bool(mo.get("spearman") is not None and mo["spearman"] >= mono_spec["min_spearman"] and mo["bands_used"] >= mono_spec["min_bands_with_n30"])
    weak = holds(spec["DIRECTIONALLY_INFORMATIVE"]["require_lower_ci_above_zero"])
    if all(strong.values()) and all(mono.values()):
        label = "OUTCOME_VALIDATED"
    elif all(weak.values()):
        label = "DIRECTIONALLY_INFORMATIVE"
    else:
        label = "HEURISTIC_UNCALIBRATED"
    return {"label": label, "outcome_validated_conditions": strong, "monotone_bands": mono, "directional_conditions": weak}


def load_market_docs(table: Path) -> list[dict[str, Any]]:
    """Market-scope news documents (they name no listed issuer): one row per document, outcome shared by the session."""
    rows = []
    with table.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("scope") == "MARKET" and r.get("is_news") == 1.0:
                rows.append({k: r.get(k) for k in ("id", "s0", "s0_date", "text", "timing", "origin", "published_at", "m_vix_level", "m_dev_vol_5d_ratio",
                                                   "m_dev_vol_20d_ratio", "m_sigma_60")} | {"split": r.get("split_P2_extended")})
    return rows


def market_validity(table: Path, store: PriceStore, rig: bm.Rig, cfg: dict[str, Any], boot: dict[str, Any], seed: int, cuts: tuple[float, float], *, log=print) -> dict[str, Any]:
    """POST-HOC (not pre-registered): the same test on market-scope reports against the S&P 500's excess move, the outcome that matches what severity means."""
    docs = load_market_docs(table)
    log(f"market scope: scoring {len(docs)} documents ...")
    attach_scores(docs, rig, log=log)
    kept = []
    off = int(store.cfg.placebo_offset_sessions)
    for d in docs:
        t, _ = store.market_target(int(d["s0"]))
        p, _ = store.market_target(int(d["s0"]) + off)
        if t is None or p is None:
            continue
        d.update(z=t.z, abs_z=t.abs_z, y=math.log1p(t.abs_z), y60=math.log1p(t.abs_z), y_placebo=math.log1p(p.abs_z), y60_placebo=math.log1p(p.abs_z))
        kept.append(d)
    base = regime_baseline([d for d in kept if d["split"] == "train"], float(cfg["regime_baseline"]["model"]["alpha"]), MARKET_COVARIATES)
    split_of = {"dev": ["train", "val"], "test": ["test"], "live": ["live"]}
    by = {n: evaluate_split([d for d in kept if d["split"] in m], base, cuts, cfg, boot, seed, vix_key="m_vix_level") for n, m in split_of.items()}
    return {"note": "POST-HOC extension, not in the pre-registration: market-scope reports vs the S&P 500's excess move (outcome-v2 market definition); it does not change the label",
            "documents": len(kept), "label_if_it_had_been_registered": decide_label(by, cfg)["label"], "by_split": by}


def run_validity(repo_root: Path, config_dir: Path, out_path: Path, *, log=print, limit: int | None = None) -> dict[str, Any]:
    pre, pre_sha = load_evidence_v3(config_dir)
    cfg = pre["severity_validity"]
    table = repo_root / pre["data"]["impact_table"]
    if not table.is_file():
        raise ConfigError(f"missing {table}: `make impact-table-v2`")
    store = build_store(repo_root, config_dir)
    cuts = regime_cutpoints(store, pre)
    log("loading episodes ...")
    episodes, _ = load_issuer_episodes(table)
    if limit:
        episodes = episodes[:: max(1, len(episodes) // limit)]
    log(f"scoring {len(episodes)} headlines with the text-only rules scorecard ...")
    attach_scores(episodes, bm.Rig.build(config_dir), log=log)
    earn = earnings_sessions(store, repo_root / pre["data"]["filings"])
    episodes, dropped = attach_outcomes(episodes, store, earn, int(store.cfg.placebo_offset_sessions))

    split_of = {"train": ["train"], "val": ["val"], "dev": ["train", "val"], "test": ["test"], "live": ["live"]}
    base = regime_baseline([e for e in episodes if e["split"] == "train"], float(cfg["regime_baseline"]["model"]["alpha"]))
    boot = pre["bootstrap"]
    seed = int(pre["seed"])
    by_split = {name: evaluate_split([e for e in episodes if e["split"] in members], base, cuts, cfg, boot, seed) for name, members in split_of.items()}
    label = decide_label(by_split, cfg)

    # secondary, reported without labels: outcome-v2 target, and the episodes whose reaction window holds no earnings (the audit found they carry no lift)
    secondary = {}
    for name in ("test", "live"):
        rows = [e for e in episodes if e["split"] == name]
        secondary[name] = {
            "outcome_v2": evaluate_split(rows, base, cuts, cfg, {**boot, "resamples": min(int(boot["resamples"]), 500)}, seed, y_key="y60", yp_key="y60_placebo"),
            "no_earnings_in_window": evaluate_split([e for e in rows if not e["earn_in_target"]], base, cuts, cfg, {**boot, "resamples": min(int(boot["resamples"]), 500)}, seed),
            "scored_only_score_ge_1": evaluate_split([e for e in rows if e["score"] >= 1], base, cuts, cfg, {**boot, "resamples": min(int(boot["resamples"]), 500)}, seed),
        }
    market = market_validity(table, store, bm.Rig.build(config_dir), cfg, boot, seed, cuts, log=log)
    out = {
        "schema": SCHEMA, "evidence_version": pre["version"], "preregistration_sha256": pre_sha, "seed": seed, "outcome_version": OUTCOME_VERSION,
        "predictor": cfg["predictor"], "inputs": {"impact_table_sha256": sha256_file(table), "episodes": len(episodes), "dropped_no_outcome": dict(dropped),
                                                  "limit": limit},
        "vix_tercile_cutpoints": list(cuts), "regime_baseline": {"covariates": list(COVARIATES), "alpha": cfg["regime_baseline"]["model"]["alpha"], "fit_on": "train"},
        "label": label, "by_split": by_split, "secondary": secondary, "posthoc_market_scope": market,
        "reading": ("The label is the strongest pre-registered condition that holds on both test (2025) and live (2026). 'HEURISTIC_UNCALIBRATED' means the score is a "
                    "transparent scale that has not been shown to rank realised market moves beyond the volatility regime; it is not a claim that it is useless."),
    }
    atomic_write_text(out_path, json.dumps(clean(out), indent=2, sort_keys=True, allow_nan=False) + "\n")
    log(f"wrote {out_path}")
    return out
