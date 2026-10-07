"""Freeze manifest: one sha256 for every file that defines the final model state, plus the cross-checks that tie them together.

    python scripts/freeze_manifest.py --write   # (re)write docs/freeze_manifest.json (only after a deliberate change)
    python scripts/freeze_manifest.py --check   # verify; exits 1 and names every drifted file (default)

What is frozen: model artifacts and cards, configs, the gold sets and their adjudication queues, the structured-event calendar,
the replay snapshot (manifest, sources, pinned embeddings, market context) and the committed evidence files.
Offline and deterministic; nothing is retrained or fetched. Human labels, when they exist, change the gold files and therefore
require a deliberate `--write` and a line in docs/PROJECT_JOURNEY.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eventshock.ingestion.snapshot import load_snapshot  # noqa: E402

OUT = ROOT / "docs" / "freeze_manifest.json"
SCHEMA = 1
MODEL_DIRS = ["models/sentiment/tfidf-lr-v1", "models/sentiment/tfidf-lr-v2", "models/event/tfidf-lr-event-v1", "models/event/hybrid-event-v2",
              "models/impact/impact-v1", "models/impact/impact-v2"]
GROUPS = {  # label -> (directory, glob); sorted, so the manifest is stable
    "models": ("models", "**/*"),
    "configs": ("configs", "*.yaml"),
    "gold_v1": ("data/gold", "*"),
    "gold_v2": ("data/gold_v2", "*.*"),                 # sheet, labels, agreement, adjudication queue, manifest
    "gold_v2_answers": ("data/gold_v2/answers", "**/*"),
    "gold_v2_prompts": ("data/gold_v2/prompts", "**/*"),
    "events": ("data/events", "*"),
    "replay": ("data/replay", "**/*"),
    "evidence": ("docs/evidence", "*.json"),
}
PROBES = ["Apple beats earnings estimates and raises full-year guidance",
          "Regulators open an investigation into the bank over money laundering",
          "Central bank holds rates steady as inflation cools", "Company announces acquisition of rival for $4 billion",
          "Shares fall after the supplier defaults on its bonds", "Weather is nice today"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect() -> dict[str, str]:
    files: dict[str, str] = {}
    for directory, pattern in GROUPS.values():
        for p in sorted((ROOT / directory).glob(pattern)):
            if p.is_file() and p.name != ".DS_Store":
                files[p.relative_to(ROOT).as_posix()] = sha(p)
    return files


def cross_checks() -> list[str]:
    """Independent consistency checks between the frozen files; each returns a message when it fails."""
    bad: list[str] = []
    for d in MODEL_DIRS:
        card = json.loads((ROOT / d / "model_card.json").read_text(encoding="utf-8"))
        actual = sha(ROOT / d / "model.joblib")
        if card["artifact_sha256"] != actual:
            bad.append(f"{d}: card artifact_sha256 {card['artifact_sha256'][:12]} != file {actual[:12]}")
    v2 = json.loads((ROOT / "models/impact/impact-v2/model_card.json").read_text(encoding="utf-8"))
    prereg = sha(ROOT / "configs/evidence_v2.yaml")
    if v2["dataset"]["preregistration_sha256"] != prereg:
        bad.append("configs/evidence_v2.yaml (the pre-registration) no longer matches the hash pinned in impact-v2's card")
    study = json.loads((ROOT / "docs/evidence/impact_study.json").read_text(encoding="utf-8"))
    if study["preregistration"]["sha256"] != prereg:
        bad.append("configs/evidence_v2.yaml no longer matches the hash stamped in docs/evidence/impact_study.json")
    cal = v2["dataset"]["calendar"]
    for name, rel in (("fomc", "data/events/fomc.json"), ("sec_filings", "data/events/sec_filings.jsonl"), ("sec_items", "configs/sec_items.yaml")):
        if cal.get(name) != sha(ROOT / rel):
            bad.append(f"{rel} no longer matches the calendar hash pinned in impact-v2's card")
    try:
        load_snapshot(ROOT / "data" / "replay")  # verifies every source, entity, portfolio, embeddings and market-context hash
    except Exception as exc:  # noqa: BLE001 - report, never swallow
        bad.append(f"replay snapshot: {exc}")
    return bad


def reload_is_deterministic() -> list[str]:
    """Load the text models twice from disk; identical probabilities on a fixed probe set. (The hybrid and impact stages are pinned by the golden digests.)"""
    import numpy as np

    from eventshock.pipeline.event_model import EventModel
    from eventshock.pipeline.sentiment_model import SentimentModel

    bad: list[str] = []
    for label, load in (("sentiment tfidf-lr-v1", lambda: SentimentModel.load(ROOT / "models/sentiment/tfidf-lr-v1")),
                        ("sentiment tfidf-lr-v2", lambda: SentimentModel.load(ROOT / "models/sentiment/tfidf-lr-v2")),
                        ("event tfidf-lr-event-v1", lambda: EventModel.load(ROOT / "models/event/tfidf-lr-event-v1"))):
        a, b = load().probabilities(PROBES), load().probabilities(PROBES)
        if not np.array_equal(a, b):
            bad.append(f"{label}: two loads of the same artifact gave different probabilities")
    return bad


def manifest() -> dict:
    cards = {d: json.loads((ROOT / d / "model_card.json").read_text(encoding="utf-8")) for d in MODEL_DIRS}
    snap = json.loads((ROOT / "data/replay/manifest.json").read_text(encoding="utf-8"))
    return {"schema": SCHEMA, "frozen_on": "2026-10-03",
            "models": {d: {"id": c["id"], "artifact_sha256": c["artifact_sha256"]} for d, c in cards.items()},
            "replay_snapshot": snap["snapshot_id"], "files": collect()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="rewrite docs/freeze_manifest.json from the files on disk")
    ap.add_argument("--check", action="store_true", help="verify against docs/freeze_manifest.json (default)")
    args = ap.parse_args()
    problems = cross_checks() + reload_is_deterministic()
    if args.write:
        if problems:
            print("refusing to write a freeze manifest over inconsistent files:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        OUT.write_text(json.dumps(manifest(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)} ({len(json.loads(OUT.read_text())['files'])} files)")
        return 0
    if not OUT.is_file():
        print(f"no {OUT.relative_to(ROOT)}: run `python scripts/freeze_manifest.py --write`", file=sys.stderr)
        return 1
    frozen = json.loads(OUT.read_text(encoding="utf-8"))
    now = manifest()
    for path in sorted(set(frozen["files"]) | set(now["files"])):
        a, b = frozen["files"].get(path), now["files"].get(path)
        if a != b:
            problems.append(f"{path}: " + ("added since the freeze" if a is None else "missing" if b is None else "changed since the freeze"))
    if frozen["models"] != now["models"]:
        problems.append("model ids / artifact hashes differ from the freeze manifest")
    if problems:
        print("FREEZE CHECK FAILED:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print(f"freeze check passed: {len(now['files'])} files, {len(now['models'])} models, snapshot {now['replay_snapshot']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
