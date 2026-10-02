"""Train, select, calibrate, tune the abstention thresholds of, and evaluate the event model; write the artifact and its model card.

``python -m eventshock.modeling train-event`` (``make train-event``). Deterministic: a fixed table, config and library versions give
identical predictions and an identical card.

What may reach the model, and what may not (each rule has a test):
* training rows come from ``data/modeling/event_train.jsonl``: the annotator's labels on our own sources and TFN topic tweets, plus
  capped TFN crosswalk silver. Nothing from the placeholder enricher, the gold set or the replay check set is a label or a feature;
* candidates are fitted on ``train`` and ranked on ``dev`` (log-loss after a one-parameter temperature). The two decision
  calibration (one temperature) is fitted on dev and the classes that are not reliable enough to assert are decided from it. The commit
  threshold is a fixed 0.5, not tuned. The model is not refitted on dev afterwards;
* the gold set, the replay check set and the TFN topic test split take no part in any choice: they are scored once, at the end.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.config import EnrichmentConfig, EventModelConfig
from ..pipeline.event_card import (
    Acceptance,
    AcceptanceCheck,
    ClassReliability,
    ConsistencyInfo,
    EventAbstention,
    EventCalibration,
    EventCandidate,
    EventConfidentError,
    EventEvalSet,
    EventModelCard,
    EventTrainingInfo,
)
from ..pipeline.event_model import ARTIFACT_FILE, CARD_FILE, CLASSES, EVENT_CLASSES, EventModel
from ..pipeline.sentiment_model import prepare_text, text_key
from .corpora import read_jsonl
from .event_eval import (
    LABELS,
    Baselines,
    class_reliability,
    confident_errors,
    evaluate_set,
    gold_event_sets,
    idx,
    operating_point,
    skipped,
)
from .event_labels import TABLE_COLUMNS
from .leakage import check_features, group_straddle, require_clean
from .sentiment_eval import reliability
from .sentiment_train import _make_serialisable, build_pipeline, fit_temperature, nll, softmax

FORBIDDEN_COLUMN = re.compile(r"^(ai_|human_|placeholder_|gold|nb_)")
SPLITS = ("train", "dev", "replay_check")
ANNOTATOR = "ai:claude"


# ------------------------------------------------------------------------------------------------------- data
def load_training_table(path: Path, *, gold_origin_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Read the event table and refuse anything that could leak an evaluation row or a weak label into training."""
    if not path.is_file():
        raise ConfigError(f"{path} missing: build it with `python -m eventshock.modeling event-table` (see docs/EVENT_MODEL.md)")
    rows = read_jsonl(path)
    if not rows:
        raise ConfigError(f"{path} is empty")
    cols = set().union(*(r.keys() for r in rows))
    bad = sorted(c for c in cols if FORBIDDEN_COLUMN.match(c))
    if bad or not cols <= TABLE_COLUMNS:
        raise ConfigError(f"{path}: unexpected columns {sorted(cols - TABLE_COLUMNS)} (placeholder/AI/gold columns can never be features)")
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ConfigError(f"{path}: duplicate row ids")
    in_gold = sorted((gold_origin_ids or set()) & set(ids))
    if in_gold:
        raise ConfigError(f"{path}: {len(in_gold)} rows are gold-set rows, e.g. {in_gold[0]!r}")
    wrong = sorted({r["label"] for r in rows} - set(LABELS))
    if wrong:
        raise ConfigError(f"{path}: unknown event labels {wrong}")
    unknown_split = sorted({r["split"] for r in rows} - set(SPLITS))
    if unknown_split:
        raise ConfigError(f"{path}: unknown splits {unknown_split}")
    for s in ("train", "dev"):
        if not any(r["split"] == s for r in rows):
            raise ConfigError(f"{path}: no rows in split {s!r}")
    absent = sorted(set(LABELS) - {r["label"] for r in rows if r["split"] == "train"})
    if absent:
        raise ConfigError(f"{path}: no training rows for {absent}: the model cannot learn a class it never sees")
    annotated = [r for r in rows if r["kind"] == "annotated" and r["split"] in ("train", "dev")]
    require_clean(group_straddle(annotated, "group", "split", ("train", "dev")))
    require_clean(check_features(["event_text"]))
    return rows


