"""Gold v2: an additive, evaluation-only event-label set for 2023-2025 documents, labelled by two independent blind passes.

Why: gold v1 (400 AI-only rows; EARNINGS 14, CREDIT_FUNDING 10) is frozen so every earlier number stays comparable, and it cannot tell two
representations apart (a paired interval on 280 weighted rows spans zero). Gold v2 adds fresh rows from the period the shipped models have never
seen, with quotas for the thin classes, and a *second* independent annotation pass so that disagreement (not just self-consistency) is measured.

Design (every rule is committed before any label exists):
* rows come from the history-v2 signals (GDELT GKG titles, 2023-2025), disjoint from gold v1, every event-label row and the replay check set,
  by id and by near-duplicate text; boilerplate templates are collapsed to one representative;
* strata: ``rand`` (a seeded simple random sample: the unbiased NONE rate), ``kw:<class>`` (random samples of documents whose placeholder keyword
  class is a thin class: a *search aid only*, never a label), ``filing`` (news about an issuer within 24 hours *after* one of its strong-tier
  8-K filings: finds earnings/deal/credit documents without a text model; again only a search aid);
* sheets are blind (id, source, ticker, text): strata, weights and weak labels live in the manifest, which annotators do not open;
* two passes: A and B use different shuffles and different prompt wording (``data/gold_v2/prompts/``); each row's final class counts as *agreed*
  only when both passes give it the same event class; the rest go to a human adjudication queue (``human_*`` columns, never filled by us);
* labels are AI-annotated (``ai:claude``) and are never described as human truth; kappa between passes is same-family agreement.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.event_context import EventCalendar, filing_events
from .corpora import HistoryDoc
from .event_labels import (
    _collapse_templates,
    _drop_near_duplicates,
    _h,
    read_answers,
    read_csv,
    validate_answers,
    write_csv,
)
from .gold import ANNOTATOR, EVENT_CLASSES, EVENT_VOCAB

SCHEMA = 1
SHEET_COLUMNS = ["label_id", "source", "ticker", "published_at", "text"]
BATCH_SIZE = 150
FILING_WINDOW = timedelta(hours=24)
STRONG_ITEMS = ("2.02", "2.01", "1.03", "2.03", "2.04")  # strong-tier items of configs/sec_items.yaml (search aid only)
RARE = ("EARNINGS_FINANCIAL_PERFORMANCE", "CREDIT_FUNDING", "GEOPOLITICAL", "MA_CORPORATE_ACTION")


def exclusion_texts(root: Path) -> tuple[list[str], set[str]]:
    """Texts and ids of everything gold v2 must not overlap: gold v1, all event-label rows, the replay check set."""
    texts: list[str] = []
    ids: set[str] = set()
    with (root / "data/gold/gold_sample.csv").open(newline="", encoding="utf-8") as fh:
        texts += [r["text"] for r in csv.DictReader(fh)]
    man = json.loads((root / "data/gold/gold_manifest.json").read_text(encoding="utf-8"))
    ids |= {str(v["origin_id"]) for v in man["items"].values()}
    ev = root / "data/event_labels"
    with (ev / "event_labels.csv").open(newline="", encoding="utf-8") as fh:
        texts += [r["text"] for r in csv.DictReader(fh)]
    ids |= {str(v["origin_id"]) for v in json.loads((ev / "manifest.json").read_text(encoding="utf-8"))["items"].values()}
    return texts, ids


def _in_period(d: HistoryDoc) -> bool:
    return datetime(2023, 1, 1, tzinfo=UTC) <= d.published_at < datetime(2026, 1, 1, tzinfo=UTC)


def build(docs: Sequence[HistoryDoc], calendar: EventCalendar, *, exclude_texts: Sequence[str], exclude_ids: set[str], rows: int, seed: int,
          near_duplicate_threshold: float, quota: dict[str, int]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Sheet rows (blind) and the manifest. Deterministic for a given seed and inputs."""
    pool = [d for d in docs if _in_period(d) and d.id not in exclude_ids and d.text.strip()]
    pool = _drop_near_duplicates(pool, lambda d: d.text, exclude_texts, near_duplicate_threshold)
    pool = _collapse_templates(pool, lambda d: d.text, lambda d: d.id, seed)
    taken: dict[str, str] = {}   # doc id -> stratum
    strata: dict[str, dict[str, Any]] = {}
    chosen: list[HistoryDoc] = []

    def take(name: str, role: str, cands: list[HistoryDoc], n: int) -> None:
        cands = [d for d in cands if d.id not in taken]
        if len(cands) < n:
            raise ConfigError(f"stratum {name}: only {len(cands)} candidates for a quota of {n}")
        picks = sorted(cands, key=lambda d: _h(seed, d.id))[:n]  # a seeded simple random sample
        for p in picks:
            taken[p.id] = name
        chosen.extend(picks)
        strata[name] = {"role": role, "population_size": len(cands), "sampled": len(picks)}

    n_targeted = sum(quota.values())
    filing_n = max(0, min(30, rows - n_targeted - 90))
    take("rand", "population", pool, rows - n_targeted - filing_n)
    for cls in RARE:
        take(f"kw:{cls}", "targeted", [d for d in pool if d.placeholder_event == cls], quota[cls])
    near_filing = []
    for d in pool:
        if not d.ticker or d.multi_entity or not calendar.has_issuer(d.ticker):
            continue
        t = d.published_at
        for f in filing_events(calendar, d.ticker):
            if any(i in STRONG_ITEMS for i in f.items) and f.acceptance <= t <= f.acceptance + FILING_WINDOW:
                near_filing.append(d)
                break
    take("filing", "targeted", near_filing, filing_n)

    ordered = sorted(chosen, key=lambda d: _h(seed, "order:" + d.id))
    sheet, items = [], {}
    for k, d in enumerate(ordered, start=1):
        lid = f"V{k:04d}"
        sheet.append({"label_id": lid, "source": d.adapter, "ticker": d.ticker or "", "published_at": d.published_at.isoformat(), "text": d.text})
        st = taken[d.id]
        items[lid] = {"origin_id": d.id, "stratum": st, "role": strata[st]["role"], "placeholder_event": d.placeholder_event,
                      "weight": round(strata[st]["population_size"] / strata[st]["sampled"], 6) if st == "rand" else 1.0,
                      "source": d.adapter, "published_at": d.published_at.isoformat()}
    manifest = {"schema": SCHEMA, "annotator": ANNOTATOR, "seed": seed, "rows": len(sheet), "strata": strata, "items": items,
                "note": "Annotators must not open this file: it holds the strata and weak labels the sheets hide.",
                "period": "2023-01-01..2025-12-31"}
    return sheet, manifest


