from __future__ import annotations

import pytest

from eventshock.domain import UNKNOWN_ENTITY, Entity
from eventshock.pipeline.entities import EntityResolver
from tests.pipe_helpers import CFG, ENTITIES

R = EntityResolver(ENTITIES, CFG.entity_resolution)


def resolve(text):
    return R.resolve(text)


class TestStrongRules:
    def test_cashtag(self):
        m, a = resolve("$AAPL - Bernstein raises price target")
        assert (m.entity_id, a.rule, m.link_confidence) == ("ENT_AAPL", "CASHTAG", 0.98)

    def test_exchange_qualified_ticker_allows_single_letter_ticker(self):
        assert resolve("Visa (NYSE: V) lifts guidance")[0].entity_id == "ENT_V"

    def test_legal_name_and_punctuation_variants(self):
        assert resolve("J.P. Morgan strategists see rate cuts")[0].entity_id == "ENT_JPM"
        assert resolve("JPMorgan Chase & Co. reports earnings")[0].entity_id == "ENT_JPM"

    def test_product_alias(self):
        m, a = resolve("iPhone sales slow in China")
        assert (m.entity_id, a.rule) == ("ENT_AAPL", "ALIAS")

    def test_bare_uppercase_ticker(self):
        assert resolve("MSFT shares slip in premarket trading")[0].entity_id == "ENT_MSFT"
        assert resolve("msft is a word i made up")[0].is_unknown

    def test_single_letter_ticker_needs_cashtag(self):
        assert resolve("Plan V is ready, says team")[0].is_unknown


class TestAmbiguity:
    @pytest.mark.parametrize("text", [
        "Apple harvest festival draws record crowds",
        "Visa waiver extended for travellers from three countries",
        "Target date funds explained for first-time savers",
    ])
    def test_ordinary_word_without_finance_context_is_not_resolved(self, text):
        m, a = resolve(text)
        assert m.is_unknown and a.rejected, "the refusal must be recorded in the audit"

    def test_ordinary_word_with_finance_context_resolves_at_lower_confidence(self):
        m, a = resolve("Apple shares fall after analyst downgrade")
        assert (m.entity_id, a.rule, m.link_confidence) == ("ENT_AAPL", "WEAK_ALIAS", 0.7)

    def test_weak_alias_is_case_sensitive(self):
        assert resolve("apple shares fall after analyst downgrade")[0].is_unknown

    def test_weak_alias_rescued_by_other_strong_mention(self):
        m, _ = resolve("Apple and Microsoft expand cloud partnership")
        assert m.entity_id in {"ENT_AAPL", "ENT_MSFT"} and not m.is_unknown

    @pytest.mark.parametrize("text", [
        "Exxon Just Set a Bold 2030 Target for LNG Sales and the Market Reacts",
        "Stock Has Average Target Price of $167 According to Analysts",
        "Morgan Stanley lifts price target on shares of the market leader",
        "Tourist visa requirements tighten for shares of the market",
        "Shell company shares fall as market slumps",
        "Studio reduced to a Shell after layoffs and the takeover",
    ])
    def test_everyday_phrases_do_not_create_weak_alias_candidates(self, text):
        _, a = resolve(text)
        assert not any(c.rule == "WEAK_ALIAS" for c in a.candidates)

    def test_dotted_names_survive_gdelt_word_tokenisation(self):
        ents = [*ENTITIES, Entity(entity_id="ENT_AMZN", name="Amazon.com, Inc.", ticker="AMZN", sector="Technology",
                                  country="US", aliases=["Amazon"])]
        r = EntityResolver(ents, CFG.entity_resolution)
        for text in ("Amazon.com expands same-day delivery", "Amazon. com expands same-day delivery"):
            m, a = r.resolve(text)
            assert m.entity_id == "ENT_AMZN" and a.rule == "LEGAL_NAME"

    def test_word_boundaries(self):
        assert resolve("Pineapple prices surge on the market")[0].is_unknown


