"""``python -m eventshock.modeling event-*``: draw the labelling pools, merge the annotator's answers, build the training table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config import REPO_ROOT, ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.config import load_event_model_config
from ..pipeline.topics import load_topic_mapping
from .config import load_modeling_config
from .corpora import iter_history_docs, load_tfn_sentiment, load_tfn_topic, prepare_text_pool
from .event_labels import (
    LABEL_COLUMNS,
    build_pools,
    build_table,
    check_disjoint,
    gold_exclusions,
    merge_labels,
    read_csv,
    read_table,
    write_batches,
    write_csv,
    write_table,
)

CONFIG_DIR = REPO_ROOT / "configs"
LABEL_DIR = REPO_ROOT / "data" / "event_labels"
BATCH_DIR = LABEL_DIR / "batches"
ANSWER_DIR = LABEL_DIR / "answers"
GOLD_DIR = REPO_ROOT / "data" / "gold"
HISTORY_SIGNALS = REPO_ROOT / "data" / "processed" / "history" / "signals.jsonl"
REPLAY_SIGNALS = REPO_ROOT / "data" / "processed" / "signals.jsonl"
SILVER = REPO_ROOT / "data" / "modeling" / "event_silver.jsonl"


def _manifest(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"{path} not found: run `python -m eventshock.modeling event-pools` first")
    return json.loads(path.read_text(encoding="utf-8"))


def _pools(args: argparse.Namespace) -> int:
    cfg = load_event_model_config(CONFIG_DIR)
    labels_path, manifest_path = REPO_ROOT / cfg.labels_file, REPO_ROOT / cfg.manifest_file
    if labels_path.exists() and not args.force:
        raise ConfigError(f"{labels_path} already exists; the pools are frozen once labelled (use --force to discard the labels)")
    for p in (HISTORY_SIGNALS, REPLAY_SIGNALS):
        if not p.is_file():
            raise ConfigError(f"missing {p}: build the history signals (scripts/build_history_pack.py, then `python -m eventshock.pipeline --replay-dir data/history --export data/processed/history`) and run `make ingest` first")
    raw = REPO_ROOT / "data" / "raw"
    thr = load_modeling_config(CONFIG_DIR).splits.text.near_duplicate_threshold
    gold_ids, gold_texts = gold_exclusions(GOLD_DIR)
    rows, manifest = build_pools(
        cfg, history=iter_history_docs(HISTORY_SIGNALS),
        topic_pool=prepare_text_pool(load_tfn_topic(raw, load_topic_mapping(CONFIG_DIR)), thr),
        sentiment_pool=prepare_text_pool(load_tfn_sentiment(raw), thr),
        replay=list(iter_history_docs(REPLAY_SIGNALS)), gold_ids=gold_ids, gold_texts=gold_texts)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(manifest_path, json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    paths = write_batches(BATCH_DIR, rows, manifest)
    print(f"{len(rows)} rows ({len(manifest['consistency'])} re-labelled for consistency) in {len(paths)} blind batches -> {BATCH_DIR}")
    for name, s in manifest["strata"].items():
        print(f"  {name:26s} {s['role']:12s} population {s['population_size']:7d}  sampled {s['sampled']:4d}")
    return 0


def _merge(args: argparse.Namespace) -> int:
    cfg = load_event_model_config(CONFIG_DIR)
    manifest = _manifest(REPO_ROOT / cfg.manifest_file)
    rows, cons = merge_labels(BATCH_DIR, ANSWER_DIR, manifest)
    write_csv(REPO_ROOT / cfg.labels_file, rows, LABEL_COLUMNS)
    atomic_write_text(LABEL_DIR / "consistency.json", json.dumps(cons, indent=1, sort_keys=True) + "\n")
    from collections import Counter

    print(f"{len(rows)} labels -> {REPO_ROOT / cfg.labels_file}")
    print("distribution:", dict(sorted(Counter(r["event_class"] for r in rows).items())))
    print("self-consistency:", cons)
    return 0


def _table(args: argparse.Namespace) -> int:
    cfg = load_event_model_config(CONFIG_DIR)
    manifest = _manifest(REPO_ROOT / cfg.manifest_file)
    labels = read_csv(REPO_ROOT / cfg.labels_file)
    if not SILVER.is_file():
        raise ConfigError(f"{SILVER} not found: run `make audit` first (the TFN silver labels)")
    gold_ids, gold_texts = gold_exclusions(GOLD_DIR)
    rows = build_table(cfg, labels, manifest, read_table(SILVER), gold_texts=gold_texts, gold_ids=gold_ids)
    problems = check_disjoint(rows, gold_texts, gold_ids)
    if problems:
        raise ConfigError("event table is not disjoint from its evaluation sets: " + "; ".join(problems))
    write_table(REPO_ROOT / cfg.table, rows)
    from collections import Counter

    for split in ("train", "dev", "replay_check"):
        sub = [r for r in rows if r["split"] == split]
        print(f"{split:13s} {len(sub):5d}  {dict(sorted(Counter(r['label'] for r in sub).items()))}")
    print(f"-> {REPO_ROOT / cfg.table}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("event-pools", help="draw the blind event-labelling batches (refuses to overwrite labels)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_pools)
    sub.add_parser("event-merge", help="validate and merge the annotator's answer files into the label CSV").set_defaults(fn=_merge)
    sub.add_parser("event-table", help="build the event training table (annotated + capped TFN silver) and check disjointness").set_defaults(fn=_table)
