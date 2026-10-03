from __future__ import annotations

import json

from eventshock.config import REPO_ROOT
from eventshock.domain import ImpactLifecycle
from eventshock.pipeline.event_card import EventModelCard
from eventshock.pipeline.impact_card import ImpactModelCard
from eventshock.pipeline.sentiment_card import SentimentModelCard
from eventshock.services import evidence as E


def cards():
    r = REPO_ROOT
    return (SentimentModelCard.model_validate_json((r / "models/sentiment/tfidf-lr-v1/model_card.json").read_text()),
            EventModelCard.model_validate_json((r / "models/event/tfidf-lr-event-v1/model_card.json").read_text()),
            ImpactModelCard.model_validate_json((r / "models/impact/impact-v1/model_card.json").read_text()))


def test_verdict_words_follow_the_interval_not_the_point_estimate():
    assert E.verdict_of({"value": -0.01, "lo": -0.02, "hi": -0.002}) == "helps"
    assert E.verdict_of({"value": -0.01, "lo": -0.02, "hi": 0.004}) == "no measurable effect"
    assert E.verdict_of({"value": 0.02, "lo": 0.005, "hi": 0.03}) == "hurts"
    assert E.verdict_of({"value": None, "lo": None, "hi": None}) == "not evaluable" and E.verdict_of(None) == "not evaluable"


def test_a_missing_impact_card_is_a_placeholder_and_a_loaded_one_is_experimental_unless_every_check_passes():
    s, e, i = cards()
    assert E.build_stages(s, e, None)[2].kind == "placeholder"
    assert E.build_stages(s, e, i)[2].kind == "experimental"
    assert E.build_stages(None, None, None)[0].kind == "placeholder"
    promoted = i.model_copy(update={"scopes": [sc.model_copy(update={"lifecycle": ImpactLifecycle.PRODUCTION}) for sc in i.scopes]})
    assert E.build_stages(s, e, promoted)[2].kind == "validated"   # a lifecycle comes from the artifact's own bar; the service never promotes by itself


def test_empty_root_gives_unavailable_sections_not_invented_numbers(tmp_path):
    b = E.build_evidence(tmp_path, *cards())
    assert not b.study.available and not b.representation.available and not b.data.available
    assert b.study.command.startswith("make ") and b.representation.command.startswith("make ")
    assert b.generated_from == [] and b.limitations and b.features


def run_entry(chain_ok: bool):
    est = {"value": -0.02, "lo": -0.03, "hi": -0.01} if chain_ok else {"value": 0.001, "lo": -0.01, "hi": 0.012}
    return {"status": "ok", "episodes": {"train": 10}, "selected": "R2-ridge", "best_state_model": "R2-ridge", "best_block_model": "R3s-full",
            "checks": [{"id": "C10", "label": "x", "value": "v", "passed": chain_ok, "detail": ""}, {"id": "C4", "label": "y", "value": "n/a", "passed": None, "detail": ""}],
            "increments": {"ridge": {"calendar": {"oof": est, "test": est}}}, "by_year": {"helpful": {"helpful": 3, "periods": 4, "share": 0.75}},
            "battery": {"selected": {"model": "R2-ridge", "neutral_skill_test": {"value": 0.05, "lo": -0.02, "hi": 0.12, "n": 300}}}, "sets": {"test": {"models": {}}}}


def test_study_view_translates_increments_and_checks_and_states_the_verdict():
    study = {"preregistration": {"file": "configs/evidence_v2.yaml", "sha256": "ab" * 32}, "p1_regression": {"statement": "ok", "status": "ok"},
             "runs": {"P2_extended/ISSUER": run_entry(False), "P1_legacy/ISSUER": {"status": "not evaluable: 2 folds"}}, "track_f": None}
    v = E.build_study(study, None)
    assert v.available and {r.protocol for r in v.runs} == {"P1_legacy", "P2_extended"}
    r = next(r for r in v.runs if r.protocol == "P2_extended")
    assert [x.verdict for x in r.increments] == ["no measurable effect", "no measurable effect"] and r.years_helpful == "3 of 4 years"
    assert "failed C10" in r.verdict and "not evaluable C4" in r.verdict
    assert next(r for r in v.runs if r.protocol == "P1_legacy").verdict.startswith("not evaluable")


def test_representation_view_reports_the_decision_checks_and_cost():
    b = {"decision": {"statement": "no candidate met every pre-registered check; the shipped TF-IDF model stays"}, "baseline": {"id": "tfidf-lr-event-v1", "sets": {"pooled": {"served_macro_f1": 0.43}}},
         "sets": {"pooled": {"n": 500}}, "candidates": {"H1[e5-base]": {"family": "H1", "params": {"dense": "m", "C": 10}, "adopt": False,
                                                                  "adoption_checks": {"served_macro_f1_delta": {"value": 0.01, "ci95": [-0.02, 0.04], "passed": False},
                                                                                      "log_loss_delta": {"value": -0.1, "passed": True}}}},
         "cost": {"m": {"kind": "dense", "ms_per_text_batch32": 50.0, "controlled": True, "deterministic_double_run": True}},
         "polarity_probe": {"c": {"pairs": 30, "share_correct": 0.9, "ci95": [0.7, 0.97]}}}
    v = E.build_representation(b)
    assert v.available and v.candidates[0].checks_failed == ["served_macro_f1_delta"] and v.candidates[0].checks_passed == ["log_loss_delta"]
    assert v.cost[0].controlled and v.probe[0].share_correct == 0.9 and v.baseline_pooled_f1 == 0.43 and "shipped TF-IDF model stays" in v.decision


def test_build_is_deterministic_and_json_serialisable(tmp_path):
    a, b = E.build_evidence(REPO_ROOT, *cards()), E.build_evidence(REPO_ROOT, *cards())
    assert json.dumps(a.model_dump(mode="json"), sort_keys=True) == json.dumps(b.model_dump(mode="json"), sort_keys=True)