def _gold_origin_ids(gold_dir: Path) -> set[str]:
    man = gold_dir / "gold_manifest.json"
    if not man.is_file():
        return set()
    return {str(v.get("origin_id")) for v in json.loads(man.read_text(encoding="utf-8"))["items"].values()}


# ------------------------------------------------------------------------------------------------------ model
@dataclass
class Trained:
    pipeline: Any
    temperature: float
    preprocessing: str
    candidates: list[EventCandidate]
    train_keys: list[str]
    used_silver: bool


def train(cfg: EventModelConfig, rows: list[dict[str, Any]], *, use_silver: bool) -> Trained:
    from sklearn.metrics import f1_score

    tr = [r for r in rows if r["split"] == "train" and (use_silver or r["kind"] == "annotated")]
    va = [r for r in rows if r["split"] == "dev"]
    ytr = [r["label"] for r in tr]
    wtr = np.array([r["sample_weight"] for r in tr], dtype=float)
    yva_i = idx([r["label"] for r in va])
    results: list[tuple[tuple[float, float, str], EventCandidate, Any]] = []
    for pre in cfg.grid.preprocessing:
        xtr = [prepare_text(r["text"], pre) for r in tr]
        xva = [prepare_text(r["text"], pre) for r in va]
        for c in cfg.grid.C:
            for cw in cfg.grid.class_weight:
                pipe = build_pipeline(cfg, c, cw).fit(xtr, ytr, m__sample_weight=wtr)  # type: ignore[arg-type]
                if sorted(map(str, pipe.classes_)) != sorted(LABELS):
                    raise ConfigError(f"classifier classes {list(pipe.classes_)} != {LABELS}: the artifact must score all nine")
                order = [list(map(str, pipe.classes_)).index(c) for c in LABELS]
                logits = pipe.decision_function(xva)[:, order]
                temp = fit_temperature(logits, yva_i, cfg.temperature_grid)
                ll = nll(softmax(logits, temp), yva_i)
                f1 = float(f1_score(yva_i, logits.argmax(axis=1), average="macro", zero_division=0))
                cand = EventCandidate(preprocessing=pre, C=c, class_weight=cw, temperature=round(temp, 4),
                                      dev_log_loss=round(ll, 4), dev_macro_f1=round(f1, 4), selected=False)
                results.append(((cand.dev_log_loss, c, f"{pre}/{cw}"), cand, pipe))
    results.sort(key=lambda t: t[0])
    _, best, pipe = results[0]
    cands = [c.model_copy(update={"selected": c is best}) for _, c, _ in results]
    _make_serialisable(pipe)
    keys = sorted({text_key(r["text"]) for r in rows if r["split"] in ("train", "dev") and (use_silver or r["kind"] == "annotated")})
    return Trained(pipe, best.temperature, best.preprocessing, cands, keys, use_silver)


# ------------------------------------------------------------------------------------------------- artifact
def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_artifact(out_dir: Path, t: Trained, *, commit_threshold: float, unreliable: list[str], route_unreliable: bool) -> Path:
    import joblib

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ARTIFACT_FILE
    joblib.dump({"pipeline": t.pipeline, "temperature": t.temperature, "classes": list(CLASSES), "preprocessing": t.preprocessing,
                 "train_keys": t.train_keys, "commit_threshold": commit_threshold,
                 "unreliable": sorted(unreliable), "route_unreliable": route_unreliable}, path, compress=3)
    return path


