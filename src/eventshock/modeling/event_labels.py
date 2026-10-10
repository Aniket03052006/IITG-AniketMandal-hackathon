"""Event-label pools: the in-domain training and evaluation data for event classification.

Why this exists (docs/notes/EVENT_MODEL.md): the only event labels in the repo were the Twitter-Financial-News *topics*, mapped to the
taxonomy by a crosswalk. A topic is not an event type; a classifier trained on it scores 0.89 macro-F1 on TFN and 0.16-0.30 on the
gold set, cannot say "not an event", and has no data for GEOPOLITICAL or PRODUCT_OPERATIONS. So we label text from our own sources.

Design:
* Every history stratum is a seeded **simple random sample**, so a row's weight is ``N_k / n_k`` and weighted dev metrics estimate the
  whole (template-collapsed) history frame. ``rand:*`` strata are the unbiased sample; ``kw:*`` strata are random samples of the
  documents whose PLACEHOLDER keyword class is a rare class. The keyword class is only used to *find* rare events, never as a label.
* TFN topic rows are labelled by the annotator and not trusted to carry the crosswalk class.
* Nothing drawn here may overlap the gold set (by id or near-duplicate text) or the replay check set: the model must never have seen
  an evaluation row. ``check_disjoint`` re-verifies that on the finished table.
* The sheets are blind (id, source, ticker, text). Strata, weights and weak labels live in the manifest, which an annotator does not open.
* Labels are produced by an AI annotator (``ai:claude``) following docs/notes/GOLD_LABELING_GUIDE.md and are never described as human truth.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.config import EventModelConfig
from .corpora import HistoryDoc, TextPool, read_jsonl
from .gold import ANNOTATOR, EVENT_CLASSES, EVENT_VOCAB
from .text import has_near_duplicate, near_duplicate_groups, template_key

BATCH_COLUMNS = ["label_id", "source", "ticker", "text"]
ANSWER_KEYS = ("event_class", "secondary_class", "notes")
LABEL_COLUMNS = ["label_id", "source", "ticker", "text", "event_class", "secondary_class", "notes", "annotator", "batch"]
BATCH_SIZE = 200
SCHEMA = 1


def _h(seed: int, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


@dataclass
class Pick:
    origin_id: str
    population: str  # "history" | "tfn" | "replay"
    stratum: str
    role: str  # "population" | "targeted" | "tfn-topic" | "replay-check"
    source: str
    ticker: str
    text: str
    weight: float = 1.0
    topic: int | None = None
    placeholder: str = ""


def _srs(pool: Sequence[Pick], n: int, seed: int) -> list[Pick]:
    return sorted(pool, key=lambda p: _h(seed, p.origin_id))[:n]


def _collapse_templates(items: Iterable[Any], text_of, id_of, seed: int) -> list[Any]:
    """One representative per boilerplate/spam template (same rule as the gold sampler), deterministic."""
    rep: dict[str, Any] = {}
    for it in items:
        tk = template_key(text_of(it))
        key = tk if len(tk.split()) >= 4 else f"id:{id_of(it)}"
        if key not in rep or _h(seed, id_of(it)) < _h(seed, id_of(rep[key])):
            rep[key] = it
    return sorted(rep.values(), key=id_of)


def _drop_near_duplicates(items: list[Any], text_of, reference: Sequence[str], threshold: float) -> list[Any]:
    if not items or not reference:
        return items
    dup = has_near_duplicate([text_of(i) for i in items], list(reference), threshold)
    return [i for i, d in zip(items, dup, strict=True) if not d]


def gold_exclusions(gold_dir: Path) -> tuple[set[str], list[str]]:
    """Origin ids and texts of the frozen gold set. Both are excluded from every pool."""
    sheet, man = gold_dir / "gold_sample.csv", gold_dir / "gold_manifest.json"
    if not (sheet.is_file() and man.is_file()):
        raise ConfigError(f"gold set not found in {gold_dir}: event labels must be drawn disjoint from it")
    with sheet.open(newline="", encoding="utf-8") as fh:
        texts = [r["text"] for r in csv.DictReader(fh)]
    items = json.loads(man.read_text(encoding="utf-8"))["items"]
    return {str(v["origin_id"]) for v in items.values()}, texts


def build_pools(cfg: EventModelConfig, *, history: Iterable[HistoryDoc], topic_pool: TextPool, sentiment_pool: TextPool,
                replay: Sequence[HistoryDoc], gold_ids: set[str], gold_texts: Sequence[str]
                ) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Returns (sheet rows, manifest). Deterministic for a given seed, config and inputs. Row order mixes strata."""
    lc = cfg.labels
    thr = lc.near_duplicate_threshold
    seed = lc.seed
    picks: list[Pick] = []
    strata: dict[str, dict[str, Any]] = {}

    def take(name: str, role: str, population: str, pool: list[Pick], quota: int) -> None:
        if len(pool) < quota:
            raise ConfigError(f"stratum {name}: only {len(pool)} candidates for a quota of {quota}")
        chosen = _srs(pool, quota, seed)
        w = len(pool) / len(chosen)
        for c in chosen:
            c.weight = round(w, 6)
        picks.extend(chosen)
        strata[name] = {"role": role, "population": population, "population_size": len(pool), "sampled": len(chosen), "quota": quota}

    # ---- replay check set first: its near-duplicates are then removed from every training pool
    replay_docs = [d for d in replay if d.id not in gold_ids and d.text.strip()]
    replay_docs = _drop_near_duplicates(replay_docs, lambda d: d.text, gold_texts, thr)
    replay_docs = _collapse_templates(replay_docs, lambda d: d.text, lambda d: d.id, seed)
    by_adapter: dict[str, list[Pick]] = defaultdict(list)
    for d in replay_docs:
        by_adapter[d.adapter].append(Pick(d.id, "replay", f"replay:{d.adapter}", "replay-check", d.adapter, d.ticker or "", d.text,
                                          placeholder=d.placeholder_event))
    for adapter, quota in sorted(lc.replay_check.items()):
        take(f"replay:{adapter}", "replay-check", "replay", by_adapter.get(adapter, []), quota)
    replay_texts = [p.text for p in picks]
    exclude_texts = [*gold_texts, *replay_texts]

    # ---- history: SRS strata over the template-collapsed frame
    tfn_texts = [e.text for e in topic_pool.examples] + [e.text for e in sentiment_pool.examples]
    docs = [d for d in history if d.id not in gold_ids and d.text.strip()]
    docs = _drop_near_duplicates(docs, lambda d: d.text, [*tfn_texts, *exclude_texts], thr)
    docs = _collapse_templates(docs, lambda d: d.text, lambda d: d.id, seed)
    rare = {c for c in EVENT_CLASSES if c != "MARKET_VALUATION"}  # MARKET_VALUATION is the keyword-less default: no signal
    hist: dict[str, list[Pick]] = defaultdict(list)
    for d in docs:
        stratum = f"kw:{d.placeholder_event}" if d.placeholder_event in rare else f"rand:{d.adapter}"
        hist[stratum].append(Pick(d.id, "history", stratum, "targeted" if stratum.startswith("kw:") else "population", d.adapter,
                                  d.ticker or "", d.text, placeholder=d.placeholder_event))
    for adapter, quota in sorted(lc.population_per_source.items()):
        take(f"rand:{adapter}", "population", "history", hist.get(f"rand:{adapter}", []), quota)
    for cls in sorted(rare):
        take(f"kw:{cls}", "targeted", "history", hist.get(f"kw:{cls}", []), lc.rare_per_class)

    # ---- TFN topic rows: one representative per near-duplicate group, gold and replay-check lookalikes removed
    seen: set[int] = set()
    topic_cands: dict[int, list[Pick]] = defaultdict(list)
    for e, g in sorted(zip(topic_pool.examples, topic_pool.groups, strict=True), key=lambda x: _h(seed, x[0].id)):
        if g in seen or e.id in gold_ids or e.topic not in lc.tfn_topic_rows:
            continue
        seen.add(g)
        topic_cands[e.topic].append(Pick(e.id, "tfn", f"tfn:{e.topic}", "tfn-topic", "tfn-topic", "", e.text, topic=e.topic))
    for topic, quota in sorted(lc.tfn_topic_rows.items()):
        pool = _drop_near_duplicates(topic_cands.get(topic, []), lambda p: p.text, exclude_texts, thr)
        take(f"tfn:{topic}", "tfn-topic", "tfn", pool, quota)

    ids = [p.origin_id for p in picks]
    if len(set(ids)) != len(ids):
        raise ConfigError("a document was drawn by two strata: pools must be disjoint")

    picks.sort(key=lambda p: (p.role == "replay-check", _h(seed, p.origin_id)))
    rows, items, n_train, n_replay = [], {}, 0, 0
    for p in picks:
        if p.role == "replay-check":
            n_replay += 1
            lid = f"R{n_replay:04d}"
        else:
            n_train += 1
            lid = f"E{n_train:04d}"
        rows.append({"label_id": lid, "source": p.source, "ticker": p.ticker, "text": p.text})
        items[lid] = {"origin_id": p.origin_id, "population": p.population, "stratum": p.stratum, "role": p.role, "weight": p.weight,
                      "source": p.source, "topic": p.topic, "placeholder_event": p.placeholder}
    train_ids = sorted(i for i, v in items.items() if v["role"] != "replay-check")
    cons = sorted(train_ids, key=lambda i: _h(seed + 1, i))[: lc.consistency_rows]
    manifest = {
        "schema": SCHEMA, "annotator": ANNOTATOR, "seed": seed, "rows": len(rows),
        "note": "Annotators must not open this file: it holds the strata and weak labels the sheets hide.",
        "strata": strata, "items": items,
        "consistency": {f"C{k:04d}": lid for k, lid in enumerate(cons, start=1)}}
    return rows, manifest


