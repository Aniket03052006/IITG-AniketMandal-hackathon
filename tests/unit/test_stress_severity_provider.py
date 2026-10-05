"""The stress engine driven by the risk assessment: the trigger reads the hybrid severity, the scenario follows the ASSESSED event class, a sector read
from the text binds sector shocks where the vocabulary scope found none, and with no provider nothing changes."""

from __future__ import annotations

from eventshock.domain import EventCategory, ScopeLevel, StressStatus
from eventshock.domain.enums import RiskFactor, ShockScope
from eventshock.domain.scenarios import ShockSpec
from eventshock.services.stress_service import SeverityView
from tests.helpers import make_asset, make_scenario, make_signal
from tests.unit.test_stress_scope import market_scope
from tests.unit.test_stress_service import REG, build

FIN = make_asset(asset_id="fin1", entity_id="E1", sector="Fin")
TECH = make_asset(asset_id="tech", entity_id="E3", sector="Tech")
SCN = make_scenario(REG, [
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-0.01),
    ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.SECTOR, value=-0.04),
])


def view(score: int, sector: str | None = "Fin", category: EventCategory = REG) -> SeverityView:
    return SeverityView(score=score, category=category, sector=sector, basis="SCORECARD", version="severity-v2", extraction_mode="RULES")


def svc(signal, v: SeverityView | None):
    s = build([signal], [FIN, TECH], [SCN])
    s._severity = (lambda _s: v) if v else None  # noqa: SLF001
    return s


def test_below_the_trigger_the_run_says_severity_and_offers_the_what_if() -> None:
    sig = make_signal(impact=9, entity_id="UNKNOWN_ENTITY", scope=market_scope())  # its own impact is high; the assessment says 3
    r = svc(sig, view(3)).run(sig.id)
    assert r.status is StressStatus.NOT_TRIGGERED and "Severity 3" in r.reason and "what-if" in r.reason
    assert r.audit.impact_origin == "ASSESSMENT" and r.audit.severity_basis == "SCORECARD" and r.audit.extraction_mode == "RULES"


def test_above_the_trigger_the_run_completes_on_the_severity_score() -> None:
    sig = make_signal(impact=2, entity_id="UNKNOWN_ENTITY", scope=market_scope())  # its own impact is low; the assessment says 8
    r = svc(sig, view(8)).run(sig.id)
    assert r.status is StressStatus.COMPLETED and r.severity.impact_used == 8 and r.audit.impact_lifecycle is None
    assert r.summary.pnl < 0


def test_the_what_if_still_works_below_the_trigger() -> None:
    sig = make_signal(impact=9, entity_id="UNKNOWN_ENTITY", scope=market_scope())
    r = svc(sig, view(3)).run(sig.id, force=True)
    assert r.status is StressStatus.COMPLETED and r.audit.forced and r.severity.impact_used == 3


def test_an_assessed_sector_binds_sector_shocks_where_the_vocabulary_scope_found_none() -> None:
    sig = make_signal(impact=9, entity_id="UNKNOWN_ENTITY", scope=market_scope())
    without = svc(sig, view(8, sector=None)).run(sig.id)
    with_sector = svc(sig, view(8, sector="Fin")).run(sig.id)
    assert {s.scope: s.applicable for s in without.shocks}[ShockScope.SECTOR] is False
    assert {s.scope: s.applicable for s in with_sector.shocks}[ShockScope.SECTOR] is True
    assert with_sector.audit.assessed_sector == "Fin" and "read from the text" in with_sector.audit.scope_note
    assert with_sector.summary.pnl < without.summary.pnl  # the financials holding takes the sector shock as well
    by_asset = {p.asset_id: p.delta for p in with_sector.positions}
    assert by_asset["fin1"] < by_asset["tech"]  # the sector shock reaches only the named sector


def test_a_partial_signal_can_be_stressed_when_the_assessment_reads_an_event() -> None:
    sig = make_signal(impact=None, entity_id="UNKNOWN_ENTITY", scope=market_scope())  # the trained model abstained
    assert svc(sig, None).run(sig.id).status is StressStatus.UNAVAILABLE
    assert svc(sig, view(8)).run(sig.id).status is StressStatus.COMPLETED


def test_the_scenario_follows_the_assessed_event_class_not_the_trained_one() -> None:
    other = make_scenario(EventCategory.GEOPOLITICAL, [ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-0.03)], sid="scn_geo")
    sig = make_signal(impact=9, category=EventCategory.REGULATORY_LEGAL, entity_id="UNKNOWN_ENTITY", scope=market_scope())
    s = build([sig], [FIN], [SCN, other], mapping={REG: SCN.id, EventCategory.GEOPOLITICAL: other.id})
    s._severity = lambda _s: view(8, category=EventCategory.GEOPOLITICAL)  # noqa: SLF001
    assert s.run(sig.id).scenario.id == "scn_geo"


def test_a_resolved_company_scope_is_never_overridden_by_an_assessed_sector() -> None:
    sig = make_signal(impact=9)  # COMPANY scope, sector Fin
    r = svc(sig, view(8, sector="Tech")).run(sig.id)
    assert r.audit.assessed_sector is None and r.audit.scope_level == "COMPANY"


def test_with_no_provider_nothing_changes() -> None:
    sig = make_signal(impact=8)
    r = build([sig], [FIN], [SCN]).run(sig.id)
    assert r.audit.impact_origin is None and r.audit.severity_basis is None and r.audit.assessed_sector is None and r.status is StressStatus.COMPLETED
    assert ScopeLevel.COMPANY.value == r.audit.scope_level


def test_run_ids_differ_only_when_the_assessment_drove_the_run() -> None:
    sig = make_signal(impact=8)
    plain = build([sig], [FIN], [SCN]).run(sig.id)
    driven = svc(sig, view(8)).run(sig.id)
    assert plain.run_id != driven.run_id
    assert svc(sig, view(8)).run(sig.id).run_id == driven.run_id  # deterministic
    s = build([sig], [FIN], [SCN])
    s.run(sig.id)
    assert [r.run_id for r in s.runs_for(sig.id)] == [plain.run_id]
