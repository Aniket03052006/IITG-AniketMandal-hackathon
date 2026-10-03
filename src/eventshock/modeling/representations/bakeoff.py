"""Representation bake-off for the event model: is a richer representation worth carrying, by the rule written beforehand?

Candidates (all trained on the same annotated ``train`` rows, hyper-parameters and temperature chosen on ``dev`` log-loss by the production
rule, the shipped ``tfidf-lr-event-v1`` as the baseline scored on the very same rows):

* ``K``  shipped TF-IDF logistic regression (the baseline);
* ``S``  one logistic regression per frozen dense encoder (e5 small/base/large, bge-base, gte-base);
* ``H1`` early fusion: ``[TF-IDF || alpha * dense]`` in one logistic regression;
* ``H2`` late fusion: a weighted blend of the TF-IDF and dense logits (weight chosen on dev), then one temperature;
* ``H3`` H1 plus a low-dimensional block of lexicon counts and affect probabilities (scaled to a fixed share of the total norm).

The fusion designs are the complete list (no search over architectures). Hybrids use the dense encoder with the best dev log-loss.
Adoption (``configs/evidence_v2.yaml``): the pooled held-out paired interval of the served macro-F1 difference must have lower bound > 0, log-loss
and calibration must not be worse, abstention precision at equal coverage must not be worse, and a double run must be bit-identical.
Nothing here is scored on a held-out set until every choice is made.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ...config import REPO_ROOT
from ...pipeline.config import load_event_model_config
from ...pipeline.event_model import EVENT_CLASSES, EventModel
from ..event_eval import LABELS, NONE_IDX, UNCERTAIN_IDX, K, _served_prf, class_reliability, confusion
from ..sentiment_eval import log_loss, reliability
from ..sentiment_train import fit_temperature, nll, softmax
from .corpus import EVAL_SETS, POOLED_PARTS, LabelledSet, load_event_corpus, load_probe, pooled
from .encoders import SPECS, load_cache, text_key
from .lexicon import Lexicon

COMMIT = 0.5


# ------------------------------------------------------------------------------------------------------------ decisions
def served_labels(probs: np.ndarray, unreliable: frozenset[int], commit: float = COMMIT) -> np.ndarray:
    """The production decision rule (``EventModel.status_for``) on nine-class posteriors -> served label index (UNCERTAIN_IDX = abstain)."""
    out = np.full(len(probs), UNCERTAIN_IDX)
    for i, p in enumerate(probs):
        ev = p[: len(EVENT_CLASSES)]
        top = int(np.argmax(ev))
        if p[NONE_IDX] >= ev[top]:
            if p[NONE_IDX] >= commit:
                out[i] = NONE_IDX
        elif ev[top] >= commit and top not in unreliable:
            out[i] = top
    return out


def served_macro_f1(y: np.ndarray, served: np.ndarray, w: np.ndarray) -> float:
    return _served_prf(confusion(y, served, w, cols=K + 1))[1]


def ece_of(probs: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    return float(reliability(probs, y, w, 10)[0])


def precision_at_coverage(probs: np.ndarray, y: np.ndarray, w: np.ndarray, coverage: float) -> float:
    """Weighted accuracy of the arg-max among the most confident rows that make up ``coverage`` of the total weight."""
    order = np.argsort(-probs.max(axis=1), kind="stable")
    cum = np.cumsum(w[order]) / w.sum()
    take = order[: int(np.searchsorted(cum, coverage) + 1)]
    return float(w[take][probs[take].argmax(axis=1) == y[take]].sum() / w[take].sum())


def committed_coverage(served: np.ndarray, w: np.ndarray) -> float:
    return float(w[served != UNCERTAIN_IDX].sum() / w.sum())


# ------------------------------------------------------------------------------------------------------------ features
class Features:
    """Per-text feature access: TF-IDF from the shipped model's fitted vectoriser, dense and affect from the cache, lexicon on the fly."""

    def __init__(self, prod: EventModel, lex: Lexicon, models: list[str], root: Path) -> None:
        self.prod, self.lex = prod, lex
        self.cache = {m: load_cache(m, root / "data/modeling/embeddings") for m in models}
        self._lex_cache: dict[str, np.ndarray] = {}

    def tfidf(self, texts: list[str]):
        return self.prod._features(texts)  # noqa: SLF001 (the vectoriser is the shipped model's own, fitted on its training rows)

    def tfidf_logits(self, texts: list[str]) -> np.ndarray:
        return self.prod.logits(self.tfidf(texts))

    def dense(self, model: str, texts: list[str]) -> np.ndarray:
        c = self.cache[model]
        missing = [t for t in texts if text_key(t) not in c]
        if missing:
            raise RuntimeError(f"{len(missing)} texts are not embedded by {model}: run `make bakeoff-embed`")
        return np.stack([c[text_key(t)] for t in texts])

    def lexicon(self, texts: list[str]) -> np.ndarray:
        todo = [t for t in texts if t not in self._lex_cache]
        if todo:
            for t, v in zip(todo, self.lex.features(todo), strict=True):
                self._lex_cache[t] = v
        return np.stack([self._lex_cache[t] for t in texts])


