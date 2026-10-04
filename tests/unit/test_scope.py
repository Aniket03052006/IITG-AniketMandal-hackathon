"""Scope resolution: the ordered rule table, its refusals, the config guards, and the evaluation arithmetic."""

from __future__ import annotations

import pytest

from eventshock.config import REPO_ROOT
from eventshock.domain import (
    UNKNOWN_ENTITY,
    EntityMention,
    EventCategory,
    EventClassification,
    EventStatus,
    ScopeBasis,
    ScopeLevel,
    ScopeStrength,
    scope_from_entity,
)
from eventshock.modeling.scope_eval import evaluate
from eventshock.pipeline.scope import ScopeConfig, ScopeResolver, load_scope_config
from tests.pipe_helpers import CFG, ENTITIES, doc

CFG_SCOPE = load_scope_config(REPO_ROOT / "configs")
R = ScopeResolver(CFG_SCOPE)
NOBODY = EntityMention()
JPM = EntityMention(entity_id="ENT_JPM", entity_name="JPMorgan Chase & Co.", ticker="JPM", sector="Financials",
                    country="US", link_confidence=0.95)


def event(category: EventCategory, status: EventStatus = EventStatus.CLASSIFIED) -> EventClassification:
    rest = (1 - 0.7) / (len(EventCategory) - 1)
    return EventClassification(category=category, status=status,
                               probabilities={c: (0.7 if c is category else rest) for c in EventCategory})


def test_company_is_enrichment_from_the_entity_master() -> None:
    s = R.resolve("JPMorgan raises its outlook", JPM, event(EventCategory.EARNINGS_FINANCIAL_PERFORMANCE))
    assert (s.level, s.sector, s.basis) == (ScopeLevel.COMPANY, "Financials", ScopeBasis.ENTITY_RESOLVER)
    assert s.regions == ["US"] and "JPMorgan" in s.note


def test_company_wins_even_when_the_text_is_all_oil() -> None:
    s = R.resolve("crude oil prices and opec output", JPM, None)
    assert s.level is ScopeLevel.COMPANY


def test_strong_sector_needs_two_distinct_terms() -> None:
    s = R.resolve("Chipmakers slide as semiconductor demand softens", NOBODY, event(EventCategory.MARKET_VALUATION))
    assert (s.level, s.sector, s.strength, s.basis) == (ScopeLevel.SECTOR, "Technology", ScopeStrength.STRONG,
                                                         ScopeBasis.SECTOR_TERMS)
    assert set(s.matched_terms["sector"]) == {"chipmakers", "semiconductor"}


def test_one_sector_term_alone_is_weak_not_strong() -> None:
    s = R.resolve("Regulators scrutinise lenders over new rules", NOBODY, event(EventCategory.REGULATORY_LEGAL))
    assert (s.level, s.sector, s.strength) == (ScopeLevel.SECTOR, "Financials", ScopeStrength.WEAK)


def test_overlapping_terms_count_once() -> None:
    # "oil prices" contains "oil": one mention is one term, so this is WEAK, never STRONG
    s = R.resolve("Oil prices slip on Monday", NOBODY, None)
    assert s.sector == "Energy" and s.strength is ScopeStrength.WEAK and s.matched_terms["sector"] == ["oil prices"]


def test_a_tie_between_sectors_is_not_a_subject() -> None:
    s = R.resolve("Banks and drugmakers both fall", NOBODY, event(EventCategory.MARKET_VALUATION))
    assert s.level is ScopeLevel.UNRESOLVED and "equal weight" in s.note


def test_central_bank_is_monetary_policy_not_the_banking_sector() -> None:
    s = R.resolve("Central bank holds interest rates as inflation cools", NOBODY, event(EventCategory.MACROECONOMIC))
    assert s.level is ScopeLevel.MARKET and s.sector is None
    assert set(s.themes) == {"inflation", "rates"} and s.basis is ScopeBasis.THEME_TERMS


def test_macro_class_without_any_vocabulary_is_market_by_the_event_model() -> None:
    s = R.resolve("Officials meet for a second round of talks", NOBODY, event(EventCategory.GEOPOLITICAL))
    assert (s.level, s.basis, s.themes) == (ScopeLevel.MARKET, ScopeBasis.EVENT_MODEL, [])


def test_macro_class_that_is_uncertain_does_not_make_market_scope() -> None:
    s = R.resolve("Officials meet for a second round of talks", NOBODY,
                  event(EventCategory.GEOPOLITICAL, EventStatus.UNCERTAIN))
    assert s.level is ScopeLevel.UNRESOLVED


def test_strong_sector_beats_a_macro_class() -> None:
    s = R.resolve("OPEC cuts crude output as oilfield drilling slows", NOBODY, event(EventCategory.GEOPOLITICAL))
    assert (s.level, s.sector, s.strength) == (ScopeLevel.SECTOR, "Energy", ScopeStrength.STRONG)
    assert "MIDEAST" in s.regions  # the region is kept as information


