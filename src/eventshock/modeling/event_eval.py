"""Evaluation of the event model: served-decision metrics, calibration, baselines, threshold tuning and the evaluation sets.

Nothing here fits the classifier or chooses a threshold. The gold set and the replay check set are scored once, after every choice.

A served decision is what the product shows: CLASSIFIED -> its class, NO_EVENT -> NONE, UNCERTAIN -> a label no truth can have
(abstaining is never counted as right). Detection is event vs not-an-event, where UNCERTAIN counts as "an event".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..domain import EventStatus
from ..pipeline.config import EnrichmentConfig, EventEvalConfig
from ..pipeline.enrich import EnrichmentInput, PlaceholderEnricher
from ..pipeline.event_card import (
    BaselineScores,
    ClassReliability,
    EventConfidentError,
    EventDetection,
    EventEvalMetrics,
    EventEvalSet,
    ServedDecision,
)
from ..pipeline.event_model import CLASSES, EVENT_CLASSES, NONE_CLASS, EventModel
from ..pipeline.sentiment_card import ClassMetrics
from .gold import effective_labels, read_sheet
from .sentiment_eval import log_loss, reliability

LABELS = list(CLASSES)
K = len(LABELS)
NONE_IDX = LABELS.index(NONE_CLASS)
UNCERTAIN_IDX = K  # the served-decision "label" no truth can have
STATUS = {EventStatus.CLASSIFIED: 0, EventStatus.NO_EVENT: 1, EventStatus.UNCERTAIN: 2}


def idx(labels: Sequence[str]) -> np.ndarray:
    return np.array([LABELS.index(x) for x in labels], dtype=int)


# --------------------------------------------------------------------------------------------------- primitives
def confusion(y: np.ndarray, pred: np.ndarray, w: np.ndarray, cols: int = K) -> np.ndarray:
    m = np.zeros((K, cols))
    np.add.at(m, (y, pred), w)
    return m


def prf(conf: np.ndarray) -> tuple[dict[str, ClassMetrics], float, float]:
    """Per-class precision/recall/F1 from a (weighted) confusion matrix; accuracy; macro-F1 over classes that occur or are predicted."""
    per: dict[str, ClassMetrics] = {}
    f1s = []
    for k, lab in enumerate(LABELS):
        tp = conf[k, k]
        fp, fn = conf[:, k].sum() - tp, conf[k, :].sum() - tp
        if tp + fp + fn == 0:
            continue
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        f1s.append(f)
        per[lab] = ClassMetrics(precision=round(float(p), 4), recall=round(float(r), 4), f1=round(float(f), 4),
                                support=round(float(conf[k, :].sum()), 2))
    total = conf.sum()
    return per, float(np.trace(conf[:, :K]) / total) if total else 0.0, float(np.mean(f1s)) if f1s else 0.0


def event_macro_f1(conf: np.ndarray) -> float:
    """Macro-F1 over the 8 event classes that occur in the truth (NONE is not a class here, only a place errors can go)."""
    f1s = []
    for k in range(len(EVENT_CLASSES)):
        tp = conf[k, k]
        fp, fn = conf[:, k].sum() - tp, conf[k, :].sum() - tp
        if conf[k, :].sum() == 0:
            continue
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * p * r / (p + r) if p + r else 0.0)
    return float(np.mean(f1s)) if f1s else 0.0


def brier(probs: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    return float((w * ((probs - np.eye(K)[y]) ** 2).sum(axis=1)).sum() / w.sum())


def detection(y: np.ndarray, predicted_event: np.ndarray, w: np.ndarray) -> EventDetection:
    truth_event = y != NONE_IDX
    tp = float(w[truth_event & predicted_event].sum())
    fp = float(w[~truth_event & predicted_event].sum())
    fn = float(w[truth_event & ~predicted_event].sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return EventDetection(precision=round(p, 4), recall=round(r, 4), f1=round(2 * p * r / (p + r) if p + r else 0.0, 4))


# ----------------------------------------------------------------------------------------------- decisions
@dataclass
class Decisions:
    texts: list[str]
    truth: list[str]
    weights: np.ndarray
    probs: np.ndarray  # calibrated (n, 9)
    status: np.ndarray  # STATUS codes
    top: np.ndarray  # arg-max event class index (0..7)
    secondary: list[str]
    dropped_unscorable: int = 0

    @property
    def served(self) -> np.ndarray:
        """Served label index per row: its class, NONE, or UNCERTAIN_IDX."""
        out = self.top.copy()
        out[self.status == STATUS[EventStatus.NO_EVENT]] = NONE_IDX
        out[self.status == STATUS[EventStatus.UNCERTAIN]] = UNCERTAIN_IDX
        return out


def decide(model: EventModel, texts: Sequence[str], truth: Sequence[str], weights: Sequence[float] | None = None,
           secondary: Sequence[str] | None = None) -> Decisions:
    keep = [i for i, t in enumerate(texts) if model.unscorable_reason(t) is None]
    kept = [texts[i] for i in keep]
    probs = model.probabilities(kept)
    status, top = np.zeros(len(kept), dtype=int), np.zeros(len(kept), dtype=int)
    for i, row in enumerate(probs):
        st, tp = model.status_for(row)
        status[i], top[i] = STATUS[st], tp
    return Decisions(kept, [truth[i] for i in keep], np.array([1.0 if weights is None else weights[i] for i in keep], dtype=float),
                     probs, status, top, [(secondary[i] if secondary else "") for i in keep], len(texts) - len(keep))


def served_scores(d: Decisions) -> ServedDecision:
    y, w, served = idx(d.truth), d.weights, d.served
    conf = confusion(y, served, w, cols=K + 1)
    acc, macro = _served_prf(conf)
    decided = served != UNCERTAIN_IDX
    cls = d.status == STATUS[EventStatus.CLASSIFIED]
    acc_dec = float(w[decided & (served == y)].sum() / w[decided].sum()) if w[decided].sum() else 0.0
    prec = float(w[cls & (d.top == y)].sum() / w[cls].sum()) if w[cls].sum() else None
    mix = {s.value: round(float(w[d.status == c].sum() / w.sum()), 4) for s, c in STATUS.items()}
    return ServedDecision(
        macro_f1=round(macro, 4), accuracy=round(acc, 4), coverage=round(float(w[decided].sum() / w.sum()), 4),
        accuracy_when_decided=round(acc_dec, 4), classified_precision=None if prec is None else round(prec, 4), status_mix=mix,
        detection=detection(y, d.status != STATUS[EventStatus.NO_EVENT], w))


def _served_prf(conf: np.ndarray) -> tuple[float, float]:
    """Macro-F1 over true classes of a (9 x 10) served confusion matrix (column 9 = UNCERTAIN, which never matches)."""
    f1s = []
    for k in range(K):
        tp = conf[k, k]
        fp, fn = conf[:, k].sum() - tp, conf[k, :].sum() - tp
        if tp + fp + fn == 0:
            continue
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * p * r / (p + r) if p + r else 0.0)
    total = conf.sum()
    return float(np.trace(conf[:, :K]) / total) if total else 0.0, float(np.mean(f1s)) if f1s else 0.0


def _bootstrap(stat, n: int, resamples: int, seed: int) -> tuple[float, float]:
    rng = np.random.RandomState(seed)
    vals = [stat(rng.randint(0, n, n)) for _ in range(resamples)]
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return round(float(lo), 4), round(float(hi), 4)


def metrics_for(d: Decisions, cfg: EventEvalConfig, *, weighted: bool, with_ci: bool) -> EventEvalMetrics:
    y, w = idx(d.truth), d.weights
    pred = d.probs.argmax(axis=1)
    conf = confusion(y, pred, w)
    per, acc, macro = prf(conf)
    ece, _ = reliability(d.probs, y, w, cfg.ece_bins)
    served = d.served

    def macro_of(s: np.ndarray) -> float:
        return prf(confusion(y[s], pred[s], w[s]))[2]

    def served_of(s: np.ndarray) -> float:
        return _served_prf(confusion(y[s], served[s], w[s], cols=K + 1))[1]

    return EventEvalMetrics(
        n=len(y), weighted=weighted, labels=LABELS, accuracy=round(acc, 4), macro_f1=round(macro, 4),
        macro_f1_ci95=_bootstrap(macro_of, len(y), cfg.bootstrap_resamples, cfg.bootstrap_seed) if with_ci else None,
        event_macro_f1=round(event_macro_f1(conf), 4), per_class=per,
        confusion=[[round(float(v), 2) for v in row] for row in conf],
        log_loss=round(log_loss(d.probs, y, w), 4), brier=round(brier(d.probs, y, w), 4), ece=round(ece, 4),
        served=served_scores(d),
        served_f1_ci95=_bootstrap(served_of, len(y), cfg.bootstrap_resamples, cfg.bootstrap_seed) if with_ci else None)


# ------------------------------------------------------------------------------------------------- baselines
def _baseline_scores(truth: Sequence[str], pred: Sequence[str], w: np.ndarray) -> BaselineScores:
    y, p = idx(truth), np.array([LABELS.index(x) for x in pred], dtype=int)
    _, acc, macro = prf(confusion(y, p, w))
    return BaselineScores(accuracy=round(acc, 4), macro_f1=round(macro, 4), detection_f1=detection(y, p != NONE_IDX, w).f1)


class Baselines:
    """The yardsticks the model has to beat, computed the same way on every evaluation set."""

    def __init__(self, train_rows: list[dict[str, Any]], silver_train: list[dict[str, Any]], enrichment_cfg: EnrichmentConfig) -> None:
        from .probe import _text_model

        labels = [r["label"] for r in train_rows]
        self.majority = max(sorted(set(labels)), key=labels.count)
        self._placeholder = PlaceholderEnricher(enrichment_cfg)
        # the Stage-3 audit probe: TF-IDF + logistic regression on the TFN topic silver only (6 classes, cannot say NONE)
        self._probe = _text_model(3.0).fit([r["text"] for r in silver_train], [r["label"] for r in silver_train])

    def placeholder(self, text: str) -> str:
        return self._placeholder.enrich(EnrichmentInput(text, None, 1)).event.category.value

    def scores(self, texts: Sequence[str], truth: Sequence[str], w: np.ndarray) -> dict[str, BaselineScores]:
        return {
            "majority_class": _baseline_scores(truth, [self.majority] * len(truth), w),
            "placeholder_keywords": _baseline_scores(truth, [self.placeholder(t) for t in texts], w),
            "tfn_topic_probe": _baseline_scores(truth, list(self._probe.predict(list(texts))), w)}


def evaluate_set(model: EventModel, baselines: Baselines, cfg: EventEvalConfig, *, id: str, title: str, role: str, description: str,
                 texts: Sequence[str], truth: Sequence[str], weights: Sequence[float] | None = None, note: str = "",
                 secondary: Sequence[str] | None = None) -> tuple[EventEvalSet, Decisions]:
    d = decide(model, texts, truth, weights, secondary)
    if d.dropped_unscorable:
        note = (note + f" {d.dropped_unscorable} text(s) the model cannot score were left out.").strip()
    es = EventEvalSet(id=id, title=title, role=role, description=description, status="ok", note=note,
                      model=metrics_for(d, cfg, weighted=weights is not None, with_ci=True),
                      baselines=baselines.scores(d.texts, d.truth, d.weights))
    return es, d


def skipped(id: str, title: str, role: str, description: str, note: str) -> EventEvalSet:
    return EventEvalSet(id=id, title=title, role=role, description=description, status="skipped", note=note)


# --------------------------------------------------------------------------------------- thresholds & reliability
def class_reliability(model_probs_dev: np.ndarray, y_dev: np.ndarray, train_counts: Counter[str], annotated_counts: Counter[str],
                      *, min_train: int, min_dev_support: int, f1_floor: float) -> list[ClassReliability]:
    """Per event class: is there enough training data, and (where measurable) does it work on held-out dev rows?"""
    conf = confusion(y_dev, model_probs_dev.argmax(axis=1), np.ones(len(y_dev)))
    out = []
    for k, lab in enumerate(EVENT_CLASSES):
        tp = conf[k, k]
        fp, fn = conf[:, k].sum() - tp, conf[k, :].sum() - tp
        support = int(conf[k, :].sum())
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
        measured = support >= min_dev_support
        if train_counts[lab] < min_train:
            status, reason = "unreliable", f"only {train_counts[lab]} training rows (< {min_train})"
        elif measured and f1 < f1_floor:
            status, reason = "unreliable", f"dev F1 {f1:.2f} on {support} rows is below {f1_floor}"
        elif not measured:
            status, reason = "unmeasured", f"only {support} dev rows (< {min_dev_support}): trained, but not verifiable on held-out data"
        else:
            status, reason = "ok", f"dev F1 {f1:.2f} on {support} rows"
        out.append(ClassReliability(label=lab, train_examples=train_counts[lab], annotated_train=annotated_counts[lab], dev_support=support,
                                    dev_f1=round(float(f1), 4) if measured else None, status=status, reason=reason))
    return out


def operating_point(model: EventModel, texts: Sequence[str], truth: Sequence[str], weights: Sequence[float]) -> dict[str, Any]:
    """What the served rule does on weighted rows: commit rate, and how often a committed class / NO_EVENT is right."""
    d = decide(model, texts, truth, weights)
    y, w = idx(d.truth), d.weights
    cls = d.status == STATUS[EventStatus.CLASSIFIED]
    non = d.status == STATUS[EventStatus.NO_EVENT]
    committed = d.status != STATUS[EventStatus.UNCERTAIN]
    share = lambda m: round(float(w[m].sum() / w.sum()), 4) if w.sum() else 0.0  # noqa: E731
    prec = lambda m, hit: round(float(w[m & hit].sum() / w[m].sum()), 4) if w[m].sum() else None  # noqa: E731
    return {"n": len(y), "coverage": share(committed), "classified_share": share(cls), "classified_precision": prec(cls, d.top == y),
            "no_event_precision": prec(non, y == NONE_IDX)}


# ----------------------------------------------------------------------------------------- the evaluation sets
def gold_event_sets(gold_dir: Path) -> dict[str, tuple[list[str], list[str], list[float], list[str]]] | None:
    """Gold event labels by population, with inclusion weights: (texts, truth, weights, secondary). Human overrides win over AI."""
    import json

    sheet_p, man_p, adj_p = gold_dir / "gold_sample.csv", gold_dir / "gold_manifest.json", gold_dir / "adjudication.csv"
    if not (sheet_p.is_file() and man_p.is_file()):
        return None
    sheet = read_sheet(sheet_p)
    lab = effective_labels(sheet, read_sheet(adj_p) if adj_p.is_file() else [])
    items = json.loads(man_p.read_text(encoding="utf-8"))["items"]
    text = {r["gold_id"]: r["text"] for r in sheet}
    out = {}
    for pop in ("history", "tfn"):
        ids = sorted(g for g in lab if items[g]["population"] == pop and lab[g]["event"] in LABELS)
        out[pop] = ([text[g] for g in ids], [lab[g]["event"] for g in ids], [float(items[g]["weight"]) for g in ids],
                    [lab[g]["secondary"] for g in ids])
    return out


def confident_errors(d: Decisions, eval_set: str, k: int, *, text_limit: int = 160) -> list[EventConfidentError]:
    """The model's most confident wrong *served* decisions (a CLASSIFIED class that is not the truth, or NO_EVENT on an event)."""
    y, served = idx(d.truth), d.served
    bad = [i for i in range(len(y)) if served[i] != y[i] and served[i] != UNCERTAIN_IDX]
    bad.sort(key=lambda i: (-float(d.probs[i].max()), d.texts[i]))
    names = {STATUS[EventStatus.CLASSIFIED]: "CLASSIFIED", STATUS[EventStatus.NO_EVENT]: "NO_EVENT", STATUS[EventStatus.UNCERTAIN]: "UNCERTAIN"}
    out = []
    for i in bad[:k]:
        top = EVENT_CLASSES[d.top[i]]
        label = f"CLASSIFIED:{top}" if names[int(d.status[i])] == "CLASSIFIED" else "NO_EVENT"
        total = float(d.probs[i][: len(EVENT_CLASSES)].sum())
        out.append(EventConfidentError(
            eval_set=eval_set, text=d.texts[i][:text_limit], truth=d.truth[i], served=label, top_class=top,
            p_none=round(float(d.probs[i][NONE_IDX]), 4), confidence=round(float(d.probs[i][d.top[i]]) / total if total else 0.0, 4)))
    return out


__all__ = ["LABELS", "Baselines", "Decisions", "class_reliability", "confident_errors", "decide", "evaluate_set", "gold_event_sets",
           "metrics_for", "operating_point", "skipped"]
