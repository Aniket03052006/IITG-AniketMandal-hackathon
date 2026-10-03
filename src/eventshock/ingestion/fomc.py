"""FOMC meeting calendar from federalreserve.gov (public): the dates the policy decision is released.

Scheduled meetings are announced a year or more ahead, so they are *known before the event*; unscheduled meetings (e.g. March 2020) are not,
and are recorded but flagged ``scheduled = False`` so a feature built from the calendar can exclude them. The decision (statement) is released on
the last day of a meeting, during the session, so ``decision_date`` is that last day. Cancelled meetings and notation votes are dropped.

Parsing is pure and unit-tested against saved page fragments; only ``fetch_fomc`` touches the network. Pages: the current calendar
(2021 and later) and one historical page per earlier year. A page that yields no meetings is an error, never an empty year.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from .fetch import FetchError, Transport, get_bytes, urllib_transport
from .snapshot import atomic_write_text

CURRENT_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
HISTORICAL_URL = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
CURRENT_FROM = 2021  # the current page lists 2021 onwards; earlier years have a historical page each
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September",
                                      "October", "November", "December"], start=1)}
ABBREV = {k[:3]: v for k, v in MONTHS.items()}


def _month(name: str) -> int:
    key = name.strip()[:3]
    if key not in ABBREV:
        raise FetchError(f"unrecognised month {name!r}")
    return ABBREV[key]


def _meeting(year: int, month_text: str, day_text: str, *, flags: str = "") -> dict[str, Any] | None:
    """One meeting from its month cell (``March`` or ``Apr/May``) and day cell (``17-18``, ``30-1``, ``22``). None: not a decision meeting."""
    low = (flags + " " + day_text).lower()
    if "cancel" in low or "notation" in low:
        return None
    months = [_month(m) for m in month_text.split("/")]
    days = [int(d) for d in re.findall(r"\d{1,2}", day_text)]
    if not days:
        raise FetchError(f"no day in {day_text!r}")
    start_month, end_month = months[0], months[-1]
    start_day, end_day = days[0], days[-1]
    if len(days) > 1 and end_day < start_day and end_month == start_month:
        end_month = start_month % 12 + 1  # "30-1" on a single-month label: the meeting ends in the next month
    end_year = year + (1 if end_month < start_month else 0)
    return {"start": date(year, start_month, start_day).isoformat(), "decision_date": date(end_year, end_month, end_day).isoformat(),
            "scheduled": "unscheduled" not in low, "projections": "*" in day_text}


def parse_current(html: str) -> list[dict[str, Any]]:
    """The 2021+ calendar page: ``<year> FOMC Meetings`` headings, each followed by month and date cells."""
    heads = list(re.finditer(r"(\d{4}) FOMC Meetings", html))
    out: list[dict[str, Any]] = []
    for i, h in enumerate(heads):
        year = int(h.group(1))
        end = heads[i + 1].start() if i + 1 < len(heads) else len(html)
        block = html[h.end():end]
        months = re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>', block)
        dates = re.findall(r'fomc-meeting__date[^>]*>([^<]+)<', block)
        if len(months) != len(dates):
            raise FetchError(f"{year}: {len(months)} month cells but {len(dates)} date cells")
        for m, d in zip(months, dates, strict=True):
            row = _meeting(year, m, d)
            if row:
                out.append(row)
    return out


_HIST = re.compile(r"((?:January|February|March|April|May|June|July|August|September|October|November|December)(?:/[A-Z][a-z]+)?)"
                   r" (\d{1,2})(?:-(?:((?:January|February|March|April|May|June|July|August|September|October|November|December)) )?(\d{1,2}))?"
                   r"(\*)?( \([a-z ]+\))? Meeting - (\d{4})")


def parse_historical(html: str, year: int) -> list[dict[str, Any]]:
    """A ``fomchistorical<year>.htm`` page: lines like ``March 17-18 (cancelled) Meeting - 2020`` or ``April 30-May 1 Meeting - 2019``."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    out: list[dict[str, Any]] = []
    for m in _HIST.finditer(text):
        if int(m.group(7)) != year:
            continue
        month_text, d1, end_month_name, d2, star, flag = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
        if end_month_name:  # "April 30-May 1"
            month_text = f"{month_text}/{end_month_name}"
        day_text = d1 + (f"-{d2}" if d2 else "") + (star or "")
        row = _meeting(year, month_text, day_text, flags=flag or "")
        if row:
            out.append(row)
    return out


def fetch_fomc(first_year: int, last_year: int, *, raw_dir: Path, transport: Transport = urllib_transport,
               sleep: Callable[[float], None] = time.sleep) -> list[dict[str, Any]]:
    """Meetings for ``first_year..last_year`` (decision dates inside the range), raw pages cached in ``raw_dir``."""
    raw_dir.mkdir(parents=True, exist_ok=True)

    def page(name: str, url: str) -> str:
        path = raw_dir / name
        if not path.is_file():
            atomic_write_text(path, get_bytes(url, transport=transport, timeout=60.0, sleep=sleep).decode("utf-8", errors="replace"))
            sleep(1.0)
        return path.read_text(encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for year in range(first_year, min(last_year, CURRENT_FROM - 1) + 1):
        got = parse_historical(page(f"fomchistorical{year}.htm", HISTORICAL_URL.format(year=year)), year)
        if not got:
            raise FetchError(f"{year}: no FOMC meetings parsed from the historical page")
        rows += got
    if last_year >= CURRENT_FROM:
        got = parse_current(page("fomccalendars.htm", CURRENT_URL))
        if not got:
            raise FetchError("no FOMC meetings parsed from the current calendar page")
        rows += got
    keep = {r["decision_date"]: r for r in rows if first_year <= int(r["decision_date"][:4]) <= last_year}
    return [keep[k] for k in sorted(keep)]


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--first-year", type=int, default=2014)
    ap.add_argument("--last-year", type=int, default=2026)
    ap.add_argument("--out", type=Path, required=True, help="directory for the cached raw pages (git-ignored)")
    args = ap.parse_args(argv)
    rows = fetch_fomc(args.first_year, args.last_year, raw_dir=args.out)
    print(f"fomc: {len(rows)} decision dates {rows[0]['decision_date']}..{rows[-1]['decision_date']} "
          f"({sum(not r['scheduled'] for r in rows)} unscheduled) -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