# ------------------------------------------------------------------------------------------------------------ candidates
@dataclass
class Candidate:
    name: str
    family: str                 # K | S | H1 | H2 | H3
    params: dict[str, Any]
    temperature: float
    unreliable: frozenset[int]
    dev_log_loss: float
    predict: Any                # texts -> (n, 9) calibrated probabilities in LABELS order


def _lr(C: float, cw: str | None, max_iter: int = 3000):
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(C=C, class_weight=cw, max_iter=max_iter)


def _ordered_logits(m, x) -> np.ndarray:
    order = [list(m.classes_).index(c) for c in range(K)]
    return m.decision_function(x)[:, order]


def _flag_unreliable(probs_dev: np.ndarray, dev: LabelledSet, train: LabelledSet, cfg) -> frozenset[int]:
    """The production rule for classes the model will not assert (too few training rows or low dev F1)."""
    from collections import Counter

    counts = Counter(LABELS[i] for i in train.y)
    rel = class_reliability(probs_dev, dev.y, counts, counts, min_train=cfg.abstention.min_train_examples,
                            min_dev_support=cfg.abstention.min_dev_support, f1_floor=cfg.abstention.dev_f1_floor)
    return frozenset(EVENT_CLASSES.index(r.label) for r in rel if r.status == "unreliable")


def _fit_grid(make_x, train: LabelledSet, dev: LabelledSet, cfg, grid: list[dict[str, Any]], name: str, family: str,
              extra_cols: int = 0) -> tuple[Candidate, np.ndarray]:
    """Fit every setting of a small grid, keep the one with the lowest dev log-loss after temperature scaling (the production rule)."""
    best = None
    for p in grid:
        xtr = make_x(train.texts, p)
        m = _lr(p["C"], p["class_weight"]).fit(xtr, train.y, sample_weight=train.w)
        z = _ordered_logits(m, make_x(dev.texts, p))
        t = fit_temperature(z, dev.y, cfg.temperature_grid)
        ll = nll(softmax(z, t), dev.y)
        if best is None or ll < best[0]:
            best = (ll, p, m, t)
    ll, p, m, t = best  # type: ignore[misc]
    probs_dev = softmax(_ordered_logits(m, make_x(dev.texts, p)), t)
    unrel = _flag_unreliable(probs_dev, dev, train, cfg)
    return Candidate(name, family, {k: v for k, v in p.items()}, t, unrel, float(ll),
                     lambda texts, _m=m, _p=p, _t=t: softmax(_ordered_logits(_m, make_x(texts, _p)), _t)), probs_dev


GRID_C = (3.0, 10.0, 30.0)
GRID_CW = (None, "balanced")
GRID_ALPHA = (0.5, 1.0, 2.0)


