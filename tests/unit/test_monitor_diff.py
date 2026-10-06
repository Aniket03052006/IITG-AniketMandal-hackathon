"""The pure diff between two states of an event: thresholds, idempotence, ordering, and what is deliberately not reported."""

from __future__ import annotations

from eventshock.monitor.diff import ORDER, diff_states
from eventshock.monitor.models import ChangeType as C
from tests.monitor_helpers import dcfg, state

CFG = dcfg().monitor


def kinds(prev, curr):  # noqa: ANN001, ANN201
    return [d.change_type for d in diff_states(prev, curr, CFG)]


def test_a_first_tracked_state_is_a_new_event_and_names_its_rule():
    (d,) = diff_states(None, state(), CFG)
    assert d.change_type is C.NEW_EVENT and "FIRST_TRACKED" in d.rule


def test_an_event_that_reaches_the_floor_later_is_new_then():
    assert kinds(state(tracked=False), state()) == [C.NEW_EVENT]


def test_an_untracked_state_reports_nothing():
    assert kinds(None, state(tracked=False)) == [] and kinds(state(), state(tracked=False, severity=2.0)) == []


def test_identical_states_report_nothing_so_repeated_polling_is_idempotent():
    s = state()
    assert kinds(s, s) == [] and kinds(s, state()) == []


def test_a_copy_alone_is_not_a_change():
    # a syndicated copy raises the report count only: no new independent source, no new cluster
    assert kinds(state(report_count=1), state(report_count=2)) == []


def test_severity_up_by_the_threshold_is_an_escalation_below_it_is_not():
    assert C.EVENT_ESCALATED in kinds(state(severity=6.0), state(severity=7.0))
    assert C.EVENT_ESCALATED not in kinds(state(severity=6.0), state(severity=6.9))
    assert C.EVENT_DE_ESCALATED in kinds(state(severity=7.0), state(severity=6.0))


def test_a_lifecycle_escalation_cue_escalates_without_a_severity_move_and_changes_lifecycle():
    ks = kinds(state(lifecycle="CONFIRMED"), state(lifecycle="ESCALATING"))
    assert ks == [C.EVENT_ESCALATED, C.LIFECYCLE_CHANGED]
    d = diff_states(state(lifecycle="CONFIRMED"), state(lifecycle="ESCALATING"), CFG)[0]
    assert d.rule == "LIFECYCLE_ESCALATING"


def test_easing_and_resolution_de_escalate():
    assert kinds(state(lifecycle="ESCALATING"), state(lifecycle="STABILIZING")) == [C.EVENT_DE_ESCALATED, C.LIFECYCLE_CHANGED]
    assert C.EVENT_DE_ESCALATED in kinds(state(lifecycle="CONFIRMED"), state(lifecycle="RESOLVED"))


def test_going_stale_is_a_lifecycle_change_not_a_de_escalation():
    assert kinds(state(lifecycle="DEVELOPING"), state(lifecycle="STALE")) == [C.LIFECYCLE_CHANGED]


def test_evidence_tier_up_and_down():
    assert kinds(state(evidence_tier="WEAK"), state(evidence_tier="STRONG", independent_sources=1)) == [C.EVIDENCE_STRENGTHENED]
    assert kinds(state(evidence_tier="STRONG"), state(evidence_tier="WEAK")) == [C.EVIDENCE_WEAKENED]


def test_a_conflict_appears_and_resolves():
    assert kinds(state(), state(conflict="CONFLICTED")) == [C.CONFLICT_APPEARED]
    assert kinds(state(conflict="POSSIBLE_CONFLICT"), state(conflict="CONFLICTED")) == []  # still open: no new change
    assert kinds(state(conflict="CONFLICTED"), state(conflict="RESOLVED_CONFLICT")) == [C.CONFLICT_RESOLVED]


def test_exposure_changes_on_a_level_move_or_on_enough_share():
    assert kinds(state(materiality="MEDIUM"), state(materiality="HIGH")) == [C.PORTFOLIO_EXPOSURE_CHANGED]
    assert kinds(state(exposure_share=0.20), state(exposure_share=0.23)) == [C.PORTFOLIO_EXPOSURE_CHANGED]      # +3 pp >= 2 pp
    assert kinds(state(exposure_share=0.20), state(exposure_share=0.21)) == []                                 # +1 pp
    assert kinds(state(exposure_share=0.20), state(exposure_share=0.22)) == [C.PORTFOLIO_EXPOSURE_CHANGED]      # exactly the threshold counts


def test_stress_changes_on_enough_movement_or_when_the_scenario_starts_applying():
    assert kinds(state(stress_pnl_pct=-0.02), state(stress_pnl_pct=-0.0235)) == [C.STRESS_CHANGED]
    assert kinds(state(stress_pnl_pct=-0.02), state(stress_pnl_pct=-0.0215)) == []                              # 0.15 pp < 0.25 pp
    assert kinds(state(stress_pnl_pct=None), state(stress_pnl_pct=-0.02, stress_status="COMPLETED")) == [C.STRESS_CHANGED]


def test_new_coverage_is_an_update():
    ks = kinds(state(), state(independent_sources=2, report_count=2, member_count=2))
    assert C.EVENT_UPDATED in ks


def test_order_is_fixed_and_the_same_for_the_same_pair():
    prev = state()
    curr = state(severity=8.0, lifecycle="ESCALATING", evidence_tier="STRONG", conflict="CONFLICTED", materiality="HIGH", stress_pnl_pct=-0.05, stress_status="COMPLETED",
                 independent_sources=3, member_count=2, report_count=3)
    first = kinds(prev, curr)
    assert first == kinds(prev, curr) and first == sorted(first, key=ORDER.index)
    assert len(first) == len(set(first))  # one change per type per event per step


def test_every_draft_names_a_rule_and_the_fields_it_changed():
    prev, curr = state(), state(severity=8.0, evidence_tier="STRONG")
    for d in diff_states(prev, curr, CFG):
        assert d.rule and d.summary and d.fields
