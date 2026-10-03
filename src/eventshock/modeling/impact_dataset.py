"""The impact modeling table: one row per (document, scope) with its point-in-time features and its realised outcome.

Row = a history document that the served pipeline could also score (it is scorable by both text models, and its issuer is either
resolved cleanly -> ISSUER scope, or unresolved -> MARKET scope). Features are exactly ``pipeline.impact_features`` and are built
by the same functions as at serving time: price state from ``PriceStore`` (sessions strictly before ``s0``), timing from the
timestamp, and the *served* sentiment/event models' output for the text (``decide_many`` / ``predict_many``: same rounding,
same code). The table carries no placeholder class, no ticker, no source id as a feature.

Nothing is dropped silently: every document that does not become a row is counted under a reason in the manifest, and
the manifest records the hashes of everything that went in, so another run with the same inputs gives a byte-identical table.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..pipeline.config import (
    ImpactModelConfig,
    load_event_model_config,
    load_impact_model_config,
    load_sentiment_model_config,
)
from ..pipeline.event_model import EventModel
from ..pipeline.impact_features import (
    FEATURE_SCHEMA,
    ISSUER,
    MARKET,
    doc_features,
    state_features,
    text_features,
)
from ..pipeline.market_context import quantize
from ..pipeline.sentiment_model import SentimentModel
from .config import ModelingConfig, load_modeling_config
from .corpora import HistoryDoc, iter_history_docs
from .leakage import (
    Finding,
    check_features,
    future_invariance,
    group_straddle,
    market_future_invariance,
    require_clean,
    time_order,
)
from .market import PriceStore, file_stem, impact_rows, market_rows
from .splits import assign_impact_splits

CHUNK = 4000
KEEP_SPLITS = ("train", "val", "test", "live")


def _sha(path: Path) -> str:
    return sha256_file(path)


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _text_columns(docs: dict[str, HistoryDoc], ids: list[str], sentiment: SentimentModel, event: EventModel
                  ) -> tuple[dict[str, dict[str, Any]], Counter]:
    """Frozen text-model features per id, and the exclusions the text stage itself causes."""
    out: dict[str, dict[str, Any]] = {}
    excluded: Counter = Counter()
    for chunk in _chunks(ids, CHUNK):
        texts = [docs[i].scored_text for i in chunk]
        bad_s, bad_e = sentiment.unscorable_reasons(texts), event.unscorable_reasons(texts)
        keep = [(i, t) for i, t, a, b in zip(chunk, texts, bad_s, bad_e, strict=True) if not a and not b]
        excluded["UNSCORABLE_TEXT"] += len(chunk) - len(keep)
        if not keep:
            continue
        kt = [t for _, t in keep]
        decisions, sents = event.decide_many(kt), sentiment.predict_many(kt)
        for (i, _t), d, s in zip(keep, decisions, sents, strict=True):
            if d.seen_in_training or s.seen_in_training:
                excluded["SEEN_BY_TEXT_MODEL"] += 1  # a text model that trained on this document has seen it: its output is not event-time-like
                continue
            tf = text_features(d.probabilities, d.no_event_probability, s.positive, s.negative)
            out[i] = {**tf, "event_top": d.category.value, "event_status": d.status.value}
    return out, excluded


HORIZONS = (1, 3)  # alternative target windows (sessions) for the sensitivity check; the target itself stays configs/modeling.yaml


def _alt_targets(store: PriceStore, alt: dict[int, PriceStore], scope: str, r: dict) -> dict[str, float | None]:
    """|z| over a 1- and a 3-session window for the same event (a sensitivity check, never a training target)."""
    out: dict[str, float | None] = {}
    for w, st in alt.items():
        if scope == ISSUER:
            t, _ = st.target(r["ticker"], r["s0"])
        else:
            t, _ = st.market_target(r["s0"])
        out[f"abs_z_w{w}"] = t.abs_z if t else None
    return out


def _assemble(rows: list[dict], scope: str, docs: dict[str, HistoryDoc], text: dict[str, dict[str, Any]], rules,
              sector_of: dict[str, str], store: PriceStore, alt: dict[int, PriceStore]) -> list[dict]:
    out = []
    for r in rows:
        if r["id"] not in text:
            continue
        d = docs[r["id"]]
        raw_state = {k[2:]: v for k, v in r.items() if k.startswith(("f_", "m_"))}
        feats = {**state_features(scope, raw_state),
                 **doc_features(scope, d.published_at, r["timing"], rules, d.source_type, d.novelty, d.link_confidence),
                 **{k: v for k, v in text[r["id"]].items() if k.startswith(("ev_p_", "sent_"))}}
        row = {
            "id": r["id"], "scope": scope, "split": r["split"], "episode": r["episode"], "s0": r["s0"], "s0_date": r["s0_date"],
            "ticker": r.get("ticker"), "sector": sector_of.get(r.get("ticker") or ""), "adapter": r["adapter"],
            "source_type": r["source_type"], "timing": r["timing"], "origin": r["origin"], "published_at": r["published_at"],
            "event_top": text[r["id"]]["event_top"], "event_status": text[r["id"]]["event_status"],
            "z": r["z"], "abs_z": r["abs_z"], "score": r["score"], "placebo_abs_z": r["placebo_abs_z"],
            "factor_model": r.get("factor_model", "market"), "text": d.scored_text,
            **_alt_targets(store, alt, scope, r),
            **{k: quantize(v) for k, v in feats.items()},
        }
        out.append(row)
    sizes = Counter(x["episode"] for x in out)
    for x in out:
        x["episode_size"] = sizes[x["episode"]]
        x["weight"] = 1.0 / sizes[x["episode"]]
    return out


def build_dataset(*, repo_root: Path, config_dir: Path, history_signals: Path | None = None, out_table: Path | None = None,
                  out_manifest: Path | None = None) -> dict[str, Any]:
    mcfg: ModelingConfig = load_modeling_config(config_dir)
    icfg: ImpactModelConfig = load_impact_model_config(config_dir)
    if abs(icfg.min_link_confidence - mcfg.impact.min_link_confidence) > 1e-12:
        raise ConfigError("impact_model.yaml min_link_confidence must equal modeling.yaml impact.min_link_confidence")
    signals = history_signals or repo_root / "data" / "processed" / "history" / "signals.jsonl"
    prices = repo_root / "data" / "raw" / "prices"
    for p in (signals, prices / "_GSPC.csv", prices / f"{file_stem(icfg.rates_symbol)}.csv"):
        if not p.is_file():
            raise ConfigError(f"missing input {p}: see docs/DATA_LICENSES.md (`make fetch-prices`, `python -m eventshock.pipeline ...`)")
    out_table = out_table or repo_root / icfg.table
    out_manifest = out_manifest or repo_root / icfg.manifest_file

    sent_dir = Path(load_sentiment_model_config(config_dir).model_dir)
    event_dir = Path(load_event_model_config(config_dir).model_dir)
    sentiment = SentimentModel.load(sent_dir if sent_dir.is_absolute() else repo_root / sent_dir)
    event = EventModel.load(event_dir if event_dir.is_absolute() else repo_root / event_dir)

    docs_list = list(iter_history_docs(signals))
    docs = {d.id: d for d in docs_list}
    ents = json.loads((repo_root / "data" / "history" / "entities.json").read_text(encoding="utf-8"))
    sectors = {e["ticker"]: e["sector"] for e in ents if e.get("ticker")}
    symbols = [*sectors, mcfg.impact.market_symbol, mcfg.impact.volatility_symbol, icfg.rates_symbol]
    store = PriceStore.from_dir(prices, symbols, sectors, mcfg.impact)
    rules = store.session_rules()

    from ..domain import UNKNOWN_ENTITY

    unknown = [d for d in docs_list if d.entity_id == UNKNOWN_ENTITY]
    iss_rows, iss_drops = impact_rows(docs_list, store, mcfg.impact)
    mkt_rows, mkt_drops = market_rows(unknown, store, mcfg.impact, icfg.rates_symbol)
    for rs in (iss_rows, mkt_rows):
        assign_impact_splits(rs, store.dates, mcfg.splits.impact)
    exclusions: dict[str, dict[str, int]] = {ISSUER: dict(iss_drops), MARKET: {k: v for k, v in mkt_drops.items() if k != "HAS_ISSUER"}}
    # impact_rows already drops everything that is not a clean single issuer; market_rows sees only no-issuer documents.
    for scope, rs in ((ISSUER, iss_rows), (MARKET, mkt_rows)):
        for name in ("embargo", "gap"):
            n = sum(1 for r in rs if r["split"] == name)
            if n:
                exclusions[scope][f"SPLIT_{name.upper()}"] = n
    iss_keep = [r for r in iss_rows if r["split"] in KEEP_SPLITS]
    mkt_keep = [r for r in mkt_rows if r["split"] in KEEP_SPLITS]
    ids = sorted({r["id"] for r in (*iss_keep, *mkt_keep)})
    text, text_excl = _text_columns(docs, ids, sentiment, event)
    for scope, rs in ((ISSUER, iss_keep), (MARKET, mkt_keep)):
        lost = Counter()
        for r in rs:
            if r["id"] not in text:
                lost["TEXT_STAGE"] += 1
        if lost:
            exclusions[scope]["TEXT_STAGE (unscorable or seen by a text model)"] = lost["TEXT_STAGE"]
    alt = {w: PriceStore(store.dates, store.close, store.volume, store.sectors, mcfg.impact.model_copy(update={"window_sessions": w}))
           for w in HORIZONS}
    final = (_assemble(iss_keep, ISSUER, docs, text, rules, sectors, store, alt)
             + _assemble(mkt_keep, MARKET, docs, text, rules, sectors, store, alt))
    final.sort(key=lambda r: (r["scope"], r["s0"], r["id"]))

    # ---- leakage gates on the table itself (the trainer repeats them): fatal, never warnings
    findings: list[Finding] = []
    for scope in (ISSUER, MARKET):
        part = [r for r in final if r["scope"] == scope]
        findings += group_straddle(part, "episode")
        findings += time_order(part, store.dates, mcfg.splits.impact.embargo_sessions)
    from ..pipeline.impact_features import ALL_FEATURES

    probe = sorted({(r["ticker"], r["s0"]) for r in final if r["scope"] == ISSUER})
    findings += future_invariance(store, probe[:: max(1, len(probe) // 40)][:40])
    probe_m = sorted({r["s0"] for r in final if r["scope"] == MARKET})
    findings += market_future_invariance(store, probe_m[:: max(1, len(probe_m) // 40)][:40], icfg.rates_symbol)

    findings += check_features(ALL_FEATURES)
    require_clean(findings)

    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=True) for r in final]
    atomic_write_text(out_table, "\n".join(lines) + "\n")

    def count(scope: str, key) -> dict[str, int]:
        return dict(sorted(Counter(key(r) for r in final if r["scope"] == scope).items()))

    manifest: dict[str, Any] = {
        "table": str(out_table.relative_to(repo_root)) if out_table.is_relative_to(repo_root) else str(out_table),
        "table_sha256": _sha(out_table), "rows": len(final), "feature_schema": FEATURE_SCHEMA,
        "target": "z / abs_z / score of configs/modeling.yaml (ISSUER: market+sector abnormal return; MARKET: S&P 500 excess return)",
        "inputs": {
            "history_signals": {"file": signals.name, "sha256": _sha(signals), "documents": len(docs_list)},
            "price_files_sha256": {s: hashlib.sha256((prices / f"{file_stem(s)}.csv").read_bytes()).hexdigest()
                                   for s in sorted(symbols)},
            "price_calendar": [store.dates[0], store.dates[-1], len(store.dates)],
            "sentiment_model": {"id": sentiment.model_id, "sha256": sentiment.artifact_sha256},
            "event_model": {"id": event.model_id, "sha256": event.artifact_sha256},
            "modeling_config_digest": mcfg.digest(),
            "impact_model_config_sha256": _sha(config_dir / "impact_model.yaml"),
        },
        "split_boundaries": mcfg.splits.impact.model_dump(mode="json"),
        "by_scope_split_rows": {s: count(s, lambda r: r["split"]) for s in (ISSUER, MARKET)},
        "by_scope_split_episodes": {s: {sp: len({r["episode"] for r in final if r["scope"] == s and r["split"] == sp})
                                        for sp in KEEP_SPLITS} for s in (ISSUER, MARKET)},
        "by_scope_source": {s: count(s, lambda r: r["adapter"]) for s in (ISSUER, MARKET)},
        "by_scope_timing": {s: count(s, lambda r: r["timing"]) for s in (ISSUER, MARKET)},
        "by_scope_event_status": {s: count(s, lambda r: r["event_status"]) for s in (ISSUER, MARKET)},
        "exclusions": {s: dict(sorted(v.items())) for s, v in exclusions.items()},
        "text_stage_exclusions": dict(sorted(text_excl.items())),
        "seeds": {"impact_model": icfg.seed},
        "leakage_findings": [{"check": f.check, "severity": f.severity, "detail": f.detail} for f in findings],
    }
    atomic_write_text(out_manifest, json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return manifest


def load_table(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("rb") as fh:
        for n, raw in enumerate(fh, start=1):
            if raw.strip():
                try:
                    rows.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{n}: unreadable JSON line ({exc})") from exc
    return rows


__all__ = ["build_dataset", "load_table"]
