"""The configuration the product actually serves, pinned end to end: sentiment tfidf-lr-v1, hybrid-event-v2 and impact-v2 (the other golden
tests pin the v1 impact reference). Also pins the intentional train/serve interaction: impact reads the TF-IDF event model's probabilities."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from eventshock.api.deps import build_container
from eventshock.config import REPO_ROOT

# Stage 6 added `scope` and `evidence.novelty_measured` to every signal, so the digest of the full dump changed on purpose.
# GOLDEN_LEGACY_DIGEST is the digest the same run produced before: it proves no pre-existing field moved.
GOLDEN_SERVED_DIGEST = "70478b2d22a001a5111d206488db75e3d345c0fe4fe295134831b86a44efc70d"
GOLDEN_LEGACY_DIGEST = "d265604e20ae3c16d9fe56298d3eac15ce9a89792c37a99b964afb73bf570cfd"
GOLDEN_SCOPE_MIX = {"COMPANY": 1182, "UNRESOLVED": 847, "MARKET": 170, "SECTOR": 131}
GOLDEN_STATUS_MIX = {"NO_EVENT": 1037, "CLASSIFIED": 962, "UNCERTAIN": 331}
GOLDEN_IMPACT_MIX = {("MODEL", "ISSUER"): 370, ("MODEL", "MARKET"): 355, ("PLACEHOLDER_RULES", None): 1605}


def card(rel: str) -> dict:
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def test_the_served_run_is_pinned(replay_container):
    assert replay_container.pipeline_report.output_digest == GOLDEN_SERVED_DIGEST
    sig = replay_container.signals.list()
    assert len(sig) == 2330
    assert dict(Counter(s.event.status.value for s in sig)) == GOLDEN_STATUS_MIX
    assert dict(Counter((s.provenance.stage_origins["impact"], s.provenance.impact.scope.value if s.provenance.impact else None) for s in sig)) == GOLDEN_IMPACT_MIX


def test_no_pre_existing_signal_field_changed(replay_container):
    """The served run, with only the Stage-6 additions removed, hashes to the Stage-5 golden digest."""
    def legacy(s):
        d = s.model_dump(mode="json")
        d.pop("scope", None)
        d["evidence"].pop("novelty_measured", None)
        return d

    sigs = sorted(replay_container.signals.list(), key=lambda s: s.id)
    payload = json.dumps([legacy(s) for s in sigs], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == GOLDEN_LEGACY_DIGEST


def test_scope_mix_is_pinned_and_no_event_is_never_given_a_subject(replay_container):
    sigs = replay_container.signals.list()
    assert dict(Counter(s.scope.level.value for s in sigs)) == GOLDEN_SCOPE_MIX
    for s in sigs:
        if s.scope.level.value != "COMPANY" and s.event.status.value == "NO_EVENT":
            assert s.scope.level.value == "UNRESOLVED"
        if s.scope.level.value == "UNRESOLVED":
            assert s.scope.note and s.scope.sector is None
        assert s.evidence.novelty_measured == (s.entity.entity_id != "UNKNOWN_ENTITY" and s.provenance.timestamp_origin.value != "SYNTHETIC_REPLAY_CLOCK")


def test_a_second_start_up_reproduces_the_served_run_exactly(replay_container):
    again = build_container(replay_container.settings)
    assert again.pipeline_report.output_digest == replay_container.pipeline_report.output_digest == GOLDEN_SERVED_DIGEST


def test_every_signal_names_the_served_models_and_their_artifacts(replay_container):
    sent, ev, imp = (card("models/sentiment/tfidf-lr-v1/model_card.json"), card("models/event/hybrid-event-v2/model_card.json"),
                     card("models/impact/impact-v2/model_card.json"))
    for s in replay_container.signals.list():
        p = s.provenance
        assert p.sentiment.model_id == "tfidf-lr-v1" and p.sentiment.artifact_sha256 == sent["artifact_sha256"]
        assert p.event.model_id == "hybrid-event-v2" and p.event.artifact_sha256 == ev["artifact_sha256"]
        if p.stage_origins["impact"] == "MODEL":
            assert p.impact.model_id == "impact-v2" and p.impact.artifact_sha256 == imp["artifact_sha256"]
            assert p.impact.feature_schema == imp["feature_schema"] == "impact-features-v2"


def test_impact_reads_the_tfidf_event_model_not_the_hybrid(replay_container):
    """Intentional and documented (docs/FINAL_MODEL_REPORT.md): both impact models were fitted on the TF-IDF event model's probabilities."""
    assert replay_container.impact_event_reference == "tfidf-lr-event-v1"
    assert "TF-IDF event model" in card("models/impact/impact-v2/model_card.json")["output_definition"]
