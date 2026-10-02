"""Builds the modeling tables and the audit that justifies them. Writes under ``data/modeling/`` (git-ignored).

``run_audit`` is the single entry point: profile -> impact table (+ leakage checks) -> text tables (+ leakage checks).
Every number in ``docs/MODELING_READINESS.md`` comes from the ``audit.json`` this produces.
"""

from __future__ import annotations

import json
import re
import statistics as stats
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.topics import TopicMapping
from .config import ModelingConfig
from .corpora import (
    HistoryDoc,
    TextExample,
    iter_history_docs,
    load_phrasebank,
    load_tfn_sentiment,
    load_tfn_topic,
    prepare_text_pool,
    read_jsonl,
    stratified_group_split,
)
from .leakage import (
    Finding,
    bootstrap_ci,
    check_features,
    duplicate_rate,
    future_invariance,
    group_straddle,
    metadata_baseline,
    spearman,
    time_order,
)
from .market import PriceStore, impact_rows
from .splits import assign_impact_splits

IMPACT_FEATURES = ["novelty", "link_confidence", "dow", "local_hour", "sector", "source_type", "f_sigma_60", "f_beta_market",
                   "f_beta_sector", "f_ret_1d", "f_ret_5d", "f_ret_20d", "f_mkt_ret_5d", "f_sector_ret_5d",
                   "f_volume_ratio", "f_vix_level", "f_vix_chg_5d"]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for r in rows]
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def _findings(fs: Iterable[Finding]) -> list[dict[str, str]]:
    return [asdict(f) for f in fs]


def _mean(v: list[float]) -> float | None:
    return round(sum(v) / len(v), 4) if v else None


def _dist(c: Counter) -> dict[str, int]:
    return {str(k): c[k] for k in sorted(c, key=str)}


# ------------------------------------------------------------------------------------------------- profile
def profile_history(docs: list[HistoryDoc], tfn_sentiment: list[TextExample]) -> dict[str, Any]:
    n = len(docs)
    by_ticker = Counter(d.ticker or d.entity_id for d in docs)
    resolved = [d for d in docs if d.ticker]
    tick = Counter(d.ticker for d in resolved)
    eff = 1 / sum((c / len(resolved)) ** 2 for c in tick.values()) if resolved else 0.0
    vocab = {w for t in tfn_sentiment for w in re.findall(r"[a-z][a-z']+", t.text.lower())}
    by_src: dict[str, list[HistoryDoc]] = defaultdict(list)
    for d in docs:
        by_src[d.adapter].append(d)

    def stat(texts: list[str]) -> dict[str, float]:
        words = [w for t in texts for w in re.findall(r"[a-z][a-z']+", t.lower())]
        return {"n": len(texts), "mean_chars": round(sum(map(len, texts)) / len(texts), 1),
                "oov_vs_tfn": round(sum(w not in vocab for w in words) / max(1, len(words)), 3),
                "url_share": round(sum("http" in t for t in texts) / len(texts), 3),
                "cashtag_share": round(sum("$" in t for t in texts) / len(texts), 3)}

    agree: dict[str, dict[str, float]] = {}
    for a, ds in by_src.items():
        tagged = [d for d in ds if d.dataset_tickers]
        if tagged:
            hit = sum(1 for d in tagged if d.ticker and d.ticker in d.dataset_tickers)
            unk = sum(1 for d in tagged if not d.ticker)
            agree[a] = {"tagged": len(tagged), "er_ticker_in_dataset_tags": round(hit / len(tagged), 3),
                        "er_unresolved": round(unk / len(tagged), 3)}
    return {
        "documents": n,
        "by_source": {a: len(v) for a, v in sorted(by_src.items())},
        "by_year": _dist(Counter(str(d.published_at.year) for d in docs)),
        "by_source_year": {a: _dist(Counter(str(d.published_at.year) for d in v)) for a, v in sorted(by_src.items())},
        "timestamp_origin": _dist(Counter(d.origin for d in docs)),
        "weekend_share": round(sum(d.published_at.weekday() >= 5 for d in docs) / n, 4),
        "top_issuers": {t: c for t, c in by_ticker.most_common(8)},
        "top2_issuer_share": round(sum(c for _, c in tick.most_common(2)) / max(1, len(resolved)), 4),
        "effective_number_of_issuers": round(eff, 2),
        "issuers_resolved": len(tick),
        "multi_entity_share": round(sum(d.multi_entity for d in docs) / n, 4),
        "unknown_entity_share": round(sum(not d.ticker for d in docs) / n, 4),
        "er_rule": _dist(Counter(d.er_rule for d in docs)),
        "er_vs_dataset_ticker": agree,
        "placeholder_event_distribution": _dist(Counter(d.placeholder_event for d in docs)),
        "placeholder_market_valuation_share": round(sum(d.placeholder_event == "MARKET_VALUATION" for d in docs) / n, 4),
        "text_shape": {a: stat([d.text for d in v]) for a, v in sorted(by_src.items())} | {"tfn-sentiment": stat([t.text for t in tfn_sentiment])},
    }


