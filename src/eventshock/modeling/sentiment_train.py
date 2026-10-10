"""Train, select, calibrate and evaluate the sentiment model; write the artifact and its model card.

``python -m eventshock.modeling train-sentiment`` (``make train-sentiment``). Deterministic: a fixed table, config and
library versions give identical predictions and an identical card.

What may reach the model, and what may not (each rule has a test):
* training rows are the ``tfn-sent-*`` rows of the audit's sentiment table, split by near-duplicate group; the label is the
  human TFN label. Nothing from the placeholder enricher and nothing from the AI-annotated gold set is a label or a feature;
* candidates are fitted on ``train`` and ranked on ``valid``; ``test``, PhraseBank and gold never take part in selection;
* the one calibration parameter (a temperature) is fitted on ``valid``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.config import EnrichmentConfig, SentimentModelConfig
from ..pipeline.sentiment_card import (
    CalibrationInfo,
    Candidate,
    SentimentModelCard,
    TrainingInfo,
)
from ..pipeline.sentiment_model import (
    ARTIFACT_FILE,
    CARD_FILE,
    CLASSES,
    SentimentModel,
    prepare_text,
    text_key,
)
from .corpora import read_jsonl
from .leakage import check_features, group_straddle, require_clean
from .sentiment_eval import (
    LABELS,
    Baselines,
    confident_errors,
    evaluate_set,
    gold_sets,
    phrasebank_set,
    reliability,
    skipped,
    tfn_test_set,
)

ALLOWED_COLUMNS = {"id", "text", "label", "split", "group", "published_split"}
FORBIDDEN_COLUMN = re.compile(r"^(ai_|human_|placeholder_|gold|nb_)")
SPLITS = ("train", "valid", "test")


# ------------------------------------------------------------------------------------------------------- data
def load_training_table(path: Path, *, gold_origin_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Read the audit's sentiment table and refuse anything that is not human-labelled, leak-free TFN sentiment."""
    if not path.is_file():
        raise ConfigError(f"{path} missing: it is built by `make audit` (and committed); see docs/notes/SENTIMENT_MODEL.md")
    rows = read_jsonl(path)
    if not rows:
        raise ConfigError(f"{path} is empty")
    cols = set().union(*(r.keys() for r in rows))
    bad_cols = sorted(c for c in cols if FORBIDDEN_COLUMN.match(c))
    if bad_cols or not cols <= ALLOWED_COLUMNS:
        raise ConfigError(f"{path}: unexpected columns {sorted(cols - ALLOWED_COLUMNS)} (placeholder/AI/gold columns can never be labels)")
    not_tfn = [r["id"] for r in rows if not str(r["id"]).startswith("tfn-sent-")]
    if not_tfn:
        raise ConfigError(f"{path}: {len(not_tfn)} rows are not TFN sentiment rows, e.g. {not_tfn[0]!r}")
    in_gold = sorted((gold_origin_ids or set()) & {r["id"] for r in rows})
    if in_gold:
        raise ConfigError(f"{path}: {len(in_gold)} training rows are gold-set rows, e.g. {in_gold[0]!r}")
    wrong = sorted({r["label"] for r in rows} - set(CLASSES))
    if wrong:
        raise ConfigError(f"{path}: unknown sentiment labels {wrong}")
    missing = [s for s in SPLITS if not any(r["split"] == s for r in rows)]
    if missing:
        raise ConfigError(f"{path}: no rows in split(s) {missing}")
    require_clean(group_straddle(rows, "group", "split", SPLITS))
    require_clean(check_features(["sentiment_text"]))
    return rows


def _gold_origin_ids(gold_dir: Path) -> set[str]:
    man = gold_dir / "gold_manifest.json"
    if not man.is_file():
        return set()
    return {str(v.get("origin_id")) for v in json.loads(man.read_text(encoding="utf-8"))["items"].values()}


# ------------------------------------------------------------------------------------------------------ model
def build_pipeline(cfg: SentimentModelConfig, C: float, class_weight: str | None):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    feats = FeatureUnion([
        ("w", TfidfVectorizer(ngram_range=tuple(cfg.word.ngram_range), min_df=cfg.word.min_df, sublinear_tf=True, lowercase=True)),
        ("c", TfidfVectorizer(analyzer="char_wb", ngram_range=tuple(cfg.char.ngram_range), min_df=cfg.char.min_df,
                              sublinear_tf=True, lowercase=True))])
    return Pipeline([("f", feats), ("m", LogisticRegression(C=C, max_iter=cfg.max_iter, class_weight=class_weight))])


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = logits / temperature
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def nll(probs: np.ndarray, y: np.ndarray) -> float:
    return float(-np.mean(np.log(np.clip(probs[np.arange(len(y)), y], 1e-12, 1.0))))


