"""Event lifecycle and narrative velocity: explicit evidence moves the state, silence and falling volume do not resolve anything."""

from __future__ import annotations

from datetime import timedelta

import pytest

from eventshock.intelligence.lifecycle import LifecycleEngine
from eventshock.intelligence.model import Availability
from eventshock.intelligence.model import LifecycleState as S
from eventshock.intelligence.velocity import build_velocity
from tests.intel_helpers import BASE, CFG, rep

E = LifecycleEngine(CFG.lifecycle, {"sec.gov"})
H = 60  # minutes per hour


def run(reports, as_of_minutes=None, conflict=lambda t: False):  # noqa: ANN001, ANN201
    as_of = BASE + timedelta(minutes=as_of_minutes if as_of_minutes is not None else max(r.published_at for r in reports).timestamp() and 0)
    if as_of_minutes is None:
        as_of = max(r.published_at for r in reports)
    return E.run(reports, conflict, as_of)


def states(trans):  # noqa: ANN001, ANN201
    return [t.to_state.value for t in trans]


def test_one_report_is_developing():
    st, since, tr = run([rep("A", "Acme probe opened")])
    assert st is S.DEVELOPING and states(tr) == ["DEVELOPING"] and tr[0].rule == "FIRST_REPORT"


def test_independent_sources_confirm_it_and_the_transition_names_its_evidence():
    st, _, tr = run([rep("A", "Acme probe opened", minutes=0), rep("B", "Acme under probe, regulator says", minutes=30)])
    assert st is S.CONFIRMED and tr[-1].rule == "CONFIRMED_INDEPENDENT" and tr[-1].evidence_report_ids == ["B"]


def test_copies_do_not_confirm_it():
    st, _, _ = run([rep("A", "Acme probe opened", minutes=0), rep("B", "Acme probe opened", minutes=30, independent=False)])
    assert st is S.DEVELOPING


def test_one_authoritative_source_confirms_it():
    st, _, tr = run([rep("A", "Acme discloses probe in filing", domain="sec.gov")])
    assert st is S.CONFIRMED and tr[-1].rule == "CONFIRMED_AUTHORITATIVE"


def test_an_open_contradiction_blocks_confirmation():
    st, _, _ = run([rep("A", "Acme probe opened", minutes=0), rep("B", "Acme under probe, regulator says", minutes=30)], conflict=lambda t: True)
    assert st is S.DEVELOPING


def test_escalation_cue_moves_a_confirmed_event_to_escalating_then_holds_to_stabilizing():
    rs = [rep("A", "Acme probe opened", minutes=0), rep("B", "Acme under probe", minutes=10), rep("C", "Probe widens to Acme's trading desk", minutes=60)]
    st, _, tr = run(rs)
    assert st is S.ESCALATING and tr[-1].rule == "ESCALATION_CUE" and tr[-1].evidence_quote == "widens"
    st2, _, tr2 = E.run(rs, lambda t: False, BASE + timedelta(minutes=60 + int(CFG.lifecycle.escalation_hold_hours * H) + 5))
    assert st2 is S.STABILIZING and tr2[-1].rule == "ESCALATION_HELD" and tr2[-1].evidence_report_ids == []


def test_a_deescalation_cue_moves_it_to_stabilizing():
    st, _, tr = run([rep("A", "Strike begins", minutes=0), rep("B", "Strike at plant", minutes=10), rep("C", "Strike eases as talks resume", minutes=120)])
    assert st is S.STABILIZING and tr[-1].rule == "DEESCALATION_CUE"


def test_resolution_needs_explicit_evidence_from_several_outlets_or_one_authoritative():
    base = [rep("A", "Strike begins", minutes=0), rep("B", "Strike at plant", minutes=10)]
    one, _, _ = run(base + [rep("C", "Strike resolved, union says", minutes=100)])
    assert one is not S.RESOLVED  # one non-authoritative outlet is not enough
    two, _, tr = run(base + [rep("C", "Strike resolved, union says", minutes=100), rep("D", "Plant strike settled after deal", minutes=130)])
    assert two is S.RESOLVED and tr[-1].rule == "RESOLVED_INDEPENDENT"
    auth, _, tr2 = run(base + [rep("E", "Strike resolved, agency confirms", minutes=100, domain="sec.gov")])
    assert auth is S.RESOLVED and tr2[-1].rule == "RESOLVED_AUTHORITATIVE"


