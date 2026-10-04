"""The seven required cases, through the deterministic rule extractor and through a scripted language model (never the real one).

What is asserted is what the product promises: the event is read, the right sector and region are found, no issuer is invented, and a name the
entity master does not hold stays a mention.
"""

from __future__ import annotations

import pytest

from eventshock.assessment.reference import Reference
from eventshock.domain import UNKNOWN_ENTITY
from tests.assess_helpers import RULES, extractor
from tests.fakes import CASES, UNKNOWN, FakeLLM

NAMES = [k for k in CASES if k != "unknown"]


@pytest.mark.parametrize("name", list(CASES))
def test_rules_read_the_event_sector_and_region(name: str) -> None:
    case = CASES[name]
    r, info = RULES.extract(case["text"])
    assert r.event_type == case["event"]
    assert set(case["sectors"]) <= set(r.sectors)
    assert set(case["regions"]) <= set(r.regions)
    assert info.mode.value == "RULES" and info.model_id == "semantics-v1"
    assert r.primary_issuer.entity_id == UNKNOWN_ENTITY and not r.primary_issuer.resolved  # no company in the entity master


@pytest.mark.parametrize("name", list(CASES))
def test_every_rule_quote_is_a_verbatim_span_of_the_text(name: str) -> None:
    r, _ = RULES.extract(CASES[name]["text"])
    assert r.evidence, "a reading with no evidence is not shown as evidence-backed"
    for s in r.evidence:
        assert r.text[s.start:s.end] == s.quote


@pytest.mark.parametrize("name", list(CASES))
def test_the_scripted_llm_path_reads_the_same_cases(name: str) -> None:
    case = CASES[name]
    fake = FakeLLM(case["answer"])
    r, info = extractor(fake).extract(case["text"], Reference())
    assert info.mode.value == "LLM" and info.model_id == "fake-llm-1" and info.fallback_reason is None
    assert r.event_type == case["event"] and r.event_subtype == case["answer"]["event_subtype"]
    assert set(case["sectors"]) <= set(r.sectors) and set(case["regions"]) <= set(r.regions)
    assert r.primary_issuer.entity_id == UNKNOWN_ENTITY
    for s in r.evidence:
        assert r.text[s.start:s.end] == s.quote


def test_an_unknown_company_is_a_mention_never_an_issuer_or_a_market_data_subject() -> None:
    # rules
    r, _ = RULES.extract(UNKNOWN)
    qd = [e for e in r.entities if e.name == "Quantum Dynamics"]
    assert qd and qd[0].resolved is False and qd[0].entity_id is None and qd[0].ticker is None
    assert r.primary_issuer.entity_id == UNKNOWN_ENTITY and r.primary_issuer.ticker is None
    assert r.sectors == [], "an unknown sector is reported as unknown, not guessed"
    # language model
    r2, _ = extractor(FakeLLM(CASES["unknown"]["answer"])).extract(UNKNOWN, Reference())
    qd2 = [e for e in r2.entities if e.name == "Quantum Dynamics"]
    assert qd2 and qd2[0].resolved is False and r2.primary_issuer.entity_id == UNKNOWN_ENTITY


def test_no_company_named_means_no_entity_at_all() -> None:
    for name in ("geopolitical", "earnings", "mna"):
        r, _ = RULES.extract(CASES[name]["text"])
        assert [e for e in r.entities if e.kind == "COMPANY"] == []
        assert r.primary_issuer.entity_id == UNKNOWN_ENTITY


def test_institutions_are_mentions_with_their_jurisdiction() -> None:
    r, _ = RULES.extract(CASES["monetary"]["text"])
    fed = next(e for e in r.entities if e.name == "Federal Reserve")
    assert fed.kind == "INSTITUTION" and fed.resolved is False
    assert r.regions == ["US"]


def test_a_non_event_is_not_called_an_event() -> None:
    r, info = RULES.extract("Lovely weather in the city this weekend, enjoy the sunshine everyone")
    assert r.event_type == "NO_EVENT" and r.severity_indicators == []
    assert "not" in info.basis.lower() or "no " in info.basis.lower()


def test_the_trained_event_model_keeps_authority_unless_the_cues_clearly_disagree() -> None:
    # a CLASSIFIED trained reading with a weak (one single word) conflicting cue is kept...
    ref = Reference(event_category="PRODUCT_OPERATIONS", event_status="CLASSIFIED", event_confidence=0.7)
    r, _ = RULES.extract("The company announces a new product launch in March", ref)
    assert r.event_type == "PRODUCT_OPERATIONS" and r.event_confidence == 0.7
    # ...and overridden only by a multi-word cue (weight 2), with a note
    ref2 = Reference(event_category="PRODUCT_OPERATIONS", event_status="CLASSIFIED", event_confidence=0.7)
    r2, info2 = RULES.extract(CASES["regulatory"]["text"], ref2)
    assert r2.event_type == "REGULATORY_LEGAL" and r2.event_confidence is None
    assert any("outweigh" in n or "cue" in n.lower() for n in info2.notes)


def test_a_missing_trained_tone_is_neutral_and_said_so() -> None:
    r, info = RULES.extract(CASES["earnings"]["text"])
    assert r.sentiment == 0.0 and r.sentiment_label == "neutral"
    assert any("tone" in n.lower() for n in info.notes)
