"""Collect every text the embedding experiment needs, once, deterministically (main venv; no network).

Writes <out>/texts.jsonl with {"key", "text"}: the event-model train/dev/replay-check rows, the gold event sets, and the first
document of every impact episode (the impact model works at the episode level, so one text per episode is what a text feature sees).
The gold set is read for evaluation only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from eventshock.modeling.event_eval import gold_event_sets  # noqa: E402


def key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]  # noqa: S324


def main(out: Path) -> None:
    texts: dict[str, str] = {}
    for line in (ROOT / "data/modeling/event_train.jsonl").read_text(encoding="utf-8").split("\n"):
        if line.strip():
            r = json.loads(line)
            if r["kind"] == "annotated":
                texts[key(r["text"])] = r["text"]
    g = gold_event_sets(ROOT / "data/gold") or {}
    for pop in g.values():
        for t in pop[0]:
            texts[key(t)] = t
    n_event = len(texts)
    seen: set[str] = set()
    with (ROOT / "data/modeling/impact_table.jsonl").open("rb") as fh:
        for raw in fh:
            r = json.loads(raw)
            if r["episode"] in seen:
                continue
            seen.add(r["episode"])
            texts[key(r["text"])] = r["text"]
    out.mkdir(parents=True, exist_ok=True)
    with (out / "texts.jsonl").open("w", encoding="utf-8") as fh:
        for k in sorted(texts):
            fh.write(json.dumps({"key": k, "text": texts[k]}, ensure_ascii=False) + "\n")
    print(f"{len(texts)} texts ({n_event} for the event experiment, {len(seen)} impact episodes) -> {out / 'texts.jsonl'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
