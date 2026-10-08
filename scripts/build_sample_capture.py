"""Build the committed offline "simulated live" stream, `data/live/sample_capture.jsonl`, from the replay pack. No network.

    python scripts/build_sample_capture.py [--check]

The pack's GDELT file (hash-pinned in `data/replay/manifest.json`) holds real articles up to 2026-10-01. The replay run stops at
`window_end` (2026-09-30), so the articles first seen on 2026-10-01 are in no REPLAY signal: played through the live engine they arrive
as new signals, not duplicates. They keep their true GDELT first-seen times (nothing is re-dated). Output = those records, one GDELT DOC
line each (the capture format `CaptureSource` reads), de-duplicated by URL, oldest first, without the pack's `x_query` bookkeeping field.

`--check` rebuilds in memory and fails if the committed file differs, so the file can only be what this derivation produces.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data" / "replay" / "gdelt" / "articles.jsonl"
OUT = ROOT / "data" / "live" / "sample_capture.jsonl"
FIRST_SEEN_FROM = "20261001T000000Z"  # the day after the replay window (window_end 2026-09-30)
DROP = {"x_query"}


def build() -> str:
    rows: dict[str, dict] = {}
    for n, line in enumerate(PACK.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError as exc:
            raise SystemExit(f"{PACK} line {n}: not JSON ({exc})") from exc
        if rec.get("seendate", "") >= FIRST_SEEN_FROM and rec.get("url"):
            rows.setdefault(rec["url"], {k: v for k, v in rec.items() if k not in DROP})
    if not rows:
        raise SystemExit(f"no articles first seen on or after {FIRST_SEEN_FROM} in {PACK}")
    ordered = sorted(rows.values(), key=lambda r: (r["seendate"], r["url"]))
    return "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in ordered) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the committed file is not what the pack produces")
    args = ap.parse_args()
    text = build()
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} is missing or differs from the replay pack's derivation: run `make capture-from-replay`", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} matches the replay pack ({text.count(chr(10))} records)")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {text.count(chr(10))} records to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