def test_a_fall_in_volume_never_resolves_an_event():
    rs = [rep(c, "Acme probe update", minutes=m) for c, m in [("A", 0), ("B", 5), ("C", 10), ("D", 20), ("E", 30)]]
    st, _, tr = E.run(rs, lambda t: False, BASE + timedelta(hours=60))  # coverage stopped; nothing says it is over
    assert st is not S.RESOLVED and "RESOLVED" not in states(tr)


def test_a_quiet_event_goes_stale_and_a_new_report_revives_it():
    rs = [rep("A", "Acme probe opened", minutes=0), rep("B", "Acme under probe", minutes=10)]
    st, _, tr = E.run(rs, lambda t: False, BASE + timedelta(hours=int(CFG.lifecycle.stale_after_hours) + 2))
    assert st is S.STALE and tr[-1].rule == "STALE_QUIET"
    revived, _, tr2 = E.run([*rs, rep("C", "Acme probe: new filing", minutes=60 * (int(CFG.lifecycle.stale_after_hours) + 5))], lambda t: False,
                            BASE + timedelta(hours=int(CFG.lifecycle.stale_after_hours) + 6))
    assert "REPORT_AFTER_STALE" in [t.rule for t in tr2] and revived in (S.DEVELOPING, S.CONFIRMED)


def test_a_resolved_event_is_not_stale_and_can_re_escalate():
    rs = [rep("A", "Strike begins", minutes=0), rep("B", "Strike at plant", minutes=10), rep("E", "Strike resolved", minutes=100, domain="sec.gov")]
    st, _, _ = E.run(rs, lambda t: False, BASE + timedelta(hours=500))
    assert st is S.RESOLVED
    st2, _, tr = E.run([*rs, rep("F", "Strike resumes and widens", minutes=60 * 600)], lambda t: False, BASE + timedelta(hours=601))
    assert st2 is S.ESCALATING and tr[-1].rule == "RE_ESCALATED"


def test_the_timeline_is_future_invariant():
    rs = [rep("A", "Acme probe opened", minutes=0), rep("B", "Acme under probe", minutes=30), rep("C", "Probe widens", minutes=90), rep("D", "Probe resolved", minutes=300, domain="sec.gov")]
    cut = BASE + timedelta(minutes=100)
    past = [r for r in rs if r.published_at <= cut]
    _, _, with_future = E.run(past, lambda t: False, cut)
    _, _, without = E.run(past, lambda t: False, cut)
    full_state, _, full = E.run(rs, lambda t: False, BASE + timedelta(minutes=300))
    assert with_future == without
    assert [(t.at, t.to_state) for t in full[: len(with_future)]] == [(t.at, t.to_state) for t in with_future]
    assert full_state is S.RESOLVED


# ---------------------------------------------------------------------------------------------------------------------- velocity
def test_velocity_states_growth_rate_and_acceleration_from_independent_sources():
    rs = [rep(c, "Acme probe", minutes=m, independent=i) for c, m, i in
          [("A", 0, True), ("B", 30, True), ("C", 90, True), ("D", 150, True), ("E", 200, True), ("F", 230, True), ("G", 240, False)]]
    v = build_velocity(rs, CFG.velocity, trusted=True)
    assert v.availability is Availability.AVAILABLE and v.window_hours == 4.0
    assert v.series[-1].independent_sources == 6 and v.series[-1].reports == 7
    assert v.velocity_per_hour == pytest.approx(5 / 4.0, abs=1e-3) and v.acceleration is not None
    assert v.source_growth.startswith("1 → 6")


def test_velocity_abstains_with_too_few_reports():
    v = build_velocity([rep("A", "x"), rep("B", "x", minutes=30)], CFG.velocity, trusted=True)
    assert v.availability is Availability.ABSTAINED and v.velocity_per_hour is None and "fewer than" in v.reason


def test_acceleration_is_null_when_the_data_are_thin():
    rs = [rep(c, "x", minutes=m) for c, m in [("A", 0), ("B", 60), ("C", 120)]]
    v = build_velocity(rs, CFG.velocity, trusted=True)
    assert v.velocity_per_hour is not None and v.acceleration is None and v.acceleration_reason


def test_velocity_is_unavailable_on_an_untrusted_clock():
    v = build_velocity([rep("A", "x", trusted=False)], CFG.velocity, trusted=False)
    assert v.availability is Availability.UNAVAILABLE and v.series == []


def test_velocity_never_reads_severity():
    import inspect

    import eventshock.intelligence.velocity as mod
    assert "severity" not in inspect.getsource(mod).lower().replace("never a severity input", "")
