"""How good is the sector vocabulary? Measured on documents whose company resolved, where the true sector is known.

    python -m eventshock.modeling.scope_eval [--out docs/evidence/scope_eval.json]

The entity master gives every resolved issuer a sector, so a document that names exactly one issuer is a free label for
"which sector is this about?". The vocabulary (``configs/scope.yaml``) never sees the company name, only the words around
it. Reported: how often the vocabulary fires, and, where it names one sector, how often that is the issuer's sector, by
strength tier and by sector, with the confusion matrix.

Honest limits, written into the output: these documents also name the company, so sector words co-occur with the name far
more than they would in a text that names no company at all. The agreement is therefore an optimistic proxy for the
no-company case, not a measurement of it. There is no labelled set of no-company documents to measure on.
Nothing here changes the vocabulary; edits made after seeing this output are disclosed in docs/PROJECT_JOURNEY.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT
from ..domain import UNKNOWN_ENTITY, Entity, RawDocument
from ..ingestion.base import Rejected
from ..pipeline.config import EntityResolutionConfig, load_pipeline_config
from ..pipeline.entities import EntityResolver
from ..pipeline.normalize import clean_text
from ..pipeline.scope import ScopeResolver, load_scope_config

SCHEMA = "eventshock-scope-eval-v1"
LIMITS = [
    "Documents used here also name their company, so sector words co-occur with it more than in a text that names none: "
    "the agreement is an optimistic proxy for the no-company case, not a measurement of it.",
    "Titles are short (GDELT supplies a headline only), so the vocabulary often finds nothing; coverage is reported beside precision.",
    "The vocabulary was written before this run. Any later edit is disclosed in docs/PROJECT_JOURNEY.md.",
]


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def evaluate(records: Iterable[RawDocument | Rejected], entities: list[Entity], er_cfg: EntityResolutionConfig,
             scope: ScopeResolver) -> dict[str, Any]:
    resolver = EntityResolver(entities, er_cfg)
    sector_of = {e.entity_id: e.sector for e in entities}
    docs = single = fired = 0
    tier: dict[str, Counter] = {"STRONG": Counter(), "WEAK": Counter()}
    truth: Counter = Counter()
    confusion: dict[str, Counter] = defaultdict(Counter)  # true sector -> predicted sector (or "none"/"tied")
    by_source: dict[str, Counter] = defaultdict(Counter)
    for rec in records:
        if isinstance(rec, Rejected):
            continue
        text = clean_text(f"{rec.headline} {rec.body}")
        docs += 1
        mention, audit = resolver.resolve(text)
        if mention.entity_id == UNKNOWN_ENTITY or audit.multi_entity:
            continue
        single += 1
        true = sector_of[mention.entity_id]
        truth[true] += 1
        hits = scope.sector_hits(text)
        src = str(rec.raw_metadata.get("adapter", rec.source))
        by_source[src]["docs"] += 1
        if not hits:
            confusion[true]["none"] += 1
            continue
        fired += 1
        by_source[src]["fired"] += 1
        top = scope.unique_sector(hits)
        if top is None:
            confusion[true]["tied"] += 1
            continue
        pred, terms = top
        name = "STRONG" if len(terms) >= scope.cfg.sector.strong_min_terms else "WEAK"
        tier[name]["predicted"] += 1
        tier[name]["correct"] += int(pred == true)
        confusion[true][pred] += 1
        by_source[src][f"{name.lower()}_predicted"] += 1
        by_source[src][f"{name.lower()}_correct"] += int(pred == true)
    per_sector = {}
    for s in sorted(truth):
        row = confusion[s]
        predicted_as_s = sum(confusion[t][s] for t in truth)
        per_sector[s] = {"documents": truth[s], "found_as_this_sector": row[s],
                         "recall": _rate(row[s], truth[s]), "predicted_as_this_sector": predicted_as_s,
                         "precision": _rate(row[s], predicted_as_s)}
    return {
        "documents_read": docs, "single_issuer_documents": single, "vocabulary_fired": fired,
        "coverage": _rate(fired, single),
        "by_strength": {k: {"predicted": v["predicted"], "correct": v["correct"], "precision": _rate(v["correct"], v["predicted"])}
                        for k, v in tier.items()},
        "per_sector": per_sector,
        "confusion": {t: dict(sorted(c.items())) for t, c in sorted(confusion.items())},
        "by_source": {k: dict(sorted(v.items())) for k, v in sorted(by_source.items())},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "evidence" / "scope_eval.json")
    ap.add_argument("--replay-dir", type=Path, default=REPO_ROOT / "data" / "replay")
    args = ap.parse_args(argv)

    from ..ingestion.snapshot import load_snapshot
    from ..pipeline.run import load_entities, read_snapshot

    cfg_dir = REPO_ROOT / "configs"
    snap = load_snapshot(args.replay_dir)
    records, _ = read_snapshot(snap)
    entities = load_entities(snap.entities_path())
    scope_cfg = load_scope_config(cfg_dir)
    result = evaluate(records, entities, load_pipeline_config(cfg_dir).entity_resolution, ScopeResolver(scope_cfg))
    scope_path = cfg_dir / "scope.yaml"
    out = {"schema": SCHEMA, "scope_config_version": scope_cfg.version,
           "scope_config_sha256": hashlib.sha256(scope_path.read_bytes()).hexdigest(),
           "snapshot_id": snap.manifest.snapshot_id, "limits": LIMITS, **result}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"  single-issuer documents {result['single_issuer_documents']}, vocabulary fired {result['vocabulary_fired']} "
          f"({result['coverage']}), by strength {result['by_strength']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
