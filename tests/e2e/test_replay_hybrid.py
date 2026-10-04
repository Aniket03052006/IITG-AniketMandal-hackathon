"""The served event stage is the hybrid (keywords + semantics), fed from hash-pinned vectors: offline, deterministic, and it changes only what it should."""

from __future__ import annotations

import random
import sys
from collections import Counter

import pytest

from eventshock.config import REPO_ROOT
from eventshock.pipeline.embeddings import PinnedEmbeddings
from eventshock.pipeline.enrich import ImpactModelEnricher
from eventshock.pipeline.hybrid_event_model import HybridEventModel
from eventshock.pipeline.run import load_entities, read_snapshot, run_documents, run_snapshot
from tests.pipe_helpers import digest_without_stage6

from . import test_replay_pack as T

DIR = REPO_ROOT / "models/event/hybrid-event-v2"
pytestmark = pytest.mark.skipif(not (DIR / "model.joblib").is_file() or T.SNAP.embeddings_path() is None, reason="run `make train-event-hybrid replay-embeddings`")

GOLDEN_HYBRID_DIGEST = "0721c9e9fefe9e12f33982a1da94b792331997976dae62acb65fcd31f8f592b5"
GOLDEN_STATUS_MIX = {"NO_EVENT": 1037, "CLASSIFIED": 962, "UNCERTAIN": 331}
GOLDEN_IMPACT_MIX = {("PARTIAL", "PLACEHOLDER_RULES", None): 1368, ("COMPLETE", "MODEL", "MARKET"): 355, ("COMPLETE", "MODEL", "ISSUER"): 370,
                     ("COMPLETE", "PLACEHOLDER_RULES", None): 237}

PINS = PinnedEmbeddings(T.SNAP.embeddings_path(), sha256=T.SNAP.manifest.embeddings.sha256) if T.SNAP.embeddings_path() else None
HYBRID_MODEL = HybridEventModel.load(DIR, PINS) if PINS else None
ENRICHER = ImpactModelEnricher(T.ENR, T.MODEL, HYBRID_MODEL, T.IMPACT_MODEL, T.CONTEXT, impact_event_model=T.EVENT) if PINS else None
HYBRID = run_snapshot(T.SNAP, T.CFG, T.ENR, ENRICHER) if PINS else None


def by_id(res):
    return {s.id: s for s in res.signals}


def test_it_runs_offline_from_pinned_vectors_and_never_needed_an_encoder():
    assert "torch" not in sys.modules and "transformers" not in sys.modules
    assert len(PINS) >= 2300 and PINS.dim == 1024 and PINS.encoder == "intfloat/multilingual-e5-large"


def test_the_pack_is_accounted_for_exactly_as_with_the_tfidf_model():
    """Which documents are scorable is decided from the TF-IDF part alone, so quarantine and clustering do not move."""
    got = HYBRID.report.counts.model_dump()
    assert {k: got[k] for k in T.GOLDEN_COUNTS} == T.GOLDEN_COUNTS
    assert {s.id for s in HYBRID.signals} == {s.id for s in T.IMPACTED.signals}
    assert [q.model_dump() for q in HYBRID.quarantined] == [q.model_dump() for q in T.IMPACTED.quarantined]


def test_the_hybrid_run_is_pinned_deterministic_and_input_order_independent():
    assert digest_without_stage6(HYBRID.signals) == GOLDEN_HYBRID_DIGEST
    records, metas = read_snapshot(T.SNAP)
    random.Random(5).shuffle(records)
    m = T.SNAP.manifest
    shuffled = run_documents(records, snapshot_id=m.snapshot_id, description=m.description, as_of=m.replay_as_of, window_start=m.window_start,
                             window_end=m.window_end, entities=load_entities(T.SNAP.entities_path()), cfg=T.CFG, enrich_cfg=T.ENR, sources=metas,
                             enricher=ENRICHER)
    assert digest_without_stage6(shuffled.signals) == GOLDEN_HYBRID_DIGEST and shuffled.report.output_digest == HYBRID.report.output_digest


def test_every_signal_names_the_hybrid_and_carries_its_audit():
    for s in HYBRID.signals:
        a = s.provenance.event
        assert a is not None and a.model_id == "hybrid-event-v2" and a.artifact_sha256 == HYBRID_MODEL.artifact_sha256 and a.calibrated
        assert s.model_versions.event.startswith("hybrid-event-v2+") and s.provenance.stage_origins["event"] == "MODEL"


def test_it_commits_more_and_abstains_less_than_the_tfidf_model_on_the_same_documents():
    mix = Counter(s.event.status.value for s in HYBRID.signals)
    assert dict(mix) == GOLDEN_STATUS_MIX
    old = Counter(s.event.status.value for s in T.IMPACTED.signals)
    assert mix["UNCERTAIN"] < old["UNCERTAIN"] and mix["CLASSIFIED"] > old["CLASSIFIED"]


def test_sentiment_entity_and_dedup_are_untouched_by_the_event_swap():
    old = by_id(T.IMPACTED)
    for s in HYBRID.signals:
        o = old[s.id]
        assert s.sentiment == o.sentiment and s.entity == o.entity and s.provenance.dedup == o.provenance.dedup and s.document == o.document


def test_impact_parity_a_signal_scored_by_the_impact_model_in_both_runs_gets_the_identical_estimate():
    """impact-v1 was trained on the TF-IDF event model's probabilities, so it keeps reading them: no train/serve skew from the swap."""
    old, both = by_id(T.IMPACTED), 0
    for s in HYBRID.signals:
        o = old[s.id]
        if s.provenance.stage_origins["impact"] == "MODEL" and o.provenance.stage_origins["impact"] == "MODEL":
            both += 1
            assert s.impact == o.impact and s.provenance.impact == o.provenance.impact
    assert both > 250


def test_impact_status_and_labelling_stay_honest_with_the_hybrid():
    mix = Counter((s.status.value, s.provenance.stage_origins["impact"], s.impact.scope if s.provenance.stage_origins["impact"] == "MODEL" else None)
                  for s in HYBRID.signals)
    assert dict(mix) == GOLDEN_IMPACT_MIX
    for s in HYBRID.signals:
        if s.event.status.value != "CLASSIFIED":
            assert s.impact is None and s.status.value == "PARTIAL"           # a non-event or an undecided type never gets an impact


def test_a_replay_text_missing_from_the_pins_would_fail_loudly_not_be_guessed():
    from eventshock.pipeline.embeddings import EmbeddingUnavailable

    with pytest.raises(EmbeddingUnavailable):
        HYBRID_MODEL.decide("A sentence that is certainly not one of the pinned replay documents, about Zorblax Industries merging.")
