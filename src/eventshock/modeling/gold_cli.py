"""``python -m eventshock.modeling gold-*``: sample, show, apply labels, validate, adjudicate, consistency, score."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config import REPO_ROOT, ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.config import load_enrichment_config
from ..pipeline.topics import load_topic_mapping
from .config import load_modeling_config
from .corpora import iter_history_docs, load_tfn_sentiment, load_tfn_topic, prepare_text_pool
from .gold import (
    ADJ_COLUMNS,
    SHEET_COLUMNS,
    adjudication_rows,
    build_sample,
    consistency_rows,
    read_sheet,
    score_gold,
    validate_sheet,
    write_sheet,
)

CONFIG_DIR = REPO_ROOT / "configs"
GOLD_DIR = REPO_ROOT / "data" / "gold"
SHEET = GOLD_DIR / "gold_sample.csv"
MANIFEST = GOLD_DIR / "gold_manifest.json"
ADJ = GOLD_DIR / "adjudication.csv"
CONSISTENCY = GOLD_DIR / "consistency_sheet.csv"
LABEL_KEYS = ("ai_sentiment", "ai_event_class", "ai_secondary_class", "ai_entity_ok", "ai_notes")


def _manifest() -> dict:
    if not MANIFEST.exists():
        raise ConfigError(f"{MANIFEST} not found: run `python -m eventshock.modeling gold-sample` first")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _sample(args: argparse.Namespace) -> int:
    if SHEET.exists() and any(r.get("ai_event_class", "").strip() for r in read_sheet(SHEET)) and not args.force:
        raise ConfigError(f"{SHEET} already contains labels; refusing to overwrite (use --force to discard them)")
    cfg = load_modeling_config(CONFIG_DIR)
    raw = REPO_ROOT / "data" / "raw"
    mapping = load_topic_mapping(CONFIG_DIR)
    thr = cfg.splits.text.near_duplicate_threshold
    rows, manifest = build_sample(
        cfg.gold, history=iter_history_docs(REPO_ROOT / "data" / "processed" / "history" / "signals.jsonl"),
        topic_pool=prepare_text_pool(load_tfn_topic(raw, mapping), thr), sentiment_pool=prepare_text_pool(load_tfn_sentiment(raw), thr),
        enrichment_cfg=load_enrichment_config(CONFIG_DIR))
    manifest["config_digest"] = cfg.digest()
    report = REPO_ROOT / "data" / "processed" / "history" / "report.json"
    manifest["history_output_digest"] = json.loads(report.read_text(encoding="utf-8")).get("output_digest") if report.exists() else None
    write_sheet(SHEET, rows)
    atomic_write_text(MANIFEST, json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"{len(rows)} rows -> {SHEET}")
    for name, s in manifest["strata"].items():
        print(f"  {name:28s} {s['role']:10s} population {s['population_size']:6d}  sampled {s['sampled']:3d} / quota {s['quota']}")
    short = {n: s for n, s in manifest["strata"].items() if s["sampled"] < s["quota"]}
    if short:
        print(f"WARNING: strata below quota: {sorted(short)}")
    return 0


def _show(args: argparse.Namespace) -> int:
    rows = read_sheet(Path(args.sheet))
    sel = [r for r in rows if not (args.unlabelled and r.get("ai_event_class", "").strip())][args.start - 1: args.start - 1 + args.count]
    for r in sel:
        text = r["text"].replace("\n", " ⏎ ")
        print(f"{r['gold_id']} | {r['source']} | {r['published_at'][:16]} | {r['ticker'] or '-'} | {text}")
    return 0


def _apply(args: argparse.Namespace) -> int:
    path = Path(args.sheet)
    rows = read_sheet(path)
    by_id = {r["gold_id"]: r for r in rows}
    n = 0
    for line in Path(args.labels).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        row = by_id.get(rec["gold_id"])
        if row is None:
            raise ConfigError(f"unknown gold_id {rec['gold_id']}")
        if row.get("ai_event_class", "").strip() and not args.overwrite:
            raise ConfigError(f"{rec['gold_id']} is already labelled (use --overwrite)")
        for k in LABEL_KEYS:
            row[k] = str(rec.get(k, "")).strip()
        n += 1
    write_sheet(path, rows, columns=list(rows[0].keys()))
    manifest = _manifest()
    rep = validate_sheet(rows, manifest, prefix="ai_", subset=path.resolve() != SHEET.resolve())
    print(f"applied {n} labels; {rep.complete}/{rep.rows} complete; {len(rep.errors)} vocabulary errors")
    for e in rep.errors[:10]:
        print("  ", e)
    return 1 if rep.errors else 0


def _validate(args: argparse.Namespace) -> int:
    rep = validate_sheet(read_sheet(Path(args.sheet)), _manifest(), require_complete=args.require_complete,
                         subset=Path(args.sheet).resolve() != SHEET.resolve())
    print(f"{rep.complete}/{rep.rows} rows completely labelled")
    print("event:", rep.event_distribution, "\nsentiment:", rep.sentiment_distribution)
    for e in rep.errors:
        print("ERROR:", e)
    return 0 if rep.ok else 1


def _adjudicate(args: argparse.Namespace) -> int:
    cfg = load_modeling_config(CONFIG_DIR).gold
    rows = adjudication_rows(read_sheet(SHEET), _manifest(), cfg)
    write_sheet(ADJ, rows, columns=ADJ_COLUMNS)
    print(f"{len(rows)} rows -> {ADJ} (fill human_* only where you disagree)")
    return 0


def _consistency(args: argparse.Namespace) -> int:
    cfg = load_modeling_config(CONFIG_DIR).gold
    rows = consistency_rows(read_sheet(SHEET), cfg)
    write_sheet(CONSISTENCY, rows, columns=SHEET_COLUMNS)
    print(f"{len(rows)} blind rows -> {CONSISTENCY}")
    return 0


def _score(args: argparse.Namespace) -> int:
    adj = read_sheet(ADJ) if ADJ.exists() else []
    cons = [r for r in read_sheet(CONSISTENCY) if r.get("ai_event_class", "").strip()] if CONSISTENCY.exists() else []
    mapping = load_topic_mapping(CONFIG_DIR)
    out = score_gold(read_sheet(SHEET), _manifest(), adj, cons, tiers={t: mapping.tier(t) for t in mapping.topics})
    text = json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False)
    if args.out:
        atomic_write_text(Path(args.out), text + "\n")
    print(text)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("gold-sample", help="draw the blind gold sample (refuses to overwrite labels)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_sample)
    p = sub.add_parser("gold-show", help="print blind rows for labelling")
    p.add_argument("--sheet", default=str(SHEET))
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--count", type=int, default=40)
    p.add_argument("--unlabelled", action="store_true", help="skip rows that already have a label")
    p.set_defaults(fn=_show)
    p = sub.add_parser("gold-apply", help="merge labels from a JSONL file into the sheet")
    p.add_argument("labels")
    p.add_argument("--sheet", default=str(SHEET))
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(fn=_apply)
    p = sub.add_parser("gold-validate", help="check vocabulary, ids and completeness")
    p.add_argument("--sheet", default=str(SHEET))
    p.add_argument("--require-complete", action="store_true")
    p.set_defaults(fn=_validate)
    sub.add_parser("gold-adjudicate", help="write the rows a human should review").set_defaults(fn=_adjudicate)
    sub.add_parser("gold-consistency", help="write a blind re-labelling sheet").set_defaults(fn=_consistency)
    p = sub.add_parser("gold-score", help="weighted scores, crosswalk precision, agreement")
    p.add_argument("--out")
    p.set_defaults(fn=_score)


def probe_gold(res: dict) -> None:
    """If the gold sheet is labelled, score the probe models on it (history population, weighted) and print."""
    from .gold import EVENT_CLASSES, SENTIMENT_NAME, effective_labels, weighted_scores

    if not (SHEET.exists() and MANIFEST.exists()):
        return
    sheet = read_sheet(SHEET)
    adj = read_sheet(ADJ) if ADJ.exists() else []
    lab = effective_labels(sheet, adj)
    if not lab:
        return
    man = _manifest()
    text = {r["gold_id"]: r["text"] for r in sheet}
    ids = sorted(lab)
    ev_pred = res["_models"]["event"].predict([text[i] for i in ids])
    se_pred = res["_models"]["sentiment"].predict([text[i] for i in ids])
    out = {}
    for pop in ("history", "tfn"):
        sel = [(i, ev_pred[k], se_pred[k]) for k, i in enumerate(ids) if man["items"][i]["population"] == pop]
        out[pop] = {
            "event_all_classes": weighted_scores([(lab[i]["event"], e, man["items"][i]["weight"]) for i, e, _ in sel], [*EVENT_CLASSES, "NONE"]),
            "sentiment": weighted_scores([(lab[i]["sentiment"], SENTIMENT_NAME[s], man["items"][i]["weight"]) for i, _, s in sel], ["-1", "0", "1"])}
    atomic_write_text(REPO_ROOT / "data" / "modeling" / "probe_gold.json", json.dumps(out, indent=1, sort_keys=True) + "\n")
    for pop, d in out.items():
        print(f"gold ({pop}, weighted): event acc {d['event_all_classes'].get('accuracy')} macro-F1 {d['event_all_classes'].get('macro_f1')}; "
              f"sentiment acc {d['sentiment'].get('accuracy')} macro-F1 {d['sentiment'].get('macro_f1')}")
