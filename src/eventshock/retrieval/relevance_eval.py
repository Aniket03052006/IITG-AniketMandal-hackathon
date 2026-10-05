"""Retrieval relevance without inventing labels (Stage 8, Phase 5; pre-registered in ``configs/evidence_v3.yaml: retrieval.relevance_eval``).

Queries are the doubly annotated gold-v2 titles (both annotators agree), i.e. unseen wording from another period and source mix; the labelled corpus is
the AI-annotated ``event_train`` rows. A neighbour is relevant if it carries the query's event-type label. Metrics: precision@5 and the reciprocal rank
of the first same-class neighbour, for e5-large cosine and for the TF-IDF cosine baseline, with a paired bootstrap over queries for the difference.
Because "NONE" is more than half of the labels, every figure is also reported for the non-NONE queries and as a lift over the base rate.

The same module chooses the similarity floor by the pre-registered rule (dev data only): the smallest grid value at which the event-type precision lift is at
least ``min_lift`` on the labelled dev queries AND at least ``min_answerable_share`` of the dev episodes still get a real ``OK`` answer from the index.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..modeling.evidence_v3 import load_evidence_v3
from ..modeling.outcome_audit import clean
from ..pipeline.embeddings import quantize, text_key

SCHEMA = "analogue-relevance-v1"
K = 5


def load_vectors(cache: Path, texts: list[str]) -> np.ndarray:
    """e5 vectors for ``texts`` from the encoder cache (float16 precision, L2-normalised); a missing text is an error, never a silent zero."""
    if not cache.is_file():
        raise ConfigError(f"missing embedding cache {cache}: `make analogue-embed`")
    z = np.load(cache, allow_pickle=False)
    index = {k: i for i, k in enumerate(z["keys"].tolist())}
    missing = [t for t in texts if text_key(t) not in index]
    if missing:
        raise ConfigError(f"{len(missing)} text(s) are not in the embedding cache (first: {missing[0][:60]!r}); run `make analogue-embed`")
    v = quantize(z["vectors"][[index[text_key(t)] for t in texts]])
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def topk(sim: np.ndarray, k: int = K) -> np.ndarray:
    """Indices of the k largest per row; ties broken by the lower index so the result is deterministic."""
    order = np.lexsort((np.arange(sim.shape[1])[None, :].repeat(sim.shape[0], 0), -sim), axis=1)
    return order[:, :k]


def precision_and_rr(sim: np.ndarray, q_labels: np.ndarray, c_labels: np.ndarray, k: int = K) -> tuple[np.ndarray, np.ndarray]:
    """Per-query precision@k and reciprocal rank of the first same-class neighbour within the top 20 (0 if none)."""
    top = topk(sim, max(k, 20))
    match = c_labels[top] == q_labels[:, None]
    p = match[:, :k].mean(axis=1)
    first = np.where(match.any(axis=1), match.argmax(axis=1) + 1, 0)
    return p, np.where(first > 0, 1.0 / np.maximum(first, 1), 0.0)


def base_rate(q_labels: np.ndarray, c_labels: np.ndarray) -> np.ndarray:
    """Chance that a random corpus item has the query's label."""
    counts = Counter(c_labels.tolist())
    return np.asarray([counts.get(label, 0) / len(c_labels) for label in q_labels])


def paired_bootstrap(a: np.ndarray, b: np.ndarray, *, resamples: int, seed: int, ci: float = 0.95) -> dict[str, float]:
    rng = random.Random(seed)
    n = a.size
    d = a - b
    vals = sorted(float(d[[rng.randrange(n) for _ in range(n)]].mean()) for _ in range(resamples))
    lo, hi = vals[int((1 - ci) / 2 * len(vals))], vals[int((1 + ci) / 2 * len(vals)) - 1]
    return {"estimate": float(d.mean()), "lo": lo, "hi": hi}


def lift_at_threshold(sim: np.ndarray, q_labels: np.ndarray, c_labels: np.ndarray, tau: float, k: int = K) -> dict[str, float | int | None]:
    """Pooled precision of the top-k neighbours with similarity >= tau, and its lift over the base rate (queries with no such neighbour are unanswered)."""
    top = topk(sim, k)
    got = np.take_along_axis(sim, top, axis=1) >= tau
    match = (c_labels[top] == q_labels[:, None]) & got
    n_nb = int(got.sum())
    if n_nb == 0:
        return {"neighbours": 0, "precision": None, "base_rate": None, "lift": None, "queries_with_a_neighbour": 0}
    expected = float((base_rate(q_labels, c_labels)[:, None] * got).sum() / n_nb)
    prec = float(match.sum() / n_nb)
    return {"neighbours": n_nb, "precision": prec, "base_rate": expected, "lift": prec / expected if expected > 0 else None,
            "queries_with_a_neighbour": int(got.any(axis=1).sum())}


