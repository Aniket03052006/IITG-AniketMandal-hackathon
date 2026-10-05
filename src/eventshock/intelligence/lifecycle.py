"""Event lifecycle: DEVELOPING -> CONFIRMED -> ESCALATING -> STABILIZING -> RESOLVED, or STALE.

A state machine over the event's reports in time order, using only explicit evidence:

* DEVELOPING at the first report;
* CONFIRMED when enough *independent* sources (or one authoritative source) carry it and no contradiction is open;
* ESCALATING when a report of a confirmed event carries an escalation cue; STABILIZING on a de-escalation cue, or when escalation has not
  been repeated for ``escalation_hold_hours``;
* RESOLVED only on an explicit resolution cue from an authoritative source or from ``resolution_min_independent`` distinct outlets: a fall
  in news volume is never read as resolution;
* STALE when no report has arrived for ``stale_after_hours`` and the event is not resolved. A later report revives it.

The state at time T uses only reports published at or before T, so the timeline is future-invariant: computing it with later reports
present and absent gives the same transitions up to T (tested). Every transition names its rule and the reports that caused it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import LifecycleCfg
from .grouping import GReport
from .model import LifecycleState, LifecycleTransition
from .textutil import cue_pattern, find_cues

S = LifecycleState

RULE_TEXT = {
    "FIRST_REPORT": "The first report of the event.",
    "CONFIRMED_INDEPENDENT": "Enough independent sources now carry the event and no contradiction is open.",
    "CONFIRMED_AUTHORITATIVE": "An authoritative source carries the event and no contradiction is open.",
    "ESCALATION_CUE": "A report of the confirmed event describes it widening or worsening.",
    "RE_ESCALATED": "After being resolved, a report describes it widening or worsening again.",
    "DEESCALATION_CUE": "A report describes the event easing or being contained.",
    "ESCALATION_HELD": "No further escalation was reported for the hold period.",
    "RESOLVED_AUTHORITATIVE": "An authoritative source states an explicit resolution.",
    "RESOLVED_INDEPENDENT": "Several independent outlets each state an explicit resolution.",
    "STALE_QUIET": "No report for the stale period, and no explicit resolution.",
    "REPORT_AFTER_STALE": "A new report arrived after the event had gone stale.",
}


@dataclass(frozen=True)
class _Cues:
    esc: str | None
    de: str | None
    res: str | None


class LifecycleEngine:
    def __init__(self, cfg: LifecycleCfg, authoritative: set[str] | frozenset[str]) -> None:
        self.cfg = cfg
        self.authoritative = frozenset(authoritative)
        self._esc = cue_pattern(cfg.escalation_cues)
        self._de = cue_pattern(cfg.deescalation_cues)
        self._res = cue_pattern(cfg.resolution_cues)

    def cues(self, r: GReport) -> _Cues:
        text = f"{r.headline}\n{r.body}" if r.body else r.headline

        def first(pat) -> str | None:  # noqa: ANN001
            h = find_cues(pat, text)
            return h[0].cue if h else None

        return _Cues(first(self._esc), first(self._de), first(self._res))

    def run(self, reports: list[GReport], conflict_open_at: Callable[[datetime], bool], as_of: datetime) -> tuple[LifecycleState | None, datetime | None, list[LifecycleTransition]]:
        """(state at ``as_of``, when it began, transitions). ``reports`` must already be cut at ``as_of`` and marked for independence."""
        cfg = self.cfg
        rs = sorted(reports, key=lambda r: (r.published_at, r.id))
        if not rs:
            return None, None, []
        trans: list[LifecycleTransition] = []
        state: LifecycleState | None = None
        since: datetime | None = None
        last_esc: datetime | None = None
        last_report: datetime | None = None
        res_domains: set[str] = set()

        def go(at: datetime, to: LifecycleState, rule: str, ids: list[str], quote: str | None = None) -> None:
            nonlocal state, since
            if to == state:
                return
            trans.append(LifecycleTransition(at=at, from_state=state, to_state=to, rule=rule, rule_text=RULE_TEXT[rule],
                                             evidence_report_ids=ids, evidence_quote=quote))
            state, since = to, at

        def tick(now: datetime) -> None:
            """Time-driven transitions that fall at or before ``now``, in chronological order."""
            while True:
                cands: list[tuple[datetime, str, LifecycleState]] = []
                if state is S.ESCALATING and last_esc is not None:
                    t = last_esc + timedelta(hours=cfg.escalation_hold_hours)
                    if t <= now:
                        cands.append((t, "ESCALATION_HELD", S.STABILIZING))
                if state not in (S.RESOLVED, S.STALE, None) and last_report is not None:
                    t = last_report + timedelta(hours=cfg.stale_after_hours)
                    if t <= now:
                        cands.append((t, "STALE_QUIET", S.STALE))
                if not cands:
                    return
                t, rule, to = min(cands)
                go(t, to, rule, [])

        seen_ind: set[str] = set()
        n_auth = 0
        for r in rs:
            tick(r.published_at)
            if r.independent:
                seen_ind.add(r.domain)
            if r.independent and r.domain in self.authoritative:
                n_auth += 1
            last_report = r.published_at
            c = self.cues(r)
            if state is None:
                go(r.published_at, S.DEVELOPING, "FIRST_REPORT", [r.id], r.headline[:160])
            elif state is S.STALE:
                go(r.published_at, S.DEVELOPING, "REPORT_AFTER_STALE", [r.id], r.headline[:160])
            if state is S.DEVELOPING and not conflict_open_at(r.published_at):
                if n_auth >= 1:
                    go(r.published_at, S.CONFIRMED, "CONFIRMED_AUTHORITATIVE", [r.id])
                elif len(seen_ind) >= cfg.confirmed_min_independent:
                    go(r.published_at, S.CONFIRMED, "CONFIRMED_INDEPENDENT", [r.id])
            if c.res and (r.independent or r.domain in self.authoritative):
                res_domains.add(r.domain)
                if r.domain in self.authoritative:
                    go(r.published_at, S.RESOLVED, "RESOLVED_AUTHORITATIVE", [r.id], c.res)
                elif len(res_domains) >= cfg.resolution_min_independent:
                    go(r.published_at, S.RESOLVED, "RESOLVED_INDEPENDENT", [r.id], c.res)
            elif c.esc and state in (S.CONFIRMED, S.STABILIZING, S.ESCALATING, S.RESOLVED):
                rule = "RE_ESCALATED" if state is S.RESOLVED else "ESCALATION_CUE"
                if state is S.RESOLVED:
                    res_domains.clear()
                last_esc = r.published_at
                go(r.published_at, S.ESCALATING, rule, [r.id], c.esc)
            elif c.de and state in (S.CONFIRMED, S.ESCALATING):
                go(r.published_at, S.STABILIZING, "DEESCALATION_CUE", [r.id], c.de)
        tick(as_of)
        return state, since, trans
