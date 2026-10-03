"""Event-time market context: session anchoring and the frozen per-session feature pack the server reads.

Why this module sits in ``pipeline`` (not ``modeling``): the serving path needs exactly the training-time rules for "which
session does this report land in" and "what did the market look like just before it", but must never import the training
package (``modeling`` imports ``pipeline``, so the reverse would be a cycle) and must never read raw prices (non-redistributable,
git-ignored). The pack is built once, by ``eventshock.modeling.market_pack``, from the same ``PriceStore.features_asof``
code that built the training table, so train and serve see identical numbers (to ``QUANT_DIGITS`` significant digits).

Point-in-time contract: every feature stored under session key ``S`` was computed from sessions strictly before ``S``.
``NEXT`` is the session after the last one in the calendar (its date is not yet known): reports published after the last
close land there, and its features read only the sessions that already exist.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import ConfigError

NEXT = "NEXT"
PACK_SCHEMA = 1
QUANT_DIGITS = 6
MAX_GAP_DAYS = 5  # a report this far past the last known session has no honest "next session"

DATE_ONLY = "SOURCE_DATE_ONLY"
GDELT_FIRST_SEEN = "GDELT_FIRST_SEEN"
TIMING_FLAGS = ("PRE_OPEN", "IN_SESSION", "DATE_ONLY", "FIRST_SEEN")  # OFF_HOURS is the baseline (all flags 0)


@dataclass(frozen=True)
class SessionRules:
    """When the exchange trades (local clock). A report at/after ``close`` reacts in the next session."""

    timezone: str
    open: time
    close: time

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def quantize(x: float | None) -> float | None:
    """Round to ``QUANT_DIGITS`` significant digits; NaN stays NaN. Training and the pack use this same function."""
    if x is None:
        return None
    if x != x:
        return x
    return float(f"{x:.{QUANT_DIGITS}g}")


def quantize_features(feats: dict[str, float]) -> dict[str, float]:
    return {k: quantize(v) for k, v in feats.items()}  # type: ignore[misc]


def anchor_session(dates: list[str], ts: datetime, origin: str, rules: SessionRules, *,
                   allow_next: bool = False) -> tuple[int | None, str]:
    """``(s0, timing)``: ``s0`` is the index of the first session whose close is after publication.

    timing: OFF_HOURS (after close / weekend / holiday: the whole reaction follows the report), PRE_OPEN, IN_SESSION (part of
    the session's move precedes the report: contaminated), DATE_ONLY (no time of day), FIRST_SEEN (GDELT crawl time, which
    lags publication). Early-close days are treated as ordinary sessions. ``s0 == len(dates)`` (the unknown next session)
    is returned only when ``allow_next``; otherwise a report beyond the calendar has no anchor (``None``).
    """
    n = len(dates)
    if origin == DATE_ONLY:
        i = bisect_left(dates, ts.astimezone(UTC).date().isoformat())
        return (i if (i < n or (allow_next and i == n)) else None), "DATE_ONLY"
    local = ts.astimezone(rules.tz)
    d = local.date().isoformat()
    i = bisect_left(dates, d)
    is_session = i < n and dates[i] == d
    t = local.time()
    if is_session and t < rules.close:
        s0, timing = i, ("PRE_OPEN" if t < rules.open else "IN_SESSION")
    else:
        s0, timing = (i + 1 if is_session else i), "OFF_HOURS"
    if origin == GDELT_FIRST_SEEN:
        timing = "FIRST_SEEN"
    return (s0 if (s0 < n or (allow_next and s0 == n)) else None), timing


def doc_time_features(ts: datetime, rules: SessionRules) -> tuple[int, float]:
    """(weekday 0=Mon, exchange-local hour as a fraction): known from the timestamp alone."""
    local = ts.astimezone(rules.tz)
    return local.weekday(), local.hour + local.minute / 60


def timing_flags(timing: str) -> dict[str, float]:
    return {f"t_{k.lower()}": 1.0 if timing == k else 0.0 for k in TIMING_FLAGS}


# -------------------------------------------------------------------------------------------------------- the pack
def pack_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class MarketContext:
    """The frozen pack: trading calendar tail plus per-(entity, session) as-of features. Read-only."""

    def __init__(self, payload: dict[str, Any], rules: SessionRules | None = None) -> None:
        try:
            if payload["schema_version"] != PACK_SCHEMA:
                raise ConfigError(f"market context schema_version {payload['schema_version']} != {PACK_SCHEMA}")
            self.feature_schema: str = payload["feature_schema"]
            self.dates: list[str] = list(payload["calendar"])
            self.last_session: str = payload["last_session"]
            self.issuer: dict[str, dict[str, dict[str, float]]] = payload["issuer"]
            self.market: dict[str, dict[str, float]] = payload["market"]
            self.built_from: dict[str, Any] = payload["built_from"]
            r = payload["session_rules"]
            self.rules = rules or SessionRules(r["timezone"], time.fromisoformat(r["open"]), time.fromisoformat(r["close"]))
        except KeyError as exc:
            raise ConfigError(f"market context is missing {exc}; rebuild it with `make market-context`") from exc
        claimed = payload.get("digest")
        if claimed is not None and claimed != pack_digest({k: v for k, v in payload.items() if k != "digest"}):
            raise ConfigError("market context content does not match its own digest: the file was edited by hand")
        if self.dates != sorted(set(self.dates)) or not self.dates or self.dates[-1] != self.last_session:
            raise ConfigError("market context calendar must be sorted, unique, and end at last_session")

    @classmethod
    def load(cls, path: Path) -> MarketContext:
        if not path.is_file():
            raise ConfigError(f"market context file missing: {path}; rebuild it with `make market-context`")
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except ValueError as exc:
            raise ConfigError(f"invalid market context {path}: {exc}") from exc

    def anchor(self, ts: datetime, origin: str) -> tuple[str | None, str, str | None]:
        """``(session key, timing, reason-if-none)``. The key is an ISO date or ``NEXT``."""
        s0, timing = anchor_session(self.dates, ts, origin, self.rules, allow_next=True)
        if s0 is None:
            return None, timing, "report is after the market-context calendar"
        if s0 == len(self.dates):
            last = date.fromisoformat(self.last_session)
            if ts.astimezone(self.rules.tz).date() - last > timedelta(days=MAX_GAP_DAYS):
                return None, timing, f"report is more than {MAX_GAP_DAYS} days after the last known session {self.last_session}"
            return NEXT, timing, None
        return self.dates[s0], timing, None

    @staticmethod
    def _nan(feats: dict[str, float | None] | None) -> dict[str, float] | None:
        return None if feats is None else {k: (float("nan") if v is None else float(v)) for k, v in feats.items()}

    def issuer_features(self, ticker: str, key: str) -> dict[str, float] | None:
        """As-of features of an issuer at a session (``None`` values come back as NaN), or None if the pack has none."""
        return self._nan(self.issuer.get(ticker, {}).get(key))

    def market_features(self, key: str) -> dict[str, float] | None:
        return self._nan(self.market.get(key))
