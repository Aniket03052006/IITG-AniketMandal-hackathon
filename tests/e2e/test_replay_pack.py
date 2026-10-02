"""Invariants over the shipped replay pack: messy real input must not corrupt the downstream signal."""

from __future__ import annotations

import json
import random

from eventshock.config import REPO_ROOT
from eventshock.domain import UNKNOWN_ENTITY, DataOrigin, SourceType
from eventshock.ingestion.snapshot import load_snapshot
from eventshock.pipeline.config import load_enrichment_config, load_pipeline_config
from eventshock.pipeline.run import load_entities, read_snapshot, run_documents, run_snapshot

PACK = REPO_ROOT / "data" / "replay"
CFG = load_pipeline_config(REPO_ROOT / "configs")
ENR = load_enrichment_config(REPO_ROOT / "configs")
SNAP = load_snapshot(PACK)
RESULT = run_snapshot(SNAP, CFG, ENR)


def test_every_record_is_accounted_for_and_nothing_quarantined_is_a_signal():
    c = RESULT.report.counts
    assert c.records_read == sum(s.records for s in SNAP.manifest.sources)
    assert c.records_read == c.quarantined + c.exact_duplicates_folded + c.reports_in_signals
    refs = {q.record_ref for q in RESULT.quarantined}
    assert not refs & {s.provenance.record_ref for s in RESULT.signals}


def test_signal_invariants():
    m = SNAP.manifest
    master = {e.entity_id: e for e in load_entities(SNAP.entities_path())}
    ids = [s.id for s in RESULT.signals]
    assert len(ids) == len(set(ids))
    assert {s.document.source_type for s in RESULT.signals} == {SourceType.NEWS, SourceType.SOCIAL}
    assert {s.provenance.adapter for s in RESULT.signals} == {"gdelt-doc", "gdelt-gkg", "tfn-replay"}
    for s in RESULT.signals:
        assert s.data_origin is DataOrigin.REAL_SOURCE_PLACEHOLDER_NLP
        assert s.entity.entity_id == UNKNOWN_ENTITY or s.entity.entity_id in master
        if s.entity.entity_id != UNKNOWN_ENTITY:
            e = master[s.entity.entity_id]
            assert (s.entity.ticker, s.entity.sector) == (e.ticker, e.sector)
            assert s.entity.link_confidence >= CFG.entity_resolution.min_link_confidence
        assert s.evidence.source_count == 1 + len(s.evidence.corroborating) == s.provenance.dedup.member_count
        assert s.evidence.unique_domain_count <= s.evidence.source_count
        assert 1 <= s.impact.score <= 10 and s.status.value == "COMPLETE"
        assert s.document.published_at <= m.replay_as_of and s.created_at == m.replay_as_of
        assert s.provenance.snapshot_id == m.snapshot_id and len(s.provenance.content_sha256) == 64
        assert s.provenance.stage_origins["impact"] == "PLACEHOLDER_RULES"
        if s.provenance.timestamp_origin.value != "SYNTHETIC_REPLAY_CLOCK":
            assert m.window_start <= s.document.published_at <= m.window_end


def test_the_pack_exercises_the_hard_cases():
    c = RESULT.report.counts
    assert c.quarantined > 0 and c.entity_unknown > 0 and c.entity_resolved > 0
    assert c.rejected_ambiguous_mentions > 0, "ambiguous names (Apple/Visa/Target...) must be exercised and refused"
    assert any(s.evidence.source_count > 1 for s in RESULT.signals), "at least one multi-report story"
    assert any(s.impact.score >= 7 for s in RESULT.signals if s.entity.entity_id != UNKNOWN_ENTITY), (
        "the demo needs a triggering signal on a known issuer")


def test_replay_is_deterministic_and_input_order_independent():
    again = run_snapshot(SNAP, CFG, ENR)
    assert again.report.output_digest == RESULT.report.output_digest
    records, metas = read_snapshot(SNAP)
    random.Random(7).shuffle(records)
    m = SNAP.manifest
    shuffled = run_documents(records, snapshot_id=m.snapshot_id, description=m.description, as_of=m.replay_as_of,
                             window_start=m.window_start, window_end=m.window_end,
                             entities=load_entities(SNAP.entities_path()), cfg=CFG, enrich_cfg=ENR, sources=metas)
    assert shuffled.report.output_digest == RESULT.report.output_digest


def test_pipeline_output_serialises_to_stable_json():
    a = json.dumps([s.model_dump(mode="json") for s in RESULT.signals[:5]], sort_keys=True)
    assert a == json.dumps([s.model_dump(mode="json") for s in run_snapshot(SNAP, CFG, ENR).signals[:5]], sort_keys=True)


GOLDEN_DIGEST = "b8074b4379d2bd14c9843a6a37d60bf62a531c54bcfd86f75b65a1d38a02eafc"
GOLDEN_COUNTS = dict(records_read=3087, quarantined=186, exact_duplicates_folded=153,
                     reports_in_signals=2748, signals=2157, entity_resolved=1157,
                     entity_unknown=1000, syndicated=515, near_duplicates=51,
                     same_event=25)


def test_golden_replay():
    """Pins the shipped pack's output. A deliberate change to rules, configs or data must update these values
    (and say why in docs/PROJECT_JOURNEY.md); an accidental one fails here."""
    got = RESULT.report.counts.model_dump()
    assert {k: got[k] for k in GOLDEN_COUNTS} == GOLDEN_COUNTS
    assert RESULT.report.output_digest == GOLDEN_DIGEST
