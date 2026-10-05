"""The language-model path: grounding (nothing is believed unchecked), the cache (no repeat calls) and every failure mode degrading to the rules."""

from __future__ import annotations

import copy
import json

import pytest

from eventshock.assessment.reference import Reference
from eventshock.domain import EntityMention
from eventshock.llm.cache import ExtractionCache
from tests.assess_helpers import extractor
from tests.fakes import CASES, REGULATORY, FakeLLM, bad_output, rate_limited, timeout

ANSWER = CASES["regulatory"]["answer"]


def run(answer: dict, text: str = REGULATORY, ref: Reference | None = None):
    return extractor(FakeLLM(answer)).extract(text, ref or Reference())


def test_an_entity_that_is_not_in_the_text_is_dropped_and_noted() -> None:
    a = copy.deepcopy(ANSWER)
    a["entities"].append(dict(surface="Goldman Sachs", kind="COMPANY", role="subject"))
    r, info = run(a)
    assert [e.name for e in r.entities] == ["European regulators"]
    assert any("Goldman Sachs" in n and "does not appear" in n for n in info.notes)
    assert r.primary_issuer.entity_id == "UNKNOWN_ENTITY"


def test_a_paraphrased_quote_is_not_evidence() -> None:
    a = copy.deepcopy(ANSWER)
    a["evidence"].append(dict(quote="tougher rules on lenders", supports="event_type"))
    r, info = run(a)
    assert all(r.text[s.start:s.end] == s.quote for s in r.evidence) and "tougher rules on lenders" not in [s.quote for s in r.evidence]
    assert any("not verbatim" in n for n in info.notes)


def test_ids_outside_the_vocabulary_are_dropped() -> None:
    a = copy.deepcopy(ANSWER)
    a.update(sectors=["Financials", "Crypto"], regions=["EU", "MARS"], affected_asset_classes=["EQUITY", "NFT"],
             severity_indicators=["capital_requirement_change", "alien_invasion"], event_subtype="made_up")
    r, info = run(a)
    assert r.sectors == ["Financials"] and r.regions == ["EU"] and r.asset_classes == ["EQUITY"]
    assert [h.id for h in r.severity_indicators] == ["capital_requirement_change"]
    assert r.event_subtype == "other" and len(info.notes) >= 5


def test_the_issuer_comes_only_from_the_entity_master() -> None:
    a = copy.deepcopy(ANSWER)
    a["entities"] = [dict(surface="Goldman Sachs", kind="COMPANY", role="subject")]
    text = "Goldman Sachs faces stricter capital requirements"
    # not in the master -> a mention, never an issuer
    r, _ = run(a, text)
    assert r.entities[0].resolved is False and r.primary_issuer.entity_id == "UNKNOWN_ENTITY"
    # in the master -> resolved, and the issuer is the master's, not the model's
    gs = EntityMention(entity_id="ENT_GS", entity_name="The Goldman Sachs Group, Inc.", ticker="GS", sector="Financials", country="US",
                       link_confidence=0.95)
    r2, _ = run(a, text, Reference(entity=gs))
    assert r2.entities[0].resolved and r2.entities[0].ticker == "GS" and r2.primary_issuer.entity_id == "ENT_GS"


def test_an_invalid_event_class_is_a_malformed_answer_and_falls_back() -> None:
    a = copy.deepcopy(ANSWER)
    a["event_type"] = "VIBES"
    r, info = run(a)
    assert info.mode.value == "RULES" and info.fallback_reason and "taxonomy" in info.fallback_reason
    assert r.event_type == "REGULATORY_LEGAL"  # the rules still read the text


@pytest.mark.parametrize("err,needle", [(timeout(), "timed out"), (rate_limited(), "rate limiting"), (bad_output(), "schema")])
def test_a_provider_failure_degrades_to_the_rules_with_a_reason(err, needle: str) -> None:
    fake = FakeLLM(error=err)
    ex = extractor(fake)
    r, info = ex.extract(REGULATORY, Reference())
    assert fake.calls == 1
    assert info.mode.value == "RULES" and needle in (info.fallback_reason or "")
    assert r.event_type == "REGULATORY_LEGAL"
    assert ex.stats.fallbacks == 1 and ex.status()["last_fallback_reason"]


def test_a_missing_required_field_is_a_malformed_answer() -> None:
    bad = {k: v for k, v in ANSWER.items() if k != "event_type"}  # the one field the answer cannot do without (with the rubric)
    r, info = run(bad)
    assert info.mode.value == "RULES" and info.fallback_reason


def test_no_key_means_rule_mode_with_the_reason_visible() -> None:
    ex = extractor(None, enabled=True, why="ANTHROPIC_API_KEY is not set")
    r, info = ex.extract(REGULATORY, Reference())
    assert info.mode.value == "RULES" and info.fallback_reason == "ANTHROPIC_API_KEY is not set"
    assert ex.status()["mode"] == "RULES" and not ex.llm_ready
    # switched off on purpose: rule mode, and nothing to apologise for
    r2, info2 = extractor(None, enabled=False).extract(REGULATORY, Reference())
    assert info2.mode.value == "RULES" and info2.fallback_reason is None


