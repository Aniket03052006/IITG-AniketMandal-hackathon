"""Freeze the replay pack in data/replay/ from the raw downloads in data/raw/ (deterministic).

Inputs  (git-ignored, produced by `make fetch-gdelt` / `make fetch-tfn`):
    data/raw/gdelt/articles.jsonl      GDELT DOC 2.0 artlist records
    data/raw/tfn/{train,valid}.jsonl   Twitter Financial News rows
Outputs (committed, small, hash-pinned by manifest.json):
    data/replay/gdelt/articles.jsonl, data/replay/social/tfn_sample.jsonl,
    data/replay/entities.json, data/replay/portfolio.json, data/replay/manifest.json

The issuers are real; the portfolio positions on them are SYNTHETIC (generated here with a fixed seed).
Usage:  python scripts/build_replay_pack.py
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from eventshock.domain import Entity, Portfolio  # noqa: E402
from eventshock.ingestion.snapshot import atomic_write_text, sha256_file  # noqa: E402
from eventshock.pipeline.normalize import dedup_key  # noqa: E402
from generate_fixtures import SECTOR_BETA, r2  # noqa: E402
from replay_universe import UNIVERSE  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "replay"
REPLAY_DIR = OUT
SNAPSHOT_ID = "replay-2026-09-30-v1"
AS_OF = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
WINDOW = (datetime(2026, 9, 17, tzinfo=UTC), datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC))
SEED = 20261001
TFN_TARGET = 300
KEEP_GDELT = ("url", "title", "seendate", "domain", "language", "sourcecountry", "x_query")
CASHTAG = re.compile(r"(?<![A-Za-z0-9$])\$([A-Za-z]{1,5})(?![A-Za-z0-9])")


def jsonl(records: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def build_entities() -> list[Entity]:
    return [Entity(entity_id=f"ENT_{i}", name=n, ticker=t, sector=s, country=c, aliases=a)
            for i, n, t, s, c, a, _q, _pd in UNIVERSE]


def sector_tilt() -> dict[str, float]:
    """Notional multiplier per sector from the transaction-derived spend mix (relative to an equal split, clamped)."""
    path = REPLAY_DIR / "sector_mix.json"
    if not path.is_file():
        return {}
    shares = json.loads(path.read_text(encoding="utf-8"))["sector_share_of_mapped_spend"]
    mean = 1 / len(shares)
    return {k: round(min(2.0, max(0.5, v / mean)), 3) for k, v in shares.items()}


def build_portfolio() -> Portfolio:
    rng = random.Random(SEED)
    tilt = sector_tilt()
    info = {f"ENT_{i}": (n, s, c, pd) for i, n, _t, s, c, _a, _q, pd in UNIVERSE}
    assets: list[dict] = []
    for ent_id, (name, sector, country, _pd) in info.items():
        n = r2(rng.uniform(3e6, 18e6) * tilt.get(sector, 1.0))
        assets.append(dict(asset_id=f"EQ-{ent_id[4:]}", asset_type="EQUITY", entity_id=ent_id,
                           name=f"{name} - Common Equity", sector=sector, geography=country, notional=n,
                           market_value=n, beta=r2(SECTOR_BETA[sector] + rng.uniform(-0.15, 0.15))))
    fin = [e for e, v in info.items() if v[1] == "Financials"]
    for k, ent_id in enumerate(list(info) + fin):
        name, sector, country, _pd = info[ent_id]
        longer = k >= len(info)
        face = r2(rng.uniform(4e6, 14e6) * tilt.get(sector, 1.0))
        assets.append(dict(
            asset_id=f"BD-{ent_id[4:]}-{'B' if longer else 'A'}", asset_type="BOND", entity_id=ent_id,
            name=f"{name} {rng.choice([4.25, 4.75, 5.25, 5.75])}% {2036 if longer else 2030} Sr Notes",
            sector=sector, geography=country, notional=face, market_value=r2(face * rng.uniform(0.93, 1.03)),
            duration=r2(rng.uniform(6.5, 9.0) if longer else rng.uniform(3.0, 5.5))))
    for k, ent_id in enumerate(e for i, e in enumerate(info) if i % 2 == 0 or info[e][1] == "Industrials"):
        name, sector, country, pd = info[ent_id]
        ead = r2(rng.uniform(6e6, 30e6) * tilt.get(sector, 1.0))
        pd_i, lgd = round(pd * rng.uniform(0.8, 1.3), 4), round(rng.uniform(0.35, 0.55), 2)
        kind = "Interbank Facility" if sector == "Financials" else rng.choice(
            ["Term Loan B", "Revolving Credit Facility", "Senior Term Loan"])
        assets.append(dict(asset_id=f"LN-{ent_id[4:]}-{k + 1:02d}", asset_type="LOAN", entity_id=ent_id,
                           name=f"{name} - {kind}", sector=sector, geography=country, notional=ead,
                           market_value=r2(ead * (1 - pd_i * lgd)), pd=pd_i, lgd=lgd,
                           default_sensitivity=round(rng.uniform(0.7, 1.4), 2)))
    for k, ent_id in enumerate(list(info)[::4]):
        name, sector, country, _pd = info[ent_id]
        und = r2(rng.uniform(4e6, 14e6) * tilt.get(sector, 1.0))
        delta = round(rng.choice([-0.55, -0.4, 0.35, 0.5, 0.6]), 2)
        kind = "Equity Total Return Swap" if delta > 0 else "Protective Put Position"
        assets.append(dict(asset_id=f"DV-{ent_id[4:]}-{k + 1:02d}", asset_type="DERIVATIVE", entity_id=ent_id,
                           name=f"{name} - {kind}", sector=sector, geography=country, notional=und,
                           market_value=r2(und * rng.uniform(0.02, 0.07)), delta=delta))
    return Portfolio(
        portfolio_id="pf_wholesale_replay", name="Synthetic Wholesale Banking Book (real issuers)",
        as_of=AS_OF, base_currency="USD",
        description=("SYNTHETIC positions generated with a fixed seed on REAL listed issuers (equity, bonds, loans, "
                     "hedges per issuer; sector-correlated betas and PD). Position sizes are tilted by sector using the "
                     "merchant-category spend mix of a public card-transaction dataset (see data/replay/sector_mix.json): "
                     "a crude proxy, not real holdings or exposures."),
        assets=assets)


def pick_tfn(tickers: set[str]) -> list[dict]:
    rows = [r for f in ("train", "valid") for r in read_jsonl(RAW / "tfn" / f"{f}.jsonl")]
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        by_key.setdefault(dedup_key(r["text"]), []).append(r)
    h = lambda r: hashlib.sha256(f"{r['split']}-{r['row']}".encode()).hexdigest()  # noqa: E731
    resolvable, unknown, plain, dups = [], [], [], []
    for r in rows:
        tags = [t.upper() for t in CASHTAG.findall(r["text"])]
        if not tags:
            plain.append(r)
        elif any(t in tickers for t in tags):
            resolvable.append(r)
        else:
            unknown.append(r)
    for group in by_key.values():
        if len(group) > 1 and any(t.upper() in tickers for t in CASHTAG.findall(group[0]["text"])):
            dups.extend(group[:2])
    chosen: dict[tuple, dict] = {}
    for r in sorted(dups, key=h)[:30]:
        chosen[(r["split"], r["row"])] = r
    per_ticker: dict[str, int] = {}
    for r in sorted(resolvable, key=h):
        if len([1 for _ in chosen]) >= 220:
            break
        t = next(x.upper() for x in CASHTAG.findall(r["text"]) if x.upper() in tickers)
        if per_ticker.get(t, 0) < 8:
            per_ticker[t] = per_ticker.get(t, 0) + 1
            chosen[(r["split"], r["row"])] = r
    for r in sorted(unknown, key=h)[:50]:
        chosen[(r["split"], r["row"])] = r
    for r in sorted(plain, key=h)[: TFN_TARGET - len(chosen)]:
        chosen[(r["split"], r["row"])] = r
    return sorted(chosen.values(), key=lambda r: (r["split"], r["row"]))


GKG_RAW = RAW / "gdelt_gkg" / "filtered.jsonl"
GKG_KEEP = ("url", "title", "seendate", "domain", "language", "x_gkg_id", "x_time_origin", "x_tone", "x_orgs")
GKG_STATS = {"kept": 0, "files": 0}
GKG_CAPS = dict(title=30, org_only=6, market=100, outside_window=20)  # per issuer (market/outside: total)


def pick_gkg(entities: list) -> list[dict]:
    """A small, stratified, deterministic slice of the (large, git-ignored) filtered GKG download.

    Rows whose *title* the pipeline's own resolver ties to an issuer are preferred (they become company signals);
    org-only rows (the title never names the company) and market-wide rows are kept in small numbers so the pack still
    exercises the unresolved path.
    """
    from eventshock.config import REPO_ROOT
    from eventshock.pipeline.config import load_pipeline_config
    from eventshock.pipeline.entities import EntityResolver

    resolver = EntityResolver(entities, load_pipeline_config(REPO_ROOT / "configs").entity_resolution)
    rows = read_jsonl(GKG_RAW)
    w0, w1 = WINDOW[0].strftime("%Y%m%dT%H%M%SZ"), WINDOW[1].strftime("%Y%m%dT%H%M%SZ")
    h = lambda r: hashlib.sha256(r["x_gkg_id"].encode()).hexdigest()  # noqa: E731
    chosen: dict[str, dict] = {}
    count: dict[tuple, int] = {}
    outside = 0
    for r in sorted(rows, key=h):
        if not w0 <= r["seendate"] <= w1:
            if outside < GKG_CAPS["outside_window"]:
                outside += 1
                chosen[r["x_gkg_id"]] = r
            continue
        mention, _ = resolver.resolve(r["title"])
        if not mention.is_unknown:
            kind, who = "title", mention.entity_id
        elif r.get("x_issuers"):
            kind, who = "org_only", r["x_issuers"][0]
        else:
            kind, who = "market", "*"
        if count.get((kind, who), 0) < GKG_CAPS[kind]:
            count[(kind, who)] = count.get((kind, who), 0) + 1
            chosen[r["x_gkg_id"]] = r
    return sorted(({k: r[k] for k in GKG_KEEP if k in r} for r in chosen.values()),
                  key=lambda r: (r["seendate"], r["url"]))


def main() -> None:
    gdelt_raw = read_jsonl(RAW / "gdelt" / "articles.jsonl")
    gdelt = sorted(({k: r[k] for k in KEEP_GDELT if k in r} for r in gdelt_raw),
                   key=lambda r: (r.get("seendate", ""), r.get("url", "")))
    entities = build_entities()
    gkg = pick_gkg(entities) if GKG_RAW.is_file() else []
    if gkg:
        ok = [e for e in read_jsonl(RAW / "gdelt_gkg" / "filtered.log.jsonl") if e.get("status") == "ok"]
        GKG_STATS.update(kept=sum(e["kept"] for e in {e["file"]: e for e in ok}.values()),
                         files=len({e["file"] for e in ok}))
    tfn = pick_tfn({e.ticker for e in entities if e.ticker})
    portfolio = build_portfolio()
    gdelt_log = RAW / "gdelt" / "articles.log.jsonl"
    fetch_log = read_jsonl(gdelt_log) if gdelt_log.is_file() else []
    plan_path = RAW / "gdelt" / "queries.json"
    fetch_plan = ([q["query"] if isinstance(q, dict) else q for q in json.loads(plan_path.read_text(encoding="utf-8"))]
                  if plan_path.is_file() else [])
    gkg_log_path = RAW / "gdelt_gkg" / "filtered.log.jsonl"
    if gkg_log_path.is_file():  # failed GKG files only: successes are summarised in the source notes
        fetch_log += [{"query": f"gkg:{e['file']}", "status": "error", "error": e.get("error", "")}
                      for e in read_jsonl(gkg_log_path) if e.get("status") == "error"
                      and not any(o["file"] == e["file"] and o["status"] == "ok" for o in read_jsonl(gkg_log_path))]

    atomic_write_text(OUT / "gdelt" / "articles.jsonl", jsonl(gdelt))
    atomic_write_text(OUT / "social" / "tfn_sample.jsonl", jsonl(tfn))
    if gkg:
        atomic_write_text(OUT / "gdelt" / "gkg_articles.jsonl", jsonl(gkg))
    atomic_write_text(OUT / "entities.json", json.dumps([e.model_dump(mode="json") for e in entities], indent=2,
                                                        ensure_ascii=False) + "\n")
    atomic_write_text(OUT / "portfolio.json", json.dumps(portfolio.model_dump(mode="json"), indent=2,
                                                         ensure_ascii=False) + "\n")
    manifest = {
        "schema_version": 1,
        "snapshot_id": SNAPSHOT_ID,
        "description": ("Frozen replay pack: GDELT DOC 2.0 article metadata for 34 listed issuers plus market-wide "
                        "queries (14-day window), and a deterministic sample of the Twitter Financial News dataset."),
        "replay_as_of": AS_OF.isoformat().replace("+00:00", "Z"),
        "window_start": WINDOW[0].isoformat().replace("+00:00", "Z"),
        "window_end": WINDOW[1].isoformat().replace("+00:00", "Z"),
        "sources": [
            {"name": "gdelt-doc", "adapter": "gdelt-doc", "source_type": "NEWS", "file": "gdelt/articles.jsonl",
             "sha256": sha256_file(OUT / "gdelt" / "articles.jsonl"), "records": len(gdelt),
             "license": "GDELT terms: free unrestricted use and redistribution with citation",
             "attribution": "The GDELT Project (https://www.gdeltproject.org)",
             "origin_url": "https://api.gdeltproject.org/api/v2/doc/doc",
             "notes": ("Metadata only (url, title, first-seen time, domain, language, country). seendate is when "
                       "GDELT first saw the page, not the publication time. Publisher text is not stored.")},
            *([{"name": "gdelt-gkg", "adapter": "gdelt-gkg", "source_type": "NEWS", "file": "gdelt/gkg_articles.jsonl",
                "sha256": sha256_file(OUT / "gdelt" / "gkg_articles.jsonl"), "records": len(gkg),
                "license": "GDELT terms: free unrestricted use and redistribution with citation",
                "attribution": "The GDELT Project (https://www.gdeltproject.org), GKG 2.1 bulk files",
                "origin_url": "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt",
                "notes": (f"Stratified {len(gkg)}-record slice of {GKG_STATS['kept']} issuer/market rows filtered from "
                          f"{GKG_STATS['files']} 15-minute GKG files (zips discarded after filtering). Page title, URL, domain, "
                          "publisher time (PAGE_PRECISEPUBTIMESTAMP, flagged SOURCE), machine tone and NER organisations; "
                          "no article text. Entity resolution reads the title only.")}] if gkg else []),
            {"name": "tfn-replay", "adapter": "tfn-replay", "source_type": "SOCIAL", "file": "social/tfn_sample.jsonl",
             "sha256": sha256_file(OUT / "social" / "tfn_sample.jsonl"), "records": len(tfn),
             "license": "MIT (dataset card of zeroshot/twitter-financial-news-sentiment); tweet text originates on X",
             "attribution": "zeroshot/twitter-financial-news-sentiment, Hugging Face",
             "origin_url": "https://huggingface.co/datasets/zeroshot/twitter-financial-news-sentiment",
             "notes": (f"{len(tfn)}-row deterministic sample (full set is never committed). The dataset has no "
                       "timestamps: replay assigns deterministic times inside the window, flagged SYNTHETIC_REPLAY_CLOCK. "
                       "Labels are human sentiment annotations. Remove data/replay/social/ on request of a rights holder.")},
        ],
        "entities": {"file": "entities.json", "sha256": sha256_file(OUT / "entities.json")},
        "portfolio": {"file": "portfolio.json", "sha256": sha256_file(OUT / "portfolio.json")},
        # derived market features: built by `make market-context` (needs data/raw/prices); kept if already present
        **({"market_context": {"file": "market/context.json", "sha256": sha256_file(OUT / "market" / "context.json")}}
           if (OUT / "market" / "context.json").is_file() else {}),
        # pinned event-model vectors: built by `make replay-embeddings`; kept if already present (re-freezing must not unpin them)
        **({"embeddings": {"file": "embeddings/event-e5-large.npz", "sha256": sha256_file(OUT / "embeddings" / "event-e5-large.npz")}}
           if (OUT / "embeddings" / "event-e5-large.npz").is_file() else {}),
        "fetch_log": fetch_log,
        "fetch_plan": fetch_plan,
    }
    atomic_write_text(OUT / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"gdelt={len(gdelt)} tfn={len(tfn)} entities={len(entities)} assets={len(portfolio.assets)} "
          f"value={portfolio.total_value:,.0f}")


if __name__ == "__main__":
    main()
