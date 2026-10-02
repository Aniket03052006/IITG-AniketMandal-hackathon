"""Evaluation of the sentiment model: metrics, calibration, baselines and the evaluation sets.

Nothing here fits the model or chooses its hyper-parameters. Every evaluation set is reported on its own, with its size:
a single blended number would hide the domain gap that the Stage-3 audit found.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..pipeline.config import EnrichmentConfig, SentimentEvalConfig
from ..pipeline.enrich import EnrichmentInput, PlaceholderEnricher
from ..pipeline.sentiment_card import (
    ClassMetrics,
    ConfidentError,
    EvalMetrics,
    EvalSet,
    LabelScores,
    ReliabilityBin,
)
from ..pipeline.sentiment_model import CLASSES, SentimentModel
from .corpora import load_phrasebank
from .gold import SENTIMENT_NAME, effective_labels, read_sheet
from .leakage import spearman
from .text import has_near_duplicate

LABELS = list(CLASSES)
_NAME_BY_GOLD = {v: k for k, v in SENTIMENT_NAME.items()}  # "-1" -> "negative"


# --------------------------------------------------------------------------------------------------- primitives
def _idx(labels: Sequence[str]) -> np.ndarray:
    return np.array([LABELS.index(x) for x in labels], dtype=int)


def confusion(y: np.ndarray, pred: np.ndarray, w: np.ndarray) -> np.ndarray:
    m = np.zeros((len(LABELS), len(LABELS)))
    np.add.at(m, (y, pred), w)
    return m


def prf(conf: np.ndarray) -> tuple[dict[str, ClassMetrics], float, float]:
    """Per-class precision/recall/F1 from a (weighted) confusion matrix; accuracy; macro-F1 over classes that occur."""
    per: dict[str, ClassMetrics] = {}
    f1s = []
    for k, lab in enumerate(LABELS):
        tp, fp, fn = conf[k, k], conf[:, k].sum() - conf[k, k], conf[k, :].sum() - conf[k, k]
        if tp + fp + fn == 0:
            continue
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        f1s.append(f)
        per[lab] = ClassMetrics(precision=round(p, 4), recall=round(r, 4), f1=round(f, 4), support=round(float(conf[k, :].sum()), 2))
    total = conf.sum()
    return per, float(np.trace(conf) / total) if total else 0.0, float(np.mean(f1s)) if f1s else 0.0


def log_loss(probs: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    p = np.clip(probs[np.arange(len(y)), y], 1e-12, 1.0)
    return float(-(w * np.log(p)).sum() / w.sum())


def brier(probs: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    onehot = np.eye(len(LABELS))[y]
    return float((w * ((probs - onehot) ** 2).sum(axis=1)).sum() / w.sum())


def reliability(probs: np.ndarray, y: np.ndarray, w: np.ndarray, bins: int) -> tuple[float, list[ReliabilityBin]]:
    """Expected calibration error of the top-label probability, and the per-bin table behind it."""
    conf, pred = probs.max(axis=1), probs.argmax(axis=1)
    hit = (pred == y).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    which = np.minimum(np.digitize(conf, edges[1:-1]), bins - 1)
    ece, table = 0.0, []
    for b in range(bins):
        m = which == b
        wb = w[m].sum()
        if not m.any() or wb == 0:
            table.append(ReliabilityBin(lo=round(float(edges[b]), 4), hi=round(float(edges[b + 1]), 4), n=0, confidence=0.0, accuracy=0.0))
            continue
        c, a = float((w[m] * conf[m]).sum() / wb), float((w[m] * hit[m]).sum() / wb)
        ece += wb / w.sum() * abs(c - a)
        table.append(ReliabilityBin(lo=round(float(edges[b]), 4), hi=round(float(edges[b + 1]), 4), n=int(m.sum()),
                                    confidence=round(c, 4), accuracy=round(a, 4)))
    return float(ece), table


def product_labels(score: np.ndarray, threshold: float) -> np.ndarray:
    """The label rule the UI applies to the score (web/src/lib/severity.ts: <= -t Negative, >= t Positive, else Neutral)."""
    out = np.full(len(score), LABELS.index("neutral"), dtype=int)
    out[score <= -threshold] = LABELS.index("negative")
    out[score >= threshold] = LABELS.index("positive")
    return out


def _macro_f1_from_labels(y: np.ndarray, pred: np.ndarray, w: np.ndarray) -> float:
    return prf(confusion(y, pred, w))[2]


def bootstrap_macro_f1(y: np.ndarray, pred: np.ndarray, w: np.ndarray, *, resamples: int, seed: int) -> tuple[float, float]:
    rng = np.random.RandomState(seed)
    n = len(y)
    vals = []
    for _ in range(resamples):
        s = rng.randint(0, n, n)
        vals.append(_macro_f1_from_labels(y[s], pred[s], w[s]))
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return round(float(lo), 4), round(float(hi), 4)


# ------------------------------------------------------------------------------------------------- one eval set
@dataclass
class Scored:
    texts: list[str]
    truth: list[str]
    weights: np.ndarray
    probs: np.ndarray  # calibrated, (n, 3)
    dropped_unscorable: int


def score_texts(model: SentimentModel, texts: Sequence[str], truth: Sequence[str], weights: Sequence[float] | None = None) -> Scored:
    keep = [i for i, t in enumerate(texts) if model.unscorable_reason(t) is None]
    kept_texts = [texts[i] for i in keep]
    w = np.array([1.0 if weights is None else weights[i] for i in keep], dtype=float)
    return Scored(kept_texts, [truth[i] for i in keep], w, model.probabilities(kept_texts), len(texts) - len(keep))


def metrics_for(sc: Scored, cfg: SentimentEvalConfig, *, weighted: bool, with_ci: bool) -> EvalMetrics:
    y = _idx(sc.truth)
    pred = sc.probs.argmax(axis=1)
    conf = confusion(y, pred, sc.weights)
    per, acc, macro = prf(conf)
    score = sc.probs[:, LABELS.index("positive")] - sc.probs[:, LABELS.index("negative")]
    pl = product_labels(score, cfg.product_threshold)
    _, pacc, pmacro = prf(confusion(y, pl, sc.weights))
    ece, _ = reliability(sc.probs, y, sc.weights, cfg.ece_bins)
    ordinal = [{"negative": -1.0, "neutral": 0.0, "positive": 1.0}[t] for t in sc.truth]
    rho = spearman(list(score), ordinal)
    by_class = {lab: round(float(np.average(score[y == k], weights=sc.weights[y == k])), 4) for k, lab in enumerate(LABELS) if (y == k).any()}
    return EvalMetrics(
        n=len(y), weighted=weighted, labels=LABELS, accuracy=round(acc, 4), macro_f1=round(macro, 4),
        macro_f1_ci95=bootstrap_macro_f1(y, pred, sc.weights, resamples=cfg.bootstrap_resamples, seed=cfg.bootstrap_seed) if with_ci else None,
        per_class=per, confusion=[[round(float(v), 2) for v in row] for row in conf],
        log_loss=round(log_loss(sc.probs, y, sc.weights), 4), brier=round(brier(sc.probs, y, sc.weights), 4), ece=round(ece, 4),
        spearman_score_vs_label=None if rho != rho else round(rho, 4), mean_score_by_class=by_class,
        product_rule=LabelScores(accuracy=round(pacc, 4), macro_f1=round(pmacro, 4)))


def label_scores(truth: Sequence[str], pred: Sequence[str], weights: Sequence[float] | None = None) -> LabelScores:
    w = np.ones(len(truth)) if weights is None else np.asarray(weights, dtype=float)
    _, acc, macro = prf(confusion(_idx(truth), _idx(pred), w))
    return LabelScores(accuracy=round(acc, 4), macro_f1=round(macro, 4))


class Baselines:
    """The yardsticks the model has to beat, computed the same way on every evaluation set."""

    def __init__(self, train_rows: list[dict[str, Any]], enrichment_cfg: EnrichmentConfig, lexicon_threshold: float) -> None:
        from .probe import _text_model

        labels = [r["label"] for r in train_rows]
        self.majority = max(LABELS, key=labels.count)
        self._lexicon = PlaceholderEnricher(enrichment_cfg)
        self._threshold = lexicon_threshold
        # the Stage-3 audit probe, re-fitted here so the comparison does not depend on a stale probe.json
        self._probe = _text_model(3.0).fit([r["text"] for r in train_rows], labels)

    def lexicon(self, text: str) -> str:
        s = self._lexicon.enrich(EnrichmentInput(text, None, 1)).sentiment.score
        return "positive" if s > self._threshold else "negative" if s < -self._threshold else "neutral"

    def scores(self, texts: Sequence[str], truth: Sequence[str], weights: Sequence[float] | None = None) -> dict[str, LabelScores]:
        return {
            "majority_class": label_scores(truth, [self.majority] * len(truth), weights),
            "placeholder_lexicon": label_scores(truth, [self.lexicon(t) for t in texts], weights),
            "audit_probe_tfidf_logreg": label_scores(truth, list(self._probe.predict(list(texts))), weights)}


def evaluate_set(model: SentimentModel, baselines: Baselines, cfg: SentimentEvalConfig, *, id: str, title: str, role: str,
                 description: str, texts: Sequence[str], truth: Sequence[str], weights: Sequence[float] | None = None,
                 note: str = "") -> tuple[EvalSet, Scored]:
    sc = score_texts(model, texts, truth, weights)
    if sc.dropped_unscorable:
        note = (note + f" {sc.dropped_unscorable} text(s) the model cannot score were left out.").strip()
    es = EvalSet(id=id, title=title, role=role, description=description, status="ok", note=note,
                 model=metrics_for(sc, cfg, weighted=weights is not None, with_ci=True),
                 baselines=baselines.scores(sc.texts, sc.truth, None if weights is None else list(sc.weights)))
    return es, sc


def skipped(id: str, title: str, role: str, description: str, note: str) -> EvalSet:
    return EvalSet(id=id, title=title, role=role, description=description, status="skipped", note=note)


# ----------------------------------------------------------------------------------------- the evaluation sets
def tfn_test_set(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    te = [r for r in rows if r["split"] == "test"]
    return [r["text"] for r in te], [r["label"] for r in te]


def phrasebank_set(raw_dir: Path) -> tuple[list[str], list[str]] | None:
    if not (raw_dir / "kaggle" / "sentiment-analysis-for-financial-news" / "all-data.csv").is_file():
        return None
    ex = load_phrasebank(raw_dir)
    return [e.text for e in ex], [e.label for e in ex]


def gold_sets(gold_dir: Path, train_texts: list[str], near_dup_threshold: float
              ) -> dict[str, tuple[list[str], list[str], list[float]]] | None:
    """Gold sentiment by population, with inclusion weights. TFN-population rows that are (near-)duplicates of training
    texts are removed first: the gold TFN sample was drawn from the topic corpus, which overlaps the sentiment corpus."""
    sheet_p, man_p, adj_p = gold_dir / "gold_sample.csv", gold_dir / "gold_manifest.json", gold_dir / "adjudication.csv"
    if not (sheet_p.is_file() and man_p.is_file()):
        return None
    import json

    sheet = read_sheet(sheet_p)
    lab = effective_labels(sheet, read_sheet(adj_p) if adj_p.is_file() else [])
    items = json.loads(man_p.read_text(encoding="utf-8"))["items"]
    text = {r["gold_id"]: r["text"] for r in sheet}
    out: dict[str, tuple[list[str], list[str], list[float]]] = {}
    for pop in ("history", "tfn"):
        ids = sorted(g for g in lab if items[g]["population"] == pop and lab[g]["sentiment"] in _NAME_BY_GOLD)
        if pop == "tfn":
            dup = has_near_duplicate([text[g] for g in ids], train_texts, near_dup_threshold)
            out["tfn_dropped"] = ([], [], [float(sum(dup))])
            ids = [g for g, d in zip(ids, dup, strict=True) if not d]
        out[pop] = ([text[g] for g in ids], [_NAME_BY_GOLD[lab[g]["sentiment"]] for g in ids], [float(items[g]["weight"]) for g in ids])
    return out


def confident_errors(scored: Scored, eval_set: str, k: int, *, text_limit: int = 160) -> list[ConfidentError]:
    """The model's most confident mistakes, which is where its failure modes show."""
    y, pred = _idx(scored.truth), scored.probs.argmax(axis=1)
    bad = [i for i in range(len(y)) if y[i] != pred[i]]
    bad.sort(key=lambda i: (-scored.probs[i].max(), scored.texts[i]))
    pos, neg = LABELS.index("positive"), LABELS.index("negative")
    return [ConfidentError(eval_set=eval_set, text=scored.texts[i][:text_limit], truth=scored.truth[i], predicted=LABELS[pred[i]],
                           confidence=round(float(scored.probs[i].max()), 4), score=round(float(scored.probs[i][pos] - scored.probs[i][neg]), 4))
            for i in bad[:k]]


__all__ = ["LABELS", "Baselines", "Scored", "confident_errors", "evaluate_set", "gold_sets", "metrics_for", "phrasebank_set",
           "reliability", "skipped", "tfn_test_set"]