LIMITATIONS = [
    "Labels are produced by an AI annotator (Claude) following the project's labelling guide, not by humans, and the gold set is "
    "annotated by the same family: shared bias is possible and is not measured. The annotator's self-consistency (training "
    "labels) bounds noise only. A human adjudication of the 60 queued gold rows is still outstanding.",
    "The abstention policy was changed once after a first full evaluation (from two tuned thresholds to one fixed commit threshold). "
    "The first run's numbers are kept in docs/evidence/ and discussed in docs/EVENT_MODEL.md; the gold and replay-check sets are therefore "
    "not perfectly untouched by design choices.",
    "Roughly 3,000 annotated rows. Rare classes (GEOPOLITICAL, CREDIT_FUNDING, ...) have few examples: see the per-class "
    "reliability table. A class flagged unreliable is never asserted; its documents are shown as UNCERTAIN.",
    "NONE (not a market event) is a judgement call (a scheduling notice, a promotion, an opinion without a fact). A different "
    "convention would move the NONE rate and the EARNINGS numbers.",
    "Dev rows select the model, fit its calibration and decide which classes are flagged unreliable. Scores on dev rows are "
    "therefore optimistic: use the gold and replay-check rows, which no choice depended on.",
    "Event type is judged from the headline or tweet alone (no article body, no price data). Multi-event texts get the dominant event "
    "only; there is no second label.",
    "Bag-of-words model: it does not understand negation scope, numbers or entities (it classifies the text, not the company).",
    "The model was fitted on train only and never refitted on dev, so it uses about 75% of the annotated rows.",
    "TFN crosswalk silver rows (if used) carry topic-derived, not event-derived, labels; the ablation in this card shows whether they helped.",
    "Probability calibration was fitted on dev rows; on other sources probabilities can be over-confident (see ECE per evaluation set).",
]


def _consistency(path: Path) -> ConsistencyInfo:
    if not path.is_file():
        return ConsistencyInfo(n=0, agreement=None, kappa=None, note="no consistency pass recorded")
    return ConsistencyInfo.model_validate(json.loads(path.read_text(encoding="utf-8")))


