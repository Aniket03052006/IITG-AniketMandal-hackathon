"""Build the HISTORY snapshot (data/history/, git-ignored) used to model impact: dated text from 2015-2026.

Inputs (git-ignored, from `make fetch-kaggle`, `make fetch-gkg`):
    data/raw/kaggle/*                      stock tweets, financial headlines, top-company tweets
    data/raw/gdelt_gkg/filtered.jsonl      filtered GKG rows
Curation: a document is kept when the pipeline's own entity resolver ties its text to one of the 34 issuers, plus a
small deterministic sample of the rest so the unresolved path stays exercised. Large sources are capped by a
content hash (deterministic). The output is a normal snapshot, so it runs through the SAME pipeline:

    python scripts/build_history_pack.py
    python -m eventshock.pipeline --replay-dir data/history --export data/processed/history
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
csv.field_size_limit(10_000_000)

from eventshock.config import REPO_ROOT  # noqa: E402
from eventshock.ingestion.snapshot import atomic_write_text, sha256_file  # noqa: E402
from eventshock.pipeline.config import load_pipeline_config  # noqa: E402
from eventshock.pipeline.entities import EntityResolver  # noqa: E402
from eventshock.pipeline.run import load_entities  # noqa: E402

RAW = ROOT / "data" / "raw"
K = RAW / "kaggle"
REPLAY = ROOT / "data" / "replay"
OUT = ROOT / "data" / "history"
SNAPSHOT_ID = "history-2015-2026-v1"
AS_OF = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
WINDOW = (datetime(2015, 1, 1, tzinfo=UTC), datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC))
UNKNOWN_SAMPLE = 1500  # unresolved documents kept per source (deterministic)
CAPS = {"top-tweets": 60_000, "gdelt-gkg": 40_000}


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Curator:
    def __init__(self) -> None:
        ents = load_entities(REPLAY / "entities.json")
        self.resolver = EntityResolver(ents, load_pipeline_config(REPO_ROOT / "configs").entity_resolution)
        self.stats: dict[str, dict[str, int]] = {}

    def keep(self, source: str, rows: list[tuple[str, dict]]) -> list[dict]:
        """rows: (text-to-resolve, record). Known-issuer rows first (capped), then a sample of unresolved rows."""
        known, unknown = [], []
        for text, rec in rows:
            (unknown if self.resolver.resolve(text)[0].is_unknown else known).append((h(json.dumps(rec, sort_keys=True)), rec))
        known.sort(key=lambda x: x[0])
        unknown.sort(key=lambda x: x[0])
        cap = CAPS.get(source)
        kept = [r for _, r in known[:cap]] + [r for _, r in unknown[:UNKNOWN_SAMPLE]]
        self.stats[source] = {"candidates": len(rows), "resolved": len(known), "kept_resolved": min(len(known), cap or len(known)),
                              "kept_unresolved": min(len(unknown), UNKNOWN_SAMPLE)}
        return kept


def stock_tweets() -> list[tuple[str, dict]]:
    out = []
    with (K / "stock-tweets-for-sentiment-analysis-and-prediction" / "stock_tweets.csv").open(newline="", encoding="utf-8") as fh:
        for i, r in enumerate(csv.DictReader(fh)):
            out.append((r["Tweet"], {"row": i, "date": r["Date"], "text": r["Tweet"], "ticker": r["Stock Name"],
                                     "company": r["Company Name"]}))
    return out


def headlines() -> list[tuple[str, dict]]:
    out = []
    for outlet in ("reuters", "cnbc", "guardian"):
        with (K / "financial-news-headlines" / f"{outlet}_headlines.csv").open(newline="", encoding="utf-8") as fh:
            for i, r in enumerate(csv.DictReader(fh)):
                desc = r.get("Description") or None
                out.append((f"{r['Headlines']} {desc or ''}", {"outlet": outlet, "row": i, "time": r["Time"],
                                                               "text": r["Headlines"], "description": desc}))
    return out


def top_tweets() -> list[tuple[str, dict]]:
    base = K / "tweets-about-the-top-companies-from-2015-to-2020"
    sample: dict[str, dict] = {}
    with (base / "Tweet.csv").open(newline="", encoding="utf-8") as fh:  # 3.7M rows: hash-sample before anything else
        for r in csv.DictReader(fh):
            if int(h(r["tweet_id"])[:8], 16) % 24 == 0:
                try:
                    ts = int(r["post_date"])
                except ValueError:
                    ts = None
                sample[r["tweet_id"]] = {"tweet_id": r["tweet_id"], "writer": r["writer"], "post_date": ts, "text": r["body"],
                                         "tickers": []}
    with (base / "Company_Tweet.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["tweet_id"] in sample:
                sample[r["tweet_id"]]["tickers"].append(r["ticker_symbol"])
    return [(rec["text"], rec) for rec in sample.values()]


def gkg() -> list[tuple[str, dict]]:
    keep = ("url", "title", "seendate", "domain", "language", "x_gkg_id", "x_time_origin", "x_tone", "x_orgs")
    out = []
    for line in (RAW / "gdelt_gkg" / "filtered.jsonl").read_text(encoding="utf-8").split("\n"):
        if line.strip():
            r = json.loads(line)
            out.append((r["title"], {k: r[k] for k in keep if k in r}))
    return out


def jsonl(records: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)


def main() -> None:
    cur = Curator()
    plan = [
        ("stock-tweets", "SOCIAL", "sources/stock_tweets.jsonl", stock_tweets, "CC0",
         "equinxx/stock-tweets-for-sentiment-analysis-and-prediction (Kaggle)", "https://www.kaggle.com/datasets/equinxx/stock-tweets-for-sentiment-analysis-and-prediction"),
        ("headlines", "NEWS", "sources/headlines.jsonl", headlines, "CC0",
         "notlucasp/financial-news-headlines (Kaggle): Reuters, CNBC, Guardian", "https://www.kaggle.com/datasets/notlucasp/financial-news-headlines"),
        ("top-tweets", "SOCIAL", "sources/top_tweets.jsonl", top_tweets, "CC0",
         "omermetinn/tweets-about-the-top-companies-from-2015-to-2020 (Kaggle), hash-sampled", "https://www.kaggle.com/datasets/omermetinn/tweets-about-the-top-companies-from-2015-to-2020"),
        ("gdelt-gkg", "NEWS", "sources/gkg.jsonl", gkg, "GDELT terms: free reuse with citation",
         "The GDELT Project, GKG 2.1 bulk files (filtered)", "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt"),
    ]
    sources = []
    for name, stype, rel, loader, lic, attr, url in plan:
        print(f"{name}: loading...", flush=True)
        kept = cur.keep(name, loader())
        atomic_write_text(OUT / rel, jsonl(kept))
        s = cur.stats[name]
        print(f"  {s} -> {len(kept)} records", flush=True)
        sources.append({"name": name, "adapter": name, "source_type": stype, "file": rel, "sha256": sha256_file(OUT / rel),
                        "records": len(kept), "license": lic, "attribution": attr, "origin_url": url,
                        "notes": f"Curated: {s['kept_resolved']} documents the entity resolver ties to an issuer + {s['kept_unresolved']} unresolved "
                                 f"(of {s['candidates']} candidates). NOT committed to git."})
    for f in ("entities.json", "portfolio.json"):
        atomic_write_text(OUT / f, (REPLAY / f).read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1, "snapshot_id": SNAPSHOT_ID,
        "description": "History snapshot for impact modelling: dated tweets, headlines and GKG rows, 2015-2026. Git-ignored.",
        "replay_as_of": AS_OF.isoformat().replace("+00:00", "Z"), "window_start": WINDOW[0].isoformat().replace("+00:00", "Z"),
        "window_end": WINDOW[1].isoformat().replace("+00:00", "Z"), "sources": sources,
        "entities": {"file": "entities.json", "sha256": sha256_file(OUT / "entities.json")},
        "portfolio": {"file": "portfolio.json", "sha256": sha256_file(OUT / "portfolio.json")}, "fetch_log": [],
    }
    atomic_write_text(OUT / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(f"history snapshot written to {OUT}")


if __name__ == "__main__":
    main()
