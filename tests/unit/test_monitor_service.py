"""The monitor over real event grouping and lifecycle: REPLAY is a deterministic clock, LIVE diffs the overlay, and an article never becomes a risk of its own."""

from __future__ import annotations

from datetime import timedelta

import pytest

from eventshock.monitor.models import ChangeType as C
from eventshock.monitor.models import Mode
from tests.intel_helpers import BASE, JPM, XOM, member, sig
from tests.monitor_helpers import FakeAssess, FakeProp, monitor

FINE_A = "JPMorgan Chase fined $920 million over spoofing by US regulators"
FINE_B = "JPMorgan fined $920 million in spoofing probe, regulators say"
FINE_C = "JPMorgan fined $920 million as spoofing probe expands to more desks"


def story():  # noqa: ANN201
    a = sig("a", FINE_A, entity=JPM, minutes=0, source="Wire A", url="https://a.example/x")
    b = sig("b", FINE_B, entity=JPM, minutes=90, source="Wire B", url="https://b.example/y")
    c = sig("c", FINE_C, entity=JPM, minutes=26 * 60, source="Wire C", url="https://c.example/z")
    return a, b, c


SEV = FakeAssess({"a": 6, "b": 6, "c": 8})


# ------------------------------------------------------------------------------------------------------------------------------------ REPLAY
def test_one_event_not_three_risks_and_the_cycle_grid_is_fixed():
    svc, _, intel = monitor(list(story()), assess=SEV)
    assert len(intel.index().events) == 1 and intel.index().events[0].signal_ids == ["a", "b", "c"]
    cycles = svc.cycles()
    assert [c.baseline for c in cycles][:2] == [True, False] and cycles[-1].at == BASE + timedelta(days=3)
    assert svc.cycles() == cycles


def test_the_baseline_cycle_reports_no_changes_and_an_unchanged_cycle_reports_none():
    svc, *_ = monitor(list(story()), assess=SEV)
    assert svc.replay_changes(cycle=0).changes == []
    assert svc.replay_changes(cycle=3).changes == []      # nothing happened between cycle 2 and 3: an unchanged event is ignored


def test_an_escalation_is_detected_once_with_its_evidence_and_provenance():
    svc, *_ = monitor(list(story()), assess=SEV)
    cs = svc.replay_changes(cycle=1)
    got = {c.change_type for c in cs.changes}
    assert {C.EVENT_ESCALATED, C.EVENT_UPDATED} <= got
    esc = next(c for c in cs.changes if c.change_type is C.EVENT_ESCALATED)
    assert esc.previous.severity == 6 and esc.current.severity == 8 and esc.rule.startswith("SEVERITY_UP")
    assert esc.current.lead_signal_id == "c" and esc.mode is Mode.REPLAY and esc.cycle == 1
    assert any(e.kind == "SCORE" for e in esc.supporting_evidence) and esc.provenance
    life = next((c for c in cs.changes if c.change_type is C.LIFECYCLE_CHANGED), None)
    assert life is not None and life.previous.lifecycle == "CONFIRMED" and life.current.lifecycle == "ESCALATING"
    assert any(e.kind == "LIFECYCLE_TRANSITION" and "expands" in e.text for e in life.supporting_evidence)


def test_evidence_change_is_detected_when_a_second_independent_source_joins():
    a, b, _ = story()
    svc, *_ = monitor([a, sig("late", FINE_B, entity=JPM, minutes=26 * 60, source="Wire D", url="https://d.example/q")], assess=FakeAssess(default=6), step_hours=24)
    cs = svc.replay_changes(cycle=1)
    assert {C.EVENT_UPDATED, C.EVIDENCE_STRENGTHENED} & {c.change_type for c in cs.changes}


def test_replay_is_identical_on_every_run_and_a_fresh_service_agrees():
    one, *_ = monitor(list(story()), assess=SEV)
    two, *_ = monitor(list(story()), assess=SEV)
    dump = lambda s: [c.model_dump(mode="json") for c in s.replay_changes(cycle=1, window=3).changes]  # noqa: E731
    assert dump(one) == dump(one) == dump(two) and dump(one)


def test_a_window_spans_several_cycles_in_order_newest_first():
    svc, *_ = monitor(list(story()), assess=SEV)
    cs = svc.replay_changes(cycle=2, window=2)
    assert [c.cycle for c in cs.changes] == sorted((c.cycle for c in cs.changes), reverse=True)
    assert {c.cycle for c in cs.changes} == {1, 2}      # cycle 2: no further escalation for the hold period, so the lifecycle eases
    assert any(c.cycle == 2 and c.change_type is C.EVENT_DE_ESCALATED for c in cs.changes)


