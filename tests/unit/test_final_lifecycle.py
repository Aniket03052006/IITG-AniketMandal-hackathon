"""The final lifecycle verdicts of the three served models, derived from their committed cards by the existing rules.

If a card is retrained or edited, one of these fails and the change must be justified in docs/notes/FINAL_MODEL_REPORT.md. Nothing
here promotes a model: the verdicts are the ones the pre-registered bars produce today.
"""
from __future__ import annotations

from eventshock.config import REPO_ROOT
from eventshock.domain import ImpactLifecycle
from eventshock.pipeline.event_card import EventModelCard
from eventshock.pipeline.impact_card import ImpactModelCard
from eventshock.pipeline.sentiment_card import SentimentModelCard
from eventshock.services import evidence as E


def served_cards():
    r = REPO_ROOT / "models"
    return (SentimentModelCard.model_validate_json((r / "sentiment/tfidf-lr-v1/model_card.json").read_text()),
            EventModelCard.model_validate_json((r / "event/hybrid-event-v2/model_card.json").read_text()),
            ImpactModelCard.model_validate_json((r / "impact/impact-v2/model_card.json").read_text()))


def test_served_model_ids():
    s, e, i = served_cards()
    assert (s.id, e.id, i.id) == ("tfidf-lr-v1", "hybrid-event-v2", "impact-v2")


def test_every_served_stage_is_experimental():
    stages = {st.stage: st for st in E.build_stages(*served_cards())}
    assert {k: v.kind for k, v in stages.items()} == {"sentiment": "experimental", "event": "experimental", "impact": "experimental"}


def test_event_model_misses_only_the_independent_set_check():
    _, e, _ = served_cards()
    assert not e.acceptance.met
    failed = [c.name for c in e.acceptance.checks if not c.passed]
    assert len(failed) == 1 and failed[0].startswith("an evaluation set that took no part in adopting this model")
    assert len(e.acceptance.checks) == 4 and sum(bool(c.passed) for c in e.acceptance.checks) == 3


def test_impact_scopes_are_calibrated_and_miss_their_registered_checks():
    _, _, i = served_cards()
    by_scope = {sc.scope: sc for sc in i.scopes}
    assert {k: v.lifecycle for k, v in by_scope.items()} == {"ISSUER": ImpactLifecycle.CALIBRATED, "MARKET": ImpactLifecycle.CALIBRATED}
    not_passed = {k: sorted(c.id for c in v.acceptance.checks if c.passed is not True) for k, v in by_scope.items()}
    assert not_passed == {"ISSUER": ["C5", "C7"], "MARKET": ["C10", "C11", "C4", "C5", "C8"]}
    assert not any(v.acceptance.met for v in by_scope.values())

