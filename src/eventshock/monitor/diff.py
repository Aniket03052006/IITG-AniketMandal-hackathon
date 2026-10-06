"""The pure difference between two states of one event: no I/O, no clock, no randomness.

A change is only reported when a configured threshold is crossed (``configs/decision.yaml``), and every change names the rule that fired. Identical states give
no change, and an event that is merely re-observed is never reported twice: ``fingerprint`` equality short-circuits everything.

Order of the drafts is fixed (``ORDER``), so the same pair of states always yields the same list in the same order.
"""

from __future__ import annotations

from ..decision.config import MonitorCfg
from .models import (
    OPEN_CONFLICT,
    RANK_EVIDENCE,
    RANK_MATERIALITY,
    ChangeDraft,
    ChangeType,
    EventState,
    FieldChange,
)

ORDER = [ChangeType.NEW_EVENT, ChangeType.EVENT_ESCALATED, ChangeType.EVENT_DE_ESCALATED, ChangeType.LIFECYCLE_CHANGED, ChangeType.EVIDENCE_STRENGTHENED,
         ChangeType.EVIDENCE_WEAKENED, ChangeType.CONFLICT_APPEARED, ChangeType.CONFLICT_RESOLVED, ChangeType.PORTFOLIO_EXPOSURE_CHANGED, ChangeType.STRESS_CHANGED,
         ChangeType.EVENT_UPDATED]

ESCALATING_STATES = {"ESCALATING"}
EASING_STATES = {"STABILIZING", "RESOLVED"}


def _f(name: str, prev: EventState | None, curr: EventState) -> FieldChange:
    return FieldChange(field=name, previous=getattr(prev, name) if prev is not None else None, current=getattr(curr, name))


def _pp(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:+.2f}%"