class TestMultiEntityAndUnknown:
    def test_multi_entity_caps_confidence_and_records_all(self):
        m, a = resolve("$AAPL $MSFT - Goldman Sachs lifts targets")
        assert a.multi_entity and m.link_confidence == CFG.entity_resolution.multi_entity_cap
        assert {c.entity_id for c in a.candidates} == {"ENT_AAPL", "ENT_MSFT", "ENT_GS"}
        assert m.entity_id == "ENT_AAPL"  # highest confidence, earliest

    def test_unknown_cashtag_is_kept_in_audit_not_forced(self):
        m2, a2 = resolve("$BYND - plant-based meat maker slides")
        assert m2.entity_id == UNKNOWN_ENTITY and a2.unmatched_cashtags == ["BYND"] and a2.rule == "NONE"

    def test_analyst_named_in_a_story_about_an_unlisted_ticker_is_not_the_subject(self):
        """"$BYND - JPMorgan reels in expectations": the subject is BYND; shocking JPMorgan would be wrong."""
        m, a = resolve("$BYND - JPMorgan reels in expectations on Beyond Meat")
        assert m.is_unknown and a.rule == "SUBJECT_UNRESOLVED" and a.unmatched_cashtags == ["BYND"]
        assert [c.entity_id for c in a.candidates] == ["ENT_JPM"] and "analyst" in a.rejected[0].reason
        m2, _ = resolve("Johnson Controls (NYSE: JCI) price target lifted by Goldman Sachs")
        assert m2.is_unknown

    def test_a_listed_cashtag_still_wins_when_an_unlisted_one_is_also_present(self):
        m, a = resolve("$AAPL $BYND - Goldman Sachs upgrades both")
        assert m.entity_id == "ENT_AAPL" and a.unmatched_cashtags == ["BYND"]

    def test_no_text_signal(self):
        m, a = resolve("Global markets steady ahead of central bank meeting")
        assert m.is_unknown and a.candidates == []

    def test_below_threshold_becomes_unknown_but_audit_survives(self):
        cfg = CFG.entity_resolution.model_copy(update={"min_link_confidence": 0.99})
        m, a = EntityResolver(ENTITIES, cfg).resolve("$AAPL - something happened today at the company")
        assert m.is_unknown and a.rule == "BELOW_THRESHOLD" and a.candidates


class TestFuzzy:
    def test_close_misspelling_matches_at_low_confidence(self):
        m, a = resolve("Microsft announces new datacentre region")
        assert (m.entity_id, a.rule, m.link_confidence) == ("ENT_MSFT", "FUZZY", 0.65)

    @pytest.mark.parametrize("text", ["Microwave sales rise in autumn", "Goldfish Sachsen opens branch", "Applet maker raises funds"])
    def test_fuzzy_does_not_invent_matches(self, text):
        assert resolve(text)[0].is_unknown

    def test_fuzzy_off(self):
        cfg = CFG.entity_resolution.model_copy(update={"fuzzy": CFG.entity_resolution.fuzzy.model_copy(update={"enabled": False})})
        assert EntityResolver(ENTITIES, cfg).resolve("Microsft announces new datacentre region")[0].is_unknown


class TestMasterIntegrity:
    def test_shared_alias_between_entities_fails_loudly(self):
        dup = [*ENTITIES, Entity(entity_id="ENT_X", name="Goldman Holdings", ticker="GHX", sector="Financials",
                                 country="US", aliases=["Goldman Sachs"])]
        with pytest.raises(ValueError, match="shared"):
            EntityResolver(dup, CFG.entity_resolution)

    def test_duplicate_ticker_fails_loudly(self):
        dup = [*ENTITIES, Entity(entity_id="ENT_X", name="Other Co", ticker="AAPL", sector="Tech", country="US")]
        with pytest.raises(ValueError, match="ticker"):
            EntityResolver(dup, CFG.entity_resolution)