def fit_temperature(logits: np.ndarray, y: np.ndarray, grid: tuple[float, float, float]) -> float:
    """The single temperature that minimises log-loss on (logits, y): a grid scan, so it is exact and deterministic."""
    lo, hi, step = grid
    temps = np.round(np.arange(lo, hi + step / 2, step), 6)
    losses = [nll(softmax(logits, float(t)), y) for t in temps]
    return float(temps[int(np.argmin(losses))])


@dataclass
class Trained:
    pipeline: Any
    temperature: float
    preprocessing: str
    candidates: list[Candidate]
    train_keys: list[str]


def _make_serialisable(pipe: Any) -> None:
    """Drop what must not be pickled: ``stop_words_`` (every pruned term, pure bloat) and ``_stop_words_id`` (a memory
    address that would make two identical trainings produce different bytes; scikit-learn recomputes it on first use)."""
    for _, vec in pipe.named_steps["f"].transformer_list:
        if hasattr(vec, "stop_words_"):
            del vec.stop_words_
        if hasattr(vec, "_stop_words_id"):
            vec._stop_words_id = 0


def train(cfg: SentimentModelConfig, rows: list[dict[str, Any]]) -> Trained:
    from sklearn.metrics import f1_score

    tr, va = ([r for r in rows if r["split"] == s] for s in ("train", "valid"))
    ytr, yva = [r["label"] for r in tr], [r["label"] for r in va]
    yva_i = np.array([LABELS.index(x) for x in yva])
    results: list[tuple[tuple[float, float, str], Candidate, Any]] = []
    for pre in cfg.grid.preprocessing:
        xtr = [prepare_text(r["text"], pre) for r in tr]
        xva = [prepare_text(r["text"], pre) for r in va]
        for c in cfg.grid.C:
            for cw in cfg.grid.class_weight:
                pipe = build_pipeline(cfg, c, cw).fit(xtr, ytr)
                if list(pipe.classes_) != LABELS:
                    raise ConfigError(f"classifier classes {list(pipe.classes_)} != {LABELS}")
                logits = pipe.decision_function(xva)
                temp = fit_temperature(logits, yva_i, cfg.temperature_grid)
                ll = nll(softmax(logits, temp), yva_i)
                f1 = float(f1_score(yva_i, logits.argmax(axis=1), average="macro", zero_division=0))
                cand = Candidate(preprocessing=pre, C=c, class_weight=cw, temperature=round(temp, 4),
                                 valid_log_loss=round(ll, 4), valid_macro_f1=round(f1, 4), selected=False)
                # ties on the rounded log-loss go to the simpler, more regularised candidate (smaller C, then name order)
                # v1 ranks on calibrated log-loss; v2 on valid macro-F1 (negated so that "smaller sorts first" holds for both)
                primary = -cand.valid_macro_f1 if cfg.selection_rule == "valid_macro_f1" else cand.valid_log_loss
                results.append(((primary, cand.valid_log_loss, c, f"{pre}/{cw}"), cand, pipe))
    results.sort(key=lambda t: t[0])
    best_key, best, pipe = results[0]
    cands = [c.model_copy(update={"selected": c is best}) for _, c, _ in results]
    _make_serialisable(pipe)
    keys = sorted({text_key(r["text"]) for r in tr + va})
    return Trained(pipe, best.temperature, best.preprocessing, cands, keys)


# ------------------------------------------------------------------------------------------------- artifact
def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_artifact(out_dir: Path, t: Trained) -> Path:
    import joblib

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ARTIFACT_FILE
    joblib.dump({"pipeline": t.pipeline, "temperature": t.temperature, "classes": list(CLASSES),
                 "preprocessing": t.preprocessing, "train_keys": t.train_keys}, path, compress=3)
    return path


LIMITATIONS = [
    "Trained on Twitter Financial News: English tweets and headlines from financial news accounts, about 65% neutral. "
    "It has not seen retail chatter, long articles or non-English text.",
    "Out of domain it is markedly weaker (see the PhraseBank and gold-set rows): treat scores on our own sources as indicative, not as accuracy figures.",
    "The gold set is annotated by an AI and has not been human-adjudicated; it bounds noise, not shared bias.",
    "Scores describe the tone of the text, not its market effect: a negative headline about a competitor, or a neutral regulatory notice, can matter more than the sign suggests.",
    "Only the exact text is checked against the training data (case, punctuation and links ignored). A rewritten copy of a training text is not flagged as seen.",
    "The model is bag-of-words: it does not model negation scope, sarcasm or numbers (a 3% rise and a 30% rise look alike).",
    "Calibration was fitted on TFN validation data; probabilities on other domains are over-confident (see ECE per evaluation set).",
]


