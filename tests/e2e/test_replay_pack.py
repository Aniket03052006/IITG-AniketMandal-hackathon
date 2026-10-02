"""Invariants over the shipped replay pack: messy real input must not corrupt the downstream signal."""

from __future__ import annotations

import json
import random

from eventshock.config import REPO_ROOT
from eventshock.domain import UNKNOWN_ENTITY, DataOrigin, SourceType
from eventshock.ingestion.snapshot import load_snapshot
from eventshock.pipeline.config import (
    load_enrichment_config,
    load_pipeline_config,
    load_sentiment_model_config,
)
from eventshock.pipeline.enrich import ModelSentimentEnricher
from eventshock.pipeline.run import load_entities, read_snapshot, run_documents, run_snapshot
from eventshock.pipeline.sentiment_model import SentimentModel

PACK = REPO_ROOT / "data" / "replay"
CFG = load_pipeline_config(REPO_ROOT / "configs")
ENR = load_enrichment_config(REPO_ROOT / "configs")
SNAP = load_snapshot(PACK)
MODEL = SentimentModel.load(REPO_ROOT / load_sentiment_model_config(REPO_ROOT / "configs").model_dir)
ENRICHER = ModelSentimentEnricher(ENR, MODEL)
RESULT = run_snapshot(SNAP, CFG, ENR, ENRICHER)  # what the app serves
PLACEHOLDER = run_snapshot(SNAP, CFG, ENR)  # the Stage-2 enricher, kept as a regression anchor


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
        assert s.data_origin is DataOrigin.REAL_SOURCE_MIXED_NLP
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
        assert s.provenance.stage_origins == {"sentiment": "MODEL", "event": "PLACEHOLDER_RULES", "impact": "PLACEHOLDER_RULES"}
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
    again = run_snapshot(SNAP, CFG, ENR, ENRICHER)
    assert again.report.output_digest == RESULT.report.output_digest
    records, metas = read_snapshot(SNAP)
    random.Random(7).shuffle(records)
    m = SNAP.manifest
    shuffled = run_documents(records, snapshot_id=m.snapshot_id, description=m.description, as_of=m.replay_as_of,
                             window_start=m.window_start, window_end=m.window_end,
                             entities=load_entities(SNAP.entities_path()), cfg=CFG, enrich_cfg=ENR, sources=metas,
                             enricher=ENRICHER)
    assert shuffled.report.output_digest == RESULT.report.output_digest


def test_pipeline_output_serialises_to_stable_json():
    a = json.dumps([s.model_dump(mode="json") for s in RESULT.signals[:5]], sort_keys=True)
    assert a == json.dumps([s.model_dump(mode="json") for s in run_snapshot(SNAP, CFG, ENR, ENRICHER).signals[:5]], sort_keys=True)


GOLDEN_DIGEST = "632ae6d015818b7c8892f78456a36667b9c60964ced1585e686febc20d0c06e9"
GOLDEN_COUNTS = dict(records_read=3087, quarantined=190, exact_duplicates_folded=153,
                     reports_in_signals=2744, signals=2153, entity_resolved=1155,
                     entity_unknown=998, syndicated=515, near_duplicates=51,
                     same_event=25)
# The Stage-2 (placeholder) digest, before provenance gained its optional `sentiment` field.
PLACEHOLDER_STAGE2_DIGEST = "b8074b4379d2bd14c9843a6a37d60bf62a531c54bcfd86f75b65a1d38a02eafc"


def test_golden_replay():
    """Pins the shipped pack's output. A deliberate change to rules, configs, data or the sentiment artifact must
    update these values (and say why in docs/PROJECT_JOURNEY.md); an accidental one fails here."""
    got = RESULT.report.counts.model_dump()
    assert {k: got[k] for k in GOLDEN_COUNTS} == GOLDEN_COUNTS
    assert RESULT.report.output_digest == GOLDEN_DIGEST


def test_placeholder_enricher_behaviour_is_unchanged():
    """Adding the sentiment model changed no placeholder behaviour: without the new null `provenance.sentiment` field
    the placeholder run reproduces the Stage-2 digest exactly."""
    import hashlib

    payload = []
    for s in sorted(PLACEHOLDER.signals, key=lambda s: s.id):
        d = s.model_dump(mode="json")
        assert d["provenance"].pop("sentiment") is None
        payload.append(d)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert digest == PLACEHOLDER_STAGE2_DIGEST
    assert all(s.data_origin is DataOrigin.REAL_SOURCE_PLACEHOLDER_NLP for s in PLACEHOLDER.signals)


def test_every_signal_carries_a_valid_sentiment_audit_matching_the_artifact():
    for s in RESULT.signals:
        a = s.provenance.sentiment
        assert a is not None and a.model_id == MODEL.model_id and a.artifact_sha256 == MODEL.artifact_sha256 and a.calibrated
        assert a.confidence >= 1 / 3 - 1e-3
        assert s.model_versions.sentiment == f"{MODEL.model_id}+{MODEL.artifact_sha256[:8]}"
        assert s.model_versions.event.startswith("placeholder") and s.model_versions.impact.startswith("placeholder")


def test_replay_tweets_are_flagged_in_sample_and_news_headlines_are_not():
    tweets = [s for s in RESULT.signals if s.provenance.adapter == "tfn-replay"]
    news = [s for s in RESULT.signals if s.provenance.adapter != "tfn-replay"]
    assert sum(s.provenance.sentiment.seen_in_training for s in tweets) > 0.8 * len(tweets), "the TFN sample comes from the training data"
    assert not any(s.provenance.sentiment.seen_in_training for s in news)


def test_model_agrees_with_the_human_labels_on_the_replay_tweets_but_does_not_copy_them():
    """In-sample sanity floor (not an accuracy claim): clearly above chance, yet not a copy of the label."""
    lab = {"bullish": 1, "bearish": -1, "neutral": 0}
    tweets = [s for s in RESULT.signals if s.provenance.adapter == "tfn-replay"]
    sign = lambda x: (x >= 0.15) - (x <= -0.15)  # noqa: E731
    agree = sum(sign(s.sentiment.score) == lab[s.document.raw_metadata["source_label"]] for s in tweets) / len(tweets)
    assert 0.8 < agree < 1.0
    assert all(abs(s.sentiment.score) < 1.0 for s in tweets), "a copied label would be exactly +-1.0"


def test_texts_the_model_cannot_score_are_quarantined_with_their_own_code_not_scored():
    assert RESULT.report.quarantine_by_code.get("UNSCORABLE_TEXT", 0) > 0
    quarantined = {q.record_ref for q in RESULT.quarantined if q.code == "UNSCORABLE_TEXT"}
    assert quarantined and not quarantined & {s.provenance.record_ref for s in RESULT.signals}
    assert all(q.detail for q in RESULT.quarantined if q.code == "UNSCORABLE_TEXT")
    assert "UNSCORABLE_TEXT" not in PLACEHOLDER.report.quarantine_by_code