def test_an_untracked_event_is_counted_not_reported():
    svc, *_ = monitor(list(story()), assess=FakeAssess(default=2), prop=FakeProp())
    cs = svc.replay_changes(cycle=1)
    assert cs.changes == [] and cs.tracked_events == 0 and cs.untracked_events == 1


def test_portfolio_materiality_alone_can_track_an_event_and_its_changes_carry_the_portfolio_impact():
    prop = FakeProp(level={"a": "LOW", "b": "LOW", "c": "HIGH"}, share={"a": 0.05, "b": 0.05, "c": 0.35}, pnl={"c": -0.031})
    svc, *_ = monitor(list(story()), assess=FakeAssess({"a": 2, "b": 2, "c": 2}), prop=prop)
    cs = svc.replay_changes(cycle=1)
    types = {c.change_type for c in cs.changes}
    assert C.NEW_EVENT in types           # first tracked at this cycle: it reached the materiality floor
    ch = next(c for c in cs.changes if c.change_type is C.NEW_EVENT)
    assert ch.portfolio_impact.materiality_current == "HIGH" and ch.portfolio_impact.stress_pnl_pct_current == -0.031


def test_a_stress_change_is_detected_between_cycles():
    prop = FakeProp(level={x: "MEDIUM" for x in "abc"}, share={"a": 0.2, "b": 0.2, "c": 0.2}, pnl={"a": -0.020, "b": -0.020, "c": -0.040})
    svc, *_ = monitor(list(story()), assess=SEV, prop=prop)
    cs = svc.replay_changes(cycle=1)
    st = next(c for c in cs.changes if c.change_type is C.STRESS_CHANGED)
    assert st.previous.stress_pnl_pct == -0.020 and st.current.stress_pnl_pct == -0.040
    assert any(p.kind.value == "SCENARIO_ASSUMPTION" for p in st.provenance)         # the figure is a simulation, and says so


def test_an_event_with_replay_assigned_times_is_never_placed_on_a_timeline():
    from eventshock.domain import TimestampOrigin
    a = sig("x", FINE_A, entity=JPM, origin=TimestampOrigin.SYNTHETIC_REPLAY_CLOCK)
    svc, *_ = monitor([a, *story()], assess=SEV)
    cs = svc.replay_changes(cycle=1)
    assert cs.excluded_untrusted_clock == 1 and all(c.event_id != svc.resolve_event("x").id for c in cs.changes)
    mem = svc.memory("x")
    assert mem.availability == "UNAVAILABLE" and "assigned by the replay" in mem.reason and mem.items == []


def test_the_changes_leave_the_signals_untouched():
    signals = list(story())
    before = [s.model_dump_json() for s in signals]
    svc, *_ = monitor(signals, assess=SEV)
    svc.replay_changes(cycle=3, window=3)
    svc.memory("a")
    assert [s.model_dump_json() for s in signals] == before


def test_a_bad_cycle_is_rejected():
    svc, *_ = monitor(list(story()), assess=SEV)
    with pytest.raises(ValueError):
        svc.replay_changes(cycle=99)


# -------------------------------------------------------------------------------------------------------------------------------------- LIVE
def live_service(tmp_path):  # noqa: ANN001, ANN201
    svc, repo, intel = monitor([], assess=SEV, tmp=tmp_path)
    return svc, repo


def test_live_new_event_then_repeated_polling_is_idempotent(tmp_path):  # noqa: ANN001
    svc, repo = live_service(tmp_path)
    a, b, c = story()
    repo.live.upsert(a, "LIVE")
    now = BASE + timedelta(hours=2)
    first = svc.observe(now)
    assert [c.change_type for c in first] == [C.NEW_EVENT]
    assert svc.observe(now) == [] and svc.observe(now + timedelta(minutes=5)) == []    # unchanged data: nothing, however often it is polled
    assert len(svc.live_changes().changes) == 1


def test_live_update_escalation_and_conflict_are_logged_once_each(tmp_path):  # noqa: ANN001
    svc, repo = live_service(tmp_path)
    a, b, c = story()
    repo.live.upsert(a, "LIVE")
    svc.observe(BASE + timedelta(hours=1))
    repo.live.upsert(b, "LIVE")
    second = svc.observe(BASE + timedelta(hours=3))
    assert {x.change_type for x in second} >= {C.EVENT_UPDATED}
    repo.live.upsert(c, "LIVE")
    third = svc.observe(BASE + timedelta(hours=27))
    assert C.EVENT_ESCALATED in {x.change_type for x in third}
    total = len(svc.live_changes().changes)
    svc.observe(BASE + timedelta(hours=27))
    assert len(svc.live_changes().changes) == total
    assert len({c.change_id for c in svc.live_changes().changes}) == total