# ------------------------------------------------------------------------------------------------- impact
def build_impact(cfg: ModelingConfig, docs: list[HistoryDoc], prices_dir: Path, entities_path: Path, out_dir: Path) -> dict[str, Any]:
    ents = json.loads(entities_path.read_text(encoding="utf-8"))
    sectors = {e["ticker"]: e["sector"] for e in ents if e.get("ticker")}
    symbols = [*sectors, cfg.impact.market_symbol, cfg.impact.volatility_symbol]
    store = PriceStore.from_dir(prices_dir, symbols, sectors, cfg.impact)
    rows, drops = impact_rows(docs, store, cfg.impact)
    split_counts = assign_impact_splits(rows, store.dates, cfg.splits.impact)
    usable = [r for r in rows if r["split"] in ("train", "val", "test", "live")]
    for r in rows:
        r["config_digest"] = cfg.digest()
    n_rows = write_jsonl(out_dir / "impact_events.jsonl", rows)

    # ---- descriptive
    episodes: dict[str, dict] = {}
    for r in rows:
        episodes.setdefault(r["episode"], r)
    score_sig = Counter(r["score"] for r in rows)
    score_ep = Counter(e["score"] for e in episodes.values())
    hi = lambda c: round(sum(v for k, v in c.items() if k >= 7) / max(1, sum(c.values())), 4)  # noqa: E731
    by = lambda key: {k: {"n": len(v), "mean_abs_z": _mean(v)} for k, v in sorted(  # noqa: E731
        (k, [r["abs_z"] for r in rows if r[key] == k]) for k in sorted({r[key] for r in rows}, key=str))}
    by_class: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_class[r["placeholder_event"]].append(r["abs_z"])
    eps_by_split = Counter(e["split"] for e in episodes.values())
    ticker_rows = Counter(r["ticker"] for r in rows)
    ticker_w: dict[str, float] = defaultdict(float)
    for r in rows:
        ticker_w[r["ticker"]] += r["weight"]
    tot_w = sum(ticker_w.values())

    # ---- leakage
    by_split = {s: [r for r in usable if r["split"] == s] for s in ("train", "val", "test", "live")}
    findings: list[Finding] = []
    findings += group_straddle(usable, "episode")
    findings += time_order(usable, store.dates, cfg.splits.impact.embargo_sessions)
    findings += check_features(IMPACT_FEATURES)
    probe_events = sorted({(r["ticker"], r["s0"]) for r in usable})
    findings += future_invariance(store, probe_events[:: max(1, len(probe_events) // 30)][:30])
    keys = [lambda r: r["ticker"], lambda r: r["adapter"], lambda r: r["s0_date"][5:7]]
    meta: dict[str, Any] = {}
    for split in ("val", "test", "live"):
        real = metadata_baseline(by_split["train"], by_split[split], "abs_z", keys)
        plac = metadata_baseline(by_split["train"], by_split[split], "placebo_abs_z", keys)
        meta[split] = {"metadata_only_spearman_target": _r(real["spearman"]), "metadata_only_spearman_placebo": _r(plac["spearman"]),
                       "n": int(real["n_test"])}
    placebo_rho = {s: meta[s]["metadata_only_spearman_placebo"] for s in meta}
    worst = max((abs(v) for v in placebo_rho.values() if v is not None), default=0.0)
    findings.append(Finding("placebo", "WARN" if worst > cfg.splits.leakage.placebo_warn_spearman else "INFO",
                            f"metadata-only skill on the placebo window {placebo_rho} (warn above {cfg.splits.leakage.placebo_warn_spearman})"))
    pairs = [(r["f_sigma_60"], r["abs_z"]) for r in usable if r["split"] in ("val", "test")]
    lo, hi_ = bootstrap_ci([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) > 100 else (None, None)
    return {
        "config_digest": cfg.digest(), "rows": n_rows, "drops": drops,
        "price_calendar": [store.dates[0], store.dates[-1], len(store.dates)],
        "eligible_rows": len(rows), "episodes": len(episodes), "rows_per_episode_mean": round(len(rows) / max(1, len(episodes)), 2),
        "split_rows": _dist(split_counts), "split_episodes": _dist(eps_by_split),
        "split_sources": {s: _dist(Counter(r["adapter"] for r in v)) for s, v in by_split.items()},
        "score_distribution_rows": _dist(score_sig), "score_distribution_episodes": _dist(score_ep),
        "share_score_ge_7_rows": hi(score_sig), "share_score_ge_7_episodes": hi(score_ep),
        "abs_z_quantiles": {q: round(sorted(r["abs_z"] for r in rows)[int(len(rows) * q)], 3) for q in (0.5, 0.75, 0.9, 0.95, 0.99)},
        "mean_abs_z_by_timing": by("timing"), "mean_abs_z_by_source": by("adapter"),
        "mean_abs_z_by_year": by_year(rows),
        "mean_abs_z_by_placeholder_class": {k: {"n": len(v), "mean_abs_z": _mean(v)} for k, v in sorted(by_class.items())},
        "placebo_mean_abs_z": _mean([r["placebo_abs_z"] for r in rows if r["placebo_abs_z"] is not None]),
        "issuer_share_rows_top3": {t: round(c / len(rows), 4) for t, c in ticker_rows.most_common(3)},
        "issuer_share_episode_weighted_top3": {t: round(w / tot_w, 4) for t, w in sorted(ticker_w.items(), key=lambda kv: -kv[1])[:3]},
        "spearman_sigma60_vs_abs_z_valtest": {"rho": _r(spearman([p[0] for p in pairs], [p[1] for p in pairs])) if pairs else None,
                                              "ci95": [_r(lo), _r(hi_)]},
        "metadata_only_baseline": meta,
        "features": IMPACT_FEATURES,
        "findings": _findings(findings),
    }


def by_year(rows: list[dict]) -> dict[str, dict[str, Any]]:
    out: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        out[r["s0_date"][:4]].append(r["abs_z"])
    return {y: {"n": len(v), "mean_abs_z": _mean(v)} for y, v in sorted(out.items())}


def _r(x: float | None) -> float | None:
    return None if x is None or x != x else round(x, 4)


# ------------------------------------------------------------------------------------------------- text
def build_text(cfg: ModelingConfig, raw_dir: Path, mapping: TopicMapping, out_dir: Path,
               gold_topic_ids: set[str] | None = None) -> dict[str, Any]:
    tcfg = cfg.splits.text
    summary: dict[str, Any] = {"config_digest": cfg.digest()}
    findings: list[Finding] = []

    # ---- sentiment (TFN, human labels)
    sent_raw = load_tfn_sentiment(raw_dir)
    pool = prepare_text_pool(sent_raw, tcfg.near_duplicate_threshold)
    labels = {g: Counter(pool.examples[i].label for i, gg in enumerate(pool.groups) if gg == g).most_common(1)[0][0]
              for g in set(pool.groups)}
    assign = stratified_group_split(labels, pool.group_sizes, tcfg.fractions, tcfg.seed)
    sent_rows = [{"id": e.id, "text": e.text, "label": e.label, "split": assign[g], "group": g, "published_split": e.published_split}
                 for e, g in zip(pool.examples, pool.groups, strict=True)]
    summary["sentiment"] = _text_summary(sent_rows, pool.dedup, sent_raw, "published_split")
    findings += _text_leakage("sentiment", sent_rows, sent_raw, tcfg.near_duplicate_threshold, cfg.splits.leakage.max_near_duplicate_rate)
    write_jsonl(out_dir / "sentiment.jsonl", sent_rows)

    # ---- event silver labels (TFN topic -> class, with tiers)
    topic_raw = load_tfn_topic(raw_dir, mapping)
    tpool = prepare_text_pool(topic_raw, tcfg.near_duplicate_threshold)
    gold_ids = gold_topic_ids or set()
    forced = {g for e, g in zip(tpool.examples, tpool.groups, strict=True) if e.id in gold_ids}
    tlabels = {g: Counter(tpool.examples[i].label for i, gg in enumerate(tpool.groups) if gg == g).most_common(1)[0][0]
               for g in set(tpool.groups)}
    tassign = stratified_group_split(tlabels, tpool.group_sizes, tcfg.fractions, tcfg.seed, forced_test=forced)
    topic_rows = [{"id": e.id, "text": e.text, "event_class": e.label, "topic": e.topic, "topic_name": e.topic_name, "tier": e.tier,
                   "train_eligible": e.tier in ("strong", "medium"), "split": tassign[g], "group": g,
                   "published_split": e.published_split, "gold_reserved": e.id in gold_ids}
                  for e, g in zip(tpool.examples, tpool.groups, strict=True)]
    summary["event_silver"] = _text_summary(topic_rows, tpool.dedup, topic_raw, "published_split", label_key="event_class") | {
        "by_tier": _dist(Counter(str(r["tier"]) for r in topic_rows)),
        "trainable_by_class": _dist(Counter(r["event_class"] for r in topic_rows if r["train_eligible"])),
        "weak_tier_by_class": _dist(Counter(r["event_class"] for r in topic_rows if r["tier"] == "weak")),
        "gold_reserved": sum(r["gold_reserved"] for r in topic_rows)}
    findings += _text_leakage("event_silver", topic_rows, topic_raw, tcfg.near_duplicate_threshold, cfg.splits.leakage.max_near_duplicate_rate)
    write_jsonl(out_dir / "event_silver.jsonl", topic_rows)

    # ---- PhraseBank: evaluation only
    try:
        pb = load_phrasebank(raw_dir)
    except FileNotFoundError:
        pb = []
    if pb:
        tr = [r["text"] for r in sent_rows if r["split"] == "train"]
        findings += duplicate_rate(tr, [e.text for e in pb], tcfg.near_duplicate_threshold, "phrasebank vs TFN-sentiment train",
                                   cfg.splits.leakage.max_near_duplicate_rate)
        write_jsonl(out_dir / "phrasebank_eval.jsonl", [{"id": e.id, "text": e.text, "label": e.label} for e in pb])
        summary["phrasebank"] = {"rows": len(pb), "labels": _dist(Counter(e.label for e in pb)), "license_scope": "eval_only"}
    summary["findings"] = _findings(findings)
    return summary


def _text_summary(rows: list[dict], dedup, raw: list[TextExample], pub_key: str, label_key: str = "label") -> dict[str, Any]:
    return {"raw_rows": dedup.input, "exact_duplicates_dropped": dedup.exact_duplicates_dropped,
            "conflicting_texts_dropped": dedup.conflicting_texts_dropped, "rows": len(rows),
            "groups": len({r["group"] for r in rows}),
            "splits": _dist(Counter(r["split"] for r in rows)),
            "label_by_split": {s: _dist(Counter(r[label_key] for r in rows if r["split"] == s)) for s in ("train", "valid", "test")},
            "published_split_rows": _dist(Counter(e.published_split for e in raw))}


def _text_leakage(name: str, rows: list[dict], raw: list[TextExample], thr: float, max_rate: float) -> list[Finding]:
    out: list[Finding] = []
    tr_pub = [e.text for e in raw if e.published_split == "train"]
    va_pub = [e.text for e in raw if e.published_split == "valid"]
    f = duplicate_rate(tr_pub, va_pub, thr, f"{name}: PUBLISHED valid vs train", max_rate)
    out += [Finding(x.check, "WARN" if x.severity == "ERROR" else x.severity, x.detail) for x in f]  # the published split is allowed to be dirty
    tr = [r["text"] for r in rows if r["split"] == "train"]
    for s in ("valid", "test"):
        out += duplicate_rate(tr, [r["text"] for r in rows if r["split"] == s], thr, f"{name}: re-split {s} vs train", max_rate)
    out += group_straddle(rows, "group", splits=("train", "valid", "test"))
    return out


# ------------------------------------------------------------------------------------------------- orchestration
def run_audit(cfg: ModelingConfig, *, repo_root: Path, config_dir: Path, mapping: TopicMapping, out_dir: Path,
              history_signals: Path | None = None, gold_topic_ids: set[str] | None = None) -> dict[str, Any]:
    raw = repo_root / "data" / "raw"
    signals = history_signals or repo_root / "data" / "processed" / "history" / "signals.jsonl"
    for p in (signals, raw / "prices" / "_GSPC.csv", raw / "tfn" / "train.jsonl"):
        if not p.exists():
            raise ConfigError(f"missing input {p}: run `make ingest-history` / `make fetch-*` first (see docs/DATA_LICENSES.md)")
    docs = list(iter_history_docs(signals))
    tfn = load_tfn_sentiment(raw)
    result: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "config_digest": cfg.digest(),
        "profile": profile_history(docs, tfn),
        "impact": build_impact(cfg, docs, raw / "prices", repo_root / "data" / "history" / "entities.json", out_dir),
        "text": build_text(cfg, raw, mapping, out_dir, gold_topic_ids),
    }
    errors = [f for sec in ("impact", "text") for f in result[sec]["findings"] if f["severity"] == "ERROR"]
    result["errors"] = errors
    atomic_write_text(out_dir / "audit.json", json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    return result


def load_impact_rows(out_dir: Path) -> list[dict[str, Any]]:
    return read_jsonl(out_dir / "impact_events.jsonl")


__all__ = ["run_audit", "build_impact", "build_text", "profile_history", "load_impact_rows", "stats"]
