"""Portfolio relevance: which part of the book an event reaches, from exposure alone."""

from __future__ import annotations

import pytest

from eventshock.domain import AssetClass, Entity, EventCategory, ScopeBasis, ScopeLevel, SignalScope
from eventshock.domain.enums import RiskFactor, ShockScope
from eventshock.domain.scenarios import ShockSpec
from eventshock.services.relevance import RelevanceLevel, RelevanceService
from eventshock.store import InMemoryPortfolioRepository
from eventshock.stress.scenarios import ScenarioCatalog
from tests.helpers import make_asset, make_portfolio, make_scenario, make_signal
from tests.unit.test_stress_service import REG

ASSETS = [
    make_asset(asset_id="e1", entity_id="E1", sector="Fin", market_value=600_000.0, notional=600_000.0),
    make_asset(asset_id="b1", entity_id="E1", sector="Fin", asset_type=AssetClass.BOND, duration=4.0,
               market_value=200_000.0, notional=200_000.0),
    make_asset(asset_id="e2", entity_id="E2", sector="Tech", market_value=200_000.0, notional=200_000.0, geography="GB"),
]
SCN = make_scenario(REG, [ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-0.01),
                          ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.ISSUER, value=-0.1)])


@pytest.fixture()
def svc() -> RelevanceService:
    ents = [Entity(entity_id=e, name=e, sector="x", country="US") for e in ("E1", "E2")]
    return RelevanceService(InMemoryPortfolioRepository(make_portfolio(ASSETS), ents),
                            ScenarioCatalog([SCN], {REG: SCN.id}, require_complete=False))


def test_a_held_issuer_is_direct_with_its_share_and_asset_split(svc) -> None:
    r = svc.assess(make_signal(entity_id="E1"))
    assert r.level is RelevanceLevel.DIRECT and r.share == pytest.approx(0.8)
    issuer = next(s for s in r.slices if s.kind == "ISSUER")
    assert issuer.asset_count == 2 and issuer.by_asset_class == {"BOND": 200_000.0, "EQUITY": 600_000.0}
    assert "directly" in r.summary and r.path[0].startswith("E1: held")
    assert r.reach.shocks_bound == 2 and r.reach.note == "every shock reaches this event"


def test_an_unheld_issuer_in_a_held_sector_is_read_across_only(svc) -> None:
    sig = make_signal(entity_id="E9", sector="Tech")
    r = svc.assess(sig)
    assert r.level is RelevanceLevel.SECTOR and r.share == pytest.approx(0.2) and "read-across" in r.summary


def test_a_sector_event_reports_the_sector_slice(svc) -> None:
    sc = SignalScope(level=ScopeLevel.SECTOR, sector="Fin", basis=ScopeBasis.SECTOR_TERMS)
    r = svc.assess(make_signal(entity_id="UNKNOWN_ENTITY", scope=sc))
    assert r.level is RelevanceLevel.SECTOR and r.share == pytest.approx(0.8)
    assert r.reach.shocks_bound == 1 and "need a company or sector" in r.reach.note


def test_a_sector_the_book_does_not_hold_is_none(svc) -> None:
    sc = SignalScope(level=ScopeLevel.SECTOR, sector="Energy", basis=ScopeBasis.SECTOR_TERMS)
    r = svc.assess(make_signal(entity_id="UNKNOWN_ENTITY", scope=sc))
    assert r.level is RelevanceLevel.NONE and r.share == 0.0


def test_a_market_event_reaches_the_whole_book_and_reports_regions(svc) -> None:
    sc = SignalScope(level=ScopeLevel.MARKET, basis=ScopeBasis.THEME_TERMS, themes=["rates"], regions=["GB", "CN"])
    r = svc.assess(make_signal(entity_id="UNKNOWN_ENTITY", scope=sc))
    assert r.level is RelevanceLevel.MARKET_WIDE and r.share == 1.0
    assert {s.kind for s in r.slices} == {"BOOK", "REGION"}
    assert next(s for s in r.slices if s.kind == "REGION").key == "GB"
    assert any("CN: no positions" in p for p in r.path)


def test_an_unresolved_event_says_it_cannot_be_stated(svc) -> None:
    r = svc.assess(make_signal(entity_id="UNKNOWN_ENTITY"))
    assert r.level is RelevanceLevel.UNDETERMINED and r.share is None
    assert r.reach.shocks_bound == 1  # the market shock binds; the issuer one does not
    assert "cannot be stated" in r.summary


def test_headline_is_the_cheap_form_of_assess(svc) -> None:
    sig = make_signal(entity_id="E1")
    assert svc.headline(sig) == (RelevanceLevel.DIRECT, pytest.approx(0.8))


def test_category_without_a_scenario_has_no_reach(svc) -> None:
    r = svc.assess(make_signal(entity_id="E1", category=EventCategory.GEOPOLITICAL))
    assert r.reach is None
