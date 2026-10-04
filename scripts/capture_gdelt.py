"""Capture what GDELT saw recently into a JSONL file that `make run-capture` replays offline as "simulated live".

    python scripts/capture_gdelt.py [--minutes 720] [--max 20] [--throttle 12] [--out data/live/sample_capture.jsonl]

It runs the same queries as the live feed (configs/live.yaml) through the same code (`GdeltLiveSource`), one every ``--throttle`` seconds
(GDELT asks for at most one request per 5 s and answers HTTP 429 for minutes to a client that does not comply). Metadata only (URL, title,
first-seen time, domain, language, country), no publisher text. A query that fails is reported and skipped; the file holds what succeeded.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eventshock.ingestion.live import GdeltLiveSource  # noqa: E402
from eventshock.services.live import load_live_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=int, default=720)
    ap.add_argument("--max", type=int, default=20, help="records per query")
    ap.add_argument("--throttle", type=float, default=12.0)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "live" / "sample_capture.jsonl")
    args = ap.parse_args()
    cfg = load_live_config(ROOT / "configs").source.gdelt.model_copy(
        update={"timespan_minutes": args.minutes, "maxrecords": args.max, "throttle_seconds": args.throttle})
    poll = GdeltLiveSource(cfg).poll()
    for e in poll.errors:
        print(f"skipped: {e[:200]}", file=sys.stderr)
    if not poll.records:
        print(f"no records captured ({poll.queries_failed} of {poll.queries_ok + poll.queries_failed} queries failed); nothing written", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in poll.records) + "\n", encoding="utf-8")
    print(f"wrote {len(poll.records)} records from {poll.queries_ok} queries to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
