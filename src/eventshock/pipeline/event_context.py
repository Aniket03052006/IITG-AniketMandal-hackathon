"""Structured event context: what the calendar says about a report *at the moment it appears*.

One implementation for training and serving (like ``market_context.anchor_session``). Every feature has exactly one availability class:

* ``a`` known before the event: scheduled or announced ahead, or a pure function of filings accepted strictly *earlier* than the report
  (the expected earnings date is projected from the issuer's own earlier item-2.02 filings; FOMC decision dates are published a year ahead);
* ``b`` published at event time: a filing the SEC accepted strictly *before* the report's own timestamp;
* ``c`` known only after (the realised EPS surprise, any filing accepted at or after the report, later periodic reports): never computed here,
  registered POST_EVENT in ``modeling.leakage`` so a model that asks for one is refused.

Point-in-time contract: a feature of a report at time ``t`` reads only filings with ``acceptance < t`` (strict). ``calendar_future_invariance``
(``modeling.leakage``) perturbs every filing at or after ``t`` and requires bit-identical features. One honest caveat, stated in the docs:
the FOMC calendar was read from a 2026 snapshot; scheduled meeting dates are announced well ahead, so this is point-in-time for scheduled
meetings (changed meetings are rare and would only add noise).
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from ..config import ConfigError

NAN = float("nan")
FILING_FORMS_EVENT = "8-K"
EARNINGS_ITEM = "2.02"
MAX_DAYS = 120.0

# name -> availability class, and the group of items a flag covers (groups come from configs/sec_items.yaml)
ISSUER_CALENDAR: dict[str, str] = {
    "earn_days_to_expected": "a", "earn_window": "a", "earn_days_since_last": "a",
    "f8k_hours_since_last": "b", "f8k_count_24h": "b", "f8k_earnings_24h": "b", "f8k_deal_24h": "b", "f8k_distress_24h": "b",
    "f8k_financing_24h": "b", "f8k_leadership_24h": "b",
    "fomc_s0": "a", "fomc_s1": "a",
}
MARKET_CALENDAR: dict[str, str] = {"fomc_s0": "a", "fomc_s1": "a"}
FLAG_GROUPS = {"f8k_earnings_24h": "earnings", "f8k_deal_24h": "deal", "f8k_distress_24h": "distress",
               "f8k_financing_24h": "financing", "f8k_leadership_24h": "leadership"}


@dataclass(frozen=True)
class Filing:
    acceptance: datetime  # UTC
    accession: str
    form: str
    items: tuple[str, ...]


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


class EventCalendar:
    """SEC filings per issuer (sorted by acceptance time) and scheduled FOMC decision dates. Read-only."""

    def __init__(self, filings: list[dict[str, Any]], fomc: list[dict[str, Any]], items_cfg: dict[str, Any],
                 *, recent_hours: float = 24.0, earnings_lookback_years: int = 2) -> None:
        by: dict[str, list[Filing]] = {}
        for r in filings:
            by.setdefault(r["ticker"], []).append(Filing(_parse(r["acceptance_utc"]), r["accession"], r["form"], tuple(r["items"])))
        self._filings = {t: sorted(v, key=lambda f: (f.acceptance, f.accession)) for t, v in by.items()}
        self._times = {t: [f.acceptance for f in v] for t, v in self._filings.items()}
        self._earn = {t: [f.acceptance for f in v if f.form == FILING_FORMS_EVENT and EARNINGS_ITEM in f.items] for t, v in self._filings.items()}
        self._fomc = frozenset(m["decision_date"] for m in fomc if m.get("scheduled", True))
        groups = items_cfg.get("groups", {})
        self._groups = {name: frozenset(groups[g]) for name, g in FLAG_GROUPS.items()}
        self._exhibit_only = frozenset(items_cfg.get("exhibit_only_items", ["9.01"]))
        self.recent = timedelta(hours=recent_hours)
        self.lookback_years = earnings_lookback_years
        self.digests: dict[str, str] = {}  # sha256 of the files this calendar was loaded from ({} when built in memory)

    @classmethod
    def load(cls, events_dir: Path, items_path: Path, *, recent_hours: float = 24.0, earnings_lookback_years: int = 2) -> EventCalendar:
        try:
            filings = [json.loads(x) for x in (events_dir / "sec_filings.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
            fomc = json.loads((events_dir / "fomc.json").read_text(encoding="utf-8"))["meetings"]
            items = yaml.safe_load(items_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError) as exc:
            raise ConfigError(f"event calendar unreadable ({exc}): rebuild with `make events-calendar`") from exc
        cal = cls(filings, fomc, items, recent_hours=recent_hours, earnings_lookback_years=earnings_lookback_years)
        import hashlib

        cal.digests = {n: hashlib.sha256(p.read_bytes()).hexdigest()
                       for n, p in (("sec_filings", events_dir / "sec_filings.jsonl"), ("fomc", events_dir / "fomc.json"), ("sec_items", items_path))}
        return cal

    def has_issuer(self, ticker: str) -> bool:
        return ticker in self._filings

    # ---------------------------------------------------------------- (b) published at event time
    def _recent_8k(self, ticker: str, t: datetime) -> list[Filing]:
        """8-K filings accepted strictly before ``t`` and within the recent window, excluding exhibit-only filings."""
        times = self._times.get(ticker, [])
        hi = bisect_left(times, t)  # strictly before t
        lo = bisect_left(times, t - self.recent)
        return [f for f in self._filings.get(ticker, [])[lo:hi]
                if f.form == FILING_FORMS_EVENT and any(i not in self._exhibit_only for i in f.items)]

    def _hours_since_last(self, ticker: str, t: datetime) -> float:
        times = self._times.get(ticker, [])
        hi = bisect_left(times, t)
        for f in reversed(self._filings.get(ticker, [])[:hi]):
            if f.form == FILING_FORMS_EVENT and any(i not in self._exhibit_only for i in f.items):
                return min((t - f.acceptance).total_seconds() / 3600.0, 24.0 * 30)
        return NAN

    # ---------------------------------------------------------------- (a) known before the event
    def earnings_features(self, ticker: str, t: datetime) -> dict[str, float]:
        """Days to the expected next earnings release (projected from the issuer's own earlier 2.02 dates), the window flag, days since the last."""
        earn = self._earn.get(ticker, [])
        hi = bisect_left(earn, t)  # earlier filings only
        prior = earn[:hi]
        out = {"earn_days_to_expected": NAN, "earn_window": NAN, "earn_days_since_last": NAN}
        if not prior:
            return out
        out["earn_days_since_last"] = min((t - prior[-1]).total_seconds() / 86400.0, MAX_DAYS)
        cutoff = t - timedelta(days=365 * self.lookback_years + 10)
        cands: list[float] = []
        for d in prior:
            if d < cutoff:
                continue
            for k in range(1, self.lookback_years + 1):  # the same quarter in a later year: 52-week steps keep the weekday
                delta = ((d + timedelta(days=364 * k)) - t).total_seconds() / 86400.0
                if -1.5 <= delta <= MAX_DAYS:  # just passed (the release may be today) or still ahead
                    cands.append(delta)
        if cands:
            nearest = min(cands, key=lambda c: abs(c))
            out["earn_days_to_expected"] = nearest
            out["earn_window"] = 1.0 if abs(nearest) <= 1.5 else 0.0
        return out

    def fomc_features(self, s0_date: str | None, s1_date: str | None) -> dict[str, float]:
        """Scheduled FOMC decision on the reaction session ``s0`` or the next one (the two sessions the target window covers)."""
        return {"fomc_s0": NAN if s0_date is None else float(s0_date in self._fomc),
                "fomc_s1": NAN if s1_date is None else float(s1_date in self._fomc)}

    def issuer_features(self, ticker: str, t: datetime, s0_date: str | None, s1_date: str | None) -> dict[str, float]:
        recent = self._recent_8k(ticker, t)
        out = {**self.earnings_features(ticker, t), "f8k_hours_since_last": self._hours_since_last(ticker, t),
               "f8k_count_24h": float(len(recent))}
        for name, grp in self._groups.items():
            out[name] = float(any(i in grp for f in recent for i in f.items))
        out.update(self.fomc_features(s0_date, s1_date))
        return {k: out[k] for k in ISSUER_CALENDAR}

    def market_features(self, s0_date: str | None, s1_date: str | None) -> dict[str, float]:
        return self.fomc_features(s0_date, s1_date)

    def perturbed_from(self, t: datetime, seed: int = 1) -> EventCalendar:
        """A copy whose filings accepted at or after ``t`` are replaced by shifted decoys (leakage test: features at ``t`` must not move)."""
        rows = []
        for tk, fl in self._filings.items():
            for f in fl:
                if f.acceptance >= t:
                    f = Filing(f.acceptance + timedelta(hours=7 + seed), f.accession + "-x", f.form, ("2.02", "1.03", "5.02"))
                rows.append({"ticker": tk, "acceptance_utc": f.acceptance.strftime("%Y-%m-%dT%H:%M:%SZ"), "accession": f.accession,
                             "form": f.form, "items": list(f.items)})
        clone = EventCalendar.__new__(EventCalendar)
        clone.__dict__.update(self.__dict__)
        by: dict[str, list[Filing]] = {}
        for r in rows:
            by.setdefault(r["ticker"], []).append(Filing(_parse(r["acceptance_utc"]), r["accession"], r["form"], tuple(r["items"])))
        clone._filings = {k: sorted(v, key=lambda f: (f.acceptance, f.accession)) for k, v in by.items()}
        clone._times = {k: [f.acceptance for f in v] for k, v in clone._filings.items()}
        clone._earn = {k: [f.acceptance for f in v if f.form == FILING_FORMS_EVENT and EARNINGS_ITEM in f.items] for k, v in clone._filings.items()}
        return clone


def session_dates(dates: list[str], s0: int) -> tuple[str | None, str | None]:
    """ISO dates of sessions ``s0`` and ``s0 + 1`` from a trading calendar (``None`` beyond it)."""
    n = len(dates)
    return (dates[s0] if 0 <= s0 < n else None, dates[s0 + 1] if 0 <= s0 + 1 < n else None)


def is_finite(x: float) -> bool:
    return not (x != x or math.isinf(x))


def filing_events(calendar: EventCalendar, ticker: str) -> list[Filing]:
    """The issuer's 8-K filings that carry at least one non-exhibit item (the events of the filing-anchored study), time ordered."""
    return [f for f in calendar._filings.get(ticker, []) if f.form == FILING_FORMS_EVENT and any(i not in calendar._exhibit_only for i in f.items)]


__all__ = ["EventCalendar", "Filing", "ISSUER_CALENDAR", "MARKET_CALENDAR", "filing_events", "session_dates", "date"]
