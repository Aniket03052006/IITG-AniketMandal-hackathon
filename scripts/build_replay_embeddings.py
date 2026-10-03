"""Pin the sentence embeddings of the replay pack, so the hybrid event model runs offline with no torch (and byte-identically).

    python scripts/build_replay_embeddings.py texts   # run the replay pipeline once with the TF-IDF event model and record the exact strings it scores
    make bakeoff-embed-replay                         # (.venv-emb) encode them with the model's encoder into the embedding cache
    python scripts/build_replay_embeddings.py pack    # write data/replay/embeddings/*.npz (float16, sorted, hash) and pin it in data/replay/manifest.json

The strings are what the pipeline hands the event stage (`"{headline} {body}"` of each cluster's canonical report); which strings those are does not depend on the event model,
so the pack stays valid whichever event model scores them. Texts the event stage never scores (quarantined, duplicates) are not embedded.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eventshock.config import REPO_ROOT  # noqa: E402
from eventshock.ingestion.snapshot import atomic_write_text, load_snapshot, sha256_file  # noqa: E402
from eventshock.pipeline.config import (  # noqa: E402
    load_enrichment_config,
    load_pipeline_config,
    load_sentiment_model_config,
)
from eventshock.pipeline.embeddings import text_key, write_pinned  # noqa: E402
from eventshock.pipeline.enrich import EnrichmentInput, ModelEnricher  # noqa: E402
from eventshock.pipeline.event_model import EventModel  # noqa: E402
from eventshock.pipeline.run import run_snapshot  # noqa: E402
from eventshock.pipeline.sentiment_model import SentimentModel  # noqa: E402

ENCODER = "intfloat/multilingual-e5-large"
TEXTS = ROOT / "data" / "modeling" / "replay_event_texts.jsonl"
PACK = ROOT / "data" / "replay" / "embeddings" / "event-e5-large.npz"


class Capturing(ModelEnricher):
    def __init__(self, *a, **k) -> None:
        super().__init__(*a, **k)
        self.seen: dict[str, None] = {}

    def enrich(self, item: EnrichmentInput):
        self.seen.setdefault(item.text)
        return super().enrich(item)


def texts() -> None:
    cfgdir = REPO_ROOT / "configs"
    snap = load_snapshot(ROOT / "data" / "replay")
    sent = SentimentModel.load(ROOT / load_sentiment_model_config(cfgdir).model_dir)
    ev = EventModel.load(ROOT / "models/event/tfidf-lr-event-v1")
    enr = Capturing(load_enrichment_config(cfgdir), sent, ev)
    run_snapshot(snap, load_pipeline_config(cfgdir), load_enrichment_config(cfgdir), enricher=enr)
    TEXTS.parent.mkdir(parents=True, exist_ok=True)
    TEXTS.write_text("".join(json.dumps({"text": t}, ensure_ascii=False) + "\n" for t in sorted(enr.seen)), encoding="utf-8")
    print(f"{len(enr.seen)} strings scored by the event stage -> {TEXTS}")


def pack() -> None:
    from eventshock.modeling.representations.encoders import load_cache

    cache = load_cache(ENCODER, ROOT / "data" / "modeling" / "embeddings")
    strings = [json.loads(x)["text"] for x in TEXTS.read_text(encoding="utf-8").split("\n") if x.strip()]
    missing = [t for t in strings if text_key(t) not in cache]
    if missing:
        raise SystemExit(f"{len(missing)} replay strings are not embedded yet: run `make bakeoff-embed-replay` (first: {missing[0][:60]!r})")
    sha = write_pinned(PACK, {text_key(t): cache[text_key(t)] for t in strings}, encoder=ENCODER)
    mpath = ROOT / "data" / "replay" / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["embeddings"] = {"file": str(PACK.relative_to(ROOT / "data" / "replay")), "sha256": sha256_file(PACK)}
    atomic_write_text(mpath, json.dumps(m, indent=2) + "\n")
    print(f"pinned {len(strings)} vectors ({PACK.stat().st_size / 1e6:.2f} MB, sha256 {sha[:12]}) and updated the replay manifest")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("texts", "pack"):
        raise SystemExit(__doc__)
    {"texts": texts, "pack": pack}[sys.argv[1]]()
