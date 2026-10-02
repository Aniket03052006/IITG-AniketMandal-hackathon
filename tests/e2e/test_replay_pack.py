"""Invariants over the shipped replay pack: messy real input must not corrupt the downstream signal."""

from __future__ import annotations

import json
import random

from eventshock.config import REPO_ROOT
from eventshock.domain import UNKNOWN_ENTITY, DataOrigin, EventStatus, SignalStatus, SourceType
from eventshock.ingestion.snapshot import load_snapshot
from eventshock.pipeline.config import (
    load_enrichment_config,
    load_event_model_config,
    load_pipeline_config,
    load_sentiment_model_config,
)
from eventshock.pipeline.enrich import ModelEnricher, ModelSentimentEnricher
from eventshock.pipeline.event_model import EventModel
from eventshock.pipeline.run import load_entities, read_snapshot, run_documents, run_snapshot
from eventshock.pipeline.sentiment_model import SentimentModel

PACK = REPO_ROOT / "data" / "replay"
CFG = load_pipeline_config(REPO_ROOT / "configs")
ENR = load_enrichment_config(REPO_ROOT / "configs")
SNAP = load_snapshot(PACK)
MODEL = SentimentModel.load(REPO_ROOT / load_sentiment_model_config(REPO_ROOT / "configs").model_dir)
EVENT = EventModel.load(REPO_ROOT / load_event_model_config(REPO_ROOT / "configs").model_dir)
ENRICHER = ModelEnricher(ENR, MODEL, EVENT)
RESULT = run_snapshot(SNAP, CFG, ENR, ENRICHER)  # what the app serves
SENTIMENT_ONLY = run_snapshot(SNAP, CFG, ENR, ModelSentimentEnricher(ENR, MODEL))  # the Stage-3 sentiment slice, a regression anchor
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
        if s.event.status is EventStatus.CLASSIFIED:
            assert s.status is SignalStatus.COMPLETE and 1 <= s.impact.score <= 10
        else:
            assert s.status is SignalStatus.PARTIAL and s.impact is None and s.status_reason
        assert s.document.published_at <= m.replay_as_of and s.created_at == m.replay_as_of
        assert s.provenance.snapshot_id == m.snapshot_id and len(s.provenance.content_sha256) == 64
        assert s.provenance.stage_origins == {"sentiment": "MODEL", "event": "MODEL", "impact": "PLACEHOLDER_RULES"}
        if s.provenance.timestamp_origin.value != "SYNTHETIC_REPLAY_CLOCK":
            assert m.window_start <= s.document.published_at <= m.window_end


