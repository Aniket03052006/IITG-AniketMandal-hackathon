"""Loaders for the modeling corpora, with the hazards found in the Stage-3 audit handled at the door.

* ``TextExample`` corpora (Twitter Financial News sentiment/topic, PhraseBank): exact-deduplicated, conflicting labels
  dropped, near-duplicate *groups* computed so a split can keep a group on one side.
* ``HistoryDoc``: one row per history signal. The placeholder enrichment is exposed only as ``placeholder_*`` fields
  (used to *find* disagreements for the gold set). They are not labels: there is no ``label`` or ``target`` field here,
  and a test keeps it that way.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..pipeline.topics import Tier, TopicMapping
from .text import exact_key, near_duplicate_groups

SENTIMENT_LABELS = {0: "negative", 1: "positive", 2: "neutral"}  # TFN: 0 bearish, 1 bullish, 2 neutral


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Split on b"\\n" only: ``str.splitlines`` would also split on U+2028 inside tweets and corrupt records."""
    rows = []
    for n, raw in enumerate(path.read_bytes().split(b"\n"), start=1):
        if raw.strip():
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: unreadable JSON line ({exc})") from exc
    return rows


@dataclass(frozen=True)
class TextExample:
    id: str
    text: str
    label: str  # sentiment label, or the topic's event class ("UNMAPPED" if the topic maps to none)
    corpus: str
    published_split: str | None = None
    topic: int | None = None
    topic_name: str | None = None
    tier: Tier | None = None
    license_scope: str = "train_eval"  # "eval_only" for non-commercial material


_URL = re.compile(r"https?://\S+")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _URL.sub("", text)).strip()


def load_tfn_sentiment(raw_dir: Path) -> list[TextExample]:
    out = []
    for split in ("train", "valid"):
        path = raw_dir / "tfn" / f"{split}.jsonl"
        for r in read_jsonl(path):
            if r["label"] not in SENTIMENT_LABELS:
                raise ValueError(f"{path}: unexpected sentiment label {r['label']!r}")
            out.append(TextExample(f"tfn-sent-{split}-{r['row']}", _clean(r["text"]), SENTIMENT_LABELS[r["label"]],
                                   "tfn-sentiment", split))
    return out


def load_tfn_topic(raw_dir: Path, mapping: TopicMapping) -> list[TextExample]:
    out = []
    for split in ("train", "valid"):
        path = raw_dir / "tfn" / f"topic_{split}.jsonl"
        for r in read_jsonl(path):
            cat = mapping.category(int(r["label"]))
            out.append(TextExample(f"tfn-topic-{split}-{r['row']}", _clean(r["text"]), cat.value if cat else "UNMAPPED",
                                   "tfn-topic", split, topic=int(r["label"]), topic_name=mapping.topics[int(r["label"])].name,
                                   tier=mapping.tier(int(r["label"]))))
    return out


def load_phrasebank(raw_dir: Path) -> list[TextExample]:
    """Financial PhraseBank derivative (CC BY-NC-SA): evaluation only, never trained on, never committed."""
    path = raw_dir / "kaggle" / "sentiment-analysis-for-financial-news" / "all-data.csv"
    with path.open(newline="", encoding="latin-1") as fh:
        rows = list(csv.reader(fh))
    return [TextExample(f"pb-{i}", _clean(r[1]), r[0].strip().lower(), "phrasebank", None, license_scope="eval_only")
            for i, r in enumerate(rows) if len(r) >= 2 and r[0].strip().lower() in {"negative", "neutral", "positive"}]


@dataclass(frozen=True)
class DedupReport:
    input: int
    exact_duplicates_dropped: int
    conflicting_texts_dropped: int  # texts that appear with more than one label are removed entirely
    kept: int


def dedup_examples(examples: Iterable[TextExample]) -> tuple[list[TextExample], DedupReport]:
    """Exact-duplicate removal (first occurrence wins). A text that carries conflicting labels is dropped, not guessed."""
    items = list(examples)
    by_key: dict[str, list[TextExample]] = defaultdict(list)
    for ex in items:
        by_key[exact_key(ex.text) or f"id:{ex.id}"].append(ex)
    kept, conflicts, dups = [], 0, 0
    for group in by_key.values():
        labels = {(e.label, e.topic) for e in group}
        if len({lab for lab, _ in labels}) > 1:
            conflicts += 1
            continue
        kept.append(group[0])
        dups += len(group) - 1
    kept_ids = {e.id for e in kept}
    ordered = [e for e in items if e.id in kept_ids]
    return ordered, DedupReport(len(items), dups, conflicts, len(ordered))