def baseline_candidate(prod: EventModel, dev: LabelledSet) -> Candidate:
    p_dev = prod.probabilities(dev.texts)
    return Candidate("tfidf-lr-event-v1", "K", {"shipped": True}, float(prod._temperature), frozenset(  # noqa: SLF001
        EVENT_CLASSES.index(c) for c in prod.unreliable), float(nll(p_dev, dev.y)), lambda texts: prod.probabilities(texts))


def short(model: str) -> str:
    return model.split("/")[-1].replace("multilingual-", "").replace("-en-v1.5", "")


def build_dense(feats: Features, train: LabelledSet, dev: LabelledSet, cfg, dense_models: list[str], log=print) -> dict[str, Candidate]:
    out: dict[str, Candidate] = {"K": baseline_candidate(feats.prod, dev)}
    log(f"K  shipped tfidf-lr-event-v1  dev log-loss {out['K'].dev_log_loss:.4f}")
    for model in dense_models:
        grid = [{"C": c, "class_weight": cw} for c in GRID_C for cw in GRID_CW]
        cand, _ = _fit_grid(lambda texts, p, _m=model: feats.dense(_m, texts), train, dev, cfg, grid, f"S:{model}", "S")
        cand.params["dense"] = model
        out[f"S:{model}"] = cand
        log(f"S  {model:34s} dev log-loss {cand.dev_log_loss:.4f}  {cand.params}")
    return out


def build_hybrids(feats: Features, train: LabelledSet, dev: LabelledSet, cfg, model: str, s_cand: Candidate, log=print) -> dict[str, Candidate]:
    """H1 early fusion, H2 late fusion and H3 (H1 + lexicon + affect block) on one dense encoder; ids carry the encoder's short name."""
    from scipy.sparse import csr_matrix, hstack

    tag = short(model)
    out: dict[str, Candidate] = {}
    grid1 = [{"C": c, "class_weight": cw, "alpha": a} for c in GRID_C for cw in GRID_CW for a in GRID_ALPHA]

    def x_h1(texts: list[str], p: dict[str, Any]):
        return hstack([feats.tfidf(texts), csr_matrix(p["alpha"] * feats.dense(model, texts))]).tocsr()

    h1, _ = _fit_grid(x_h1, train, dev, cfg, grid1, f"H1[{tag}]", "H1")
    h1.params["dense"] = model
    out[h1.name] = h1
    log(f"H1 early fusion on {tag:14s} dev log-loss {h1.dev_log_loss:.4f}  {h1.params}")

    ms = _lr(s_cand.params["C"], s_cand.params["class_weight"]).fit(feats.dense(model, train.texts), train.y, sample_weight=train.w)
    zk_dev, zs_dev = feats.tfidf_logits(dev.texts), _ordered_logits(ms, feats.dense(model, dev.texts))
    best = None
    for wk in np.round(np.arange(0.0, 1.0001, 0.1), 2):
        z = wk * zk_dev + (1 - wk) * zs_dev
        t = fit_temperature(z, dev.y, cfg.temperature_grid)
        ll = nll(softmax(z, t), dev.y)
        if best is None or ll < best[0]:
            best = (ll, float(wk), t)
    ll, wk, t = best  # type: ignore[misc]

    def p_h2(texts: list[str], _wk=wk, _t=t, _ms=ms) -> np.ndarray:
        return softmax(_wk * feats.tfidf_logits(texts) + (1 - _wk) * _ordered_logits(_ms, feats.dense(model, texts)), _t)

    out[f"H2[{tag}]"] = Candidate(f"H2[{tag}]", "H2", {"weight_tfidf": wk, "dense": model}, t, _flag_unreliable(p_h2(dev.texts), dev, train, cfg), float(ll), p_h2)
    log(f"H2 late fusion on {tag:14s} dev log-loss {ll:.4f}  weight on TF-IDF {wk}")

    affect_models = [m for m in feats.cache if SPECS[m].kind == "affect" and feats.cache[m]]

    def block(texts: list[str]) -> np.ndarray:
        return np.hstack([feats.lexicon(texts)] + [feats.dense(a, texts) for a in affect_models])

    btr = block(train.texts)
    mu, sd = btr.mean(axis=0), btr.std(axis=0) + 1e-6
    grid3 = [{**{k: h1.params[k] for k in ("C", "class_weight", "alpha")}, "beta": b} for b in (0.25, 0.5, 1.0)]  # H1's best settings; only the block weight is tuned

    def x_h3(texts: list[str], p: dict[str, Any]):
        z = (block(texts) - mu) / sd
        return hstack([feats.tfidf(texts), csr_matrix(p["alpha"] * feats.dense(model, texts)),
                       csr_matrix(p["beta"] * z / math.sqrt(z.shape[1]))]).tocsr()

    h3, _ = _fit_grid(x_h3, train, dev, cfg, grid3, f"H3[{tag}]", "H3")
    h3.params["dense"] = model
    h3.params["affect_models"] = affect_models
    out[h3.name] = h3
    log(f"H3 hybrid+lexicon+affect on {tag:8s} dev log-loss {h3.dev_log_loss:.4f}  {h3.params}")
    return out


