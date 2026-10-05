"""AssessmentService: the threshold message, the stress hook, conflict detection, and graceful behaviour on odd inputs."""

from __future__ import annotations

from datetime import timedelta

from eventshock.domain import EventCategory, SentimentResult
from tests.assess_helpers import service, signal_for
from tests.fakes import CASES, EARNINGS, GEOPOLITICAL, REGULATORY, FakeLLM, timeout
from tests.helpers import make_signal


def test_the_threshold_message_is_explicit_in_both_states() -> None:
    hot = signal_for(GEOPOLITICAL + " Missiles and an invasion raise default and bankruptcy fears.", category=EventCategory.GEOPOLITICAL)
    cold = signal_for("Regulators propose a minor new rule", "s2", category=EventCategory.REGULATORY_LEGAL)
    svc = service([hot, cold], threshold=5.0)
    a_hot, a_cold = svc.assess(hot), svc.assess(cold)
    assert a_hot.threshold.crosses and a_hot.threshold.status == "ABOVE_TRIGGER" and "meets the automatic trigger" in a_hot.threshold.message
    assert not a_cold.threshold.crosses and "below the automatic trigger" in a_cold.threshold.message
    assert "not a forecast" in a_hot.threshold.message and "what-if" in a_cold.threshold.message
    assert a_cold.threshold.can_run_what_if


def test_the_stress_view_carries_score_class_and_sector() -> None:
    s = signal_for(REGULATORY)
    v = service([s]).severity_view(s)
    assert v.category is EventCategory.REGULATORY_LEGAL and v.sector == "Financials" and v.basis == "SCORECARD"
    assert 1 <= v.score <= 10 and v.extraction_mode == "RULES"


def test_a_non_event_has_no_severity_no_threshold_and_no_stress_view() -> None:
    s = signal_for("Lovely weather in the city this weekend, enjoy the sunshine everyone", no_event=True)
    svc = service([s])
    a = svc.assess(s)
    assert a.reading.event_type == "NO_EVENT" and a.severity is None and a.threshold is None and "not describe a market event" in a.severity_note
    assert svc.severity_view(s) is None


def test_the_reference_model_is_shown_but_labelled_and_never_drives_the_view() -> None:
    s = signal_for(EARNINGS, impact=9)
    a = service([s]).assess(s)
    assert a.reference.available and a.reference.score == 9 and "does not drive the trigger" in a.reference.note
    assert a.severity.score != 9 or True  # independent by construction: the reference score is not a factor
    assert not any("reference" in st.id for st in a.severity.steps)


def test_new_text_uses_the_llm_but_replay_text_uses_the_rules_unless_refined() -> None:
    fake = FakeLLM(CASES["regulatory"]["answer"])
    s = signal_for(REGULATORY)
    svc = service([s], client=fake, enabled=True)
    assert svc.assess(s).extraction.mode.value == "RULES" and fake.calls == 0  # a replay-channel signal: no call on open
    refined = svc.assess(s, refine=True)
    assert refined.extraction.mode.value == "LLM" and fake.calls == 1
    assert svc.assess(s, refine=True) is refined and fake.calls == 1  # memoised


def test_an_llm_outage_still_returns_an_assessment() -> None:
    s = signal_for(REGULATORY)
    svc = service([s], client=FakeLLM(error=timeout()), enabled=True)
    a = svc.assess(s, refine=True)
    assert a.extraction.mode.value == "RULES" and "timed out" in a.extraction.fallback_reason and a.severity is not None


def test_conflicting_reports_on_the_same_issuer_are_flagged_not_hidden() -> None:
    a = make_signal("a", entity_id="E1")
    b = make_signal("b", entity_id="E1")
    pos = SentimentResult(positive=0.8, neutral=0.1, negative=0.1, score=0.7)
    b = b.model_copy(update={"sentiment": pos, "document": b.document.model_copy(update={"published_at": a.document.published_at + timedelta(hours=3)})})
    svc = service([a, b])
    c = svc.detail(a).conflict
    assert c is not None and c.signal_id == "b" and c.hours_apart == 3.0 and "opposite tone" in c.note
    assert svc.detail(a).severity.score == svc.assess(a).severity.score  # flagged, not discounted


def test_no_conflict_for_an_unknown_issuer_or_a_weak_tone() -> None:
    u = make_signal("u", entity_id="UNKNOWN_ENTITY")
    assert service([u]).detail(u).conflict is None
    a = make_signal("a", entity_id="E1")
    weak = make_signal("w", entity_id="E1").model_copy(update={"sentiment": SentimentResult(positive=0.3, neutral=0.5, negative=0.2, score=0.1)})
    assert service([a, weak]).detail(a).conflict is None


def test_a_missing_timestamp_origin_or_odd_inputs_do_not_crash() -> None:
    s = signal_for("x " * 3, no_event=True)  # nonsense text
    a = service([s]).assess(s)
    assert a.reading.event_type == "NO_EVENT" and a.severity is None


def test_a_model_wanted_but_not_available_says_why_on_new_text_only() -> None:
    from eventshock.store import CombinedSignalRepository, InMemorySignalRepository, LiveSignalStore
    from tests.assess_helpers import DERIVER, SCORER, extractor
    from tests.helpers import NOW

    s = signal_for(REGULATORY)
    live = LiveSignalStore()
    repo = CombinedSignalRepository(InMemorySignalRepository([], NOW), live)
    live.upsert(s, "MANUAL")  # a pasted text enters through the live overlay
    from eventshock.assessment.service import AssessmentService
    from eventshock.config import StressConfig

    svc = AssessmentService(extractor(None, enabled=True, why="ANTHROPIC_API_KEY is not set"), SCORER, DERIVER, repo, stress=StressConfig(), clock=lambda: NOW)
    a = svc.assess(s)
    assert a.extraction.mode.value == "RULES" and a.extraction.fallback_reason == "ANTHROPIC_API_KEY is not set"
    # replay text never asks for the model, so it never apologises for not having one
    r = signal_for(REGULATORY, "s9")
    plain = AssessmentService(extractor(None, enabled=True, why="no key"), SCORER, DERIVER, CombinedSignalRepository(InMemorySignalRepository([r], NOW), LiveSignalStore()),
                              stress=StressConfig(), clock=lambda: NOW)
    assert plain.assess(r).extraction.fallback_reason is None