# ------------------------------------------------------------------------------------------------- sheet I/O
def write_csv(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n", extrasaction="raise")
    w.writeheader()
    w.writerows(rows)
    atomic_write_text(path, buf.getvalue())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_batches(out_dir: Path, rows: Sequence[dict[str, str]], manifest: dict[str, Any]) -> list[Path]:
    """Blind batches of at most ``BATCH_SIZE`` rows: E*** rows in order, then the replay check set, then the consistency re-label."""
    out_dir.mkdir(parents=True, exist_ok=True)
    by_id = {r["label_id"]: r for r in rows}
    train = [r for r in rows if r["label_id"].startswith("E")]
    replay = [r for r in rows if r["label_id"].startswith("R")]
    cons = [{**by_id[lid], "label_id": cid} for cid, lid in manifest["consistency"].items()]
    # the consistency rows are shuffled away from their original positions so the re-label is blind to the first pass
    cons.sort(key=lambda r: _h(manifest["seed"] + 2, r["label_id"]))
    paths = []
    for tag, part in (("batch", train), ("replay", replay), ("consistency", cons)):
        for k in range(0, len(part), BATCH_SIZE):
            path = out_dir / f"{tag}_{k // BATCH_SIZE + 1:02d}.csv"
            write_csv(path, part[k:k + BATCH_SIZE], BATCH_COLUMNS)
            paths.append(path)
    return paths


# -------------------------------------------------------------------------------------------------- answers
def read_answers(path: Path) -> list[dict[str, str]]:
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if line.strip():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"{path}:{n}: unreadable JSON ({exc})") from exc
            out.append({"label_id": str(rec.get("label_id", "")).strip(),
                        **{k: str(rec.get(k, "") or "").strip() for k in ANSWER_KEYS}})
    return out