def run(cfg: EventModelConfig, *, repo_root: Path, enrichment_cfg: EnrichmentConfig, out_dir: Path | None = None,
        heldout: bool = True) -> EventModelCard:
    """Train -> tune -> write artifact -> evaluate the *loaded* artifact (what serving uses) -> write the card.

    ``heldout=False`` (``train-event --dev-only``) skips the gold, replay-check and TFN-topic-test sets, so the model can be iterated
    on dev alone; such a card must never be shipped (its acceptance block says so) and goes to ``out_dir`` only.
    """
    table_path = repo_root / cfg.table
    gold_dir = repo_root / "data" / "gold"
    gold_ids = _gold_origin_ids(gold_dir)
    rows = load_training_table(table_path, gold_origin_ids=gold_ids)
    out_dir = out_dir or repo_root / cfg.model_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    card_path = out_dir / CARD_FILE
    ev = cfg.evaluation
    ab = cfg.abstention

    # ---- ablation: do the TFN crosswalk silver rows help the in-domain dev log-loss? Chosen on dev only.
    with_silver = train(cfg, rows, use_silver=cfg.silver.use) if cfg.silver.use else None
    without = train(cfg, rows, use_silver=False)
    best_ll = lambda t: min(c.dev_log_loss for c in t.candidates)  # noqa: E731
    t = with_silver if with_silver and best_ll(with_silver) < best_ll(without) else without
    ablation = {"dev_log_loss_without_silver": best_ll(without), **({"dev_log_loss_with_silver": best_ll(with_silver)} if with_silver else {}),
                "silver_used": 1.0 if t.used_silver else 0.0}

    dev = [r for r in rows if r["split"] == "dev"]
    dev_history = [r for r in dev if r["population"] == "history"]
    train_rows = [r for r in rows if r["split"] == "train" and (t.used_silver or r["kind"] == "annotated")]
    train_counts = Counter(r["label"] for r in train_rows)
    annotated_counts = Counter(r["label"] for r in train_rows if r["kind"] == "annotated")

    import numpy
    import scipy
    import sklearn

    libs = {"scikit-learn": sklearn.__version__, "numpy": numpy.__version__, "scipy": scipy.__version__}

    # ---- first artifact (no thresholds yet) -> calibrated dev probabilities -> reliability + thresholds -> final artifact
    probe_dir = out_dir / ".tuning"
    art = write_artifact(probe_dir, t, commit_threshold=ab.commit_threshold, unreliable=[], route_unreliable=False)
    atomic_write_text(probe_dir / CARD_FILE, _card(cfg, t, _sha256_file(art), art, libs, rows, repo_root, ablation, calibration=None,
                                                   abstention=None, reliability_rows=[], evaluations=[], errors=[], acceptance=None,
                                                   train_rows=train_rows).model_dump_json(indent=1) + "\n")
    tuning_model = EventModel.load(probe_dir)
    # a text with no words (only links, handles, tickers) is quarantined by the pipeline, never scored: it takes no part in tuning
    dev = [r for r in dev if tuning_model.unscorable_reason(r["text"]) is None]
    dev_history = [r for r in dev if r["population"] == "history"]
    dev_probs = tuning_model.probabilities([r["text"] for r in dev])
    reliab = class_reliability(dev_probs, idx([r["label"] for r in dev]), train_counts, annotated_counts, min_train=ab.min_train_examples,
                               min_dev_support=ab.min_dev_support, f1_floor=ab.dev_f1_floor)
    unreliable = [c.label for c in reliab if c.status == "unreliable"]
    hist_texts = [r["text"] for r in dev_history]
    hist_probs = tuning_model.probabilities(hist_texts)
    y_hist = idx([r["label"] for r in dev_history])
    w_hist = np.array([r["pop_weight"] for r in dev_history], dtype=float)
    ece_before, _ = reliability(softmax(tuning_model.logits(tuning_model._features(hist_texts))),  # noqa: SLF001
                                y_hist, w_hist, ev.ece_bins)
    ece_after, rel_table = reliability(hist_probs, y_hist, w_hist, ev.ece_bins)
    import shutil

    shutil.rmtree(probe_dir)

    art_path = write_artifact(out_dir, t, commit_threshold=ab.commit_threshold, unreliable=unreliable,
                              route_unreliable=ab.route_unreliable_to_uncertain)
    sha = _sha256_file(art_path)
    calibration = EventCalibration(method="temperature scaling (one parameter on the nine logits)", temperature=t.temperature,
                                   fitted_on="dev rows (annotated, held out from training)", ece_dev_population_before=round(ece_before, 4),
                                   ece_dev_population_after=round(ece_after, 4), reliability_dev_population=rel_table)
    atomic_write_text(card_path, _card(cfg, t, sha, art_path, libs, rows, repo_root, ablation, calibration=calibration, abstention=None,
                                       reliability_rows=reliab, evaluations=[], errors=[], acceptance=None,
                                       train_rows=train_rows).model_dump_json(indent=1) + "\n")  # the loader needs a card to load
    final_model = EventModel.load(out_dir)
    op = operating_point(final_model, hist_texts, [r["label"] for r in dev_history], list(w_hist))
    abstention = EventAbstention(
        commit_threshold=ab.commit_threshold,
        rationale="arg-max of the calibrated 9-class posterior is committed only when its probability is at least this (more likely than not); "
                  "not tuned. Below it the document is UNCERTAIN; a class flagged unreliable is never asserted.",
        dev_population_n=len(dev_history), dev_coverage=op["coverage"], dev_classified_share=op["classified_share"],
        dev_classified_precision=op["classified_precision"], dev_no_event_precision=op["no_event_precision"],
        route_unreliable_to_uncertain=ab.route_unreliable_to_uncertain, unreliable_classes=sorted(unreliable))
    stub = _card(cfg, t, sha, art_path, libs, rows, repo_root, ablation, calibration=calibration, abstention=abstention,
                 reliability_rows=reliab, evaluations=[], errors=[], acceptance=None, train_rows=train_rows)
    atomic_write_text(card_path, stub.model_dump_json(indent=1) + "\n")
    model = EventModel.load(out_dir)

    # ---- evaluation: dev first (selected on: optimistic), then the sets no choice depended on
    silver_train = [r for r in rows if r["split"] == "train" and r["kind"] == "silver"] or [r for r in rows if r["split"] == "train"
                                                                                           and r["label"] in EVENT_CLASSES]
    baselines = Baselines(train_rows, silver_train, enrichment_cfg)
    evaluations: list[EventEvalSet] = []
    errors: list[EventConfidentError] = []

    def add(set_id: str, title: str, role: str, description: str, texts, truth, weights=None, note: str = "", secondary=None, k: int = 0):
        es, d = evaluate_set(model, baselines, ev, id=set_id, title=title, role=role, description=description, texts=texts, truth=truth,
                             weights=weights, note=note, secondary=secondary)
        evaluations.append(es)
        if k:
            errors.extend(confident_errors(d, set_id, k))
        return es

    add("dev_history", "Held-out dev rows, our own sources (selected on)", "in_domain",
        "A random quarter of the annotator-labelled history rows (tweets, headlines, GDELT titles), inclusion-weighted to the population. "
        "Model selection, calibration and class reliability were decided here, so these numbers are optimistic.",
        [r["text"] for r in dev_history], [r["label"] for r in dev_history], [r["pop_weight"] for r in dev_history])
    dev_tfn = [r for r in dev if r["population"] == "tfn"]
    add("dev_tfn_topics", "Held-out dev rows, TFN topic tweets (relabelled)", "in_domain",
        "News tweets from the weakly-mapped TFN topics, labelled by the annotator (not the crosswalk), weighted within that sample.",
        [r["text"] for r in dev_tfn], [r["label"] for r in dev_tfn], [r["pop_weight"] for r in dev_tfn])

    g = gold_event_sets(gold_dir) if heldout else None
    if not heldout:
        for sid, title in (("gold_history", "Gold set, our own sources"), ("gold_tfn", "Gold set, TFN-style news tweets"),
                           ("replay_check", "Replay-pack check set"), ("tfn_topic_test", "TFN topic test split")):
            evaluations.append(skipped(sid, title, "indicative", "Held-out set.", "dev-only run: held-out sets are not scored while iterating"))
    elif g is None:
        evaluations.append(skipped("gold_history", "Gold set, our own sources", "indicative", "AI-annotated gold sample.", "Gold files not present."))
    else:
        t_, y_, w_, s_ = g["history"]
        add("gold_history", "Gold set, our own sources (AI-annotated)", "indicative",
            "280 tweets, headlines and GDELT titles from the sources EventShock ingests, inclusion-weighted to the population. Frozen before "
            "this model existed; no training or model-selection choice used it. One serving-policy change (two tuned abstention thresholds "
            "replaced by one fixed 0.5 commit threshold) was made after a first full run: see docs/EVENT_MODEL.md. Labels are AI-annotated.", t_, y_, w_, secondary=s_, k=ev.confident_errors)
        t_, y_, w_, s_ = g["tfn"]
        add("gold_tfn", "Gold set, TFN-style news tweets (AI-annotated)", "indicative",
            "120 TFN topic tweets from the gold sample (weighted within the TFN population). Near-duplicates of them were removed from training.",
            t_, y_, w_, secondary=s_)

    replay = [r for r in rows if r["split"] == "replay_check"]
    if not heldout:
        pass
    elif replay:
        add("replay_check", "Replay-pack check set (fresh documents)", "in_domain",
            "Documents of the shipped replay pack (GDELT DOC and GKG titles, TFN tweets) that the model never saw, labelled blind by the "
            "annotator, weighted by source. The closest test of what the product serves.",
            [r["text"] for r in replay], [r["label"] for r in replay], [r["pop_weight"] for r in replay], k=ev.confident_errors)
    else:
        evaluations.append(skipped("replay_check", "Replay-pack check set", "in_domain", "Fresh replay documents.", "No replay_check rows in the table."))

    silver_test = repo_root / "data" / "modeling" / "event_silver.jsonl"
    if not heldout:
        pass
    elif silver_test.is_file():
        st = [r for r in read_jsonl(silver_test) if r["split"] == "test" and r["train_eligible"] and not r["gold_reserved"]]
        add("tfn_topic_test", "TFN topic test split (crosswalk labels)", "secondary",
            "The old benchmark: TFN test tweets with the topic->class crosswalk as label. Reported only to show how different it is from event "
            "classification on our own sources (a tweet about earnings is often a scheduling notice here, NONE there).",
            [r["text"] for r in st], [r["event_class"] for r in st],
            note="Crosswalk (weak) labels; strong and medium tiers only; the model may say NONE or UNCERTAIN, which counts as wrong here.")
    else:
        evaluations.append(skipped("tfn_topic_test", "TFN topic test split", "secondary", "Crosswalk labels.", "data/modeling/event_silver.jsonl absent (run `make audit`)."))

    acceptance = _acceptance(evaluations)
    card = _card(cfg, t, sha, art_path, libs, rows, repo_root, ablation, calibration=calibration, abstention=abstention, reliability_rows=reliab,
                 evaluations=evaluations, errors=errors, acceptance=acceptance, train_rows=train_rows)
    atomic_write_text(card_path, card.model_dump_json(indent=1) + "\n")
    EventModel.load(out_dir)  # the written pair must load
    return card


