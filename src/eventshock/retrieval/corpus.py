"""The analogue corpus: one row per past news report (issuer scope: one per ticker-session episode) with its realised ``outcome-v3`` move.

Built from the v2 impact table (documents, clocks, splits) and the local prices (the outcome, recomputed with ``outcome_v3``; only derived numbers are
kept). Rows carry ``available_from``: the first session date on which the analogue may be used by a query, ``s0 + window + embargo`` sessions after its
own reaction session, so that no analogue's outcome window can overlap or precede the query's own (``configs/evidence_v3.yaml: retrieval.point_in_time``).

``clock`` is TRUSTED only for an exact publisher timestamp that falls before the open or after the close, so the whole reaction window follows the report;
the Stage 8 audit showed the other clocks carry no more outcome signal than the placebo window. Only TRUSTED rows are served as analogues with outcomes;
the rest are kept for use as queries in the experiments.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..modeling.evidence_v3 import load_evidence_v3
from ..modeling.outcome_audit import build_store
from ..modeling.outcome_v3 import VERSION as ISSUER_OUTCOME
from ..modeling.outcome_v3 import outcome_v3

SCHEMA = "analogue-corpus-v1"
TRUSTED_TIMINGS = ("PRE_OPEN", "OFF_HOURS")
MARKET_OUTCOME = "outcome-v2-market"


def clock_of(origin: str, timing: str) -> str:
    return "TRUSTED" if origin == "SOURCE" and timing in TRUSTED_TIMINGS else "WEAK"


def _pick_rows(table: Path) -> list[dict[str, Any]]:
    """News documents of both scopes. ISSUER: the earliest news report of each ticker-session episode. MARKET: every news document (they share a session outcome)."""
    best: dict[str, dict[str, Any]] = {}
    market: list[dict[str, Any]] = []
    with table.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("is_news") != 1.0:
                continue
            if r["scope"] == "ISSUER":
                cur = best.get(r["episode"])
                if cur is None or (r["published_at"], r["id"]) < (cur["published_at"], cur["id"]):
                    best[r["episode"]] = r
            else:
                market.append(r)
    return sorted(best.values(), key=lambda r: (r["s0"], r["ticker"])) + sorted(market, key=lambda r: (r["s0"], r["published_at"], r["id"]))


def build_corpus(repo_root: Path, config_dir: Path, out_dir: Path, *, log=print) -> dict[str, Any]:
    pre, pre_sha = load_evidence_v3(config_dir)
    rcfg = pre["retrieval"]
    table = repo_root / pre["data"]["impact_table"]
    if not table.is_file():
        raise ConfigError(f"missing {table}: `make impact-table-v2`")
    store = build_store(repo_root, config_dir)
    pit = rcfg["point_in_time"]
    window, embargo = int(pit["window_sessions"]), int(pit["embargo_sessions"])
    split_col = pre["split_column"]
    rows, dropped, out = _pick_rows(table), Counter(), []
    for r in rows:
        s0 = int(r["s0"])
        if r["scope"] == "ISSUER":
            o, why = outcome_v3(store, r["ticker"], s0)
            if o is None:
                dropped[why] += 1
                continue
            outcome = {"car": o.car, "z": o.z, "abs_z": o.abs_z, "sigma": o.sigma_ewma, "outcome_version": ISSUER_OUTCOME}
            vix = r.get("f_vix_level")
        else:
            t, why = store.market_target(s0)
            if t is None:
                dropped[why] += 1
                continue
            outcome = {"car": t.car, "z": t.z, "abs_z": t.abs_z, "sigma": t.sigma, "outcome_version": MARKET_OUTCOME}
            vix = r.get("m_vix_level")
        avail = min(s0 + window + embargo, len(store.dates) - 1)
        out.append({
            "id": r["id"], "episode": r["episode"], "scope": r["scope"], "ticker": r.get("ticker"), "sector": r.get("sector"), "s0": s0, "s0_date": r["s0_date"],
            "published_at": r["published_at"], "timing": r["timing"], "origin": r["origin"], "clock": clock_of(r["origin"], r["timing"]),
            "available_from": store.dates[avail], "text": r["text"], "adapter": r["adapter"], "split": r.get(split_col), "event_top": r.get("event_top"),
            "vix_level": vix, **outcome})
    out_dir.mkdir(parents=True, exist_ok=True)
    corpus_path, texts_path = out_dir / "analogue_corpus.jsonl", out_dir / "analogue_texts.jsonl"
    atomic_write_text(corpus_path, "".join(json.dumps(x, sort_keys=True, allow_nan=False) + "\n" for x in out))
    atomic_write_text(texts_path, "".join(json.dumps({"text": t}) + "\n" for t in dict.fromkeys(x["text"] for x in out)))
    by: dict[str, Counter] = defaultdict(Counter)
    for x in out:
        by["scope"][x["scope"]] += 1
        by["clock"][f"{x['scope']}:{x['clock']}"] += 1
        by["year"][x["s0_date"][:4]] += 1
        by["split"][str(x["split"])] += 1
    manifest = {"schema": SCHEMA, "preregistration_sha256": pre_sha, "impact_table_sha256": sha256_file(table), "rows": len(out), "dropped_no_outcome": dict(dropped),
                "unique_texts": len(dict.fromkeys(x["text"] for x in out)), "point_in_time": {"window_sessions": window, "embargo_sessions": embargo},
                "trusted_timings": list(TRUSTED_TIMINGS), "counts": {k: dict(sorted(v.items())) for k, v in by.items()}, "corpus_sha256": sha256_file(corpus_path)}
    atomic_write_text(out_dir / "analogue_corpus.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    log(f"corpus: {len(out)} rows, {manifest['unique_texts']} unique texts; trusted {sum(v for k, v in by['clock'].items() if k.endswith('TRUSTED'))}; dropped {dict(dropped)}")
    return manifest


def load_corpus(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ConfigError(f"missing {path}: `make analogue-corpus`")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
