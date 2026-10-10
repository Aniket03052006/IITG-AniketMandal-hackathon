"""Train, calibrate and evaluate the hybrid event model (``hybrid-event-v2``) and write ``models/event/hybrid-event-v2/``.

Not a new search: the representation study (``docs/evidence/representation_bakeoff.json``, rule in ``configs/evidence_v2.yaml``) already chose *which* hybrid and *which* encoder.
This module refits exactly that configuration on the same training rows, re-derives the same hyper-parameters on the same dev rows (and refuses to continue if they differ from the
study's: the shipped model must be the one that was evaluated), then evaluates the **loaded artifact** (what serving uses) on every set the TF-IDF model's card reports, plus gold v2.

    python -m eventshock.modeling.hybrid_train            # needs data/modeling/embeddings (make bakeoff-embed) and the bake-off evidence
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix, hstack

from ..config import REPO_ROOT, ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.config import load_enrichment_config, load_event_model_config
from ..pipeline.embeddings import DictEmbeddings
from ..pipeline.event_card import EventCandidate, EventModelCard
from ..pipeline.event_model import ARTIFACT_FILE, CARD_FILE, CLASSES, EVENT_CLASSES, EventModel
from ..pipeline.hybrid_event_model import KIND, HybridEventModel
from ..pipeline.sentiment_model import text_key
from . import event_train as ET
from .corpora import read_jsonl
from .event_eval import (
    Baselines,
    class_reliability,
    confident_errors,
    evaluate_set,
    gold_event_sets,
    idx,
    operating_point,
    skipped,
)
from .representations.corpus import load_gold_v2
from .representations.encoders import SPECS, load_cache
from .sentiment_eval import reliability
from .sentiment_train import fit_temperature, nll, softmax

MODEL_ID = "hybrid-event-v2"
GRID_C = (3.0, 10.0, 30.0)          # the study's grid, repeated here so the selection can be checked against it
GRID_CW = (None, "balanced")
GRID_ALPHA = (0.5, 1.0, 2.0)


def _lr(c: float, cw: str | None):
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(C=c, class_weight=cw, max_iter=3000)


def study_choice(root: Path) -> dict[str, Any]:
    ev = json.loads((root / "docs/evidence/representation_bakeoff.json").read_text(encoding="utf-8"))
    adopted = ev["decision"]["adopted"]
    if not adopted or not adopted.startswith("H1["):
        raise ConfigError(f"the representation study adopted {adopted!r}; this trainer builds the early-fusion hybrid (H1) only")
    return {"id": adopted, **ev["candidates"][adopted]["params"], "evidence": ev["decision"]["statement"]}


def fit(prod: EventModel, emb: DictEmbeddings, train: list[dict], dev: list[dict], cfg) -> tuple[Any, list[EventCandidate], dict[str, Any], np.ndarray]:
    """Grid over (C, class weight, alpha) ranked on dev log-loss after temperature scaling: the production rule."""
    f = prod._pipe.named_steps["f"]  # noqa: SLF001 (the fitted TF-IDF featurizer of the shipped model)

    def feats(rows: list[dict], alpha: float):
        texts = [r["text"] for r in rows]
        return hstack([f.transform([prepare(t, prod.preprocessing) for t in texts]), csr_matrix(alpha * emb.embed(texts))]).tocsr()

    ytr_names = [r["label"] for r in train]  # the classifier is fitted on class NAMES, like the TF-IDF model: the loader orders its logits by name
    ydev = idx([r["label"] for r in dev])
    wtr = np.array([r["sample_weight"] for r in train], dtype=float)
    results = []
    for c in GRID_C:
        for cw in GRID_CW:
            for a in GRID_ALPHA:
                m = _lr(c, cw).fit(feats(train, a), ytr_names, sample_weight=wtr)
                order = [list(map(str, m.classes_)).index(k) for k in CLASSES]
                z = m.decision_function(feats(dev, a))[:, order]
                t = fit_temperature(z, ydev, cfg.temperature_grid)
                ll = nll(softmax(z, t), ydev)
                from sklearn.metrics import f1_score

                results.append(((round(ll, 4), c, str(cw), a), m, {"C": c, "class_weight": cw, "alpha": a, "temperature": t, "ll": ll,
                                                                   "f1": float(f1_score(ydev, z.argmax(axis=1), average="macro", zero_division=0))}))
    results.sort(key=lambda r: r[0])
    best = results[0]
    cands = [EventCandidate(preprocessing=f"{prod.preprocessing}+{SHORT}x{r[2]['alpha']}", C=r[2]["C"], class_weight=r[2]["class_weight"],
                            temperature=round(r[2]["temperature"], 4), dev_log_loss=round(r[2]["ll"], 4), dev_macro_f1=round(r[2]["f1"], 4),
                            selected=r is best) for r in results]
    return best[1], cands, best[2], f


SHORT = "e5-large"


def prepare(text: str, mode: str) -> str:
    from ..pipeline.sentiment_model import prepare_text

    return prepare_text(text, mode)


LIMITATIONS = [
    "Labels are produced by an AI annotator (Claude) following the project's labelling guide, not by humans; gold v1 and gold v2 are annotated by the same family, so shared bias is "
    "possible and is not measured: a model that imitates the annotator's conventions would look better than it is. Gold v2 has two independent blind passes (agreement and kappa in "
    "data/gold_v2/agreement.json) which bound noise, not shared bias. Human adjudication of the queued rows is still outstanding.",
    "Chosen by a pre-registered rule from a fixed list of designs on pooled held-out sets, but after a dry run on gold v1 and the replay check had shown a large early-fusion gain. "
    "Two guards were added afterwards and only make adoption harder: evaluation rows within cosine 0.90 of a training text (e5-large) are removed, and the gain must hold on what remains; and a "
    "cost rule picks the cheapest candidate within 0.02 of the best. Both are disclosed in configs/evidence_v2.yaml and docs/notes/EVIDENCE_V2.md.",
    "It needs a sentence encoder (intfloat/multilingual-e5-large, 560M parameters, about 105 ms per text on CPU at batch 32, 2.7 GB resident) for any text that is not in the pinned replay "
    "embeddings. The frozen replay pack is covered by hash-pinned float16 vectors so the default run needs no torch; a new document needs `pip install -r requirements-embed.txt`.",
    "Dev rows select the hyper-parameters, fit the temperature and decide which classes are flagged unreliable: scores on dev are optimistic.",
    "No untouched evaluation set remains for this model. Gold v1, gold v2 and the replay check all fed the pooled statistic that adopted it (and gold v1 and the replay check were read by the dry run), "
    "so the acceptance bar below, although met, is not independent evidence. The choice was among five fixed designs with a large effect on every set separately, but an independent check needs new labels: "
    "the human adjudication queue (data/gold_v2/adjudication_v2.csv) and a fresh sample.",
    "Roughly 3,000 annotated rows. Rare classes have few examples: see the per-class reliability table. A class flagged unreliable is never asserted; its documents are shown as UNCERTAIN.",
    "Event type is judged from the headline or tweet alone (no article body, no price data). Multi-event texts get the dominant event only.",
    "Probability calibration was fitted on dev rows; on other sources probabilities can be over-confident (see ECE per evaluation set).",
    "The impact models (impact-v1 and impact-v2) were trained on the TF-IDF event model's probabilities, so the impact stage keeps reading those (train/serve parity); only the user-facing event stage uses this model.",
]


def write_artifact(out_dir: Path, *, f: Any, m: Any, chosen: dict[str, Any], preprocessing: str, train_keys: list[str], unreliable: list[str],
                   commit: float, route: bool) -> Path:
    import joblib

    out_dir.mkdir(parents=True, exist_ok=True)
    for _, vec in f.transformer_list:  # same as the TF-IDF model: drop what makes two identical trainings write different bytes (a memory address)
        if hasattr(vec, "stop_words_"):
            del vec.stop_words_
        if hasattr(vec, "_stop_words_id"):
            vec._stop_words_id = 0
    spec = SPECS[chosen["dense"]]
    path = out_dir / ARTIFACT_FILE
    joblib.dump({"kind": KIND, "tfidf": f, "lr": m, "alpha": chosen["alpha"], "temperature": chosen["temperature"], "classes": list(CLASSES),
                 "preprocessing": preprocessing, "train_keys": train_keys, "commit_threshold": commit, "unreliable": sorted(unreliable),
                 "route_unreliable": route, "encoder": {"name": chosen["dense"], "dim": {"intfloat/multilingual-e5-large": 1024}.get(chosen["dense"], 768), "prefix": spec.prefix,
                                                        "pooling": spec.pooling, "max_tokens": 128, "precision": "float16"}}, path, compress=3)
    return path


def run(root: Path = REPO_ROOT, out_dir: Path | None = None, log=print) -> EventModelCard:
    import numpy
    import scipy
    import sklearn

    cfg = load_event_model_config(root / "configs")
    enrich = load_enrichment_config(root / "configs")
    choice = study_choice(root)
    dim = {"intfloat/multilingual-e5-large": 1024}.get(choice["dense"], 768)
    prod = EventModel.load(root / "models/event/tfidf-lr-event-v1")
    rows = ET.load_training_table(root / cfg.table, gold_origin_ids=ET._gold_origin_ids(root / "data/gold"))  # noqa: SLF001
    cache = load_cache(choice["dense"], root / "data/modeling/embeddings")
    emb = DictEmbeddings(cache, dim)
    out_dir = out_dir or root / "models/event" / MODEL_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    scorable = lambda r: prod.unscorable_reason(r["text"]) is None  # noqa: E731
    train = [r for r in rows if r["split"] == "train" and r["kind"] == "annotated"]
    dev = [r for r in rows if r["split"] == "dev" and scorable(r)]
    m, cands, best, f = fit(prod, emb, train, dev, cfg)
    for k in ("C", "class_weight", "alpha"):
        if best[k] != choice[k]:
            raise ConfigError(f"the refit chose {k}={best[k]!r} but the representation study chose {choice[k]!r}: the shipped model must be the evaluated one")
    log(f"fit: C={best['C']} class_weight={best['class_weight']} alpha={best['alpha']} T={best['temperature']:.2f} dev log-loss {best['ll']:.4f} (matches the study)")
    train_keys = sorted({text_key(r["text"]) for r in rows if r["split"] in ("train", "dev") and r["kind"] == "annotated"})
    ab = cfg.abstention
    train_counts = Counter(r["label"] for r in train)

    def build(unreliable: list[str]) -> Path:
        return write_artifact(out_dir, f=f, m=m, chosen={**choice, **best}, preprocessing=prod.preprocessing, train_keys=train_keys, unreliable=unreliable,
                              commit=ab.commit_threshold, route=ab.route_unreliable_to_uncertain)

    libs = {"scikit-learn": sklearn.__version__, "numpy": numpy.__version__, "scipy": scipy.__version__}
    t = ET.Trained(pipeline=None, temperature=best["temperature"], preprocessing=f"{prod.preprocessing}+{SHORT}x{best['alpha']}", candidates=cands,
                   train_keys=train_keys, used_silver=False)
    ablation = {"dev_log_loss_tfidf_only": round(float(prod_dev_ll(prod, dev)), 4), "dev_log_loss_hybrid": round(best["ll"], 4), "silver_used": 0.0}
    # tuning pass: artifact with no thresholds -> calibrated dev probabilities -> reliability flags
    art = build([])
    sha = hashlib.sha256(art.read_bytes()).hexdigest()
    base_card = ET._card(cfg, t, sha, art, libs, rows, root, ablation, calibration=None, abstention=None, reliability_rows=[], evaluations=[], errors=[],  # noqa: SLF001
                         acceptance=None, train_rows=train)
    atomic_write_text(out_dir / CARD_FILE, _restyle(base_card, choice, sha, art).model_dump_json(indent=1) + "\n")
    tuning = HybridEventModel.load(out_dir, emb)
    dev_probs = tuning.probabilities([r["text"] for r in dev])
    reliab = class_reliability(dev_probs, idx([r["label"] for r in dev]), train_counts, train_counts, min_train=ab.min_train_examples,
                               min_dev_support=ab.min_dev_support, f1_floor=ab.dev_f1_floor)
    unreliable = [c.label for c in reliab if c.status == "unreliable"]
    dev_history = [r for r in dev if r["population"] == "history"]
    hist_texts = [r["text"] for r in dev_history]
    y_hist = idx([r["label"] for r in dev_history])
    w_hist = np.array([r["pop_weight"] for r in dev_history], dtype=float)
    hist_probs = tuning.probabilities(hist_texts)
    ece_before, _ = reliability(softmax(tuning.logits(tuning._features(hist_texts))), y_hist, w_hist, cfg.evaluation.ece_bins)  # noqa: SLF001
    ece_after, rel_table = reliability(hist_probs, y_hist, w_hist, cfg.evaluation.ece_bins)

    art = build(unreliable)
    sha = hashlib.sha256(art.read_bytes()).hexdigest()
    from ..pipeline.event_card import EventAbstention, EventCalibration

    calibration = EventCalibration(method="temperature scaling (one parameter on the nine logits)", temperature=best["temperature"],
                                   fitted_on="dev rows (annotated, held out from training)", ece_dev_population_before=round(ece_before, 4),
                                   ece_dev_population_after=round(ece_after, 4), reliability_dev_population=rel_table)
    atomic_write_text(out_dir / CARD_FILE, _restyle(ET._card(cfg, t, sha, art, libs, rows, root, ablation, calibration=calibration, abstention=None,  # noqa: SLF001
                                                              reliability_rows=reliab, evaluations=[], errors=[], acceptance=None, train_rows=train),
                                                    choice, sha, art).model_dump_json(indent=1) + "\n")
    model = HybridEventModel.load(out_dir, emb)
    op = operating_point(model, hist_texts, [r["label"] for r in dev_history], list(w_hist))
    abstention = EventAbstention(
        commit_threshold=ab.commit_threshold,
        rationale="arg-max of the calibrated 9-class posterior is committed only when its probability is at least this (more likely than not); not tuned. "
                  "Below it the document is UNCERTAIN; a class flagged unreliable is never asserted.",
        dev_population_n=len(dev_history), dev_coverage=op["coverage"], dev_classified_share=op["classified_share"],
        dev_classified_precision=op["classified_precision"], dev_no_event_precision=op["no_event_precision"],
        route_unreliable_to_uncertain=ab.route_unreliable_to_uncertain, unreliable_classes=sorted(unreliable))

    # ---- evaluation of the loaded artifact on every set the TF-IDF card reports, plus gold v2
    silver_train = [r for r in rows if r["split"] == "train" and r["kind"] == "silver"] or [r for r in rows if r["split"] == "train" and r["label"] in EVENT_CLASSES]
    baselines = Baselines(train, silver_train, enrich)
    ev = cfg.evaluation
    evaluations, errors = [], []

    def add(set_id, title, role, description, texts, truth, weights=None, note="", secondary=None, k=0):
        es, d = evaluate_set(model, baselines, ev, id=set_id, title=title, role=role, description=description, texts=texts, truth=truth, weights=weights,
                             note=note, secondary=secondary)
        evaluations.append(es)
        if k:
            errors.extend(confident_errors(d, set_id, k))

    dev_tfn = [r for r in dev if r["population"] == "tfn"]
    add("dev_history", "Held-out dev rows, our own sources (selected on)", "in_domain",
        "Hyper-parameters, calibration and class reliability were decided here, so these numbers are optimistic.", hist_texts,
        [r["label"] for r in dev_history], [r["pop_weight"] for r in dev_history])
    add("dev_tfn_topics", "Held-out dev rows, TFN topic tweets (relabelled)", "in_domain", "News tweets from weakly-mapped TFN topics, labelled by the annotator.",
        [r["text"] for r in dev_tfn], [r["label"] for r in dev_tfn], [r["pop_weight"] for r in dev_tfn])
    g = gold_event_sets(root / "data/gold")
    if g:
        t_, y_, w_, s_ = g["history"]
        add("gold_history", "Gold set, our own sources (AI-annotated)", "indicative",
            "The frozen gold v1 history rows, inclusion-weighted. No training or selection choice used them (the representation dry run read them once; see docs/notes/EVIDENCE_V2.md).",
            t_, y_, w_, secondary=s_, k=ev.confident_errors)
        t_, y_, w_, s_ = g["tfn"]
        add("gold_tfn", "Gold set, TFN-style news tweets (AI-annotated)", "indicative", "The frozen gold v1 TFN-style rows.", t_, y_, w_, secondary=s_)
    g2 = load_gold_v2(root / "data/gold_v2")
    if g2 is not None:
        add("gold_v2", "Gold v2, 2023-2025 news titles (two independent AI passes, agreed rows)", "indicative",
            "Rows from the 2023-2025 GDELT sample on which both blind annotation passes gave the same event class. A period no model was trained on.",
            g2.texts, [LABEL_NAMES[i] for i in g2.y], note="agreed rows only; same-family agreement, not human kappa")
    replay = [r for r in rows if r["split"] == "replay_check"]
    add("replay_check", "Replay-pack check set (fresh documents)", "in_domain", "Documents of the shipped replay pack that no model saw, labelled blind.",
        [r["text"] for r in replay], [r["label"] for r in replay], [r["pop_weight"] for r in replay], k=ev.confident_errors)
    silver = root / "data/modeling/event_silver.jsonl"
    if silver.is_file():
        st = [r for r in read_jsonl(silver) if r["split"] == "test" and r["train_eligible"] and not r["gold_reserved"]]
        try:
            add("tfn_topic_test", "TFN topic test split (crosswalk labels)", "secondary", "The old benchmark with crosswalk labels; shown only to contrast.",
                [r["text"] for r in st], [r["event_class"] for r in st], note="Crosswalk (weak) labels; the model may say NONE or UNCERTAIN, which counts as wrong here.")
        except ConfigError as exc:
            evaluations.append(skipped("tfn_topic_test", "TFN topic test split", "secondary", "Crosswalk labels.", f"not embedded ({exc})"))
    base_acc = ET._acceptance(evaluations)  # noqa: SLF001 (the bar fixed for the TF-IDF model, applied unchanged)
    from ..pipeline.event_card import Acceptance, AcceptanceCheck

    independent = AcceptanceCheck(
        name="an evaluation set that took no part in adopting this model: scored and passed", model=None, baseline=None, passed=False,
        detail="none exists yet: gold v1, gold v2 and the replay check all fed the adoption statistic. Needs human-adjudicated rows "
               "(data/gold_v2/adjudication_v2.csv) or a fresh blind sample, scored once")
    acceptance = Acceptance(rule=base_acc.rule + " PLUS, for this model (added because it was chosen on those very sets): a set that took no part in its adoption must also pass.",
                            met=False, checks=[*base_acc.checks, independent])
    card = _restyle(ET._card(cfg, t, sha, art, libs, rows, root, ablation, calibration=calibration, abstention=abstention, reliability_rows=reliab,  # noqa: SLF001
                             evaluations=evaluations, errors=errors, acceptance=acceptance, train_rows=train), choice, sha, art)
    atomic_write_text(out_dir / CARD_FILE, card.model_dump_json(indent=1) + "\n")
    HybridEventModel.load(out_dir, emb)  # the written pair must load
    return card


LABEL_NAMES = [*EVENT_CLASSES, "NONE"]


def prod_dev_ll(prod: EventModel, dev: list[dict]) -> float:
    return nll(prod.probabilities([r["text"] for r in dev]), idx([r["label"] for r in dev]))


def _restyle(card: EventModelCard, choice: dict[str, Any], sha: str, art: Path) -> EventModelCard:
    """The v1 card builder describes the TF-IDF model; relabel the fields that are about *this* model."""
    return card.model_copy(update={
        "id": MODEL_ID, "version": MODEL_ID, "artifact_sha256": sha, "artifact_bytes": art.stat().st_size,
        "algorithm": (f"[TF-IDF (word 1-2gram + char_wb 2-5gram, sublinear) || {choice['alpha']} x {choice['dense']} sentence embedding (frozen, mean pooled, L2-normalised, float16)] "
                      "-> multinomial logistic regression over 9 classes -> temperature scaling -> one commit threshold (0.5) on the calibrated posterior"),
        "limitations": LIMITATIONS})


def main(argv: list[str] | None = None) -> int:
    card = run()
    sel = next(c for c in card.candidates if c.selected)
    print(f"model {card.id}: C={sel.C}, class_weight={sel.class_weight}, T={sel.temperature}, dev log-loss {sel.dev_log_loss}; artifact {card.artifact_bytes / 1e6:.2f} MB sha256 {card.artifact_sha256[:12]}")
    print(f"unreliable: {card.abstention.unreliable_classes}")
    for e in card.evaluations:
        if e.model is None:
            print(f"  {e.id:16s} skipped: {e.note}")
            continue
        m, s = e.model, e.model.served
        base = " ".join(f"{k.split('_')[0]} {v.macro_f1:.3f}" for k, v in e.baselines.items())
        print(f"  {e.id:16s} n={m.n:4d} served macro-F1 {s.macro_f1:.3f} [{m.served_f1_ci95[0]:.3f}, {m.served_f1_ci95[1]:.3f}]  detect-F1 {s.detection.f1:.3f}  coverage {s.coverage:.2f} | baselines: {base}")
    print(f"acceptance (the TF-IDF model's pre-registered bar, unchanged): {'MET' if card.acceptance.met else 'NOT MET'}")
    for c in card.acceptance.checks:
        print(f"  [{'x' if c.passed else ' '}] {c.name}: {c.detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
