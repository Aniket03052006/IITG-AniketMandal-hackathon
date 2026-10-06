"""The monitor over the real replay pack: nothing is written onto a signal (the pinned digest holds), REPLAY gives the same changes every run and after a side-car rebuild,
and no change refers to an event whose time was assigned by the replay."""

from __future__ import annotations

from eventshock.api.deps import rebuild_sidecars
from eventshock.pipeline.run import _digest
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST


def dump(cs):  # noqa: ANN001, ANN201
    return [c.model_dump_json() for c in cs.changes]


def test_a_sweep_of_cycles_changes_nothing_and_is_the_same_every_time(replay_container):
    c = replay_container
    m = c.monitor
    cycles = m.cycles()
    picks = [1, len(cycles) // 3, len(cycles) // 2, len(cycles) - 1]
    first = {k: dump(m.replay_changes(cycle=k)) for k in picks}
    assert any(first.values())
    assert first == {k: dump(m.replay_changes(cycle=k)) for k in picks}
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST


def test_a_rebuilt_sidecar_gives_the_same_changes(replay_container):
    c = replay_container
    k = len(c.monitor.cycles()) // 2
    before = dump(c.monitor.replay_changes(cycle=k, window=2))
    rebuild_sidecars(c, {})
    assert dump(c.monitor.replay_changes(cycle=k, window=2)) == before


def test_no_change_is_about_an_event_with_replay_assigned_times_and_each_is_one_event(replay_container):
    c = replay_container
    idx = c.intelligence.index()
    k = len(c.monitor.cycles()) // 2
    cs = c.monitor.replay_changes(cycle=k, window=3)
    for ch in cs.changes:
        ev = idx.event(ch.event_id)
        assert ev is not None and ev.trusted and ch.current.event_id == ev.id
    per = {}
    for ch in cs.changes:
        per.setdefault((ch.cycle, ch.event_id, ch.change_type), 0)
        per[(ch.cycle, ch.event_id, ch.change_type)] += 1
    assert all(v == 1 for v in per.values())


def test_every_event_with_a_change_has_a_timeline_whose_first_report_is_a_new_event(replay_container):
    c = replay_container
    k = len(c.monitor.cycles()) - 1
    seen = 0
    for ch in c.monitor.replay_changes(cycle=k, window=4).changes[:6]:
        mem = c.monitor.memory(ch.event_id)
        assert mem.availability == "AVAILABLE" and mem.items
        first = next(i for i in mem.items if i.kind == "REPORT")
        assert first.update_kind.value == "NEW_EVENT" and sum(mem.update_counts.values()) == len([i for i in mem.items if i.kind == "REPORT"])
        seen += 1
    assert seen


def test_the_digest_is_identical_after_a_sidecar_rebuild_and_leaves_the_signals_alone(replay_container):
    c = replay_container
    k = len(c.monitor.cycles()) - 1
    before = c.digest.digest(cycle=k, window=4).model_dump_json()
    rebuild_sidecars(c, {})
    assert c.digest.digest(cycle=k, window=4).model_dump_json() == before
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST


def test_feedback_does_not_move_the_signals_or_any_frozen_artifact(replay_container):
    from eventshock.feedback.models import FeedbackInput
    c = replay_container
    _, states = c.monitor.replay_states(None)
    eid = sorted(states.states)[0]
    before_cfg = c.config.model_dump_json()
    for t, v in (("RELEVANCE", "IRRELEVANT"), ("SCOPE", "INCORRECT"), ("EVENT", "INCORRECT")):
        c.feedback.submit(FeedbackInput(event_id=eid, type=t, value=v, analyst_id="e2e"))
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST and c.config.model_dump_json() == before_cfg


def test_derived_views_never_change_which_stress_runs_exist(replay_container):
    """The monitor, the digest, an explanation, the lab and reverse stress are derived: the propagation view's `existing_run_id` and the stress service's runs are what a person ran."""
    from eventshock.explain.models import Subject
    from eventshock.lab.models import Assumption, AssumptionKind, ReverseStressRequest, ScenarioRequest
    c = replay_container
    runs_before = list(c.stress._runs)  # noqa: SLF001
    k = len(c.monitor.cycles()) - 1
    _, states = c.monitor.replay_states(k)
    c.digest.digest(cycle=k, window=4)
    for eid in sorted(states.states)[:10]:
        c.explain.event(eid, Subject.STRESS)
    c.lab.run(ScenarioRequest(assumptions=[Assumption(kind=AssumptionKind.EQUITY_MARKET, value=-0.1)]))
    c.lab.reverse(ReverseStressRequest(target_pct=-5))
    assert list(c.stress._runs) == runs_before  # noqa: SLF001
