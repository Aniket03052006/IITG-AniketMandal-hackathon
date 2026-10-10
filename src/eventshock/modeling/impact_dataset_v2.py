"""The v2 impact modeling table: the v1 construction, over history v2 (adds 2023-2025 news), with structured-calendar features and one split column per protocol.

Composition, not a fork: document eligibility, targets, price-state features, text-model features and every exclusion reason are the v1 functions
(``impact_dataset``, ``market``), so a v2 row equals its v1 row wherever both exist (``test_impact_dataset_v2`` pins that, and the study repeats it as a
regression gate). What v2 adds:

* ``split_<protocol>`` for each pre-registered protocol (P1 legacy = impact-v1's boundaries, P2 extended); a row is kept if any protocol uses it;
* the calendar block of ``pipeline.event_context`` (availability classes a and b) computed from filings accepted strictly before the report;
* a manifest that pins the calendar tables, the history snapshot, the pre-registration file and every input hash, and counts rows by year and source.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..pipeline.config import load_event_model_config, load_impact_model_config, load_sentiment_model_config
from ..pipeline.event_context import EventCalendar, session_dates
from ..pipeline.event_model import EventModel
from ..pipeline.impact_features import ISSUER, MARKET
from ..pipeline.impact_features_v2 import ALL_FEATURES_V2, FEATURE_SCHEMA_V2
from ..pipeline.market_context import quantize
from ..pipeline.sentiment_model import SentimentModel
from .config import load_modeling_config
from .corpora import iter_history_docs
from .impact_dataset import HORIZONS, KEEP_SPLITS, _assemble, _text_columns
from .leakage import (
    Finding,
    calendar_future_invariance,
    check_features,
    future_invariance,
    group_straddle,
    market_future_invariance,
    require_clean,
    time_order,
)
from .market import PriceStore, file_stem, impact_rows, market_rows
from .splits import impact_split
from .study_config import load_study_config


def build_dataset_v2(*, repo_root: Path, config_dir: Path, history_signals: Path, out_table: Path, out_manifest: Path) -> dict[str, Any]:
    scfg, study_sha = load_study_config(config_dir)
    mcfg = load_modeling_config(config_dir)
    icfg = load_impact_model_config(config_dir)
    prices = repo_root / "data" / "raw" / "prices"
    for p in (history_signals, prices / "_GSPC.csv", prices / f"{file_stem(icfg.rates_symbol)}.csv"):
        if not p.is_file():
            raise ConfigError(f"missing input {p}: see docs/notes/EVIDENCE_V2.md (`make fetch-prices`, `make ingest-history-v2`)")
    events_dir = repo_root / scfg.data["calendar_dir"]
    sf = scfg.structured_features
    calendar = EventCalendar.load(events_dir, repo_root / scfg.data["sec_items"], recent_hours=float(sf["recent_filing_hours"]),
                                  earnings_lookback_years=int(sf["earnings_lookback_years"]))
    protocols = {name: scfg.protocol(name).split_config() for name in ("P1_legacy", "P2_extended")}

    sent_dir = Path(load_sentiment_model_config(config_dir).model_dir)
    event_dir = Path(load_event_model_config(config_dir).model_dir)
    sentiment = SentimentModel.load(sent_dir if sent_dir.is_absolute() else repo_root / sent_dir)
    event = EventModel.load(event_dir if event_dir.is_absolute() else repo_root / event_dir)

    docs_list = list(iter_history_docs(history_signals))
    docs = {d.id: d for d in docs_list}
    ents_path = repo_root / "data" / "history_v2" / "entities.json"
    if not ents_path.is_file():
        ents_path = repo_root / "data" / "history" / "entities.json"
    sectors = {e["ticker"]: e["sector"] for e in json.loads(ents_path.read_text(encoding="utf-8")) if e.get("ticker")}
    symbols = [*sectors, mcfg.impact.market_symbol, mcfg.impact.volatility_symbol, icfg.rates_symbol]
    store = PriceStore.from_dir(prices, symbols, sectors, mcfg.impact)
    rules = store.session_rules()

    from ..domain import UNKNOWN_ENTITY

    unknown = [d for d in docs_list if d.entity_id == UNKNOWN_ENTITY]
    iss_rows, iss_drops = impact_rows(docs_list, store, mcfg.impact)
    mkt_rows, mkt_drops = market_rows(unknown, store, mcfg.impact, icfg.rates_symbol)
    exclusions: dict[str, dict[str, int]] = {ISSUER: dict(iss_drops), MARKET: {k: v for k, v in mkt_drops.items() if k != "HAS_ISSUER"}}
    for scope, rs in ((ISSUER, iss_rows), (MARKET, mkt_rows)):
        for r in rs:
            for name, cfg in protocols.items():
                r[f"split_{name}"] = impact_split(r["s0"], store.dates, cfg)
            r["split"] = r["split_P1_legacy"]
        for name in protocols:
            for kind in ("embargo", "gap"):
                n = sum(1 for r in rs if r[f"split_{name}"] == kind)
                if n:
                    exclusions[scope][f"SPLIT_{kind.upper()}[{name}]"] = n
    keep = lambda r: any(r[f"split_{n}"] in KEEP_SPLITS for n in protocols)  # noqa: E731
    iss_keep, mkt_keep = [r for r in iss_rows if keep(r)], [r for r in mkt_rows if keep(r)]
    ids = sorted({r["id"] for r in (*iss_keep, *mkt_keep)})
    text, text_excl = _text_columns(docs, ids, sentiment, event)
    for scope, rs in ((ISSUER, iss_keep), (MARKET, mkt_keep)):
        lost = sum(1 for r in rs if r["id"] not in text)
        if lost:
            exclusions[scope]["TEXT_STAGE (unscorable or seen by a text model)"] = lost
    alt = {w: PriceStore(store.dates, store.close, store.volume, store.sectors, mcfg.impact.model_copy(update={"window_sessions": w}))
           for w in HORIZONS}
    final: list[dict] = []
    for scope, rs in ((ISSUER, iss_keep), (MARKET, mkt_keep)):
        by_id = {r["id"]: r for r in rs}
        for row in _assemble(rs, scope, docs, text, rules, sectors, store, alt):
            src = by_id[row["id"]]
            t = datetime.fromisoformat(row["published_at"])
            d0, d1 = session_dates(store.dates, row["s0"])
            cal = (calendar.issuer_features(row["ticker"], t, d0, d1) if scope == ISSUER else calendar.market_features(d0, d1))
            row.update({k: quantize(v) for k, v in cal.items()})
            row.update({f"split_{n}": src[f"split_{n}"] for n in protocols})
            row["split"] = src["split_P1_legacy"]
            final.append(row)
    final.sort(key=lambda r: (r["scope"], r["s0"], r["id"]))

    # ---- leakage gates (fatal): per protocol, plus the calendar and price future-invariance checks
    findings: list[Finding] = []
    for scope in (ISSUER, MARKET):
        part = [r for r in final if r["scope"] == scope]
        for name, cfg in protocols.items():
            pseudo = [{"split": r[f"split_{name}"], "episode": r["episode"], "s0": r["s0"]} for r in part]
            findings += [Finding(f.check + f"[{name}]", f.severity, f.detail) for f in group_straddle(pseudo, "episode")]
            findings += [Finding(f.check + f"[{name}]", f.severity, f.detail) for f in time_order(pseudo, store.dates, cfg.embargo_sessions)]
    probe = sorted({(r["ticker"], r["s0"]) for r in final if r["scope"] == ISSUER})
    findings += future_invariance(store, probe[:: max(1, len(probe) // 40)][:40])
    probe_m = sorted({r["s0"] for r in final if r["scope"] == MARKET})
    findings += market_future_invariance(store, probe_m[:: max(1, len(probe_m) // 40)][:40], icfg.rates_symbol)
    sample = [r for r in final if r["scope"] == ISSUER]
    sample = sample[:: max(1, len(sample) // 60)][:60]
    cal_events = [(r["ticker"], datetime.fromisoformat(r["published_at"]), *session_dates(store.dates, r["s0"])) for r in sample]
    msample = [r for r in final if r["scope"] == MARKET]
    msample = msample[:: max(1, len(msample) // 20)][:20]
    cal_events += [(None, datetime.fromisoformat(r["published_at"]), *session_dates(store.dates, r["s0"])) for r in msample]
    findings += calendar_future_invariance(calendar, cal_events)
    findings += check_features(ALL_FEATURES_V2)
    require_clean(findings)

    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=True) for r in final]
    atomic_write_text(out_table, "\n".join(lines) + "\n")

    def count(scope: str, key) -> dict[str, int]:
        return dict(sorted(Counter(key(r) for r in final if r["scope"] == scope).items()))

    def eps(scope: str, name: str, sp: str) -> int:
        return len({r["episode"] for r in final if r["scope"] == scope and r[f"split_{name}"] == sp})

    events_manifest = json.loads((events_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest: dict[str, Any] = {
        "table": str(out_table.relative_to(repo_root)) if out_table.is_relative_to(repo_root) else str(out_table),
        "table_sha256": sha256_file(out_table), "rows": len(final), "feature_schema": FEATURE_SCHEMA_V2,
        "preregistration": {"file": "configs/evidence_v2.yaml", "sha256": study_sha},
        "target": "z / abs_z / score of configs/modeling.yaml (ISSUER: market+sector abnormal return; MARKET: S&P 500 excess return)",
        "inputs": {
            "history_signals": {"file": str(history_signals.relative_to(repo_root)) if history_signals.is_relative_to(repo_root) else history_signals.name,
                                "sha256": sha256_file(history_signals), "documents": len(docs_list)},
            "price_files_sha256": {s: hashlib.sha256((prices / f"{file_stem(s)}.csv").read_bytes()).hexdigest() for s in sorted(symbols)},
            "price_calendar": [store.dates[0], store.dates[-1], len(store.dates)],
            "sentiment_model": {"id": sentiment.model_id, "sha256": sentiment.artifact_sha256},
            "event_model": {"id": event.model_id, "sha256": event.artifact_sha256},
            "modeling_config_digest": mcfg.digest(),
            "impact_model_config_sha256": sha256_file(config_dir / "impact_model.yaml"),
            "calendar": {k: v["sha256"] for k, v in events_manifest["sources"].items()},
            "sec_items_sha256": sha256_file(repo_root / scfg.data["sec_items"]),
        },
        "protocols": {n: c.model_dump(mode="json") for n, c in protocols.items()},
        "by_scope_protocol_split_rows": {s: {n: count(s, lambda r, n=n: r[f"split_{n}"]) for n in protocols} for s in (ISSUER, MARKET)},
        "by_scope_protocol_split_episodes": {s: {n: {sp: eps(s, n, sp) for sp in KEEP_SPLITS} for n in protocols} for s in (ISSUER, MARKET)},
        "by_scope_year": {s: count(s, lambda r: r["s0_date"][:4]) for s in (ISSUER, MARKET)},
        "by_scope_source": {s: count(s, lambda r: r["adapter"]) for s in (ISSUER, MARKET)},
        "by_scope_timing": {s: count(s, lambda r: r["timing"]) for s in (ISSUER, MARKET)},
        "by_scope_event_status": {s: count(s, lambda r: r["event_status"]) for s in (ISSUER, MARKET)},
        "exclusions": {s: dict(sorted(v.items())) for s, v in exclusions.items()},
        "text_stage_exclusions": dict(sorted(text_excl.items())),
        "seeds": {"impact_model": icfg.seed, "study": scfg.seed},
        "leakage_findings": [{"check": f.check, "severity": f.severity, "detail": f.detail} for f in findings],
    }
    atomic_write_text(out_manifest, json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return manifest


__all__ = ["build_dataset_v2"]