def test_macro_theme_beats_a_single_weak_sector_term() -> None:
    s = R.resolve("Fed signals rate cuts as a bank slows", NOBODY, None)
    assert s.level is ScopeLevel.MARKET and "rates" in s.themes


def test_two_sector_terms_beat_a_macro_theme_and_keep_the_theme() -> None:
    s = R.resolve("Fed signals rate cuts as bank lending slows", NOBODY, None)
    assert (s.level, s.sector, s.strength) == (ScopeLevel.SECTOR, "Financials", ScopeStrength.STRONG)
    assert s.themes == ["rates"]  # information kept, the scope is still the sector


def test_not_a_market_event_is_unresolved_even_with_vocabulary() -> None:
    s = R.resolve("Our oil painting class meets on tuesday", NOBODY, event(EventCategory.PRODUCT_OPERATIONS, EventStatus.NO_EVENT))
    assert s.level is ScopeLevel.UNRESOLVED and "not to be a market event" in s.note


def test_unresolved_says_why_and_invents_nothing() -> None:
    s = R.resolve("Shares of the company tumbled after a surprise announcement", NOBODY,
                  event(EventCategory.EARNINGS_FINANCIAL_PERFORMANCE))
    assert s.level is ScopeLevel.UNRESOLVED and s.sector is None and s.themes == [] and s.matched_terms == {}
    assert "earnings_financial_performance" in s.note and "no company" in s.note


def test_regions_are_reported_even_when_the_book_has_no_exposure_to_them() -> None:
    s = R.resolve("Beijing announces new export controls on rare earths", NOBODY, None)
    assert s.level is ScopeLevel.MARKET and s.regions == ["CN"] and s.themes == ["trade_and_conflict"]


def test_resolution_is_deterministic() -> None:
    args = ("Fed signals rate cuts as bank lending slows", NOBODY, event(EventCategory.MACROECONOMIC))
    assert R.resolve(*args) == R.resolve(*args)


def test_scope_from_entity_never_claims_more_than_the_entity() -> None:
    assert scope_from_entity(NOBODY).level is ScopeLevel.UNRESOLVED
    assert scope_from_entity(JPM).sector == "Financials"
    assert NOBODY.entity_id == UNKNOWN_ENTITY


# ------------------------------------------------------------------------------------------------ config guards
def _cfg(**over) -> dict:
    base = CFG_SCOPE.model_dump(mode="json")
    base.update(over)
    return base


def test_a_term_shared_by_two_sectors_is_refused() -> None:
    sectors = {**CFG_SCOPE.sectors, "Energy": [*CFG_SCOPE.sectors["Energy"], "bank"]}
    with pytest.raises(ValueError, match="belongs to both"):
        ScopeConfig.model_validate(_cfg(sectors=sectors))


def test_an_empty_sector_is_refused() -> None:
    with pytest.raises(ValueError, match="no terms"):
        ScopeConfig.model_validate(_cfg(sectors={**CFG_SCOPE.sectors, "Energy": []}))


def test_unknown_keys_are_refused() -> None:
    with pytest.raises(ValueError):
        ScopeConfig.model_validate(_cfg(strong_terms=3))


def test_every_sector_is_one_of_the_portfolios() -> None:
    import json

    sectors = {a["sector"] for a in json.loads((REPO_ROOT / "data/replay/portfolio.json").read_text())["assets"]}
    assert set(CFG_SCOPE.sectors) == sectors


# ---------------------------------------------------------------------------------------------------- evaluation
def test_evaluation_counts_agreement_against_the_issuers_sector() -> None:
    rows = [doc("a", "Apple Inc. unveils new chip as semiconductor demand grows"),         # Technology, STRONG, correct
            doc("b", "JPMorgan faces probe as lenders tighten standards"),            # Financials, WEAK, correct
            doc("c", "Goldman Sachs trims oil forecasts"),                           # Financials truth, Energy WEAK: wrong
            doc("d", "Apple Inc. says nothing at all today"),                              # no vocabulary
            doc("e", "Apple Inc. and Microsoft meet about oil and drugmakers")]            # two issuers: excluded
    out = evaluate(rows, ENTITIES, CFG.entity_resolution, R)
    assert out["single_issuer_documents"] == 4 and out["vocabulary_fired"] == 3
    assert out["by_strength"]["STRONG"] == {"predicted": 1, "correct": 1, "precision": 1.0}
    assert out["by_strength"]["WEAK"] == {"predicted": 2, "correct": 1, "precision": 0.5}
    assert out["confusion"]["Financials"] == {"Energy": 1, "Financials": 1}
    assert out["per_sector"]["Technology"]["recall"] == 0.5
