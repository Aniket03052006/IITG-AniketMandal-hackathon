"""A company's sentiment score at one instant, from the reports published at or before it.

    w_k    = 0.5 ** (age_k / half_life)                       a report's weight halves every half-life; reports older than the lookback are ignored
    W_s    = sum of w_k over source s's reports               the source's evidence;  xbar_s = sum(w_k x_k) / W_s  its decayed mean sentiment
    c_s    = min(W_s, source_vote_cap)                        one source, one vote: a source cannot shout louder by publishing more
    S      = sum_s c_s xbar_s / (sum_s c_s + n0)              n0 pseudo-reports of sentiment 0: thin evidence gives a weak score

S lies in [-1, 1] and the contribution of every report (c_s w_k x_k / (W_s (sum c + n0))) adds up to S exactly, which is how the UI explains a score.
Only the sentiment score of a report is read: tone-independent confidence, severity, impact and source reliability are not inputs.

The one exception is the experimental ``sentiment_impact`` strategy (``impact_floor`` given): each report's tone is multiplied by m = floor + (1 - floor)(impact - 1)/9, in [floor, 1],
and a report with no impact score gets m = floor. m only shrinks a tone, so S stays in [-1, 1] and the contributions still add up to it exactly. The default call reads no impact.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from .config import Evidence


@dataclass(frozen=True)
class Report:
    signal_id: str
    ticker: str
    source: str
    published_at: datetime
    sentiment: float
    headline: str = ""
    url: str | None = None
    impact: int | None = None   # the engine's 1-10 impact score; read only by the experimental impact strategy


@dataclass(frozen=True)
class Contribution:
    report: Report
    age_hours: float
    decayed_weight: float
    contribution: float
    multiplier: float = 1.0   # the impact multiplier applied to this report's tone (1.0 unless the impact strategy is on)


@dataclass(frozen=True)
class Score:
    value: float
    evidence: float            # sum of c_s
    reports: int
    sources: int
    contributions: list[Contribution] = field(default_factory=list)


EMPTY = Score(0.0, 0.0, 0, 0, [])


def impact_multiplier(impact: int | None, floor: float) -> float:
    """floor at impact 1 (and when there is none), rising linearly to 1 at impact 10."""
    if impact is None:
        return floor
    return floor + (1.0 - floor) * (min(10, max(1, impact)) - 1) / 9.0


def score(reports: Iterable[Report], at: datetime, cfg: Evidence, *, half_life_hours: float | None = None, impact_floor: float | None = None) -> Score:
    """The score of one company at ``at``. A report published after ``at`` is never read (point-in-time by construction)."""
    h = cfg.half_life_hours if half_life_hours is None else half_life_hours
    if h <= 0:
        raise ValueError("half_life_hours must be positive")
    horizon = cfg.lookback_half_lives * h
    by_source: dict[str, list[tuple[Report, float, float]]] = defaultdict(list)
    for r in reports:
        age = (at - r.published_at).total_seconds() / 3600.0
        if age < 0 or age > horizon:
            continue
        by_source[r.source].append((r, age, 0.5 ** (age / h)))
    if not by_source:
        return EMPTY
    parts = []
    for src in sorted(by_source):   # sorted: the float sums below are then identical on every run
        rows = sorted(by_source[src], key=lambda x: (x[0].published_at, x[0].signal_id))   # a fixed order inside a source too: float sums must not depend on arrival order
        total = sum(w for _, _, w in rows)
        parts.append((src, rows, total, min(total, cfg.source_vote_cap)))
    denom = sum(c for _, _, _, c in parts) + cfg.prior_pseudo_count
    if denom <= 0:
        return EMPTY
    contributions: list[Contribution] = []
    value = 0.0
    for _, rows, total, c in parts:
        for r, age, w in rows:
            m = 1.0 if impact_floor is None else impact_multiplier(r.impact, impact_floor)
            share = c * (w / total) * (r.sentiment * m) / denom
            value += share
            contributions.append(Contribution(r, age, w, share, m))
    contributions.sort(key=lambda k: (-abs(k.contribution), k.report.signal_id))
    return Score(max(-1.0, min(1.0, value)), denom - cfg.prior_pseudo_count, len(contributions), len(parts), contributions)
