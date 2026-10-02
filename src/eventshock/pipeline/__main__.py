"""Run the ingestion pipeline over a snapshot and export its outputs for inspection.

    python -m eventshock.pipeline [--replay-dir data/replay] [--export data/processed]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config import REPO_ROOT, ConfigError, Settings
from ..ingestion.snapshot import atomic_write_text, load_snapshot
from .config import load_enrichment_config, load_pipeline_config
from .run import run_snapshot


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--replay-dir", type=Path, default=REPO_ROOT / "data" / "replay")
    ap.add_argument("--export", type=Path, default=None, help="write signals.jsonl / quarantine.json / report.json here")
    args = ap.parse_args(argv)
    settings = Settings()
    try:
        snap = load_snapshot(args.replay_dir)
        res = run_snapshot(snap, load_pipeline_config(settings.config_dir), load_enrichment_config(settings.config_dir))
    except ConfigError as exc:
        print(f"error: {exc}")
        return 2
    c = res.report.counts
    print(f"snapshot {snap.manifest.snapshot_id}: read={c.records_read} quarantined={c.quarantined} "
          f"folded={c.exact_duplicates_folded} kept={c.reports_in_signals} signals={c.signals} "
          f"(resolved={c.entity_resolved} unknown={c.entity_unknown})")
    print(f"digest {res.report.output_digest}")
    if args.export:
        dump = lambda o: json.dumps(o, indent=2, ensure_ascii=False, sort_keys=True) + "\n"  # noqa: E731
        atomic_write_text(args.export / "signals.jsonl", "".join(
            json.dumps(s.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            for s in sorted(res.signals, key=lambda s: s.id)))
        atomic_write_text(args.export / "quarantine.json", dump([q.model_dump(mode="json") for q in res.quarantined]))
        atomic_write_text(args.export / "report.json", dump(res.report.model_dump(mode="json")))
        print(f"exported to {args.export}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