def pick_hybrid_encoders(dense: dict[str, Candidate], costs: dict[str, float | None], cap: float) -> list[str]:
    """The encoder with the best dev log-loss, and the best one under the cost cap (the same one if it already is)."""
    ranked = sorted((k[2:] for k in dense if k.startswith("S:")), key=lambda m: dense[f"S:{m}"].dev_log_loss)
    chosen = [ranked[0]]
    under = [m for m in ranked if costs.get(m) is not None and costs[m] <= cap]
    if under and under[0] not in chosen:
        chosen.append(under[0])
    return chosen


def build_candidates(feats: Features, train: LabelledSet, dev: LabelledSet, cfg, dense_models: list[str], costs: dict[str, float | None], cap: float,
                     log=print) -> dict[str, Candidate]:
    out = build_dense(feats, train, dev, cfg, dense_models, log)
    for model in pick_hybrid_encoders(out, costs, cap):
        log(f"hybrids on {model}")
        out.update(build_hybrids(feats, train, dev, cfg, model, out[f"S:{model}"], log))
    return out


# ------------------------------------------------------------------------------------------------------------ evaluation
def paired_bootstrap(stat, y: np.ndarray, a: np.ndarray, b: np.ndarray, w: np.ndarray, *, n: int = 1000, seed: int = 11,
                     groups: list[str] | None = None) -> tuple[float, float, float]:
    """(point difference, 2.5%, 97.5%) of ``stat(y, a) - stat(y, b)`` resampling rows with probability proportional to weight.

    ``stat(y, pred, weights)`` is evaluated on each resample with unit weights (the weights already shaped the draw).
    """
    rng = np.random.default_rng(seed)
    pr = w / w.sum()
    ones = np.ones(len(y))
    point = stat(y, a, w) - stat(y, b, w)
    d = np.empty(n)
    for i in range(n):
        idx = rng.choice(len(y), len(y), p=pr)
        d[i] = stat(y[idx], a[idx], ones) - stat(y[idx], b[idx], ones)
    return float(point), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def score_set(cand: Candidate, probs: np.ndarray, s: LabelledSet) -> dict[str, Any]:
    served = served_labels(probs, cand.unreliable)
    decided = served != UNCERTAIN_IDX
    cls = (served < NONE_IDX)
    return {"n": s.n, "served_macro_f1": round(served_macro_f1(s.y, served, s.w), 4), "log_loss": round(log_loss(probs, s.y, s.w), 4),
            "ece": round(ece_of(probs, s.y, s.w), 4), "coverage": round(committed_coverage(served, s.w), 4),
            "accuracy_when_decided": round(float(s.w[decided & (served == s.y)].sum() / s.w[decided].sum()), 4) if s.w[decided].any() else None,
            "classified_precision": round(float(s.w[cls & (served == s.y)].sum() / s.w[cls].sum()), 4) if s.w[cls].any() else None}


