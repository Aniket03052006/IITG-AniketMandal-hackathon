"""Build the HISTORY v2 snapshot (data/history_v2/, git-ignored): the v1 history plus GDELT GKG documents for 2023-2025.

v1 (`data/history/`, `scripts/build_history_pack.py`) is left untouched so the shipped impact-v1 and its table stay reproducible. v2 copies
its four sources byte for byte and adds ``gkg-2023-25``: the filtered GKG slice (six fixed 15-minute files per UTC day, `make fetch-gkg-2023`).

Curation of the new source (deterministic, every drop counted in the manifest):
* a row is kept only if its own timestamp lies in 2023-01-01..2025-12-31 (GDELT re-crawls old pages; those carry old publisher times and
  would pollute the period, so they are dropped and counted, never moved);
* every title is resolved with the pipeline's own entity resolver first, then at most ``PER_DAY`` documents are kept per (resolved issuer, UTC date),
  chosen by content hash: episodes stay covered and the pipeline stays fast;
* documents that resolve to no issuer (market scope) are capped per day too, and several-issuer documents per issuer-group-day.

    python scripts/build_history_v2.py
    python -m eventshock.pipeline --replay-dir data/history_v2 --export data/processed/history_v2
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_history_pack import Curator, h, jsonl  # noqa: E402
from eventshock.ingestion.snapshot import atomic_write_text, sha256_file  # noqa: E402

V1 = ROOT / "data" / "history"
OUT = ROOT / "data" / "history_v2"
import os  # noqa: E402

RAW = Path(os.environ.get("EVENTSHOCK_GKG_SLICE", ROOT / "data" / "raw" / "gdelt_gkg" / "filtered_2023_25.jsonl"))  # override: smoke tests on a partial slice
SNAPSHOT_ID = "history-2015-2026-v2"
START, END = "20230101T000000Z", "20251231T235959Z"
PER_DAY = 3
UNKNOWN_PER_DAY = 3
KEEP = ("url", "title", "seendate", "domain", "language", "x_gkg_id", "x_time_origin", "x_tone", "x_orgs")


def load_rows() -> tuple[list[dict], Counter]:
    drops: Counter = Counter()
    rows = []
    for line in RAW.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        r = json.loads(line)
        if not (START <= r["seendate"] <= END):
            drops["outside_2023_2025_timestamp"] += 1
            continue
        rows.append(r)
    return rows, drops


def cap_per_day(rows: list[dict], curator: Curator) -> tuple[list[dict], dict[str, int], int, int]:
    """Resolve every title with the pipeline's own resolver, then keep the PER_DAY (UNKNOWN_PER_DAY) lowest content hashes per
    (resolved ticker | MULTI | MARKET, UTC date). Capping after resolution keeps the budget on documents the model can actually use."""
    groups: dict[tuple[str, str], list[tuple[str, dict]]] = defaultdict(list)
    for r in rows:
        ent, audit = curator.resolver.resolve(r["title"])
        key = "MARKET" if ent.is_unknown else ("MULTI" if audit.multi_entity else ent.ticker)
        groups[(key, r["seendate"][:8])].append((h(r["x_gkg_id"]), r))
    kept: list[dict] = []
    stats: Counter = Counter()
    n_known = n_unknown = 0
    for (key, _day), items in sorted(groups.items()):
        cap = UNKNOWN_PER_DAY if key == "MARKET" else PER_DAY
        items.sort(key=lambda x: x[0])
        kept += [r for _, r in items[:cap]]
        if key == "MARKET":
            n_unknown += min(cap, len(items))
        else:
            n_known += min(cap, len(items))
        stats["groups"] += 1
        stats["dropped_by_cap"] += max(0, len(items) - cap)
    return kept, dict(stats), n_known, n_unknown


def main() -> None:
    if not RAW.is_file():
        raise SystemExit(f"{RAW} is missing: run `make fetch-gkg-2023` first")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sources").mkdir(exist_ok=True)
    manifest = json.loads((V1 / "manifest.json").read_text(encoding="utf-8"))
    for src in manifest["sources"]:
        shutil.copyfile(V1 / src["file"], OUT / src["file"])
        if sha256_file(OUT / src["file"]) != src["sha256"]:
            raise SystemExit(f"copy of {src['file']} does not match its v1 hash")
    rows, drops = load_rows()
    cur = Curator()
    kept, cap_stats, n_known, n_unknown = cap_per_day(rows, cur)
    kept.sort(key=lambda r: (r["seendate"], r["url"]))
    rel = "sources/gkg_2023_25.jsonl"
    atomic_write_text(OUT / rel, jsonl(kept))
    manifest["sources"].append({
        "name": "gdelt-gkg-2023-25", "adapter": "gdelt-gkg", "source_type": "NEWS", "file": rel, "sha256": sha256_file(OUT / rel), "records": len(kept),
        "license": "GDELT terms: free reuse with citation", "attribution": "The GDELT Project, GKG 2.1 bulk files (filtered, sampled)",
        "origin_url": "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt",
        "notes": (f"Six fixed 15-minute files per UTC day, 2023-01..2025-12 (about 6% of the flow), titles only. {len(rows)} rows in window "
                  f"({dict(drops)} dropped before that), capped at {PER_DAY} per issuer-hint-day and {UNKNOWN_PER_DAY} market documents per day "
                  f"({cap_stats}); {n_known} resolve to an issuer, {n_unknown} do not. NOT committed to git.")})
    manifest["snapshot_id"] = SNAPSHOT_ID
    manifest["description"] = "History v2 for impact modelling: v1 sources plus GDELT GKG 2023-2025 (sampled). Git-ignored."
    for f in ("entities.json", "portfolio.json"):
        shutil.copyfile(V1 / f, OUT / f)
    atomic_write_text(OUT / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(f"history v2 written to {OUT}: +{len(kept)} documents ({n_known} resolved, {n_unknown} unresolved) from {len(rows)} in-window rows")
    print(f"  built {datetime.now(UTC).isoformat(timespec='seconds')}; drops {dict(drops)}; cap {cap_stats}")


if __name__ == "__main__":
    main()
