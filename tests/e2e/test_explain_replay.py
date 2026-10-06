"""Explanations over the real replay pack: every tracked event and every detected change explains itself, deterministically, and nothing is written onto a signal."""

from __future__ import annotations

from eventshock.api.deps import rebuild_sidecars
from eventshock.explain.models import Subject
from eventshock.pipeline.run import _digest
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST


def test_no_tracked_event_and_no_change_is_left_without_reasons(replay_container):
    c = replay_container
    m = c.monitor
    k = len(m.cycles()) - 1
    _, states = m.replay_states(k)
    ids = sorted(states.states)[:60]
    assert ids
    for eid in ids:
        for subject in (Subject.PRIORITY, Subject.VISIBILITY):
            e = c.explain.event(eid, subject)
            assert e.availability == "AVAILABLE" and e.reasons, (eid, subject)
            assert all(r.source_ref and r.provenance for r in e.reasons)
    for ch in m.replay_changes(cycle=k, window=4).changes[:40]:
        e = c.explain.event(ch.event_id, Subject.CHANGE, cycle=k, change_id=ch.change_id)
        assert e.reasons and e.reasons[0].value == ch.rule
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST


def test_explanations_are_identical_after_a_sidecar_rebuild(replay_container):
    c = replay_container
    _, states = c.monitor.replay_states(None)
    ids = sorted(states.states)[:12]
    before = [c.explain.event(i, Subject.PRIORITY).model_dump_json() for i in ids]
    rebuild_sidecars(c, {})
    assert [c.explain.event(i, Subject.PRIORITY).model_dump_json() for i in ids] == before