def validate_answers(answers: Sequence[dict[str, str]], valid_ids: set[str]) -> list[str]:
    errors, seen = [], set()
    for a in answers:
        lid = a["label_id"]
        if lid in seen:
            errors.append(f"{lid}: labelled twice")
        seen.add(lid)
        if lid not in valid_ids:
            errors.append(f"{lid}: unknown id")
        if a["event_class"] not in EVENT_VOCAB:
            errors.append(f"{lid}: event_class {a['event_class']!r} is not one of the 8 classes or NONE")
        sec = a["secondary_class"]
        if sec and (sec not in EVENT_CLASSES or sec == a["event_class"]):
            errors.append(f"{lid}: secondary_class {sec!r} must be one of the 8 classes and differ from the primary")
    return errors


def merge_labels(batches_dir: Path, answers_dir: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Merge answer files into label rows (first pass) and consistency rows (second blind pass). Errors are collected, not skipped."""
    text_of: dict[str, dict[str, str]] = {}
    for path in sorted(batches_dir.glob("*.csv")):
        for r in read_csv(path):
            text_of[r["label_id"]] = r
    cons_map = manifest["consistency"]
    labels, second, errors, batches = {}, {}, [], {}
    for path in sorted(answers_dir.glob("*.jsonl")):
        for a in read_answers(path):
            errors += validate_answers([a], set(text_of))
            (second if a["label_id"] in cons_map else labels)[a["label_id"]] = a
            batches[a["label_id"]] = path.stem
    if errors:
        raise ConfigError(f"{len(errors)} invalid answer(s), e.g. " + "; ".join(errors[:5]))
    missing = sorted(set(manifest["items"]) - set(labels))
    if missing:
        raise ConfigError(f"{len(missing)} of {len(manifest['items'])} rows are not labelled yet, e.g. {missing[:5]}")
    rows = [{"label_id": lid, "source": text_of[lid]["source"], "ticker": text_of[lid]["ticker"], "text": text_of[lid]["text"],
             **{k: labels[lid][k] for k in ANSWER_KEYS}, "annotator": ANNOTATOR, "batch": batches[lid]}
            for lid in sorted(manifest["items"])]
    pairs = [(labels[cons_map[cid]]["event_class"], second[cid]["event_class"]) for cid in sorted(second)]
    return rows, consistency(pairs)


def consistency(pairs: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """Agreement and Cohen's kappa between two blind passes of the SAME annotator: bounds label noise, not shared bias."""
    n = len(pairs)
    if not n:
        return {"n": 0, "agreement": None, "kappa": None}
    agree = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    kappa = (agree - pe) / (1 - pe) if pe < 1 else 1.0
    none_first = sum(a == "NONE" for a, _ in pairs)
    return {"n": n, "agreement": round(agree, 4), "kappa": round(kappa, 4), "share_none_first_pass": round(none_first / n, 4),
            "note": "same annotator, second blind pass: an upper bound on label noise, NOT an independent inter-annotator kappa"}


# ------------------------------------------------------------------------------------------- training table
LABELS9 = [*EVENT_CLASSES, "NONE"]
TABLE_COLUMNS = {"id", "text", "label", "split", "kind", "group", "sample_weight", "pop_weight", "stratum", "population", "source"}


def build_table(cfg: EventModelConfig, label_rows: Sequence[dict[str, str]], manifest: dict[str, Any], silver_rows: Sequence[dict[str, Any]],
                *, gold_texts: Sequence[str], gold_ids: set[str], split_seed: int | None = None) -> list[dict[str, Any]]:
    """The one table the trainer reads: annotated rows (train/dev/replay_check) plus capped TFN silver (train only).

    * dev is a near-duplicate-group-aware, label-stratified slice of the annotated rows; replay-check rows are never trained on.
    * silver rows are TFN topic rows whose crosswalk tier is strong/medium (``train_eligible``). They are dropped if the annotator
      relabelled them, if they sit in the TFN test split, or if they are near-duplicates of a dev / replay-check / gold text.
    """
    from .corpora import stratified_group_split

    seed = cfg.seed if split_seed is None else split_seed
    items = manifest["items"]
    annotated = [r for r in label_rows if items[r["label_id"]]["role"] != "replay-check"]
    replay = [r for r in label_rows if items[r["label_id"]]["role"] == "replay-check"]
    groups = near_duplicate_groups([r["text"] for r in annotated], 0.7)
    group_label: dict[int, str] = {}
    sizes: dict[int, int] = Counter()
    for r, g in zip(annotated, groups, strict=True):
        group_label.setdefault(g, r["event_class"])
        sizes[g] += 1
    frac = cfg.labels.dev_fraction
    assign = stratified_group_split(group_label, dict(sizes), {"train": 1 - frac, "dev": frac}, seed)

    rows: list[dict[str, Any]] = []
    for r, g in zip(annotated, groups, strict=True):
        it = items[r["label_id"]]
        rows.append({"id": r["label_id"], "text": r["text"], "label": r["event_class"], "split": assign[g], "kind": "annotated",
                     "group": int(g), "sample_weight": 1.0, "pop_weight": 1.0, "stratum": it["stratum"],
                     "population": it["population"], "source": it["source"]})
    for r in replay:
        it = items[r["label_id"]]
        rows.append({"id": r["label_id"], "text": r["text"], "label": r["event_class"], "split": "replay_check", "kind": "annotated",
                     "group": -1, "sample_weight": 1.0, "pop_weight": 1.0, "stratum": it["stratum"],
                     "population": it["population"], "source": it["source"]})
    # inclusion weights per split: a stratum's N rows are represented by the n of its rows that landed in that split, so
    # weighted dev (or replay-check) metrics estimate the whole stratified population, whatever the split did to each stratum
    n_in = Counter((r["stratum"], r["split"]) for r in rows)
    for r in rows:
        r["pop_weight"] = round(manifest["strata"][r["stratum"]]["population_size"] / n_in[(r["stratum"], r["split"])], 6)

    if cfg.silver.use:
        relabelled = {it["origin_id"] for it in items.values()}
        elig = [s for s in silver_rows if s["train_eligible"] and s["split"] == "train" and s["id"] not in relabelled
                and s["id"] not in gold_ids and not s["gold_reserved"]]
        held = [r["text"] for r in rows if r["split"] in ("dev", "replay_check")] + list(gold_texts)
        elig = _drop_near_duplicates(elig, lambda s: s["text"], held, 0.8)
        per: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for s in elig:
            per[s["event_class"]].append(s)
        for cls in sorted(per):
            for s in sorted(per[cls], key=lambda s: _h(seed, s["id"]))[: cfg.silver.max_rows_per_class]:
                rows.append({"id": s["id"], "text": s["text"], "label": cls, "split": "train", "kind": "silver", "group": int(s["group"]),
                             "sample_weight": cfg.silver.sample_weight, "pop_weight": 1.0, "stratum": f"silver:{s['topic']}",
                             "population": "tfn", "source": "tfn-topic"})
    return sorted(rows, key=lambda r: (r["kind"], r["id"]))


def check_disjoint(rows: Sequence[dict[str, Any]], gold_texts: Sequence[str], gold_ids: set[str], threshold: float = 0.8) -> list[str]:
    """Problems that would void the evaluation: a training row that is (near) a dev, replay-check or gold row."""
    problems = [f"{r['id']}: is a gold row" for r in rows if r["id"] in gold_ids]
    train = [r["text"] for r in rows if r["split"] == "train"]
    for name, ref in (("dev", [r["text"] for r in rows if r["split"] == "dev"]),
                      ("replay_check", [r["text"] for r in rows if r["split"] == "replay_check"]), ("gold", list(gold_texts))):
        dup = has_near_duplicate(train, ref, threshold)
        n = sum(dup)
        if n:
            problems.append(f"{n} training text(s) are near-duplicates of {name} texts")
    return problems


def write_table(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    atomic_write_text(path, "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows) + "\n")


def read_table(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)
