"""Is the market state recent enough to be "the market at the time" of a report? An explicit policy, never a silent default.

The market state EventShock holds is the close of a trading session. For a report, the relevant session is the *last completed* one before it. The state may
lag that session by at most ``max_sessions_behind`` sessions; beyond that it is excluded from the score and the reason is shown. A state dated after the
report's last completed session is excluded too (it could not have been known). Sessions are weekdays: exchange holidays are not modelled, so around a
holiday the lag is overstated by a session at most (the conservative direction: data is excluded, not wrongly accepted).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from .config import RegimeConfig
from .model import MarketUse


def previous_weekday(day: date) -> date:
    d = day - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def last_completed_session(report: datetime, close_hour_utc: int) -> date:
    """The last weekday session that had closed when the report was published."""
    t = report.astimezone(UTC)
    day = t.date()
    if day.weekday() >= 5:
        return previous_weekday(day)  # a weekend: the Friday close (or the weekday before a Monday holiday-less run)
    return day if t.hour >= close_hour_utc else previous_weekday(day)


def sessions_between(earlier: date, later: date) -> int:
    """Number of weekday sessions after ``earlier`` up to and including ``later`` (0 when equal or ``earlier`` is later)."""
    n, d = 0, earlier
    while d < later:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def assess_market(report_time: datetime, as_of: str | None, vix: float | None, cfg: RegimeConfig) -> MarketUse:
    """Decide whether the market state may enter the score, and say why or why not."""
    limit = cfg.max_sessions_behind
    if vix is None or as_of is None:
        return MarketUse(used=False, vix=None, as_of=as_of, report_session=None, sessions_behind=None, max_sessions_behind=limit,
                         reason="No market state was recorded for this report, so the market regime is not used.")
    try:
        state = date.fromisoformat(as_of)
    except ValueError:
        return MarketUse(used=False, vix=vix, as_of=as_of, report_session=None, sessions_behind=None, max_sessions_behind=limit,
                         reason=f"The market state's date ({as_of!r}) is unreadable, so it is not used.")
    session = last_completed_session(report_time, cfg.session_close_utc_hour)
    if state > session:
        return MarketUse(used=False, vix=vix, as_of=as_of, report_session=session.isoformat(), sessions_behind=None, max_sessions_behind=limit,
                         reason=f"The market state is dated {as_of}, after the last session completed before the report ({session.isoformat()}): "
                                "it could not have been known, so it is not used.")
    behind = sessions_between(state, session)
    if behind > limit:
        return MarketUse(used=False, vix=vix, as_of=as_of, report_session=session.isoformat(), sessions_behind=behind, max_sessions_behind=limit,
                         reason=f"The market data held ends {as_of}, {behind} sessions before the last completed session ({session.isoformat()}); "
                                f"the policy allows at most {limit}. It is too stale to be the market at the time, so it is not used.")
    lag = "current" if behind == 0 else f"{behind} session{'s' if behind != 1 else ''} behind"
    return MarketUse(used=True, vix=vix, as_of=as_of, report_session=session.isoformat(), sessions_behind=behind, max_sessions_behind=limit,
                     reason=f"VIX {vix:.1f} from the {as_of} close ({lag}; the last completed session before the report is {session.isoformat()}).")