def run(cfg: SentimentModelConfig, *, repo_root: Path, enrichment_cfg: EnrichmentConfig, out_dir: Path | None = None) -> SentimentModelCard:
    """Train -> write artifact -> evaluate the *loaded* artifact (what serving will use) -> write the card."""
    table_path = repo_root / cfg.table
    gold_dir = repo_root / "data" / "gold"
    rows = load_training_table(table_path, gold_origin_ids=_gold_origin_ids(gold_dir))
    out_dir = out_dir or repo_root / cfg.model_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    card_path = out_dir / CARD_FILE

    t = train(cfg, rows)
    art_path = write_artifact(out_dir, t)
    sha = _sha256_file(art_path)
    import numpy
    import scipy
    import sklearn

    libs = {"scikit-learn": sklearn.__version__, "numpy": numpy.__version__, "scipy": scipy.__version__}
    # Evaluation needs a loadable card; write a stub first, evaluate the artifact exactly as serving loads it, then the real card.
    ev = cfg.evaluation
    tr_rows = [r for r in rows if r["split"] == "train"]
    seen_texts = [r["text"] for r in rows if r["split"] in ("train", "valid")]
    baselines = Baselines(tr_rows, enrichment_cfg, ev.lexicon_threshold)

    stub = _card(cfg, t, sha, art_path, libs, rows, table_path, calibration=None, evaluations=[], errors=[])
    atomic_write_text(card_path, stub.model_dump_json(indent=1) + "\n")
    model = SentimentModel.load(out_dir)

    evaluations, errors = [], []
    texts, truth = tfn_test_set(rows)
    es, tfn_scored = evaluate_set(
        model, baselines, ev, id="tfn_test", title="Twitter Financial News, held-out test", role="in_domain",
        description="Same source and style as the training data; near-duplicate groups never straddle the split. The primary in-domain result.",
        texts=texts, truth=truth)
    evaluations.append(es)
    errors += confident_errors(tfn_scored, "tfn_test", ev.confident_errors // 2)

    g = gold_sets(gold_dir, seen_texts, ev.near_duplicate_threshold)
    pb = phrasebank_set(repo_root / "data" / "raw")
    if pb is None:
        evaluations.append(skipped("phrasebank", "Financial PhraseBank (external)", "external",
                                   "Sentences from Finnish-company news, labelled by finance professionals; non-commercial licence, evaluation only.",
                                   "Raw file not present (data/raw is not committed). Re-run `make train-sentiment` with it fetched to fill this row."))
    else:
        es, _ = evaluate_set(model, baselines, ev, id="phrasebank", title="Financial PhraseBank (external)", role="external",
                             description="Sentences from Finnish-company news, labelled by finance professionals; non-commercial licence, evaluation only, never trained on.",
                             texts=pb[0], truth=pb[1])
        evaluations.append(es)
    if g is None:
        evaluations.append(skipped("gold_history", "Gold set, our own sources", "indicative", "Our replay sources, AI-annotated.", "Gold files not present."))
    else:
        h_texts, h_truth, h_w = g["history"]
        es, hs = evaluate_set(
            model, baselines, ev, id="gold_history", title="Gold set, our own sources (AI-annotated)", role="indicative",
            description="280 tweets and headlines from the sources EventShock actually ingests, inclusion-weighted to the population. "
                        "Labels are AI-annotated and not human-adjudicated.", texts=h_texts, truth=h_truth, weights=h_w)
        evaluations.append(es)
        errors += confident_errors(hs, "gold_history", ev.confident_errors - ev.confident_errors // 2)
        d_texts, d_truth, d_w = g["tfn"]
        dropped = int(g["tfn_dropped"][2][0])
        es, _ = evaluate_set(
            model, baselines, ev, id="gold_tfn", title="Gold set, TFN-style text (AI-annotated)", role="indicative",
            description="TFN-style headlines from the gold sample.", texts=d_texts, truth=d_truth, weights=d_w,
            note=f"{dropped} of {dropped + len(d_texts)} rows were removed because the training data holds a near-duplicate.")
        evaluations.append(es)

    # calibration, on the held-out TFN test set: before vs after the temperature
    y = np.array([LABELS.index(x) for x in tfn_scored.truth])
    w = np.ones(len(y))
    raw_logits = model._pipe.decision_function([prepare_text(x, model.preprocessing) for x in tfn_scored.texts])  # noqa: SLF001
    ece_before, _ = reliability(softmax(raw_logits), y, w, ev.ece_bins)
    ece_after, table = reliability(tfn_scored.probs, y, w, ev.ece_bins)
    calibration = CalibrationInfo(method="temperature scaling (one parameter on the logits)", temperature=t.temperature,
                                  fitted_on="TFN valid split", ece_test_before=round(ece_before, 4), ece_test_after=round(ece_after, 4),
                                  reliability_test=table)
    card = _card(cfg, t, sha, art_path, libs, rows, table_path, calibration=calibration, evaluations=evaluations, errors=errors)
    atomic_write_text(card_path, card.model_dump_json(indent=1) + "\n")
    SentimentModel.load(out_dir)  # the written pair must load
    return card


def _card(cfg, t: Trained, sha: str, art_path: Path, libs: dict[str, str], rows, table_path: Path, *, calibration, evaluations, errors) -> SentimentModelCard:
    dist: dict[str, int] = {}
    for r in rows:
        if r["split"] == "train":
            dist[r["label"]] = dist.get(r["label"], 0) + 1
    digest = hashlib.sha256(json.dumps(cfg.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:16]
    stub_cal = calibration or CalibrationInfo(method="temperature scaling (one parameter on the logits)", temperature=t.temperature,
                                               fitted_on="TFN valid split", ece_test_before=0.0, ece_test_after=0.0, reliability_test=[])
    return SentimentModelCard(
        id=cfg.version, version=cfg.version,
        algorithm="TF-IDF (word 1-2gram + char_wb 2-5gram, sublinear) -> multinomial logistic regression -> temperature scaling",
        preprocessing=t.preprocessing, classes=list(CLASSES),
        score_definition="score = P(positive) - P(negative), in [-1, 1]; probabilities are calibrated and rounded to 4 decimals",
        artifact_file=ARTIFACT_FILE, artifact_sha256=sha, artifact_bytes=art_path.stat().st_size, libraries=libs,
        training=TrainingInfo(
            dataset="Twitter Financial News sentiment (zeroshot/twitter-financial-news-sentiment)", licence="MIT",
            table=cfg.table, table_sha256=_sha256_file(table_path),
            rows={s: sum(r["split"] == s for r in rows) for s in SPLITS}, label_distribution=dict(sorted(dist.items())),
            split_note="exact duplicates and conflicting labels removed, near-duplicate groups kept on one side (Jaccard >= 0.7)",
            seed=cfg.seed, config_digest=digest),
        selection_rule=cfg.selection_rule, candidates=t.candidates, calibration=stub_cal, evaluations=evaluations,
        confident_errors=errors, limitations=LIMITATIONS)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI wrapper, exercised by `make train-sentiment`
    import argparse

    from ..config import REPO_ROOT
    from ..pipeline.config import load_enrichment_config, load_sentiment_model_config

    ap = argparse.ArgumentParser(prog="train-sentiment")
    ap.add_argument("--config", default="sentiment_model.yaml", help="file under configs/ (v2: sentiment_model_v2.yaml)")
    args = ap.parse_args(argv)
    cfg = load_sentiment_model_config(REPO_ROOT / "configs", args.config)
    card = run(cfg, repo_root=REPO_ROOT, enrichment_cfg=load_enrichment_config(REPO_ROOT / "configs"))
    sel = next(c for c in card.candidates if c.selected)
    print(f"model {card.id}: {sel.preprocessing}, C={sel.C}, class_weight={sel.class_weight}, T={sel.temperature} "
          f"({len(card.candidates)} candidates, valid log-loss {sel.valid_log_loss}, macro-F1 {sel.valid_macro_f1})")
    print(f"artifact {card.artifact_file} {card.artifact_bytes / 1e6:.2f} MB sha256 {card.artifact_sha256[:12]}")
    for e in card.evaluations:
        if e.model is None:
            print(f"  {e.id:13s} skipped: {e.note}")
            continue
        b = e.baselines
        print(f"  {e.id:13s} n={e.model.n:5d} acc {e.model.accuracy:.3f} macro-F1 {e.model.macro_f1:.3f}"
              + (f" [{e.model.macro_f1_ci95[0]:.3f}, {e.model.macro_f1_ci95[1]:.3f}]" if e.model.macro_f1_ci95 else "")
              + f"  ECE {e.model.ece:.3f}  | lexicon {b['placeholder_lexicon'].macro_f1:.3f}  majority {b['majority_class'].macro_f1:.3f}"
              f"  audit-probe {b['audit_probe_tfidf_logreg'].macro_f1:.3f}")
    c = card.calibration
    print(f"calibration (TFN test): ECE {c.ece_test_before:.3f} -> {c.ece_test_after:.3f} with T={c.temperature}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