def decontaminate(corpus: dict[str, LabelledSet], train: LabelledSet, cache: dict[str, np.ndarray], max_cosine: float) -> tuple[dict[str, LabelledSet], dict[str, Any]]:
    """Evaluation sets without the rows whose nearest TRAINING text is within ``max_cosine`` (a semantic near-duplicate the token check cannot see)."""
    tr = np.stack([cache[text_key(t)] for t in train.texts])
    out: dict[str, LabelledSet] = {}
    audit: dict[str, Any] = {}
    for name in EVAL_SETS:
        s = corpus.get(name)
        if s is None:
            continue
        x = np.stack([cache[text_key(t)] for t in s.texts])
        mx = (x @ tr.T).max(axis=1)
        keep = np.flatnonzero(mx < max_cosine)
        out[name] = LabelledSet(f"{name}_decontaminated", [s.texts[i] for i in keep], s.y[keep], s.w[keep], s.note + f"; rows within cosine {max_cosine} of a training text removed")
        audit[name] = {"rows": s.n, "removed": int(s.n - len(keep)), "removed_share": round(float(1 - len(keep) / s.n), 4),
                       "max_cosine_quantiles": [round(float(v), 3) for v in np.quantile(mx, [0.1, 0.5, 0.9, 0.99])]}
    return out, audit


def evaluate(cands: dict[str, Candidate], corpus: dict[str, LabelledSet], rule: dict[str, Any], n_boot: int, seed: int, log=print,
             decon: dict[str, LabelledSet] | None = None) -> dict[str, Any]:
    sets = {k: corpus[k] for k in EVAL_SETS if k in corpus}
    pool = pooled(corpus)
    if pool is not None:
        sets = {**sets, "pooled": pool}
    pool_d = pooled(decon, tuple(f for f in POOLED_PARTS if f in decon)) if decon else None
    if pool_d is not None:
        sets = {**sets, "pooled_decontaminated": pool_d}
    probs = {name: {sn: c.predict(s.texts) for sn, s in sets.items()} for name, c in cands.items()}
    base = cands["K"]
    results: dict[str, Any] = {}
    for name, c in cands.items():
        per = {sn: score_set(c, probs[name][sn], s) for sn, s in sets.items()}
        entry: dict[str, Any] = {"family": c.family, "params": c.params, "temperature": c.temperature, "dev_log_loss": round(c.dev_log_loss, 4),
                                 "unreliable_classes": sorted(EVENT_CLASSES[i] for i in c.unreliable), "sets": per}
        if name != "K" and pool is not None:
            sb = served_labels(probs["K"]["pooled"], base.unreliable)
            sc = served_labels(probs[name]["pooled"], c.unreliable)
            pt, lo, hi = paired_bootstrap(served_macro_f1, pool.y, sc, sb, pool.w, n=n_boot, seed=seed)
            cov_b = committed_coverage(sb, pool.w)
            prec_c = precision_at_coverage(probs[name]["pooled"], pool.y, pool.w, cov_b)
            prec_b = precision_at_coverage(probs["K"]["pooled"], pool.y, pool.w, cov_b)
            ll_d = per["pooled"]["log_loss"] - results["K"]["sets"]["pooled"]["log_loss"]
            ece_d = per["pooled"]["ece"] - results["K"]["sets"]["pooled"]["ece"]
            checks = {
                "served_macro_f1_delta": {"value": round(pt, 4), "ci95": [round(lo, 4), round(hi, 4)],
                                           "passed": bool(lo > rule["pooled_served_macro_f1_delta_ci_lower_above"])},
                "log_loss_delta": {"value": round(ll_d, 4), "passed": bool(ll_d <= rule["log_loss_not_worse_by_more_than"])},
                "ece_delta": {"value": round(ece_d, 4), "passed": bool(ece_d <= rule["ece_not_worse_by_more_than"])},
                "abstention_precision_at_equal_coverage_delta": {"value": round(prec_c - prec_b, 4), "coverage": round(cov_b, 4),
                                                                  "passed": bool(prec_c - prec_b >= -rule["abstention_precision_not_worse_by_more_than"])}}
            if pool_d is not None:
                sbd = served_labels(probs["K"]["pooled_decontaminated"], base.unreliable)
                scd = served_labels(probs[name]["pooled_decontaminated"], c.unreliable)
                ptd, lod, hid = paired_bootstrap(served_macro_f1, pool_d.y, scd, sbd, pool_d.w, n=n_boot, seed=seed)
                checks["decontaminated_served_macro_f1_delta"] = {"value": round(ptd, 4), "ci95": [round(lod, 4), round(hid, 4)],
                                                                  "passed": bool(lod > rule.get("decontaminated_served_macro_f1_delta_ci_lower_above", 0.0))}
            entry["adoption_checks"] = checks
            entry["adopt_on_evidence"] = all(v["passed"] for v in checks.values())
            # per-set paired deltas, for the robustness table (never part of the rule)
            deltas = {}
            for sn, s in sets.items():
                if sn in ("pooled", "pooled_decontaminated"):
                    continue
                a = served_labels(probs[name][sn], c.unreliable)
                b = served_labels(probs["K"][sn], base.unreliable)
                p, lo_d, hi_d = paired_bootstrap(served_macro_f1, s.y, a, b, s.w, n=n_boot, seed=seed)
                deltas[sn] = {"served_macro_f1_delta": round(p, 4), "ci95": [round(lo_d, 4), round(hi_d, 4)]}
            entry["per_set_delta_vs_baseline"] = deltas
        results[name] = entry
        if "adoption_checks" in entry:
            log(f"{name:40s} pooled Δ served macro-F1 {entry['adoption_checks']['served_macro_f1_delta']['value']:+.3f} "
                f"{entry['adoption_checks']['served_macro_f1_delta']['ci95']}  adopt_on_evidence={entry['adopt_on_evidence']}")
    return results


