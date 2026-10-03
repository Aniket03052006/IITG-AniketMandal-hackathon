"""Build the committed structured-event tables from the downloaded EDGAR and FOMC pages (offline, deterministic).

Inputs (git-ignored, from `make fetch-edgar fetch-fomc`):
    data/raw/edgar/*.json       SEC submissions index per issuer (and predecessor registrants)
    data/raw/fomc/*.htm         federalreserve.gov calendar pages
Outputs (committed; derived, public-domain facts, a few MB):
    data/events/sec_filings.jsonl   one row per 8-K / 10-K / 10-Q / 6-K / 20-F: ticker, accession, exact acceptance time (UTC), form, items
    data/events/fomc.json           FOMC decision dates (scheduled flag)
    data/events/manifest.json       sha256 of every file, counts, per-issuer coverage, known gaps

    python scripts/build_event_calendar.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eventshock.ingestion.edgar import load_filings, ticker_to_cik  # noqa: E402
from eventshock.ingestion.fetch import FetchError  # noqa: E402
from eventshock.ingestion.fomc import fetch_fomc  # noqa: E402
from eventshock.ingestion.snapshot import atomic_write_text, sha256_file  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "events"
SCHEMA_VERSION = 1
FIRST_YEAR, LAST_YEAR = 2014, 2026
DEDUP_SECONDS = 300  # same issuer, form and items from two different registrants within this window: one event


def _no_network(url: str, timeout: float) -> tuple[int, bytes]:
    raise FetchError(f"{url} is not cached in data/raw/fomc: run `make fetch-fomc` first")


def _secs(stamp: str) -> int:
    from datetime import UTC, datetime

    return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())


def collapse(rows: list[dict]) -> tuple[list[dict], int]:
    """Drop a near-simultaneous copy of one event filed by a *different* registrant of the same issuer (holding-company transitions).

    Two filings by the same registrant are never merged, even seconds apart: foreign issuers file several 6-Ks in a burst. Rows sorted by time.
    """
    kept: list[dict] = []
    last: dict[tuple, tuple[int, int]] = {}
    dropped = 0
    for r in rows:
        key = (r["ticker"], r["form"], tuple(r["items"]))
        t = _secs(r["acceptance_utc"])
        if key in last and last[key][1] != r["cik"] and t - last[key][0] <= DEDUP_SECONDS:
            dropped += 1
            continue
        last[key] = (t, r["cik"])
        kept.append(r)
    return kept, dropped


def main() -> None:
    raw = RAW / "edgar"
    symbols = [s for s in json.loads((RAW / "prices" / "symbols.json").read_text(encoding="utf-8")) if not s.startswith("^")]
    cik_map = ticker_to_cik(json.loads((raw / "company_tickers.json").read_text(encoding="utf-8")))
    rows: list[dict] = []
    coverage: dict[str, dict] = {}
    for t in symbols:
        r = load_filings(raw, t, cik_map[t])
        rows += r
        forms = Counter(x["form"] for x in r)
        eights = [x for x in r if x["form"] == "8-K"]
        coverage[t] = {"forms": dict(sorted(forms.items())), "first": r[0]["acceptance_utc"], "last": r[-1]["acceptance_utc"],
                       "eight_k_with_items": sum(1 for x in eights if x["items"]),
                       "item_codes": "none (foreign private issuer: 6-K/20-F carry no item codes)" if not eights else "8-K items"}
    rows.sort(key=lambda r: (r["acceptance_utc"], r["ticker"], r["accession"]))
    rows, dropped = collapse(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUT / "sec_filings.jsonl",
                      "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))
    fomc = fetch_fomc(FIRST_YEAR, LAST_YEAR, raw_dir=RAW / "fomc", transport=_no_network)
    atomic_write_text(OUT / "fomc.json", json.dumps({"source": "federalreserve.gov FOMC calendars", "meetings": fomc}, indent=1) + "\n")

    per_year: dict[str, Counter] = defaultdict(Counter)
    items = Counter()
    for r in rows:
        per_year[r["acceptance_utc"][:4]][r["form"]] += 1
        if r["form"] == "8-K":
            items.update(r["items"] or ["(none)"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "description": "Structured event calendar: SEC filing acceptance times and 8-K item codes for the 34 issuers, and FOMC decision dates.",
        "sources": {
            "sec_filings": {"origin": "https://data.sec.gov/submissions/ (EDGAR submissions index)", "licence": "US government work, public domain; "
                            "SEC fair-access policy followed (declared contact, <= 10 req/s)",
                            "file": "sec_filings.jsonl", "sha256": sha256_file(OUT / "sec_filings.jsonl"), "rows": len(rows),
                            "near_duplicates_collapsed": dropped},
            "fomc": {"origin": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm and fomchistorical<year>.htm",
                     "licence": "US government work, public domain", "file": "fomc.json", "sha256": sha256_file(OUT / "fomc.json"),
                     "meetings": len(fomc), "unscheduled": sum(not m["scheduled"] for m in fomc)},
        },
        "rows_by_year_and_form": {y: dict(sorted(c.items())) for y, c in sorted(per_year.items())},
        "eight_k_item_counts": dict(items.most_common()),
        "coverage_by_issuer": coverage,
        "known_gaps": [
            "SHEL and BP are foreign private issuers: they file 6-K / 20-F, which carry no item codes, so item features are unavailable for them.",
            "Predecessor registrants merged (GOOGL: Google Inc. before Alphabet; XOM: Exxon Mobil Corp alongside the 2026 holding company).",
            "Filings without an acceptance time (paper era) are dropped; none exist after 2014.",
            "Earnings dates come from 8-K item 2.02 acceptance times: that is when results were published, not the date announced in advance.",
            "Realised EPS surprise needs consensus estimates, which are not free: not obtained, never a feature.",
            "Jobs / CPI release calendars (BLS) were not obtained; only FOMC dates are in the macro calendar.",
        ],
    }
    atomic_write_text(OUT / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"events: {len(rows)} filings ({dropped} near-duplicates collapsed), {len(fomc)} FOMC decisions -> {OUT}")


if __name__ == "__main__":
    main()
