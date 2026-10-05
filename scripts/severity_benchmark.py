#!/usr/bin/env python
"""Severity benchmark: record real model outputs once, evaluate the scorecard in rule mode and on the recorded outputs, write docs/evidence/severity_benchmark.json.

    python scripts/severity_benchmark.py record [dev|heldout] [--fresh]   # LIVE: calls the configured provider once per benchmark text (needs a key); writes data/benchmarks/llm_outputs.jsonl
    python scripts/severity_benchmark.py evaluate   # no network: rules + the recorded outputs -> docs/evidence/severity_benchmark.json (also run by the tests)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eventshock.assessment import benchmark as bm  # noqa: E402
from eventshock.config import Settings  # noqa: E402
from eventshock.llm.cache import ExtractionCache  # noqa: E402
from eventshock.llm.client import CLIENTS  # noqa: E402
from eventshock.llm.prompt import PROMPT_VERSION  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "severity_benchmark.json"
PACE_SECONDS = float(os.environ.get("BENCH_PACE_SECONDS", "22"))  # the provider allows ~8,000 tokens a minute; one call is ~2,700


def write_meta(ds: bm.Dataset, model: str, provider: str, rig: bm.Rig, texts: int, *, complete: bool) -> None:
    keep = [ln for ln in ds.recorded.read_text(encoding="utf-8").splitlines() if ln.strip() and '"__meta__"' not in ln] if ds.recorded.exists() else []
    meta = {"key": "__meta__", "value": {
        "model": model, "provider": provider, "prompt_version": PROMPT_VERSION, "vocabulary_version": rig.vocab.cfg.version, "benchmark_sha256": bm.file_sha256(ds.path),
        "texts": texts, "complete": complete,
        "note": "real model outputs, recorded once; replayed by the tests with zero provider calls"
                + ("" if complete else ". INCOMPLETE: not every text was recorded (interrupted, or the provider's daily token quota ran out)")}}
    ds.recorded.write_text(json.dumps(meta) + "\n" + "\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")


def record(ds: bm.Dataset) -> int:
    s = Settings()
    rig = bm.Rig.build()
    cfg = rig.llm_cfg.for_provider(s.llm_provider or rig.llm_cfg.provider, s.llm_model)
    key = s.llm_key(cfg.provider)
    if not key:
        print(f"no {cfg.key_env} in the environment / .env: cannot record", file=sys.stderr)
        return 1
    if "--fresh" in sys.argv:
        ds.recorded.unlink(missing_ok=True)
    elif ds.recorded.exists():  # resume: keep the answers already recorded, drop only the metadata line (rewritten below)
        keep = [ln for ln in ds.recorded.read_text(encoding="utf-8").splitlines() if '"__meta__"' not in ln]
        ds.recorded.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    # a batch job can wait where a person cannot: honour the provider's Retry-After and allow several attempts (the product's own policy stays strict)
    cfg = cfg.model_copy(update={"max_retry_after_seconds": 75, "max_total_seconds": 400, "timeout_seconds": 45, "max_retries": 5, "cooldown_seconds": 0})
    client = CLIENTS[cfg.provider](key, cfg)
    rig.llm_cfg = cfg
    write_meta(ds, client.model_id, cfg.provider, rig, len(bm.load_rows(ds.path)), complete=False)  # first, so an interrupted run is still a valid partial recording
    ex = rig.extractor(client, ExtractionCache(ds.recorded, 100000))
    rows = bm.load_rows(ds.path)
    fell = 0
    for r in rows:
        t0 = time.time()
        res = bm.score_text(rig, r["text"], ex, use_llm=True)
        if not ex.stats.cache_hits and time.time() - t0 < PACE_SECONDS:  # a real call was made: pace them (provider rate limits)
            time.sleep(PACE_SECONDS - (time.time() - t0))
        fell += bool(res["fallback"])
        print(f"{r['id']:>3} {res['mode']:5} {time.time() - t0:4.1f}s  expected {r['expected_band']:10} -> {res['score']}  {res['fallback'] or ''}")
    write_meta(ds, client.model_id, cfg.provider, rig, len(rows), complete=not fell)
    print(f"recorded {len(rows)} outputs, {fell} fallbacks -> {ds.recorded}")
    return 1 if fell else 0


def evaluate() -> int:
    rig = bm.Rig.build()
    out: dict = {"severity_version": rig.scorer.version, "vocabulary_version": rig.vocab.cfg.version, "datasets": {}}
    for ds in bm.DATASETS.values():
        d: dict = {"sha256": bm.file_sha256(ds.path), "rules": bm.evaluate_rules(rig, ds)}
        if ds.recorded.exists():
            d["llm_recorded"] = bm.evaluate_recorded(rig, ds)
        out["datasets"][ds.name] = d
        for mode in ("rules", "llm_recorded"):
            if mode in d:
                r = d[mode]
                print(f"{ds.name:8} {mode:13} n={r['n']} min={r['min']} max={r['max']} mean={r['mean']} median={r['median']} p10={r['p10']} p90={r['p90']} "
                      f"spearman={r['spearman']} exact={r['exact_band']} within1={r['within_one_band']} bands={r['band_counts']} all_criteria={r['all_criteria_pass']}")
    base = ROOT / "docs" / "evidence" / "severity_baseline_v1.json"
    if base.exists():
        b = json.loads(base.read_text())
        out["baseline_v1_on_dev"] = {m: {k: b[m][k] for k in ("min", "max", "mean", "median", "p10", "p90", "band_counts", "spearman", "exact_band", "within_one")} for m in ("rules", "llm")}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "evaluate"
    if cmd == "record":
        name = next((a for a in sys.argv[2:] if a in bm.DATASETS), "dev")
        raise SystemExit(record(bm.DATASETS[name]))
    raise SystemExit(evaluate() if cmd == "evaluate" else print(__doc__) or 2)