# ------------------------------------------------------------------------------------------------------------ probe
def polarity_probe(feats: Features, probe: list[dict], sentiment_scores: np.ndarray | None) -> dict[str, Any]:
    """Share of minimal pairs whose good-news sentence scores above its bad-news sentence, per channel (a diagnostic, never a selector)."""
    texts = [r["text"] for r in probe]
    pol = np.array([r["polarity"] for r in probe])
    pair = np.array([r["pair_id"] for r in probe])
    channels: dict[str, np.ndarray] = {}
    if sentiment_scores is not None:
        channels["shipped sentiment model (P(pos)-P(neg))"] = sentiment_scores
    lex = Lexicon.load(REPO_ROOT / "configs/lexicons.yaml")
    f = feats.lexicon(texts)
    channels["lexicon (upside - distress)"] = f[:, lex.names.index("upside")] - f[:, lex.names.index("distress")]
    for name in ("yiyanghkust/finbert-tone", "ProsusAI/finbert"):
        if feats.cache.get(name):
            e = feats.dense(name, texts)
            lab = SPECS[name].labels
            channels[f"{name} (P(pos)-P(neg))"] = e[:, lab.index("positive")] - e[:, lab.index("negative")]
    emo = "j-hartmann/emotion-english-distilroberta-base"
    if feats.cache.get(emo):
        e = feats.dense(emo, texts)
        lab = SPECS[emo].labels
        channels[f"{emo} (joy+surprise - fear-sadness-anger-disgust)"] = (e[:, lab.index("joy")] + e[:, lab.index("surprise")]
                                                                           - e[:, lab.index("fear")] - e[:, lab.index("sadness")]
                                                                           - e[:, lab.index("anger")] - e[:, lab.index("disgust")])
    out = {}
    for name, s in channels.items():
        hits = ties = 0
        ids = sorted(set(pair.tolist()))
        for i in ids:
            sp, sn = s[(pair == i) & (pol == 1)][0], s[(pair == i) & (pol == -1)][0]
            hits += sp > sn
            ties += sp == sn
        n = len(ids)
        lo, hi = _wilson(hits, n)
        out[name] = {"pairs": n, "correct": int(hits), "ties": int(ties), "share_correct": round(hits / n, 3), "ci95": [round(lo, 3), round(hi, 3)]}
    return out


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