def _acceptance(evaluations: list[EventEvalSet]) -> Acceptance:
    """The bar, fixed before the gold set was scored: the served 9-class macro-F1 must be above every baseline's point estimate
    with its whole bootstrap interval, on the gold history rows and on the replay check set, and event-vs-NONE F1 must not be worse
    than the best baseline on the gold history rows."""
    by = {e.id: e for e in evaluations if e.model is not None}
    checks: list[AcceptanceCheck] = []
    for sid, label in (("gold_history", "gold history rows"), ("replay_check", "replay check set")):
        e = by.get(sid)
        if e is None or e.model is None or e.model.served_f1_ci95 is None:
            checks.append(AcceptanceCheck(name=f"served macro-F1 on {label}", model=None, baseline=None, detail="set not evaluated", passed=False))
            continue
        base = max(e.baselines.values(), key=lambda b: b.macro_f1)
        lo = e.model.served_f1_ci95[0]
        checks.append(AcceptanceCheck(
            name=f"served macro-F1 on {label}: CI lower bound above the best baseline", model=lo, baseline=base.macro_f1,
            detail=f"model {e.model.served.macro_f1:.3f} [{lo:.3f}, {e.model.served_f1_ci95[1]:.3f}] vs best baseline {base.macro_f1:.3f}",
            passed=lo > base.macro_f1))
    e = by.get("gold_history")
    if e is not None and e.model is not None:
        best = max((b.detection_f1 or 0.0) for b in e.baselines.values())
        checks.append(AcceptanceCheck(name="event-vs-NONE F1 on gold history rows at least the best baseline's", model=e.model.served.detection.f1,
                                      baseline=best, detail=f"model {e.model.served.detection.f1:.3f} vs {best:.3f}",
                                      passed=e.model.served.detection.f1 >= best))
    return Acceptance(rule="Pre-registered: served 9-class macro-F1 CI lower bound above every baseline on gold_history and replay_check, "
                           "and event-vs-NONE F1 on gold_history not below the best baseline. Reported either way.",
                      met=bool(checks) and all(c.passed for c in checks), checks=checks)


