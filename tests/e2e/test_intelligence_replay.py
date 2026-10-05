"""Event intelligence over the real replay pack: it never raises, never touches a signal (the pinned digest holds), groups consistently, and the one
engine that serves live and pasted text produces the same signals as the replay batch for the same records (unified ingestion)."""

from __future__ import annotations

from collections import Counter

from eventshock.domain import UNKNOWN_ENTITY
from eventshock.pipeline.config import load_pipeline_config
from eventshock.pipeline.engine import RiskEngine
from eventshock.pipeline.run import _digest, load_entities, read_snapshot, run_documents
from eventshock.store import LiveSignalStore
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST


def test_every_signal_gets_intelligence_and_none_is_touched(replay_container):
    c = replay_container
    sigs = c.signals.list()
    for s in sigs:
        r = c.intelligence.for_signal(s, include_stress=False)
        assert r.signal_id == s.id and r.group.report_count >= s.evidence.source_count
        assert r.scope.scope_type.value == "UNRESOLVED" or r.scope.scope_value
        assert r.scope.scope_type.value != "COMPANY" or s.entity.entity_id != UNKNOWN_ENTITY  # a company is only ever the pipeline's resolved one
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST  # nothing was written onto any signal


def test_event_grouping_is_a_partition_and_untrusted_clocks_stay_alone(replay_container):
    idx = replay_container.intelligence.index()
    sigs = replay_container.signals.list()
    seen = Counter(sid for e in idx.events for sid in e.signal_ids)
    assert set(seen) == {s.id for s in sigs} and set(seen.values()) == {1}
    assert all(len(e.nodes) == 1 for e in idx.events if not e.trusted)
    assert len(idx.events) < len(sigs)  # the replay pack does contain several clusters of one story


def test_one_engine_serves_replay_live_and_pasted_text_alike(replay_container):
    """The same records through the incremental engine (the door pasted text and the live feed use) and through the replay batch give identical signals."""
    c = replay_container
    snap = c.snapshot
    records, _ = read_snapshot(snap)
    # whole clusters (a record joins a cluster only through its earliest report, whose text is the one with a pinned vector)
    keep: set[str] = set()
    for s in c.signals.list()[::9][:220]:
        keep.add(s.document.id)
        keep.update(m.document_id for m in s.provenance.dedup.members)
    sample = [r for r in records if getattr(r, "id", None) in keep]
    assert len(sample) > 150
    cfg = load_pipeline_config(c.settings.config_dir)
    m = snap.manifest
    batch = run_documents(sample, snapshot_id=m.snapshot_id, as_of=m.replay_as_of, window_start=m.window_start, window_end=m.window_end,
                          entities=load_entities(snap.entities_path()), cfg=cfg, enrich_cfg=c.engine._enrich_cfg, enricher=c.engine._primary,  # noqa: SLF001
                          scope_resolver=c.engine._scope)  # noqa: SLF001
    engine = RiskEngine(entities=load_entities(snap.entities_path()), pipeline_cfg=cfg, enrich_cfg=c.engine._enrich_cfg, scope_resolver=c.engine._scope,  # noqa: SLF001
                        enricher=c.engine._primary, fallback_enricher=None, store=LiveSignalStore(24 * 365 * 20, 100000),  # noqa: SLF001
                        event_model_id=c.engine.status.event_model, snapshot_id=m.snapshot_id)
    out = engine.ingest(sample, channel="LIVE", now=m.replay_as_of)
    live = {s.id: s for s, _ in engine.store.items()}
    want = {s.id: s for s in batch.signals}
    assert set(live) == set(want), (len(live), len(want))
    for sid, s in want.items():
        a, b = s.model_dump(mode="json"), live[sid].model_dump(mode="json")
        assert a == b, sid
    assert len([o for o in out if o.outcome.value == "QUARANTINED"]) == len(batch.quarantined)