# ------------------------------------------------------------------------------------------------------------ orchestration
def determinism_check(cands: dict[str, Candidate], corpus: dict[str, LabelledSet]) -> dict[str, bool]:
    """A second prediction pass over the same texts must be bit-identical (fusion and temperature are pure functions of cached vectors)."""
    s = corpus.get("gold_history") or next(iter(corpus.values()))
    texts = s.texts[:200]
    return {n: bool(np.array_equal(c.predict(texts), c.predict(texts))) for n, c in cands.items()}


def load_costs(root: Path, models: list[str]) -> tuple[dict[str, dict[str, Any]], bool]:
    """Per-model cost records. The controlled benchmark (quiet machine, fixed threads) wins; the cost seen while building the cache is a loaded upper bound."""
    d = root / "data/modeling/embeddings"
    bench = d / "cost_benchmark.json"
    if bench.is_file():
        b = json.loads(bench.read_text())["models"]
        return {m: {**b[m], "controlled": True} for m in models if m in b}, True
    out = {}
    for m in models:
        p = d / f"{m.replace('/', '__')}.cost.json"
        if p.is_file():
            c = json.loads(p.read_text())
            out[m] = {"kind": c["kind"], "ms_per_text_batch32": c["ms_per_text"], "peak_rss_mb": c["peak_rss_mb"], "controlled": False}
    return out, False


def candidate_cost(c: Candidate, costs: dict[str, dict[str, Any]]) -> float | None:
    """ms per text of everything a candidate must run in addition to TF-IDF (its dense encoder, and for H3 its affect models)."""
    if c.family == "K":
        return 0.0
    parts = [c.params.get("dense"), *c.params.get("affect_models", [])]
    ms = [costs.get(m, {}).get("ms_per_text_batch32") for m in parts if m]
    return None if any(v is None for v in ms) else round(float(sum(ms)), 2)


def choose(results: dict[str, Any], costs: dict[str, dict[str, Any]], cands: dict[str, Candidate], margin: float) -> dict[str, Any]:
    """Among candidates that passed every check, the cheapest whose pooled served macro-F1 is within ``margin`` of the best passing one."""
    ok = {n: r for n, r in results.items() if r.get("adopt")}
    if not ok:
        return {"adopted": None, "statement": "no candidate met every pre-registered check; the shipped TF-IDF model stays", "passing": []}
    f1 = {n: r["sets"]["pooled"]["served_macro_f1"] for n, r in ok.items()}
    best = max(f1.values())
    near = [n for n in ok if f1[n] >= best - margin]
    cost = {n: candidate_cost(cands[n], costs) for n in near}
    pick = min(near, key=lambda n: (cost[n] if cost[n] is not None else 1e9, -f1[n]))
    return {"adopted": pick, "passing": sorted(ok, key=lambda n: -f1[n]), "cost_ms_per_text": cost[pick], "pooled_served_macro_f1": f1[pick],
            "best_passing_pooled_served_macro_f1": best,
            "statement": (f"{pick} meets every pre-registered check and is the cheapest candidate within {margin} of the best passing one "
                          f"(pooled served macro-F1 {f1[pick]:.3f} vs best {best:.3f}; extra cost {cost[pick]} ms per text)")}


