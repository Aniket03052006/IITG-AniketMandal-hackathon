"""Hierarchical scope: one case per scope type, the abstentions, and the rule that nothing is invented."""

from __future__ import annotations

from eventshock.domain import EventCategory as C
from eventshock.domain import EventStatus as E
from eventshock.intelligence.model import ConfidenceTier, ResolutionStatus, ScopeType
from tests.intel_helpers import JPM, XOM, scope_resolver, sig

R = scope_resolver()


def path(s) -> list[str]:  # noqa: ANN001
    return [f"{n.type.value}:{n.value}" for n in s.scope_path]


def test_company_path_runs_company_industry_sector_geography_market():
    s = R.resolve(sig("a", "JPMorgan Chase faces a regulatory probe over trading", entity=JPM))
    assert s.scope_type is ScopeType.COMPANY and s.scope_value == "JPMorgan Chase"
    assert path(s) == ["COMPANY:JPMorgan Chase", "INDUSTRY:Banks", "SECTOR:Financials", "GEOGRAPHY:United States", "MARKET:Equity market"]
    assert s.resolution_status is ResolutionStatus.RESOLVED and s.scope_confidence.tier is ConfidenceTier.HIGH
    assert s.scope_evidence[0].quote and s.scope_evidence[0].dimension == "company"


def test_company_without_an_industry_mapping_omits_the_level():
    ent = {**JPM, "entity_id": "ENT_XYZ", "ticker": "XYZ", "entity_name": "Xyz Corp"}
    s = R.resolve(sig("a", "Xyz Corp faces a probe", entity=ent))
    assert "INDUSTRY" not in {n.type.value for n in s.scope_path}  # no industry is invented for a ticker the map does not hold


def test_industry_scope_names_its_parent_sector():
    s = R.resolve(sig("b", "Semiconductor makers brace for export curbs as chipmakers warn"))
    assert s.scope_type is ScopeType.INDUSTRY and s.scope_value == "Semiconductors"
    assert path(s)[:2] == ["INDUSTRY:Semiconductors", "SECTOR:Technology"]
    assert s.scope_confidence.tier is ConfidenceTier.MEDIUM and {e.dimension for e in s.scope_evidence} == {"industry"}


def test_strong_sector_scope_cites_the_measured_agreement():
    s = R.resolve(sig("c", "Banks cut lending as mortgage defaults climb"))
    assert s.scope_type is ScopeType.SECTOR and s.scope_value == "Financials"
    assert s.resolution_status is ResolutionStatus.RESOLVED
    assert s.scope_confidence.measured is None or "agreed" in s.scope_confidence.measured


def test_geography_scope_is_partial():
    s = R.resolve(sig("d", "Tensions flare in the Middle East overnight", category=C.GEOPOLITICAL))
    assert s.scope_type is ScopeType.GEOGRAPHY and s.scope_value == "Middle East"
    assert s.resolution_status is ResolutionStatus.PARTIAL


def test_macro_theme_and_market_scopes():
    macro = R.resolve(sig("e", "Fed holds interest rates as inflation cools", category=C.MACROECONOMIC))
    assert macro.scope_type is ScopeType.MACRO and macro.scope_value == "rates"
    theme = R.resolve(sig("g", "Credit spreads widen as default fears grow", category=C.CREDIT_FUNDING))
    assert theme.scope_type is ScopeType.THEME and theme.scope_value == "credit stress"
    market = R.resolve(sig("f", "Stocks tumble as the S&P 500 slides to a six-week low", category=C.MARKET_VALUATION))
    assert market.scope_type is ScopeType.MARKET and path(market) == ["MARKET:Equity market"]


def test_event_class_alone_gives_a_low_partial_macro_scope():
    s = R.resolve(sig("k", "Officials meet again on Thursday", category=C.MACROECONOMIC))
    assert s.scope_type is ScopeType.MACRO and s.scope_confidence.tier is ConfidenceTier.LOW
    assert s.resolution_status is ResolutionStatus.PARTIAL and s.scope_evidence[0].dimension == "event_class"


def test_unresolved_is_a_valid_result_with_a_reason():
    s = R.resolve(sig("h", "Local festival draws record crowds"))
    assert s.scope_type is ScopeType.UNRESOLVED and s.scope_value is None and s.scope_path == []
    assert s.resolution_status is ResolutionStatus.UNRESOLVED and s.scope_confidence.tier is ConfidenceTier.NONE
    assert "not guessed" in s.reason


def test_not_a_market_event_is_unresolved_not_guessed():
    s = R.resolve(sig("i", "Banks cut lending as mortgage defaults climb", status=E.NO_EVENT))
    assert s.scope_type is ScopeType.UNRESOLVED and "not to be a market event" in s.reason


def test_tied_sectors_are_ambiguous_and_none_is_chosen():
    s = R.resolve(sig("j", "Oil and software both in focus today"))
    assert s.scope_type is ScopeType.UNRESOLVED and s.resolution_status is ResolutionStatus.AMBIGUOUS
    assert set(s.candidates) == {"Energy", "Technology"}


def test_several_named_companies_are_ambiguous_and_listed():
    s0 = sig("m", "Exxon Mobil and JPMorgan Chase lead the market", entity=XOM)
    from eventshock.domain.provenance import EntityAudit, EntityCandidate
    audit = EntityAudit(rule="ALIAS", matched_text="Exxon Mobil", multi_entity=True, candidates=[
        EntityCandidate(entity_id="ENT_XOM", entity_name="Exxon Mobil", matched_text="Exxon Mobil", rule="ALIAS", confidence=0.95),
        EntityCandidate(entity_id="ENT_JPM", entity_name="JPMorgan Chase", matched_text="JPMorgan Chase", rule="ALIAS", confidence=0.95)])
    s0 = s0.model_copy(update={"provenance": s0.provenance.model_copy(update={"entity_audit": audit})})
    s = R.resolve(s0)
    assert s.scope_type is ScopeType.COMPANY and s.resolution_status is ResolutionStatus.AMBIGUOUS
    assert s.candidates == ["JPMorgan Chase"] and s.scope_confidence.tier is not ConfidenceTier.HIGH


def test_a_company_looking_name_is_never_resolved_by_this_layer():
    # "Zorblax Inc" is not in the entity master: the pipeline left the entity unknown, and so does the scope
    s = R.resolve(sig("n", "Zorblax Inc under investigation by regulators"))
    assert s.scope_type is not ScopeType.COMPANY


def test_scope_evidence_quotes_sit_at_their_offsets():
    from eventshock.assessment.reference import analysed_text
    sg = sig("p", "Semiconductor makers brace for export curbs as chipmakers warn")
    s = R.resolve(sg)
    text = analysed_text(sg.document.headline, sg.document.body)
    for e in s.scope_evidence:
        if e.quote is not None:
            assert text[e.start:e.end] == e.quote
