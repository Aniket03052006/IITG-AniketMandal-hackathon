"""The configuration the product actually serves, pinned end to end: sentiment tfidf-lr-v1, hybrid-event-v2 and impact-v2 (the other golden
tests pin the v1 impact reference). Also pins the intentional train/serve interaction: impact reads the TF-IDF event model's probabilities."""

from __future__ import annotations

import json
from collections import Counter

from eventshock.api.deps import build_container
from eventshock.config import REPO_ROOT

GOLDEN_SERVED_DIGEST = "d265604e20ae3c16d9fe56298d3eac15ce9a89792c37a99b964afb73bf570cfd"
GOLDEN_STATUS_MIX = {"NO_EVENT": 1037, "CLASSIFIED": 962, "UNCERTAIN": 331}
GOLDEN_IMPACT_MIX = {("MODEL", "ISSUER"): 370, ("MODEL", "MARKET"): 355, ("PLACEHOLDER_RULES", None): 1605}


def card(rel: str) -> dict:
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def test_the_served_run_is_pinned(replay_container):
    assert replay_container.pipeline_report.output_digest == GOLDEN_SERVED_DIGEST
    sig = replay_container.signals._signals  # noqa: SLF001
    assert len(sig) == 2330
    assert dict(Counter(s.event.status.value for s in sig)) == GOLDEN_STATUS_MIX
    assert dict(Counter((s.provenance.stage_origins["impact"], s.provenance.impact.scope.value if s.provenance.impact else None) for s in sig)) == GOLDEN_IMPACT_MIX


def test_a_second_start_up_reproduces_the_served_run_exactly(replay_container):
    again = build_container(replay_container.settings)
    assert again.pipeline_report.output_digest == replay_container.pipeline_report.output_digest == GOLDEN_SERVED_DIGEST


def test_every_signal_names_the_served_models_and_their_artifacts(replay_container):
    sent, ev, imp = (card("models/sentiment/tfidf-lr-v1/model_card.json"), card("models/event/hybrid-event-v2/model_card.json"),
                     card("models/impact/impact-v2/model_card.json"))
    for s in replay_container.signals._signals:  # noqa: SLF001
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
