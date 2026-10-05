"""Event -> portfolio propagation over the real replay pack: every signal can be mapped without raising, nothing is written onto a signal (the pinned digest holds),
a rebuilt side-car answers byte for byte the same, generated scenarios run through the engine and reconcile, and an adjustment that is reset leaves no trace."""

from __future__ import annotations

import pytest

from eventshock.api.deps import rebuild_sidecars
from eventshock.pipeline.run import _digest
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST


def sample(c, step=7):
    return c.signals.list()[::step]


def test_every_sampled_signal_maps_without_raising_and_nothing_is_written_onto_a_signal(replay_container):
    c = replay_container
    levels = set()
    for s in sample(c):
        f = c.propagation.flow(s)
        g, m = f.graph, f.materiality
        assert 0 <= g.reached_share <= 1 + 1e-9 and 0 <= g.direct_share <= g.reached_share + 1e-9
        assert g.evidenced_share + g.assumed_share == pytest.approx(g.reached_share)
        assert {h.asset_id for h in g.reached} <= {a.asset_id for a in c.portfolio.get().assets}
        assert m.level in ("LOW", "MEDIUM", "HIGH", "CRITICAL", "NONE", "UNDETERMINED")
        assert (m.level == "UNDETERMINED") == (g.availability.value == "ABSTAINED")
        levels.add(m.level)
        assert f.scenario.label == "SCENARIO SIMULATION — NOT A PREDICTION"
    assert len(levels) >= 3  # the pack exercises relevance, not one degenerate value
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST


def test_a_rebuilt_sidecar_answers_byte_for_byte_the_same(replay_container):
    c = replay_container
    sigs = sample(c, 23)
    before = [c.propagation.flow(s).model_dump_json() for s in sigs]
    old = c.propagation
    rebuild_sidecars(c, {})
    assert c.propagation is not old  # a different instance ...
    assert [c.propagation.flow(s).model_dump_json() for s in sigs] == before  # ... the same answers


def test_the_direct_share_agrees_with_the_existing_relevance_service(replay_container):
    """Stage 9's relevance and Stage 11's mapping are two readings of the same holdings: where the named issuer is held they must agree."""
    c = replay_container
    checked = 0
    for s in c.signals.list():
        r = c.relevance.assess(s, with_reach=False)
        if r.level.value != "DIRECT":
            continue
        g = c.propagation.graph(s)
        assert g.direct_share == pytest.approx(r.share, abs=1e-9), s.id
        checked += 1
        if checked >= 25:
            break
    assert checked >= 5


def test_generated_scenarios_run_and_every_attribution_table_adds_up(replay_container):
    c = replay_container
    ran = 0
    for s in c.signals.list():
        gen = c.propagation.scenario(s)
        if gen.availability.value != "AVAILABLE":
            continue
        r = c.propagation.portfolio_stress(s)
        assert r.run is not None
        if r.run.status.value != "COMPLETED":
            continue
        att = r.attribution
        assert att is not None and att.reconciled
        for t in [att.drivers, *att.tables]:
            assert abs(sum(x.delta for x in t.rows) - r.run.summary.pnl) <= att.tolerance + 1e-6, (s.id, t.dimension)
        assert abs(r.chain.total_impact - r.run.summary.pnl) <= 0.02
        ran += 1
        if ran >= 12:
            break
    assert ran >= 1


def test_adjust_then_reset_leaves_every_answer_unchanged(replay_container):
    c = replay_container
    sigs = sample(c, 31)
    before = [(c.propagation.flow(s).model_dump_json(), c.intelligence.for_signal(s, include_stress=False).model_dump_json()) for s in sigs]
    try:
        assert c.adjust.put({"propagation.generation.min_severity": 3, "intelligence.novelty.lookback_days": 5}).ok
        during = [c.propagation.flow(s).model_dump_json() for s in sigs]
        assert during != [b[0] for b in before]  # the adjustment is visible (and labelled)
        assert all('"adjustments":{"count":2' in d for d in during)
    finally:
        c.adjust.reset()
    after = [(c.propagation.flow(s).model_dump_json(), c.intelligence.for_signal(s, include_stress=False).model_dump_json()) for s in sigs]
    assert after == before
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST


def test_overlap_clusters_respect_their_own_thresholds(replay_container):
    c = replay_container
    cfg = c.propagation.cfg.concentration
    v = c.propagation.overlaps()
    assert v.availability.value == "AVAILABLE"
    for k in v.clusters:
        assert len(k.events) >= cfg.min_events and k.shared_share >= cfg.min_overlap_share
        assert len({e.event_id for e in k.events}) == len(k.events)  # one story is one event