def run(root: Path = REPO_ROOT, *, dense_models: list[str] | None = None, log=print) -> dict[str, Any]:
    reg = yaml.safe_load((root / "configs/evidence_v2.yaml").read_text(encoding="utf-8"))
    rcfg = reg["representation"]
    cfg = load_event_model_config(root / "configs")
    prod = EventModel.load(root / cfg.model_dir)
    corpus = load_event_corpus(root)
    cache_dir = root / "data/modeling/embeddings"
    dense = dense_models or [m for m in rcfg["dense_models"] if load_cache(m, cache_dir)]
    if not dense:
        raise RuntimeError("no dense embeddings cached: run `make bakeoff-embed` first")
    affect = [m for m in rcfg["affect_models"] if load_cache(m, cache_dir)]
    feats = Features(prod, Lexicon.load(root / "configs/lexicons.yaml"), [*dense, *affect], root)
    # texts the shipped model cannot score are left out of every set, exactly as the pipeline quarantines them
    for name, s in list(corpus.items()):
        keep = [i for i, t in enumerate(s.texts) if prod.unscorable_reason(t) is None]
        if len(keep) != s.n:
            corpus[name] = LabelledSet(s.name, [s.texts[i] for i in keep], s.y[keep], s.w[keep], s.note)
    train, dev = corpus["train"], corpus["dev"]
    costs, controlled = load_costs(root, [*dense, *affect])
    cap = float(rcfg["cost_cap_ms_per_text"])
    ms = {m: costs.get(m, {}).get("ms_per_text_batch32") for m in dense}
    cands = build_candidates(feats, train, dev, cfg, dense, ms, cap, log)
    # ---- every choice is made; only now are the held-out sets scored
    dcfg = rcfg["decontaminate"]
    decon, decon_audit = decontaminate(corpus, train, load_cache(dcfg["model"], cache_dir), float(dcfg["max_cosine"]))
    results = evaluate(cands, corpus, rcfg["adopt_if"], rcfg["bootstrap_resamples"], rcfg["bootstrap_seed"], log, decon)
    det = determinism_check(cands, corpus)
    for n, ok in det.items():
        results[n]["deterministic_double_run"] = ok
        if "adopt_on_evidence" in results[n]:
            ctl = costs.get(results[n]["params"].get("dense", ""), {}).get("deterministic_double_run", True)  # encoder re-encoding check, when benchmarked
            results[n]["encoder_deterministic"] = ctl
            results[n]["adopt"] = bool(results[n]["adopt_on_evidence"] and ok and ctl)
    for n in results:
        results[n]["cost_ms_per_text"] = candidate_cost(cands[n], costs)
    probe = polarity_probe(feats, load_probe(root), _sentiment_scores(root, [r["text"] for r in load_probe(root)]))
    decision = choose(results, costs, cands, float(rcfg["tie_margin_served_macro_f1"]))
    return {
        "preregistration": {"file": "configs/evidence_v2.yaml", "sha256": _sha(root / "configs/evidence_v2.yaml"), "rule": rcfg["adopt_if"],
                            "cost_cap_ms_per_text": cap, "tie_margin": rcfg["tie_margin_served_macro_f1"], "decontaminate": dcfg},
        "baseline": results["K"] | {"id": "tfidf-lr-event-v1", "artifact_sha256": prod.artifact_sha256},
        "sets": {k: {"n": s.n, "note": s.note} for k, s in {**corpus, **{f"{k}_decontaminated": v for k, v in decon.items()}, "pooled": pooled(corpus),
                                                        "pooled_decontaminated": pooled(decon, tuple(f for f in POOLED_PARTS if f in decon))}.items() if s is not None},
        "decontamination": decon_audit, "candidates": {n: r for n, r in results.items() if n != "K"}, "decision": decision,
        "cost": costs, "cost_controlled": controlled, "polarity_probe": probe,
        "texts": {"train": train.n, "dev": dev.n, "pooled": (pooled(corpus).n if pooled(corpus) else 0)},
        "disclosure": "A dry run of this comparison on gold v1 + the replay check (before gold v2 existed) showed a large early-fusion gain; the decontamination check and the "
                      "cost rule were added to configs/evidence_v2.yaml after that, and only make adoption harder or cheaper.",
    }


def _sentiment_scores(root: Path, texts: list[str]) -> np.ndarray | None:
    try:
        from ...pipeline.config import load_sentiment_model_config
        from ...pipeline.sentiment_model import SentimentModel

        d = Path(load_sentiment_model_config(root / "configs").model_dir)
        m = SentimentModel.load(d if d.is_absolute() else root / d)
        return np.array([p.positive - p.negative for p in m.predict_many(texts)])
    except Exception:  # noqa: BLE001 (the probe is a diagnostic: a missing sentiment artifact must not stop the study)
        return None


def _sha(p: Path) -> str:
    import hashlib

    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs/evidence/representation_bakeoff.json")
    args = ap.parse_args(argv)
    res = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(res["decision"]["statement"])
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
