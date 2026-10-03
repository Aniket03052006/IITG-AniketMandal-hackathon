"""SEC EDGAR filing index: exact acceptance timestamps and 8-K item codes for the entity master (public domain).

Why this source: an 8-K carries an official event type (its *item codes*: 2.02 results of operations, 5.02 officer change, ...)
and the exact moment the SEC accepted it (``acceptanceDateTime``, UTC), so it is an event with a known type and a precise clock,
free and reproducible. Used for (a) structured event context, (b) a filing-anchored event study, (c) deterministic checks.

Network boundary: only ``fetch_edgar`` talks to sec.gov. SEC's fair-access policy asks for a declared contact in the User-Agent and at most
10 requests per second; we send ``EVENTSHOCK_SEC_CONTACT`` (environment or ``.env``, never committed) and throttle to ~4 per second.
Raw submissions JSON is kept in ``data/raw/edgar/`` (git-ignored); the committed artefact is the derived table built by
``scripts/build_event_calendar.py``. Nothing is guessed: an issuer whose filings cannot be fetched is logged and the run reports failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .fetch import FetchError, Transport, get_bytes
from .snapshot import atomic_write_text

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/"
CONTACT_VAR = "EVENTSHOCK_SEC_CONTACT"
# Forms kept in the derived table: 8-K (items), the periodic reports (earnings-cycle calendar), and the foreign-issuer equivalents.
KEPT_FORMS = frozenset({"8-K", "10-K", "10-Q", "6-K", "20-F", "40-F"})
FIRST_DATE = "2014-01-01"  # price history starts 2014-01-02
THROTTLE_SECONDS = 0.25
# Reorganised registrants: the ticker now maps to a successor CIK, but the filings of the period live under the predecessor. Both are
# fetched and merged (de-duplicated by accession). Verified against the submissions index: Google Inc. (pre-Alphabet), Exxon Mobil Corp
# (still filing; ExxonMobil Holdings Corp is the 2026 holding company).
PREDECESSOR_CIKS: dict[str, tuple[int, ...]] = {"GOOGL": (1288776,), "XOM": (34088,)}


def sec_contact(env: dict[str, str] | None = None, dotenv: Path | None = Path(".env")) -> str:
    """The declared contact for the User-Agent. Raises with instructions rather than sending an anonymous request."""
    env = dict(os.environ) if env is None else env
    value = env.get(CONTACT_VAR, "").strip()
    if not value and dotenv is not None and dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition("=")
            if key.strip() == CONTACT_VAR:
                value = rest.strip().strip("'\"")
    if not value or "@" not in value:
        raise FetchError(f"{CONTACT_VAR} is not set (an email address): SEC requires a declared contact. "
                         f"Put `{CONTACT_VAR}=you@example.com` in .env (git-ignored) or the environment.")
    return value


def sec_transport(contact: str) -> Transport:
    ua = f"EventShock-hackathon research prototype ({contact})"

    def transport(url: str, timeout: float) -> tuple[int, bytes]:
        if not url.startswith("https://"):
            raise FetchError(f"refusing non-https url: {url}")
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FetchError(f"network error for {url}: {exc}") from exc

    return transport


def ticker_to_cik(payload: Any) -> dict[str, int]:
    """``company_tickers.json`` is ``{"0": {"cik_str": 320193, "ticker": "AAPL", "title": ...}, ...}``."""
    if not isinstance(payload, dict):
        raise FetchError("company_tickers.json: unexpected shape")
    out: dict[str, int] = {}
    for row in payload.values():
        try:
            out.setdefault(str(row["ticker"]).upper(), int(row["cik_str"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise FetchError(f"company_tickers.json: malformed row {row!r}") from exc
    return out


def cik10(cik: int) -> str:
    return f"{int(cik):010d}"


def filing_rows(page: Any, *, ticker: str, cik: int) -> list[dict[str, Any]]:
    """Parallel arrays of one submissions page (``filings.recent`` or an overflow file) -> one dict per kept filing."""
    if not isinstance(page, dict) or "accessionNumber" not in page:
        raise FetchError(f"{ticker}: unexpected submissions page shape")
    n = len(page["accessionNumber"])
    cols = {k: page.get(k) or [""] * n for k in ("form", "filingDate", "acceptanceDateTime", "items", "primaryDocument",
                                                   "primaryDocDescription")}
    for k, v in cols.items():
        if len(v) != n:
            raise FetchError(f"{ticker}: column {k} has {len(v)} entries, expected {n}")
    rows = []
    for i in range(n):
        form = cols["form"][i]
        if form not in KEPT_FORMS or cols["filingDate"][i] < FIRST_DATE:
            continue
        accepted = cols["acceptanceDateTime"][i]
        if not accepted:  # old paper-era filings carry no acceptance time: unusable as an event clock, never invented
            continue
        rows.append({
            "ticker": ticker, "cik": cik, "accession": page["accessionNumber"][i], "form": form,
            "filing_date": cols["filingDate"][i], "acceptance_utc": accepted.replace(".000Z", "Z"),
            "items": [x for x in cols["items"][i].split(",") if x] if cols["items"][i] else [],
            "primary_document": cols["primaryDocument"][i],
        })
    return rows


def fetch_edgar(tickers: Iterable[str], *, out_dir: Path, transport: Transport, sleep: Callable[[float], None] = time.sleep,
                progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Download each issuer's submissions JSON (and overflow pages) into ``out_dir``. Resumable: existing files are kept."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tickers_path = out_dir / "company_tickers.json"
    if not tickers_path.is_file():
        atomic_write_text(tickers_path, get_bytes(TICKERS_URL, transport=transport, timeout=60.0).decode("utf-8"))
        sleep(THROTTLE_SECONDS)
    cik_map = ticker_to_cik(json.loads(tickers_path.read_text(encoding="utf-8")))
    log: list[dict[str, Any]] = []
    for t in tickers:
        cik = cik_map.get(t.upper())
        if cik is None:
            log.append({"ticker": t, "status": "error", "error": "ticker not in company_tickers.json"})
            continue
        try:
            pages = 0
            for c in (cik, *PREDECESSOR_CIKS.get(t.upper(), ())):
                main_path = out_dir / f"CIK{cik10(c)}.json"
                if not main_path.is_file():
                    atomic_write_text(main_path, get_bytes(f"{SUBMISSIONS_URL}CIK{cik10(c)}.json", transport=transport,
                                                           timeout=60.0).decode("utf-8"))
                    sleep(THROTTLE_SECONDS)
                main = json.loads(main_path.read_text(encoding="utf-8"))
                for ref in main.get("filings", {}).get("files", []):
                    if ref.get("filingTo", "9999") < FIRST_DATE:
                        continue  # whole page predates the price history
                    p = out_dir / ref["name"]
                    if not p.is_file():
                        atomic_write_text(p, get_bytes(SUBMISSIONS_URL + ref["name"], transport=transport, timeout=60.0).decode("utf-8"))
                        sleep(THROTTLE_SECONDS)
                    pages += 1
            log.append({"ticker": t, "cik": cik, "status": "ok", "overflow_pages": pages})
            if progress:
                progress(f"{t} (CIK {cik}): ok, {pages} overflow page(s)")
        except (FetchError, json.JSONDecodeError) as exc:
            log.append({"ticker": t, "cik": cik, "status": "error", "error": str(exc)[-200:]})
            if progress:
                progress(f"{t}: ERROR {exc}")
    return {"log": log, "failed": [e["ticker"] for e in log if e["status"] == "error"]}


def load_filings(raw_dir: Path, ticker: str, cik: int) -> list[dict[str, Any]]:
    """All kept filing rows for one issuer (its CIK and any predecessor CIK), de-duplicated by accession, sorted by acceptance time."""
    rows: dict[str, dict[str, Any]] = {}
    for c in (cik, *PREDECESSOR_CIKS.get(ticker.upper(), ())):
        main = json.loads((raw_dir / f"CIK{cik10(c)}.json").read_text(encoding="utf-8"))
        pages = [main["filings"]["recent"]]
        for ref in main.get("filings", {}).get("files", []):
            if ref.get("filingTo", "9999") >= FIRST_DATE:
                pages.append(json.loads((raw_dir / ref["name"]).read_text(encoding="utf-8")))
        for page in pages:
            for r in filing_rows(page, ticker=ticker, cik=c):
                rows[r["accession"]] = r
    return sorted(rows.values(), key=lambda r: (r["acceptance_utc"], r["accession"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols-file", type=Path, required=True, help="JSON list of Yahoo symbols; ^-prefixed index symbols are skipped")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    tickers = [s for s in json.loads(args.symbols_file.read_text(encoding="utf-8")) if not s.startswith("^")]
    res = fetch_edgar(tickers, out_dir=args.out, transport=sec_transport(sec_contact()),
                      progress=lambda m: print(m, file=sys.stderr, flush=True))
    ok = len(tickers) - len(res["failed"])
    print(f"edgar: {ok}/{len(tickers)} issuers ok -> {args.out}")
    for t in res["failed"]:
        print(f"  FAILED: {t}")
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