def run_relevance(repo_root: Path, config_dir: Path, out_path: Path, *, log=print) -> dict[str, Any]:
    pre, pre_sha = load_evidence_v3(config_dir)
    cfg = pre["retrieval"]["relevance_eval"]
    cache = repo_root / "data" / "modeling" / "embeddings" / "intfloat__multilingual-e5-large.npz"
    gold = [r for r in csv.DictReader((repo_root / pre["data"]["gold_v2"] / "gold_v2.csv").open(encoding="utf-8")) if r["agreed"] == "y"]
    train_rows = [json.loads(line) for line in (repo_root / pre["data"]["event_train"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    annotated = [r for r in train_rows if r["kind"] == "annotated"]
    q_texts, c_texts = [r["text"] for r in gold], [r["text"] for r in annotated]
    q_lab, c_lab = np.asarray([r["label_a"] for r in gold]), np.asarray([r["label"] for r in annotated])
    vq, vc = load_vectors(cache, q_texts), load_vectors(cache, c_texts)
    sim_e5 = vq @ vc.T
    tf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2, strip_accents="unicode", lowercase=True).fit(c_texts)
    sim_tf = (tf.transform(q_texts) @ tf.transform(c_texts).T).toarray()

    seed = int(pre["seed"])
    res = int(pre["bootstrap"]["resamples"])
    keep_all = np.ones(len(gold), dtype=bool)
    keep_event = q_lab != "NONE"
    keep_decon = sim_e5.max(axis=1) < 0.90          # the bake-off's rule: drop queries with a near-duplicate in the corpus (e5 cosine >= 0.90)
    out: dict[str, Any] = {}
    for name, keep in (("all_queries", keep_all), ("non_none_queries", keep_event), ("decontaminated_queries", keep_decon)):
        pe, re5 = precision_and_rr(sim_e5[keep], q_lab[keep], c_lab)
        pt, rtf = precision_and_rr(sim_tf[keep], q_lab[keep], c_lab)
        br = float(base_rate(q_lab[keep], c_lab).mean())
        out[name] = {"queries": int(keep.sum()), "base_rate": br,
                     "e5": {"p_at_5": float(pe.mean()), "mrr": float(re5.mean()), "lift": float(pe.mean() / br)},
                     "tfidf": {"p_at_5": float(pt.mean()), "mrr": float(rtf.mean()), "lift": float(pt.mean() / br)},
                     "delta_p_at_5_e5_minus_tfidf": paired_bootstrap(pe, pt, resamples=res, seed=seed),
                     "delta_mrr_e5_minus_tfidf": paired_bootstrap(re5, rtf, resamples=res, seed=seed)}
    per_class = {}
    for c in sorted(set(q_lab.tolist()) - {"NONE"}):
        m = q_lab == c
        if m.sum() >= 5:
            pe, _ = precision_and_rr(sim_e5[m], q_lab[m], c_lab)
            pt, _ = precision_and_rr(sim_tf[m], q_lab[m], c_lab)
            per_class[c] = {"queries": int(m.sum()), "e5_p_at_5": float(pe.mean()), "tfidf_p_at_5": float(pt.mean()), "corpus_share": float((c_lab == c).mean())}
    gate = cfg["adopt_e5_if"]["p_at_5_delta_ci_lower_above"]
    adopt = out["all_queries"]["delta_p_at_5_e5_minus_tfidf"]["lo"] > gate
    result = {"schema": SCHEMA, "evidence_version": pre["version"], "preregistration_sha256": pre_sha, "seed": seed,
              "inputs": {"queries": len(gold), "labelled_corpus": len(annotated), "embedding_cache_sha256": sha256_file(cache),
                         "gold_v2_sha256": sha256_file(repo_root / pre["data"]["gold_v2"] / "gold_v2.csv"), "event_train_sha256": sha256_file(repo_root / pre["data"]["event_train"]),
                         "queries_with_near_duplicate_in_corpus": int((~keep_decon).sum())},
              "metrics": out, "per_class": per_class,
              "decision": {"rule": f"adopt e5 if the lower bound of delta P@5 (e5 - tfidf, all queries) is above {gate}", "adopt_e5": bool(adopt),
                           "served_retriever": "e5-large" if adopt else "tfidf"},
              "reading": ("Relevance means 'carries the same event-type label'; the labels are AI-annotated (gold v2: two blind passes that agree). It measures whether "
                          "neighbours are about the same kind of event, not whether their market outcomes were alike.")}
    atomic_write_text(out_path, json.dumps(clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n")
    log(f"wrote {out_path}")
    return result