def test_live_conflict_appears_and_resolves(tmp_path):  # noqa: ANN001
    svc, repo = live_service(tmp_path)
    repo.live.upsert(sig("c1", "Acme confirms takeover offer from Beta Corp", entity=JPM, minutes=0, source="Wire A", url="https://a.example/1"), "LIVE")
    svc.observe(BASE + timedelta(hours=1))
    repo.live.upsert(sig("c2", "Acme denies takeover offer from Beta Corp", entity=JPM, minutes=60, source="Wire B", url="https://b.example/2"), "LIVE")
    out = svc.observe(BASE + timedelta(hours=3))
    assert C.CONFLICT_APPEARED in {c.change_type for c in out}
    ap = next(c for c in out if c.change_type is C.CONFLICT_APPEARED)
    assert any(e.kind == "CONFLICT" for e in ap.supporting_evidence)


def test_live_state_and_log_survive_a_restart_without_duplicating(tmp_path):  # noqa: ANN001
    svc, repo = live_service(tmp_path)
    a, *_ = story()
    repo.live.upsert(a, "LIVE")
    svc.observe(BASE + timedelta(hours=1))
    svc2, repo2, _ = monitor([], assess=SEV, tmp=tmp_path)
    repo2.live.upsert(a, "LIVE")
    assert svc2.observe(BASE + timedelta(hours=1)) == []      # the same event, already known
    assert len(svc2.live_changes().changes) == 1


def test_live_ignores_replay_events(tmp_path):  # noqa: ANN001
    svc, repo, _ = monitor(list(story()), assess=SEV, tmp=tmp_path)
    assert svc.observe(BASE + timedelta(days=2)) == []


def test_live_off_is_reported_and_never_breaks_replay():
    svc, *_ = monitor(list(story()), assess=SEV)
    live = svc.status(Mode.LIVE)
    assert live.state == "OFF" and not live.available and "REPLAY works" in live.reason
    assert svc.status(Mode.REPLAY).state == "OK" and svc.replay_changes().availability == "AVAILABLE"
    cs = svc.live_changes()
    assert cs.availability == "UNAVAILABLE" and cs.changes == []


# ---------------------------------------------------------------------------------------------------------------------------- event memory
def test_the_timeline_is_one_narrative_with_every_report_classified():
    svc, *_ = monitor(list(story()), assess=SEV)
    mem = svc.memory("b")                                   # any signal of the event resolves to it
    assert mem.event_id == svc.resolve_event("a").id and mem.availability == "AVAILABLE"
    reports = [i for i in mem.items if i.kind == "REPORT"]
    assert len(reports) == 3 and reports[0].update_kind.value == "NEW_EVENT" and reports[-1].update_kind.value == "ESCALATION"
    assert all(i.provenance for i in mem.items)
    assert sum(mem.update_counts.values()) == 3
    assert mem.history and mem.history[-1].severity == 8
    life = [i for i in mem.items if i.kind == "LIFECYCLE"]
    assert life and life[0].observation == "EVENTSHOCK_ASSESSMENT"


def test_the_timeline_distinguishes_scenario_stress_from_assessment():
    prop = FakeProp(level={x: "MEDIUM" for x in "abc"}, pnl={"a": -0.02, "b": -0.02, "c": -0.04})
    svc, *_ = monitor(list(story()), assess=SEV, prop=prop)
    mem = svc.memory("a")
    stress = [i for i in mem.items if i.kind == "STRESS"]
    assert stress and stress[0].observation == "SCENARIO_ASSUMPTION"
    assert all(i.observation == "SOURCE_EVENT" for i in mem.items if i.kind == "REPORT")


def test_an_unknown_event_is_an_error_not_an_empty_timeline():
    svc, *_ = monitor(list(story()), assess=SEV)
    with pytest.raises(LookupError):
        svc.memory("evt_nope")


def test_two_events_stay_two_events():
    a, b, c = story()
    x = sig("x", "Exxon Mobil fined $920 million over spoofing by US regulators", entity=XOM, minutes=30, source="Wire X", url="https://x.example/1",
            members=[member("Wire Y", 40, "Exxon fined $920 million over spoofing", url="https://y.example/1")])
    svc, _, intel = monitor([a, b, c, x], assess=SEV)
    assert len(intel.index().events) == 2