def diff_states(prev: EventState | None, curr: EventState, cfg: MonitorCfg) -> list[ChangeDraft]:
    """The changes from ``prev`` to ``curr``. An event that is not tracked produces none; a tracked event with no earlier tracked state is NEW_EVENT."""
    if not curr.tracked:
        return []
    if prev is None or not prev.tracked:
        why = "the event is first seen" if prev is None else "the event now reaches the tracking floor"
        return [ChangeDraft(
            change_type=ChangeType.NEW_EVENT, rule=f"FIRST_TRACKED (severity >= {cfg.track_min_severity:g} or materiality >= {cfg.track_min_materiality})",
            summary=f"New tracked risk: {why}; severity {curr.severity if curr.severity is not None else 'n/a'}, lifecycle {curr.lifecycle or 'unknown'}, "
                    f"evidence {curr.evidence_tier}.", fields=[_f("severity", prev, curr), _f("materiality", prev, curr), _f("evidence_tier", prev, curr)])]
    if prev.fingerprint == curr.fingerprint:
        return []
    out: dict[ChangeType, ChangeDraft] = {}

    # ---- severity / lifecycle escalation
    sev_delta = None if prev.severity is None or curr.severity is None else curr.severity - prev.severity
    if sev_delta is not None and sev_delta >= cfg.escalation_delta:
        out[ChangeType.EVENT_ESCALATED] = ChangeDraft(
            change_type=ChangeType.EVENT_ESCALATED, rule=f"SEVERITY_UP (>= {cfg.escalation_delta:g} points)", fields=[_f("severity", prev, curr), _f("lead_signal_id", prev, curr)],
            summary=f"Severity rose {prev.severity:g} -> {curr.severity:g}.")
    elif prev.severity is None and curr.severity is not None:
        out[ChangeType.EVENT_ESCALATED] = ChangeDraft(
            change_type=ChangeType.EVENT_ESCALATED, rule="SEVERITY_APPEARED", fields=[_f("severity", prev, curr)],
            summary=f"The event is now scored: severity {curr.severity:g}.")
    elif curr.lifecycle in ESCALATING_STATES and prev.lifecycle not in ESCALATING_STATES and prev.lifecycle is not None:
        out[ChangeType.EVENT_ESCALATED] = ChangeDraft(
            change_type=ChangeType.EVENT_ESCALATED, rule="LIFECYCLE_ESCALATING", fields=[_f("lifecycle", prev, curr)],
            summary=f"Lifecycle moved {prev.lifecycle} -> {curr.lifecycle}: a report describes the event widening or worsening.")
    if sev_delta is not None and sev_delta <= -cfg.escalation_delta:
        out[ChangeType.EVENT_DE_ESCALATED] = ChangeDraft(
            change_type=ChangeType.EVENT_DE_ESCALATED, rule=f"SEVERITY_DOWN (>= {cfg.escalation_delta:g} points)", fields=[_f("severity", prev, curr)],
            summary=f"Severity fell {prev.severity:g} -> {curr.severity:g}.")
    elif ChangeType.EVENT_ESCALATED not in out and curr.lifecycle in EASING_STATES and prev.lifecycle not in EASING_STATES and prev.lifecycle is not None:
        out[ChangeType.EVENT_DE_ESCALATED] = ChangeDraft(
            change_type=ChangeType.EVENT_DE_ESCALATED, rule="LIFECYCLE_EASING", fields=[_f("lifecycle", prev, curr)],
            summary=f"Lifecycle moved {prev.lifecycle} -> {curr.lifecycle}: reports describe the event easing or resolved.")

    if prev.lifecycle != curr.lifecycle and (prev.lifecycle is not None or curr.lifecycle is not None):
        out[ChangeType.LIFECYCLE_CHANGED] = ChangeDraft(
            change_type=ChangeType.LIFECYCLE_CHANGED, rule="LIFECYCLE_STATE_CHANGED", fields=[_f("lifecycle", prev, curr)],
            summary=f"Lifecycle {prev.lifecycle or 'unknown'} -> {curr.lifecycle or 'unknown'}.")

    # ---- evidence
    pe, ce = RANK_EVIDENCE.get(prev.evidence_tier, 0), RANK_EVIDENCE.get(curr.evidence_tier, 0)
    if ce > pe:
        out[ChangeType.EVIDENCE_STRENGTHENED] = ChangeDraft(
            change_type=ChangeType.EVIDENCE_STRENGTHENED, rule="EVIDENCE_TIER_UP", fields=[_f("evidence_tier", prev, curr), _f("independent_sources", prev, curr)],
            summary=f"Evidence {prev.evidence_tier} -> {curr.evidence_tier} ({prev.independent_sources} -> {curr.independent_sources} independent sources).")
    elif ce < pe:
        out[ChangeType.EVIDENCE_WEAKENED] = ChangeDraft(
            change_type=ChangeType.EVIDENCE_WEAKENED, rule="EVIDENCE_TIER_DOWN", fields=[_f("evidence_tier", prev, curr), _f("conflict", prev, curr)],
            summary=f"Evidence {prev.evidence_tier} -> {curr.evidence_tier}.")

    # ---- conflict
    was_open, is_open = prev.conflict in OPEN_CONFLICT, curr.conflict in OPEN_CONFLICT
    if is_open and not was_open:
        out[ChangeType.CONFLICT_APPEARED] = ChangeDraft(
            change_type=ChangeType.CONFLICT_APPEARED, rule="CLAIM_CONFLICT_OPENED", fields=[_f("conflict", prev, curr)],
            summary=f"Reports now contradict each other on a tracked claim ({prev.conflict} -> {curr.conflict}).")
    elif was_open and not is_open:
        out[ChangeType.CONFLICT_RESOLVED] = ChangeDraft(
            change_type=ChangeType.CONFLICT_RESOLVED, rule="CLAIM_CONFLICT_CLOSED", fields=[_f("conflict", prev, curr)],
            summary=f"The conflict between reports is no longer open ({prev.conflict} -> {curr.conflict}).")

    # ---- portfolio exposure
    dshare = None if prev.exposure_share is None or curr.exposure_share is None else round((curr.exposure_share - prev.exposure_share) * 100.0, 6)
    level_moved = prev.materiality != curr.materiality and (RANK_MATERIALITY.get(prev.materiality or "UNDETERMINED", -1)
                                                              != RANK_MATERIALITY.get(curr.materiality or "UNDETERMINED", -1))
    if level_moved or (dshare is not None and abs(dshare) >= cfg.exposure_change_pp):
        bits = []
        if level_moved:
            bits.append(f"materiality {prev.materiality or 'n/a'} -> {curr.materiality or 'n/a'}")
        if dshare is not None and abs(dshare) >= cfg.exposure_change_pp:
            bits.append(f"share of the book reached {prev.exposure_share * 100:.1f}% -> {curr.exposure_share * 100:.1f}%")  # type: ignore[operator]
        out[ChangeType.PORTFOLIO_EXPOSURE_CHANGED] = ChangeDraft(
            change_type=ChangeType.PORTFOLIO_EXPOSURE_CHANGED, rule=f"EXPOSURE (materiality level or >= {cfg.exposure_change_pp:g} pp of the book)",
            fields=[_f("materiality", prev, curr), _f("exposure_share", prev, curr)], summary="Portfolio relevance changed: " + "; ".join(bits) + ".")

    # ---- stress
    ps, cs = prev.stress_pnl_pct, curr.stress_pnl_pct
    if (ps is None) != (cs is None) or (ps is not None and cs is not None and round(abs(cs - ps) * 100.0, 6) >= cfg.stress_change_pp):
        out[ChangeType.STRESS_CHANGED] = ChangeDraft(
            change_type=ChangeType.STRESS_CHANGED, rule=f"STRESS_MOVE (>= {cfg.stress_change_pp:g} pp of the book, or the scenario started/stopped applying)",
            fields=[_f("stress_pnl_pct", prev, curr), _f("stress_status", prev, curr)],
            summary=f"Modeled scenario P&L {_pp(ps)} -> {_pp(cs)} of the book (a simulation under an illustrative scenario, not a forecast).")

    # ---- plain update: a new independent source or a new report cluster joined the event
    if curr.independent_sources > prev.independent_sources or curr.member_count > prev.member_count:
        out[ChangeType.EVENT_UPDATED] = ChangeDraft(
            change_type=ChangeType.EVENT_UPDATED, rule="NEW_COVERAGE", fields=[_f("member_count", prev, curr), _f("independent_sources", prev, curr), _f("report_count", prev, curr)],
            summary=f"New coverage: {prev.independent_sources} -> {curr.independent_sources} independent sources, {prev.report_count} -> {curr.report_count} reports.")

    return [out[t] for t in ORDER if t in out]
