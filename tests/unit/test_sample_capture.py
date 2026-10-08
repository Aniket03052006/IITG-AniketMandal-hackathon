"""The committed offline "simulated live" stream is exactly what the hash-pinned replay pack produces: real records, true times, no network."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from eventshock.config import REPO_ROOT
from eventshock.ingestion.live import CaptureSource, CaptureSourceConfig
from eventshock.services.live import load_live_config

SCRIPT = REPO_ROOT / "scripts" / "build_sample_capture.py"
CAPTURE = REPO_ROOT / "data" / "live" / "sample_capture.jsonl"


def _script():
    spec = importlib.util.spec_from_file_location("build_sample_capture", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_committed_capture_is_exactly_the_replay_packs_derivation() -> None:
    assert CAPTURE.read_text(encoding="utf-8") == _script().build()


def test_it_holds_only_articles_first_seen_after_the_replay_window_with_their_true_times() -> None:
    rows = [json.loads(ln) for ln in CAPTURE.read_text(encoding="utf-8").splitlines()]
    pack = {r["url"]: r for r in (json.loads(ln) for ln in (REPO_ROOT / "data/replay/gdelt/articles.jsonl").read_text(encoding="utf-8").splitlines())}
    assert len(rows) >= 100 and len({r["url"] for r in rows}) == len(rows)
    assert [r["seendate"] for r in rows] == sorted(r["seendate"] for r in rows)
    manifest = json.loads((REPO_ROOT / "data/replay/manifest.json").read_text(encoding="utf-8"))
    window_end = manifest["window_end"][:10].replace("-", "")
    assert all(r["seendate"][:8] > window_end for r in rows)  # none can already be a REPLAY signal
    assert all(pack[r["url"]]["seendate"] == r["seendate"] and "x_query" not in r for r in rows)  # nothing re-dated, no bookkeeping field


def test_the_capture_source_reads_it_in_batches_to_the_end() -> None:
    cfg = load_live_config(REPO_ROOT / "configs").source.capture
    src = CaptureSource(CaptureSourceConfig(path=CAPTURE, batch_size=cfg.batch_size, interval_seconds=cfg.interval_seconds), base=REPO_ROOT)
    total, polls = 0, 0
    while True:
        poll = src.poll()
        total += len(poll.records)
        polls += 1
        if poll.exhausted:
            break
        assert polls < 100
    assert total == len(CAPTURE.read_text(encoding="utf-8").splitlines())


def test_the_config_points_at_the_committed_file() -> None:
    cfg = load_live_config(REPO_ROOT / "configs")
    assert (REPO_ROOT / Path(cfg.source.capture.path)).resolve() == CAPTURE.resolve()