def test_the_pack_exercises_the_hard_cases():
    c = RESULT.report.counts
    assert c.quarantined > 0 and c.entity_unknown > 0 and c.entity_resolved > 0
    assert c.rejected_ambiguous_mentions > 0, "ambiguous names (Apple/Visa/Target...) must be exercised and refused"
    assert any(s.evidence.source_count > 1 for s in RESULT.signals), "at least one multi-report story"
    assert any(s.impact is not None and s.impact.score >= 7 for s in RESULT.signals if s.entity.entity_id != UNKNOWN_ENTITY), (
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


GOLDEN_DIGEST = "60d8d02038053b4a6ea6a33a0e8559105585d7d4df5749e141b2e862c0c839ab"
GOLDEN_COUNTS = dict(records_read=3455, quarantined=244, exact_duplicates_folded=184,
                     reports_in_signals=3027, signals=2330, entity_resolved=1182,
                     entity_unknown=1148, syndicated=612, near_duplicates=59,
                     same_event=26)
# Anchors for the stages the event model was added on top of. The pack grew when the four rate-limited GDELT queries were
# re-fetched (3087 -> 3455 records), so these were re-pinned once; docs/PROJECT_JOURNEY.md records that the placeholder enricher
# still reproduces its pre-refetch Stage-2 digest (b8074b43...) byte for byte on the old pack.
SENTIMENT_ONLY_DIGEST = "1532effe5cb61634fdb36d9fd355363418e25cb986513a48c3eefd6efc08d905"
PLACEHOLDER_DIGEST = "fbe26c47f94912cec4dd73ff85659bce308a3b8b78accc8fb7c25c07ef81fab1"


def test_golden_replay():
    """Pins the shipped pack's output. A deliberate change to rules, configs, data or a model artifact must
    update these values (and say why in docs/PROJECT_JOURNEY.md); an accidental one fails here."""
    got = RESULT.report.counts.model_dump()
    assert {k: got[k] for k in GOLDEN_COUNTS} == GOLDEN_COUNTS
    assert RESULT.report.output_digest == GOLDEN_DIGEST


def test_sentiment_only_enricher_behaviour_is_unchanged():
    """The event model changed nothing about the sentiment-only path: same counts, and (apart from the new null event fields)
    the same signals as before."""
    got = SENTIMENT_ONLY.report.counts.model_dump()
    assert {k: got[k] for k in GOLDEN_COUNTS} == GOLDEN_COUNTS
    assert SENTIMENT_ONLY.report.output_digest == SENTIMENT_ONLY_DIGEST
    assert all(s.event.status is EventStatus.CLASSIFIED and s.provenance.event is None for s in SENTIMENT_ONLY.signals)


def test_placeholder_enricher_behaviour_is_unchanged():
    """Without the null fields later stages added (`provenance.sentiment`, `provenance.event`, `event.status`,
    `event.no_event_probability`) the placeholder run reproduces its digest exactly."""
    import hashlib

    payload = []
    for s in sorted(PLACEHOLDER.signals, key=lambda s: s.id):
        d = s.model_dump(mode="json")
        assert d["provenance"].pop("sentiment") is None and d["provenance"].pop("event") is None
        assert d["event"].pop("status") == "CLASSIFIED" and d["event"].pop("no_event_probability") is None
        payload.append(d)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert digest == PLACEHOLDER_DIGEST
    assert all(s.data_origin is DataOrigin.REAL_SOURCE_PLACEHOLDER_NLP for s in PLACEHOLDER.signals)


def test_every_signal_carries_a_valid_sentiment_audit_matching_the_artifact():
    for s in RESULT.signals:
        a = s.provenance.sentiment
        assert a is not None and a.model_id == MODEL.model_id and a.artifact_sha256 == MODEL.artifact_sha256 and a.calibrated
        assert a.confidence >= 1 / 3 - 1e-3
        assert s.model_versions.sentiment == f"{MODEL.model_id}+{MODEL.artifact_sha256[:8]}"
        assert s.model_versions.event == f"{EVENT.model_id}+{EVENT.artifact_sha256[:8]}"
        assert s.model_versions.impact.startswith("placeholder")


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


# --------------------------------------------------------------------------------------------- the event stage
def test_every_signal_carries_a_valid_event_audit_matching_the_artifact():
    for s in RESULT.signals:
        a = s.provenance.event
        assert a is not None and a.model_id == EVENT.model_id and a.artifact_sha256 == EVENT.artifact_sha256 and a.calibrated
        assert s.event.no_event_probability == a.no_event_probability
        assert s.provenance.stage_origins["event"] == "MODEL"
        if s.event.status is EventStatus.CLASSIFIED:
            assert a.confidence >= EVENT.commit_threshold - 1e-3 and not a.unreliable_class
            assert s.event.category.value not in EVENT.unreliable, "a class the card flags unreliable is never asserted"


def test_the_event_model_commits_to_some_events_abstains_on_others_and_says_not_an_event():
    mix = {st: sum(s.event.status is st for s in RESULT.signals) for st in EventStatus}
    assert all(n > 0 for n in mix.values()), mix
    assert mix[EventStatus.CLASSIFIED] > 0.1 * len(RESULT.signals)


def test_non_events_never_get_an_impact_so_the_stress_engine_cannot_fire_on_them():
    partial = [s for s in RESULT.signals if s.event.status is not EventStatus.CLASSIFIED]
    assert partial and all(s.impact is None and s.status is SignalStatus.PARTIAL for s in partial)
    assert all(s.status_reason.startswith(("No market event", "Event type uncertain")) for s in partial)


def test_the_event_model_is_not_the_placeholder_it_replaced():
    by_id = {s.id: s for s in PLACEHOLDER.signals}
    changed = sum(s.event.category != by_id[s.id].event.category for s in RESULT.signals if s.event.status is EventStatus.CLASSIFIED)
    assert changed > 0.2 * sum(s.event.status is EventStatus.CLASSIFIED for s in RESULT.signals)
    assert sum(s.event.category.value == "MARKET_VALUATION" for s in PLACEHOLDER.signals) > 0.5 * len(PLACEHOLDER.signals), (
        "the placeholder's no-keyword default dominates; the model should not")


def test_replay_documents_seen_in_event_training_are_flagged():
    seen = [s for s in RESULT.signals if s.provenance.event.seen_in_training]
    assert len(seen) < 0.1 * len(RESULT.signals), "the replay pack is not the event model's training data"
