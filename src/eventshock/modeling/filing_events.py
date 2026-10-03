"""Track F: the filing-anchored event table. An 8-K is an event with an official type (its item codes) and an exact clock (SEC acceptance time).

Why it exists: the news layer cannot say what a report *is* without a text model, and its clocks are noisy. A filing is the cleanest event we can get for
free: the type is chosen by the filer to match a legal trigger, the time is the SEC's own acceptance time, and the 34 issuers file hundreds of them across
2014-2026, including 2023-2025 where we have no other event source. Two uses:

* an **event study**: |z| around a filing versus a matched quiet session of the same issuer and volatility bucket (does an event move prices more than a
  non-event of the same regime?), by item type and by period;
* a **test bed for event-specific skill**: given state, calendar and the filing's own item codes (published at event time: the report *is* the filing),
  does knowing the event type predict how large the reaction is?

One row per (issuer, reaction session) episode. Controls are sessions with no 8-K event within ``exclusion_sessions`` sessions, matched one to one on issuer
and volatility bucket (``impact_regime.match_controls``). Targets, state features and anchoring are exactly the impact-table functions.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..pipeline.event_context import EventCalendar, filing_events, session_dates
from ..pipeline.impact_features import ISSUER, TIMING, state_features
from ..pipeline.market_context import quantize, timing_flags
from .config import load_modeling_config
from .impact_regime import bucket_edges, bucketize, match_controls
from .market import PriceStore, file_stem
from .splits import impact_split
from .study_config import load_study_config

ITEM_FLAGS = ["item_earnings", "item_deal", "item_distress", "item_financing", "item_leadership", "item_other"]
CONTROL_STRIDE = 3  # every third eligible session is a control candidate (deterministic thinning: features_asof per session is the cost)
MIN_SESSION = 125   # beyond the 120-session history rule plus slack


def _flags(items: set[str], groups: dict[str, frozenset[str]], exhibit_only: frozenset[str]) -> dict[str, float]:
    named = {f"item_{g}": float(bool(items & grp)) for g, grp in groups.items()}
    other = items - exhibit_only - set().union(*groups.values())
    return {**named, "item_other": float(bool(other))}


def _row(kind: str, ticker: str, sector: str | None, t: datetime, s0: int, timing: str, store: PriceStore, calendar: EventCalendar,
         protocols: dict[str, Any], items: list[str], flags: dict[str, float], tgt, placebo, feats) -> dict[str, Any]:
    d0, d1 = session_dates(store.dates, s0)
    cal = calendar.issuer_features(ticker, t, d0, d1)
    local = t.astimezone(store.tz)
    row: dict[str, Any] = {
        "id": f"{'F' if kind == 'event' else 'C'}:{ticker}:{store.dates[s0]}", "kind": kind, "scope": ISSUER, "ticker": ticker, "sector": sector,
        "episode": f"{ticker}|{store.dates[s0]}", "s0": s0, "s0_date": store.dates[s0], "timing": timing, "published_at": t.isoformat(),
        "origin": "SOURCE", "adapter": "sec-8k" if kind == "event" else "control", "source_type": "FILING", "items": sorted(items),
        "event_top": "NONE", "event_status": "NONE", "weight": 1.0, "dow": float(local.weekday()), "local_hour": local.hour + local.minute / 60,
        "z": tgt.z, "abs_z": tgt.abs_z, "score": tgt.score, "placebo_abs_z": placebo.abs_z if placebo else None, "car": tgt.car,
        "factor_model": tgt.fit.factor_model, **state_features(ISSUER, feats), **timing_flags(timing), **cal, **flags,
        **{f"split_{n}": impact_split(s0, store.dates, c) for n, c in protocols.items()}}
    return {k: (quantize(v) if isinstance(v, float) else v) for k, v in row.items()}


def build_filing_table(*, repo_root: Path, config_dir: Path, out_table: Path, out_manifest: Path) -> dict[str, Any]:
    scfg, study_sha = load_study_config(config_dir)
    mcfg = load_modeling_config(config_dir)
    protocols = {n: scfg.protocol(n).split_config() for n in ("P1_legacy", "P2_extended")}
    sf = scfg.structured_features
    items_path = repo_root / scfg.data["sec_items"]
    calendar = EventCalendar.load(repo_root / scfg.data["calendar_dir"], items_path, recent_hours=float(sf["recent_filing_hours"]),
                                  earnings_lookback_years=int(sf["earnings_lookback_years"]))
    items_cfg = yaml.safe_load(items_path.read_text(encoding="utf-8"))
    groups = {g: frozenset(v) for g, v in items_cfg["groups"].items()}
    exhibit_only = frozenset(items_cfg.get("exhibit_only_items", ["9.01"]))
    ents = repo_root / "data" / "history_v2" / "entities.json"
    ents = ents if ents.is_file() else repo_root / "data" / "history" / "entities.json"
    sectors = {e["ticker"]: e["sector"] for e in json.loads(ents.read_text(encoding="utf-8")) if e.get("ticker")}
    prices = repo_root / "data" / "raw" / "prices"
    symbols = [*sectors, mcfg.impact.market_symbol, mcfg.impact.volatility_symbol]
    for s in symbols:
        if not (prices / f"{file_stem(s)}.csv").is_file():
            raise ConfigError(f"missing prices for {s}: run `make fetch-prices`")
    store = PriceStore.from_dir(prices, symbols, sectors, mcfg.impact)
    battery = scfg.impact.battery
    exclusion = int(battery.control["exclusion_sessions"])
    max_dist = int(battery.control["max_distance_sessions"])
    drops: Counter = Counter()

    # ---- events: filings -> episodes (several filings in one reaction session are one episode, items united)
    episodes: dict[tuple[str, int], dict[str, Any]] = {}
    for ticker in sorted(sectors):
        if not calendar.has_issuer(ticker):
            continue
        for f in filing_events(calendar, ticker):
            s0, timing = store.anchor(f.acceptance, "SOURCE")
            if s0 is None:
                drops["BEYOND_PRICES"] += 1
                continue
            e = episodes.setdefault((ticker, s0), {"t": f.acceptance, "timing": timing, "items": set(), "accessions": []})
            e["items"] |= set(f.items)
            e["accessions"].append(f.accession)
    event_rows: list[dict[str, Any]] = []
    for (ticker, s0), e in sorted(episodes.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        tgt, why = store.target(ticker, s0)
        if tgt is None:
            drops[why] += 1
            continue
        feats = store.features_asof(ticker, s0)
        if feats is None:
            drops["INSUFFICIENT_HISTORY"] += 1
            continue
        placebo, _ = store.target(ticker, s0 + mcfg.impact.placebo_offset_sessions)
        r = _row("event", ticker, sectors.get(ticker), e["t"], s0, e["timing"], store, calendar, protocols, sorted(e["items"]),
                 _flags(e["items"], groups, exhibit_only), tgt, placebo, feats)
        r["accessions"] = sorted(e["accessions"])
        event_rows.append(r)

    # ---- controls: quiet sessions of the same issuers (no event within +-exclusion sessions), thinned deterministically
    event_sessions: dict[str, list[int]] = defaultdict(list)
    for (ticker, s0) in episodes:
        event_sessions[ticker].append(s0)
    pool_rows: list[dict[str, Any]] = []
    for ticker in sorted({r["ticker"] for r in event_rows}):
        ev = np.array(sorted(event_sessions[ticker]))
        for s0 in range(MIN_SESSION, len(store.dates) - 3):
            if s0 % CONTROL_STRIDE:
                continue
            if len(ev) and np.abs(ev - s0).min() <= exclusion:
                drops["CONTROL_NEAR_EVENT"] += 1
                continue
            tgt, why = store.target(ticker, s0)
            feats = store.features_asof(ticker, s0)
            if tgt is None or feats is None:
                drops[f"CONTROL_{why or 'INSUFFICIENT_HISTORY'}"] += 1
                continue
            placebo, _ = store.target(ticker, s0 + mcfg.impact.placebo_offset_sessions)
            local_open = datetime.fromisoformat(store.dates[s0]).replace(hour=8, tzinfo=store.tz).astimezone(UTC)  # a pre-open clock for the session
            pool_rows.append(_row("control", ticker, sectors.get(ticker), local_open, s0, "PRE_OPEN", store, calendar, protocols, [],
                                  _flags(set(), groups, exhibit_only), tgt, placebo, feats))

    # ---- volatility buckets from the P2 training period only, then one-to-one matching
    train_end = protocols["P2_extended"].train_end.isoformat()
    ref = np.array([r["f_resid_vol_20d_ratio"] if r["f_resid_vol_20d_ratio"] is not None else np.nan
                    for r in (*event_rows, *pool_rows) if r["s0_date"] <= train_end], dtype=float)
    edges = bucket_edges(ref, battery.vol_buckets)
    for r in (*event_rows, *pool_rows):
        v = r["f_resid_vol_20d_ratio"]
        r["vol_bucket"] = int(bucketize(np.array([np.nan if v is None else v]), edges)[0])
    pairs = match_controls([{"ticker": r["ticker"], "s0": r["s0"], "bucket": r["vol_bucket"]} for r in event_rows],
                           [{"ticker": r["ticker"], "s0": r["s0"], "bucket": r["vol_bucket"]} for r in pool_rows], max_distance=max_dist)
    matched_events = {i for i, _ in pairs}
    for k, (i, j) in enumerate(pairs):
        event_rows[i]["pair_id"] = k
        pool_rows[j]["pair_id"] = k
    for i, r in enumerate(event_rows):
        r.setdefault("pair_id", None)
        if i not in matched_events:
            drops["EVENT_WITHOUT_CONTROL"] += 1
    used = {j for _, j in pairs}
    controls = [r for j, r in enumerate(pool_rows) if j in used]
    final = sorted([*event_rows, *controls], key=lambda r: (r["s0"], r["ticker"], r["kind"]))
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=True) for r in final]
    atomic_write_text(out_table, "\n".join(lines) + "\n")

    def by(key) -> dict[str, int]:
        return dict(sorted(Counter(key(r) for r in event_rows).items()))

    ev_manifest = json.loads((repo_root / scfg.data["calendar_dir"] / "manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "table": str(out_table.relative_to(repo_root)) if out_table.is_relative_to(repo_root) else str(out_table), "table_sha256": sha256_file(out_table),
        "rows": len(final), "event_episodes": len(event_rows), "matched_pairs": len(pairs), "controls": len(controls),
        "preregistration": {"file": "configs/evidence_v2.yaml", "sha256": study_sha},
        "inputs": {"calendar": {k: v["sha256"] for k, v in ev_manifest["sources"].items()}, "sec_items_sha256": sha256_file(items_path),
                   "price_files_sha256": {s: hashlib.sha256((prices / f"{file_stem(s)}.csv").read_bytes()).hexdigest() for s in sorted(symbols)},
                   "modeling_config_digest": mcfg.digest()},
        "control_rule": {"exclusion_sessions": exclusion, "max_distance_sessions": max_dist, "stride": CONTROL_STRIDE, "vol_buckets": battery.vol_buckets,
                         "bucket_edges_f_resid_vol_20d_ratio": [round(float(x), 6) for x in edges], "edges_from": f"events and candidates up to {train_end}"},
        "events_by_year": by(lambda r: r["s0_date"][:4]), "events_by_timing": by(lambda r: r["timing"]),
        "events_by_item_group": dict(sorted(Counter(k for r in event_rows for k in ITEM_FLAGS if r.get(k)).items())),
        "events_by_protocol_split": {n: by(lambda r, n=n: r[f"split_{n}"]) for n in protocols},
        "exclusions": dict(sorted(drops.items())),
        "note": "A filing accepted during the session (IN_SESSION) is contaminated (part of the move precedes it) and is analysed separately; "
                "controls carry a pre-open clock on their session.",
    }
    atomic_write_text(out_manifest, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


__all__ = ["ITEM_FLAGS", "TIMING", "build_filing_table"]