@dataclass(frozen=True)
class TextPool:
    examples: list[TextExample]
    groups: list[int]  # near-duplicate component id per example (index of its first member)
    dedup: DedupReport

    @property
    def group_sizes(self) -> dict[int, int]:
        out: dict[int, int] = defaultdict(int)
        for g in self.groups:
            out[g] += 1
        return dict(out)


def prepare_text_pool(examples: Iterable[TextExample], near_duplicate_threshold: float) -> TextPool:
    """Exact-dedup, then group near-duplicates/templates. Shared by the splitter and the gold sampler."""
    kept, report = dedup_examples(examples)
    return TextPool(kept, near_duplicate_groups([e.text for e in kept], near_duplicate_threshold), report)


def stratified_group_split(group_labels: dict[int, str], sizes: dict[int, int], fractions: dict[str, float], seed: int,
                           forced_test: set[int] | None = None) -> dict[int, str]:
    """Assign whole groups to train/valid/test, stratified by label, deterministically.

    Per label, groups are ordered by a seeded hash and each goes to the split furthest below its target share of that
    label's examples. ``forced_test`` groups (e.g. rows reserved for the gold set) always go to test.
    """
    forced = forced_test or set()
    out: dict[int, str] = {g: "test" for g in forced if g in group_labels}
    by_label: dict[str, list[int]] = defaultdict(list)
    for g, lab in group_labels.items():
        if g not in out:
            by_label[lab].append(g)
    for lab in sorted(by_label):
        total = sum(sizes[g] for g in by_label[lab]) + sum(sizes[g] for g, v in out.items() if group_labels[g] == lab)
        got = {s: 0.0 for s in fractions}
        got["test"] += sum(sizes[g] for g, v in out.items() if group_labels[g] == lab)
        for g in sorted(by_label[lab], key=lambda x: hashlib.sha256(f"{seed}:{x}".encode()).hexdigest()):
            split = max(fractions, key=lambda s: fractions[s] * total - got[s])
            out[g] = split
            got[split] += sizes[g]
    return out


# --------------------------------------------------------------------------------------------- history signals
@dataclass(frozen=True)
class HistoryDoc:
    id: str
    adapter: str
    source_type: str
    text: str
    published_at: datetime
    origin: str  # TimestampOrigin value
    ticker: str | None
    entity_id: str
    link_confidence: float
    multi_entity: bool
    er_rule: str
    novelty: float  # past-only (pipeline._apply_novelty), the one cluster-level feature that is safe at event time
    dataset_tickers: tuple[str, ...]  # the source dataset's own ticker tag(s): an independent check on entity resolution
    cluster_id: str
    member_count: int
    placeholder_event: str  # placeholder-v0 keyword class, NOT a label
    placeholder_sentiment: float  # placeholder-v0 lexicon score, NOT a label
    gkg_tone: float | None = field(default=None)  # GDELT machine tone (positive - negative), a silver cross-check only


def _tone(md: dict[str, Any]) -> float | None:
    t = md.get("gkg_tone")
    if isinstance(t, str):
        try:
            t = json.loads(t.replace("'", '"'))
        except ValueError:
            return None
    if isinstance(t, dict) and "positive" in t and "negative" in t:
        return float(t["positive"]) - float(t["negative"])
    return None


def iter_history_docs(path: Path) -> Iterator[HistoryDoc]:
    """Stream history signals (JSONL exported by ``python -m eventshock.pipeline --export``)."""
    with path.open("rb") as fh:
        for n, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            try:
                s = json.loads(raw)
                d, md, ent = s["document"], s["document"]["raw_metadata"], s["entity"]
                tags = md.get("x_tickers") or ([md["x_ticker"]] if md.get("x_ticker") else [])
                yield HistoryDoc(
                    id=s["id"], adapter=md["adapter"], source_type=d["source_type"], text=d["headline"],
                    published_at=datetime.fromisoformat(d["published_at"].replace("Z", "+00:00")),
                    origin=s["provenance"]["timestamp_origin"], ticker=ent["ticker"], entity_id=ent["entity_id"],
                    link_confidence=float(ent["link_confidence"]),
                    multi_entity=bool(s["provenance"]["entity_audit"]["multi_entity"]),
                    er_rule=s["provenance"]["entity_audit"]["rule"], novelty=float(s["evidence"]["novelty_score"]),
                    dataset_tickers=tuple(tags), cluster_id=s["provenance"]["dedup"]["cluster_id"],
                    member_count=int(s["provenance"]["dedup"]["member_count"]),
                    placeholder_event=s["event"]["category"], placeholder_sentiment=float(s["sentiment"]["score"]),
                    gkg_tone=_tone(md))
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{n}: not a valid exported signal ({exc!r})") from exc


def label_distribution(examples: Iterable[TextExample]) -> dict[str, int]:
    return dict(sorted(Counter(e.label for e in examples).items()))
