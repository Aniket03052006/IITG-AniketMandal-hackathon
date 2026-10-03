"""Per-signal context for the UI: the model's inputs grouped by family/availability, the issuer's filings placed around the report,
and (labelled, separate) what the market did afterwards.

Read-only and additive: nothing here feeds scoring, and the realised outcome is never attached to ``RiskSignal`` (so it cannot leak into a
signal and the replay output digest is untouched). Filings reuse the calendar's own point-in-time rule: a filing is "before" only if it was
accepted strictly earlier than the report, exactly as ``EventCalendar`` computes its features.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..api.schemas import ContextInput, FilingMoment, RealisedOutcome, SignalContext
from ..config import ConfigError
from ..domain import RiskSignal
from ..pipeline.event_context import EARNINGS_ITEM, EventCalendar, filing_events
from ..pipeline.impact_features_v2 import feature_group_v2

OUTCOMES_SCHEMA = "eventshock-replay-outcomes-v1"
BEFORE_DAYS = 45
AFTER_DAYS = 14
MAX_EACH_SIDE = 6
LAST_8K_CAP_DAYS = 30  # event_context caps f8k_hours_since_last at 30 days

NOT_USED = [
    "how many outlets carried the story (it would leak later coverage)",
    "any report published after this one",
    "SEC filings accepted at or after the report",
    "the realised market move",
]

OutcomeKey = tuple[str, str, str]  # (scope, ticker or "", reaction session)


@dataclass(frozen=True)
class OutcomeRow:
    scope: str
    ticker: str
    session: str
    abs_z: float
    z: float
    score: int


class Outcomes:
    """Realised outcomes per (scope, issuer, reaction session): committed, derived, read-only."""

    def __init__(self, rows: dict[OutcomeKey, OutcomeRow], window_sessions: int, definition: str) -> None:
        self.rows = rows
        self.window_sessions = window_sessions
        self.definition = definition

    @classmethod
    def load(cls, path: Path) -> Outcomes:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc["schema"] != OUTCOMES_SCHEMA:
                raise ValueError(f"schema {doc['schema']!r}")
            rows = {}
            for r in doc["rows"]:
                row = OutcomeRow(r["scope"], r["ticker"], r["session"], float(r["abs_z"]), float(r["z"]), int(r["score"]))
                rows[(row.scope, row.ticker, row.session)] = row
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigError(f"replay outcomes file unreadable ({exc}): rebuild with `make outcomes`") from exc
        return cls(rows, int(doc["window_sessions"]), str(doc["definition"]))


def availability_of(name: str) -> str:
    from ..modeling.leakage import availability_class

    if name.startswith("item_"):
        return "b"
    return availability_class(name) or "t"


def _filings(signal: RiskSignal, calendar: EventCalendar | None, as_of: datetime) -> tuple[list[FilingMoment], str | None]:
    ticker = signal.entity.ticker
    if calendar is None:
        return [], "this profile has no SEC filing calendar loaded"
    if not ticker or signal.entity.entity_id == "UNKNOWN_ENTITY":
        return [], "no single company was linked to this report, so there is no issuer to read filings for"
    if not calendar.has_issuer(ticker):
        return [], f"no SEC filings are held for {ticker}"
    t = signal.document.published_at
    all_ = filing_events(calendar, ticker)
    before = [f for f in all_ if f.acceptance < t and f.acceptance >= t - timedelta(days=BEFORE_DAYS)][-MAX_EACH_SIDE:]
    after = [f for f in all_ if f.acceptance >= t and f.acceptance <= t + timedelta(days=AFTER_DAYS)][:MAX_EACH_SIDE]
    earn_cut = t - timedelta(days=365 * calendar.lookback_years + 10)
    out: list[FilingMoment] = []
    for n, f in enumerate(before):
        recent = f.acceptance >= t - calendar.recent
        earnings = EARNINGS_ITEM in f.items and f.acceptance >= earn_cut
        latest = n == len(before) - 1 and (t - f.acceptance) <= timedelta(days=LAST_8K_CAP_DAYS)  # sets "hours since the last 8-K"
        if recent:
            role, note = "FEEDS_MODEL", "accepted within the 24 hours before the report: read by the recent-filings features"
        elif latest:
            role, note = "FEEDS_MODEL", "the most recent 8-K before the report: it sets the 'hours since the last 8-K' feature"
        elif earnings:
            role, note = "FEEDS_MODEL", "an earnings filing: the earnings-calendar features are projected from filings like it"
        else:
            role, note = "BEFORE_NOT_USED", "accepted before the report but not read by any feature (not the latest, not within 24 hours, not an earnings filing)"
        out.append(FilingMoment(accession=f.accession, form=f.form, items=list(f.items), acceptance_utc=f.acceptance,
                                hours_from_report=round((f.acceptance - t).total_seconds() / 3600.0, 2), role=role, role_note=note,
                                known_at_assessment=f.acceptance <= as_of))
    for f in after:
        out.append(FilingMoment(accession=f.accession, form=f.form, items=list(f.items), acceptance_utc=f.acceptance,
                                hours_from_report=round((f.acceptance - t).total_seconds() / 3600.0, 2), role="AFTER_REPORT",
                                role_note="accepted at or after the report: the model never reads it (the calendar is tested to ignore it)",
                                known_at_assessment=f.acceptance <= as_of))
    return out, None


def build_signal_context(signal: RiskSignal, calendar: EventCalendar | None, outcomes: Outcomes | None, as_of: datetime) -> SignalContext:
    audit = signal.provenance.impact if signal.provenance else None
    inputs = ([ContextInput(name=k, group=feature_group_v2(k), availability=availability_of(k), value=v)
               for k, v in sorted(audit.inputs.items())] if audit else [])
    filings, filings_note = _filings(signal, calendar, as_of)

    outcome: RealisedOutcome | None = None
    if outcomes is None:
        outcome_note = "realised outcomes are not available in this profile"
    elif audit is None:
        outcome_note = "no model-scored impact for this signal, so there is no stated reaction window to compare with"
    elif audit.session == "NEXT":
        outcome_note = "the reaction session had not traded when EventShock assessed this report, and no outcome is recorded for it"
    else:
        ticker = (signal.entity.ticker or "") if audit.scope.value == "ISSUER" else ""
        row = outcomes.rows.get((audit.scope.value, ticker, audit.session))
        if row is None:
            outcome_note = (f"no realised move is recorded for this {'issuer and ' if audit.scope.value == 'ISSUER' else ''}session "
                            "(the reaction window had not completed)")
        else:
            outcome = RealisedOutcome(
                scope=row.scope, ticker=row.ticker or None, session=row.session, window_sessions=outcomes.window_sessions,
                abs_z=row.abs_z, z=row.z, score=row.score,
                note=("the move of the issuer (not of this article) over the sessions after the report; direction is observed, never predicted"
                      if row.scope == "ISSUER" else "the S&P 500's own move over the sessions after the report"))
            outcome_note = outcomes.definition

    return SignalContext(
        signal_id=signal.id, report_time=signal.document.published_at,
        timestamp_origin=signal.provenance.timestamp_origin.value if signal.provenance else "UNKNOWN",
        assessed_at=signal.created_at, impact_scored=audit is not None, inputs=inputs,
        missing_inputs=sorted(audit.missing_inputs) if audit else [], not_used=NOT_USED if audit else [],
        filings=filings, filings_note=filings_note, outcome=outcome, outcome_note=outcome_note)
