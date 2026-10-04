"""Scope decides which shocks bind. Hand-checkable books; the unresolved-and-zero defect found in Stage 6 is pinned here."""

from __future__ import annotations

import pytest

from eventshock.domain import EventCategory, ScopeBasis, ScopeLevel, ScopeStrength, SignalScope, StressStatus
from eventshock.domain.enums import RiskFactor, ShockScope
from eventshock.domain.scenarios import ShockSpec
from tests.helpers import NOW, make_asset, make_scenario, make_signal
from tests.unit.test_stress_service import REG, build

EQ_FIN = make_asset(asset_id="fin1", entity_id="E1", sector="Fin")
EQ_FIN2 = make_asset(asset_id="fin2", entity_id="E2", sector="Fin")
EQ_TECH = make_asset(asset_id="tech", entity_id="E3", sector="Tech")

SCN = make_scenario(REG, [
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-0.01),
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.SECTOR, value=-0.04),
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.ISSUER, value=-0.10),
])
ISSUER_ONLY = make_scenario(EventCategory.MA_CORPORATE_ACTION, [
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.SECTOR, value=-0.015),
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.ISSUER, value=-0.07),
], sid="scn_issuer_only")


def sector_scope(sector: str = "Fin") -> SignalScope:
    return SignalScope(level=ScopeLevel.SECTOR, sector=sector, basis=ScopeBasis.SECTOR_TERMS, strength=ScopeStrength.STRONG)


def market_scope() -> SignalScope:
    return SignalScope(level=ScopeLevel.MARKET, basis=ScopeBasis.THEME_TERMS, themes=["rates"])


def run(signal, scn=SCN, assets=(EQ_FIN, EQ_FIN2, EQ_TECH)):
    return build([signal], list(assets), [scn]).run(signal.id)


def test_company_scope_binds_all_three_scopes() -> None:
    r = run(make_signal(impact=7))
    assert {s.scope: s.applicable for s in r.shocks} == {ShockScope.MARKET: True, ShockScope.SECTOR: True, ShockScope.ISSUER: True}
    assert r.audit.scope_level == "COMPANY"


def test_sector_scope_applies_sector_and_market_shocks_but_not_issuer() -> None:
    r = run(make_signal(impact=7, entity_id="UNKNOWN_ENTITY", scope=sector_scope("Fin")))
    by = {s.scope: s for s in r.shocks}
    assert by[ShockScope.SECTOR].applicable and by[ShockScope.MARKET].applicable
    assert by[ShockScope.ISSUER].applicable is False and "sector" in by[ShockScope.ISSUER].not_applicable_reason
    pos = {p.asset_id: p.delta for p in r.positions}
    assert pos["fin1"] == pytest.approx(-40_000) and pos["fin2"] == pytest.approx(-40_000)  # the sector shock, no issuer shock
    assert pos["tech"] == pytest.approx(-10_000)  # market shock only
    assert r.audit.scope_level == "SECTOR" and "Sector (Fin)" in r.audit.scope_note


def test_market_scope_applies_market_shocks_only() -> None:
    r = run(make_signal(impact=7, entity_id="UNKNOWN_ENTITY", scope=market_scope()))
    assert [s.scope for s in r.shocks if s.applicable] == [ShockScope.MARKET]
    assert all("market as a whole" in s.not_applicable_reason for s in r.shocks if not s.applicable)
    assert r.summary.pnl == pytest.approx(-30_000)


def test_unresolved_with_no_market_shock_is_not_applicable_rather_than_a_zero() -> None:
    sig = make_signal(impact=7, entity_id="UNKNOWN_ENTITY", category=EventCategory.MA_CORPORATE_ACTION)
    r = build([sig], [EQ_FIN, EQ_TECH], [ISSUER_ONLY], {EventCategory.MA_CORPORATE_ACTION: ISSUER_ONLY.id}).run("s1")
    assert r.status is StressStatus.NOT_APPLICABLE
    assert r.summary is None and r.positions == [] and r.uncovered is None
    assert "reaches what this event is about" in r.reason and "no company, sector or market theme" in r.reason
    assert [s.applicable for s in r.shocks] == [False, False] and all(s.not_applicable_reason for s in r.shocks)
    assert r.severity is not None and r.audit.scope_level == "UNRESOLVED"


def test_the_same_issuer_only_scenario_does_apply_to_a_sector_event() -> None:
    sig = make_signal(impact=7, entity_id="UNKNOWN_ENTITY", scope=sector_scope("Fin"), category=EventCategory.MA_CORPORATE_ACTION)
    r = build([sig], [EQ_FIN, EQ_TECH], [ISSUER_ONLY], {EventCategory.MA_CORPORATE_ACTION: ISSUER_ONLY.id}).run("s1")
    assert r.status is StressStatus.COMPLETED
    assert {p.asset_id: p.delta for p in r.positions} == {"fin1": pytest.approx(-15_000), "tech": 0.0}


def test_not_applicable_run_ids_differ_from_completed_ones() -> None:
    a = build([make_signal(impact=7, entity_id="UNKNOWN_ENTITY", category=EventCategory.MA_CORPORATE_ACTION)], [EQ_FIN],
              [ISSUER_ONLY], {EventCategory.MA_CORPORATE_ACTION: ISSUER_ONLY.id}).run("s1")
    b = build([make_signal(impact=7, entity_id="UNKNOWN_ENTITY", category=EventCategory.MA_CORPORATE_ACTION,
                           scope=sector_scope("Fin"))], [EQ_FIN], [ISSUER_ONLY],
              {EventCategory.MA_CORPORATE_ACTION: ISSUER_ONLY.id}).run("s1")
    assert a.run_id != b.run_id


def test_existing_signals_bind_exactly_as_before() -> None:
    """A fixture-style signal (no scope given) derives COMPANY / UNRESOLVED from its entity: same shocks as the pre-scope rule."""
    known = run(make_signal(impact=7))
    unknown = run(make_signal(impact=7, entity_id="UNKNOWN_ENTITY"))
    assert [s.applicable for s in known.shocks] == [True, True, True]
    assert [s.applicable for s in unknown.shocks] == [True, False, False]


def test_calculated_at_is_never_before_the_signal() -> None:
    sig = make_signal(impact=7)
    assert run(sig).audit.calculated_at >= sig.created_at
    assert sig.created_at == NOW
