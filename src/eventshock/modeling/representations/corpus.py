"""The labelled texts the representation study uses, assembled once, with their roles fixed.

Roles (never mixed): ``train`` fits a candidate; ``dev`` chooses its hyper-parameters, temperature and unreliable classes (the production
selection rule); every other set is evaluation only and is scored after every choice. Gold v1 and the replay check are the sets the shipped
model was judged on, so candidates are compared with it on exactly those rows; gold v2 (2023-2025 documents) adds a set the shipped model
has never seen and that is later in time than anything it was trained on.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..corpora import read_jsonl
from ..event_eval import LABELS, gold_event_sets

GOLD_V2_FILE = "gold_v2.csv"


@dataclass
class LabelledSet:
    name: str
    texts: list[str]
    y: np.ndarray            # indices into LABELS
    w: np.ndarray            # inclusion weights (sum normalised to n for pooled use)
    note: str = ""
    groups: list[str] = field(default_factory=list)  # bootstrap clusters (default: each row its own)

    @property
    def n(self) -> int:
        return len(self.texts)


def _set(name: str, texts: list[str], labels: list[str], w: list[float] | None = None, note: str = "") -> LabelledSet:
    y = np.array([LABELS.index(x) for x in labels], dtype=int)
    wt = np.ones(len(texts)) if w is None else np.array(w, dtype=float)
    wt = wt * (len(wt) / wt.sum()) if len(wt) else wt  # normalised so pooling weights each set by its row count, not its inclusion scale
    return LabelledSet(name, list(texts), y, wt, note)


def load_gold_v2(gold_v2_dir: Path, *, agreed_only: bool = True, pass_name: str = "agreed") -> LabelledSet | None:
    """Gold v2 rows: ``agreed`` keeps rows where both independent annotator passes gave the same event class; ``a`` / ``b`` use one pass."""
    p = gold_v2_dir / GOLD_V2_FILE
    if not p.is_file():
        return None
    with p.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if pass_name == "agreed":
        use = [r for r in rows if r["label_a"] == r["label_b"] and r["label_a"] in LABELS]
        lab = [r["label_a"] for r in use]
    else:
        key = "label_a" if pass_name == "a" else "label_b"
        use = [r for r in rows if r[key] in LABELS]
        lab = [r[key] for r in use]
    return _set(f"gold_v2_{pass_name}", [r["text"] for r in use], lab, note="2023-2025 documents; doubly annotated; "
                + ("agreed rows only" if pass_name == "agreed" else f"pass {pass_name} labels")) if use else None


def load_event_corpus(root: Path) -> dict[str, LabelledSet]:
    """train, dev (history + tfn populations, weighted as in training), replay_check, gold_history, gold_tfn, and gold_v2 if present."""
    rows = [json.loads(x) for x in (root / "data/modeling/event_train.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
    ann = [r for r in rows if r["kind"] == "annotated"]
    out: dict[str, LabelledSet] = {}
    tr = [r for r in ann if r["split"] == "train"]
    out["train"] = _set("train", [r["text"] for r in tr], [r["label"] for r in tr], [r["sample_weight"] for r in tr])
    dev = [r for r in ann if r["split"] == "dev"]
    out["dev"] = _set("dev", [r["text"] for r in dev], [r["label"] for r in dev], [r["pop_weight"] if r["population"] == "history" else 1.0 for r in dev],
                      "selection set: optimistic by construction")
    out["dev"].groups = [str(r["group"]) for r in dev]
    rc = [r for r in ann if r["split"] == "replay_check"]
    out["replay_check"] = _set("replay_check", [r["text"] for r in rc], [r["label"] for r in rc], note="fresh documents of the served 2026 pack")
    g = gold_event_sets(root / "data/gold")
    if g:
        out["gold_history"] = _set("gold_history", g["history"][0], g["history"][1], g["history"][2], "our own sources, population-weighted")
        out["gold_tfn"] = _set("gold_tfn", g["tfn"][0], g["tfn"][1], g["tfn"][2], "TFN-style tweets")
    v2 = load_gold_v2(root / "data/gold_v2")
    if v2:
        out["gold_v2"] = v2
    return out


EVAL_SETS = ("gold_history", "gold_tfn", "replay_check", "gold_v2")
POOLED_PARTS = ("gold_history", "gold_v2", "replay_check")  # the pre-registered pooled held-out statistic


def pooled(corpus: dict[str, LabelledSet], parts: tuple[str, ...] = POOLED_PARTS) -> LabelledSet | None:
    use = [corpus[p] for p in parts if p in corpus]
    if not use:
        return None
    return LabelledSet("pooled", [t for s in use for t in s.texts], np.concatenate([s.y for s in use]), np.concatenate([s.w for s in use]),
                       note="pooled held-out: " + " + ".join(s.name for s in use))


def all_texts(corpus: dict[str, LabelledSet], extra: list[str] | None = None) -> list[str]:
    seen: dict[str, None] = {}
    for s in corpus.values():
        for t in s.texts:
            seen.setdefault(t)
    for t in extra or []:
        seen.setdefault(t)
    return list(seen)


def load_probe(root: Path) -> list[dict]:
    p = root / "data/probes/finance_polarity_pairs.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").split("\n") if x.strip()]


def write_texts(root: Path, out: Path) -> int:
    """Every text any channel must encode, one per line, deterministic order (the input of ``representations.encoders``)."""
    extra = [r["text"] for r in load_probe(root)]
    silver = root / "data/modeling/event_silver.jsonl"
    if silver.is_file():  # the TFN topic test split is scored by the hybrid model's card, so its texts are embedded too
        extra += [r["text"] for r in read_jsonl(silver) if r["split"] == "test" and r["train_eligible"] and not r["gold_reserved"]]
    texts = all_texts(load_event_corpus(root), extra)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps({"text": t}, ensure_ascii=False) + "\n" for t in sorted(texts)), encoding="utf-8")
    return len(texts)