def write_passes(out_dir: Path, sheet: Sequence[dict[str, str]], manifest: dict[str, Any]) -> list[Path]:
    """Blind batches for pass A (id order) and pass B (a different shuffle, so each pass sees different neighbours)."""
    paths = []
    for tag, order in (("A", sorted(sheet, key=lambda r: r["label_id"])),
                       ("B", sorted(sheet, key=lambda r: _h(manifest["seed"] + 7, r["label_id"])))):
        d = out_dir / "batches" / tag
        d.mkdir(parents=True, exist_ok=True)
        for k in range(0, len(order), BATCH_SIZE):
            p = d / f"pass{tag}_{k // BATCH_SIZE + 1:02d}.csv"
            write_csv(p, order[k:k + BATCH_SIZE], SHEET_COLUMNS)
            paths.append(p)
    return paths


def read_pass(answers_dir: Path, valid_ids: set[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for path in sorted(answers_dir.glob("*.jsonl")):
        for a in read_answers(path):
            errors += validate_answers([a], valid_ids)
            out[a["label_id"]] = a
    if errors:
        raise ConfigError(f"{len(errors)} invalid answer(s) in {answers_dir}, e.g. " + "; ".join(errors[:5]))
    missing = sorted(valid_ids - set(out))
    if missing:
        raise ConfigError(f"{len(missing)} of {len(valid_ids)} rows are not labelled in {answers_dir}, e.g. {missing[:5]}")
    return out


def kappa(pairs: Sequence[tuple[str, str]]) -> dict[str, Any]:
    n = len(pairs)
    if not n:
        return {"n": 0, "agreement": None, "kappa": None}
    agree = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return {"n": n, "agreement": round(agree, 4), "kappa": round((agree - pe) / (1 - pe) if pe < 1 else 1.0, 4)}


def merge(sheet: Sequence[dict[str, str]], manifest: dict[str, Any], pass_a: dict[str, dict[str, str]], pass_b: dict[str, dict[str, str]]
          ) -> tuple[list[dict[str, str]], dict[str, Any], list[dict[str, str]]]:
    """gold_v2 rows (both labels), the agreement report, and the human adjudication queue (disagreements)."""
    rows, queue = [], []
    for r in sheet:
        lid = r["label_id"]
        a, b = pass_a[lid], pass_b[lid]
        row = {**r, "label_a": a["event_class"], "label_b": b["event_class"], "secondary_a": a["secondary_class"], "secondary_b": b["secondary_class"],
               "agreed": "y" if a["event_class"] == b["event_class"] else "n", "stratum": manifest["items"][lid]["stratum"],
               "notes_a": a["notes"], "notes_b": b["notes"], "annotator": ANNOTATOR}
        rows.append(row)
        if row["agreed"] == "n":
            queue.append({"label_id": lid, "text": r["text"], "label_a": a["event_class"], "label_b": b["event_class"],
                          "notes_a": a["notes"], "notes_b": b["notes"], "human_event_class": "", "human_notes": ""})
    pairs = [(r["label_a"], r["label_b"]) for r in rows]
    per_class = {}
    for c in EVENT_VOCAB:
        pa = [(a, b) for a, b in pairs if a == c or b == c]
        per_class[c] = {"rows_either_pass_says": len(pa), "both_say": sum(a == b == c for a, b in pairs),
                        "share_agreed": round(sum(a == b == c for a, b in pairs) / len(pa), 3) if pa else None}
    label_counts = {"pass_a": dict(sorted(Counter(r["label_a"] for r in rows).items())), "pass_b": dict(sorted(Counter(r["label_b"] for r in rows).items())),
                    "agreed": dict(sorted(Counter(r["label_a"] for r in rows if r["agreed"] == "y").items()))}
    report = {"rows": len(rows), "agreed_rows": sum(r["agreed"] == "y" for r in rows), "overall": kappa(pairs), "per_class": per_class,
              "label_counts": label_counts, "by_stratum": {s: kappa([(r["label_a"], r["label_b"]) for r in rows if r["stratum"] == s])
                                                          for s in sorted({r["stratum"] for r in rows})},
              "note": "two independent blind passes by the same AI annotator family with different prompts and orderings: agreement bounds label noise "
                      "and discovers ambiguity, it is NOT human inter-annotator kappa. Disagreements are queued for human adjudication."}
    return rows, report, queue


MERGED_COLUMNS = [*SHEET_COLUMNS, "label_a", "label_b", "secondary_a", "secondary_b", "agreed", "stratum", "notes_a", "notes_b", "annotator"]
QUEUE_COLUMNS = ["label_id", "text", "label_a", "label_b", "notes_a", "notes_b", "human_event_class", "human_notes"]


def write_outputs(out_dir: Path, rows: Sequence[dict[str, str]], report: dict[str, Any], queue: Sequence[dict[str, str]]) -> None:
    write_csv(out_dir / "gold_v2.csv", rows, MERGED_COLUMNS)
    write_csv(out_dir / "adjudication_v2.csv", queue, QUEUE_COLUMNS)
    atomic_write_text(out_dir / "agreement.json", json.dumps(report, indent=1, sort_keys=True) + "\n")


def read_all(path: Path) -> list[dict[str, str]]:
    return read_csv(path)


def csv_text(rows: Sequence[dict[str, str]], columns: Sequence[str]) -> str:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    import argparse

    import yaml

    from ..config import REPO_ROOT
    from .corpora import iter_history_docs

    ap = argparse.ArgumentParser(prog="python -m eventshock.modeling.gold_v2", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample", help="draw the rows and write the blind batches for passes A and B (refuses to overwrite)")
    sub.add_parser("merge", help="merge the answer files of both passes into gold_v2.csv, agreement.json and the adjudication queue")
    args = ap.parse_args(argv)
    root = REPO_ROOT
    out = root / "data" / "gold_v2"
    reg = yaml.safe_load((root / "configs/evidence_v2.yaml").read_text(encoding="utf-8"))
    cfg = reg["gold_v2"]
    if args.cmd == "sample":
        if (out / "manifest.json").is_file():
            raise ConfigError("gold v2 was already sampled; the sample is frozen (delete data/gold_v2 deliberately to redraw)")
        signals = root / "data/processed/history_v2/signals.jsonl"
        if not signals.is_file():
            raise ConfigError(f"{signals} is missing: run the pipeline over data/history_v2 first (see scripts/build_history_v2.py)")
        texts, ids = exclusion_texts(root)
        cal = EventCalendar.load(root / reg["data"]["calendar_dir"], root / reg["data"]["sec_items"])
        sheet, manifest = build(list(iter_history_docs(signals)), cal, exclude_texts=texts, exclude_ids=ids, rows=cfg["rows"], seed=cfg["seed"],
                                near_duplicate_threshold=cfg["near_duplicate_threshold"], quota=cfg["quota"])
        out.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out / "manifest.json", json.dumps(manifest, indent=1, sort_keys=True) + "\n")
        write_csv(out / "sheet.csv", sheet, SHEET_COLUMNS)
        paths = write_passes(out, sheet, manifest)
        print(f"gold v2: {len(sheet)} rows, strata {manifest['strata']}; {len(paths)} blind batches under {out / 'batches'}")
        return 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    sheet = read_csv(out / "sheet.csv")
    ids = {r["label_id"] for r in sheet}
    rows, report, queue = merge(sheet, manifest, read_pass(out / "answers" / "A", ids), read_pass(out / "answers" / "B", ids))
    write_outputs(out, rows, report, queue)
    print(f"gold v2: {report['agreed_rows']}/{report['rows']} rows agreed, kappa {report['overall']['kappa']}; {len(queue)} queued for human adjudication")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())


__all__ = ["EVENT_CLASSES", "build", "kappa", "main", "merge", "read_pass", "write_outputs", "write_passes"]