def _card(cfg: EventModelConfig, t: Trained, sha: str, art_path: Path, libs: dict[str, str], rows: list[dict[str, Any]], repo_root: Path,
          ablation: dict[str, float], *, calibration, abstention, reliability_rows: list[ClassReliability], evaluations, errors,
          acceptance, train_rows: list[dict[str, Any]]) -> EventModelCard:
    digest = hashlib.sha256(json.dumps(cfg.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:16]
    dist = lambda sel: dict(sorted(Counter(r["label"] for r in sel).items()))  # noqa: E731
    dev = [r for r in rows if r["split"] == "dev"]
    counts = {"train/annotated": sum(r["kind"] == "annotated" for r in train_rows), "train/silver": sum(r["kind"] == "silver" for r in train_rows),
              "dev": len(dev), "replay_check": sum(r["split"] == "replay_check" for r in rows)}
    stub_cal = calibration or EventCalibration(method="temperature scaling (one parameter on the nine logits)", temperature=t.temperature,
                                               fitted_on="dev rows", ece_dev_population_before=0.0, ece_dev_population_after=0.0,
                                               reliability_dev_population=[])
    stub_ab = abstention or EventAbstention(
        commit_threshold=cfg.abstention.commit_threshold, rationale="(not yet evaluated)", dev_population_n=0, dev_coverage=0.0,
        dev_classified_share=0.0, dev_classified_precision=None, dev_no_event_precision=None,
        route_unreliable_to_uncertain=cfg.abstention.route_unreliable_to_uncertain, unreliable_classes=[])
    stub_acc = acceptance or Acceptance(rule="(not yet evaluated)", met=False, checks=[])
    if t.used_silver:
        silver_note = (f"TFN topic crosswalk rows (strong + medium tiers) were used as extra training data, capped at "
                       f"{cfg.silver.max_rows_per_class} per class at weight {cfg.silver.sample_weight}, because they lowered dev log-loss.")
    else:
        w, wo = ablation.get("dev_log_loss_with_silver"), ablation.get("dev_log_loss_without_silver")
        silver_note = ("TFN topic crosswalk rows (strong + medium tiers) were tried as extra training data and NOT used"
                       + (f": dev log-loss {w:.3f} with them vs {wo:.3f} without." if w is not None and wo is not None else "."))
    return EventModelCard(
        id=cfg.version, version=cfg.version,
        algorithm="TF-IDF (word 1-2gram + char_wb 2-5gram, sublinear) -> multinomial logistic regression over 9 classes -> temperature scaling "
                  "-> one commit threshold (0.5) on the calibrated posterior",
        preprocessing=t.preprocessing, classes=list(CLASSES),
        output_definition="Calibrated P(8 event classes + NONE). The arg-max is committed only at probability >= commit_threshold: "
                          "NONE -> NO_EVENT, an event class -> CLASSIFIED (UNCERTAIN if flagged unreliable); below it -> UNCERTAIN.",
        artifact_file=ARTIFACT_FILE, artifact_sha256=sha, artifact_bytes=art_path.stat().st_size, libraries=libs,
        training=EventTrainingInfo(
            labels_file=cfg.labels_file, labels_sha256=_sha256_file(repo_root / cfg.labels_file), table=cfg.table,
            table_sha256=_sha256_file(repo_root / cfg.table), annotator=ANNOTATOR, rows=counts,
            label_distribution_train=dist(train_rows), label_distribution_dev=dist(dev), silver_note=silver_note,
            consistency=_consistency(repo_root / "data" / "event_labels" / "consistency.json"), seed=cfg.seed, config_digest=digest),
        selection_rule=cfg.selection_rule, ablation=ablation, candidates=t.candidates, calibration=stub_cal, abstention=stub_ab,
        class_reliability=reliability_rows, evaluations=evaluations, acceptance=stub_acc, confident_errors=errors, limitations=LIMITATIONS)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI wrapper, exercised by `make train-event`
    import argparse

    from ..config import REPO_ROOT
    from ..pipeline.config import load_enrichment_config, load_event_model_config

    ap = argparse.ArgumentParser(prog="train-event")
    ap.add_argument("--dev-only", metavar="OUT_DIR", help="iterate on dev rows only: skip the held-out sets, write to OUT_DIR (never shipped)")
    args = ap.parse_args(argv)
    cfg = load_event_model_config(REPO_ROOT / "configs")
    card = run(cfg, repo_root=REPO_ROOT, enrichment_cfg=load_enrichment_config(REPO_ROOT / "configs"),
               out_dir=Path(args.dev_only) if args.dev_only else None, heldout=not args.dev_only)
    sel = next(c for c in card.candidates if c.selected)
    print(f"model {card.id}: {sel.preprocessing}, C={sel.C}, class_weight={sel.class_weight}, T={sel.temperature} "
          f"({len(card.candidates)} candidates, dev log-loss {sel.dev_log_loss}, macro-F1 {sel.dev_macro_f1}); ablation {card.ablation}")
    print(f"artifact {card.artifact_file} {card.artifact_bytes / 1e6:.2f} MB sha256 {card.artifact_sha256[:12]}")
    ab = card.abstention
    print(f"abstention: commit at P>={ab.commit_threshold}; dev coverage {ab.dev_coverage}, classified share {ab.dev_classified_share} "
          f"(precision {ab.dev_classified_precision}), NO_EVENT precision {ab.dev_no_event_precision}; unreliable {ab.unreliable_classes}")
    for r in card.class_reliability:
        print(f"  {r.label:32s} {r.status:10s} {r.reason}")
    for e in card.evaluations:
        if e.model is None:
            print(f"  {e.id:16s} skipped: {e.note}")
            continue
        m, s = e.model, e.model.served
        base = " ".join(f"{k.split('_')[0]} {v.macro_f1:.3f}" for k, v in e.baselines.items())
        print(f"  {e.id:16s} n={m.n:5d} argmax macro-F1 {m.macro_f1:.3f}  served macro-F1 {s.macro_f1:.3f} "
              f"[{m.served_f1_ci95[0]:.3f}, {m.served_f1_ci95[1]:.3f}]  detect-F1 {s.detection.f1:.3f}  coverage {s.coverage:.2f}  | baselines: {base}")
    print(f"acceptance: {'MET' if card.acceptance.met else 'NOT MET'}")
    for c in card.acceptance.checks:
        print(f"  [{'x' if c.passed else ' '}] {c.name}: {c.detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