def test_the_same_text_is_never_sent_twice(tmp_path) -> None:
    cache = ExtractionCache(tmp_path / "c.jsonl")
    fake = FakeLLM(ANSWER)
    ex = extractor(fake, cache=cache)
    first, i1 = ex.extract(REGULATORY, Reference())
    second, i2 = ex.extract(REGULATORY, Reference())
    assert fake.calls == 1 and i1.cached is False and i2.cached is True
    assert first.model_dump() == second.model_dump()
    # a fresh process over the same file still hits: a restart re-ingesting the journal costs nothing
    fake2 = FakeLLM(ANSWER)
    again, i3 = extractor(fake2, cache=ExtractionCache(tmp_path / "c.jsonl")).extract(REGULATORY, Reference())
    assert fake2.calls == 0 and i3.cached is True


def test_a_failed_call_is_not_cached(tmp_path) -> None:
    cache = ExtractionCache(tmp_path / "c.jsonl")
    extractor(FakeLLM(error=timeout()), cache=cache).extract(REGULATORY, Reference())
    assert len(cache) == 0
    ok = FakeLLM(ANSWER)
    extractor(ok, cache=cache).extract(REGULATORY, Reference())
    assert ok.calls == 1 and len(cache) == 1


def test_a_corrupt_cache_line_is_skipped_not_fatal(tmp_path) -> None:
    p = tmp_path / "c.jsonl"
    p.write_text("not json\n" + json.dumps({"key": "k", "value": {"a": 1}}) + "\n", encoding="utf-8")
    cache = ExtractionCache(p)
    assert len(cache) == 1 and cache.get("k") == {"a": 1}


def test_only_the_configured_amount_of_text_is_sent() -> None:
    seen: list[str] = []

    class Spy(FakeLLM):
        def extract(self, **kw):
            seen.append(kw["user"])
            return super().extract(**kw)

    long_text = REGULATORY + " " + "padding " * 600
    extractor(Spy(ANSWER)).extract(long_text, Reference())
    assert len(seen) == 1 and len(seen[0]) < 2200 and "padding padding" in seen[0]


def test_a_name_inside_another_word_is_not_the_master_entity() -> None:
    a = copy.deepcopy(ANSWER)
    a["entities"] = [dict(surface="Pineapple Co", kind="COMPANY", role="subject")]
    apple = EntityMention(entity_id="ENT_AAPL", entity_name="Apple Inc.", ticker="AAPL", sector="Technology", country="US", link_confidence=0.9)
    r, _ = run(a, "Pineapple Co faces stricter capital requirements", Reference(entity=apple))
    assert r.entities[0].resolved is False


def test_a_local_call_cap_sends_the_overflow_to_the_rules_with_a_reason() -> None:
    from eventshock.assessment.extractor import SemanticExtractor
    from tests.assess_helpers import LLM_CFG, RULES, VOCAB

    fake = FakeLLM(ANSWER)
    ex = SemanticExtractor(VOCAB, RULES, LLM_CFG.model_copy(update={"enabled": True, "max_calls_per_minute": 2}), client=fake)
    clock = [0.0]
    ex._clock = lambda: clock[0]  # noqa: SLF001
    texts = [REGULATORY + f" variant {i}" for i in range(3)]
    infos = [ex.extract(t, Reference())[1] for t in texts]
    assert [i.mode.value for i in infos] == ["LLM", "LLM", "RULES"] and fake.calls == 2
    assert "local limit of 2 calls per minute" in infos[2].fallback_reason
    clock[0] = 61.0  # a minute later the window has emptied
    assert ex.extract(REGULATORY + " variant 9", Reference())[1].mode.value == "LLM"


def test_a_quote_that_is_the_whole_text_is_not_evidence() -> None:
    a = copy.deepcopy(ANSWER)
    a["evidence"] = [dict(quote=REGULATORY, supports="event_type"), dict(quote="stricter capital requirements", supports="event_type")]
    r, info = run(a)
    quotes = [s.quote for s in r.evidence]
    assert "stricter capital requirements" in quotes and REGULATORY not in quotes
    assert any("cover nearly the whole text" in n for n in info.notes)
    # a short text is exempt: there the whole headline can be the only possible quote
    short = "Bank defaults on bonds"
    b = copy.deepcopy(ANSWER)
    b["evidence"] = [dict(quote=short, supports="event_type")]
    assert len(run(b, short)[0].evidence) == 1


def test_after_a_provider_failure_new_text_goes_straight_to_the_rules_until_the_cooldown_ends() -> None:
    from eventshock.assessment.extractor import SemanticExtractor
    from tests.assess_helpers import LLM_CFG, RULES, VOCAB

    fake = FakeLLM(error=timeout())
    ex = SemanticExtractor(VOCAB, RULES, LLM_CFG.model_copy(update={"enabled": True, "cooldown_seconds": 60.0}), client=fake)
    now = [100.0]
    ex._clock = lambda: now[0]  # noqa: SLF001
    first = ex.extract(REGULATORY + " one", Reference())[1]
    assert fake.calls == 1 and first.mode.value == "RULES" and "timed out" in first.fallback_reason
    second = ex.extract(REGULATORY + " two", Reference())[1]
    assert fake.calls == 1, "the provider must not be called during the cooldown"
    assert second.mode.value == "RULES" and "not retried for another" in second.fallback_reason and "timed out" in second.fallback_reason
    now[0] += 61.0
    fake.error, fake.answer = None, ANSWER
    assert ex.extract(REGULATORY + " three", Reference())[1].mode.value == "LLM" and fake.calls == 2  # the breaker closes by itself
