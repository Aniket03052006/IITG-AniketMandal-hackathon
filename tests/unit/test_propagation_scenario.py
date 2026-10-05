"""Event -> scenario: deterministic, configurable, labelled a simulation, unavailable (with the reason) when nothing defensible exists."""

from __future__ import annotations

import pytest

from eventshock.config import REPO_ROOT, AppConfig, StressConfig
from eventshock.domain import Entity, EventCategory, RiskFactor, ScopeLevel, ShockScope, StressStatus
from eventshock.intelligence.model import Availability
from eventshock.propagation.config import load_propagation_config
from eventshock.propagation.models import SCENARIO_LABEL, Status
from eventshock.propagation.scenario_gen import ScenarioGenerator
from eventshock.services.stress_service import StressService
from eventshock.store import InMemoryPortfolioRepository, InMemorySignalRepository
from tests.helpers import NOW, make_signal
from tests.intel_helpers import JPM
from tests.prop_helpers import PROP_CFG, assessor, book, catalog, mapped, mapper

SANCTIONS = "Sanctions on Russia disrupt trade across Ukraine"


def gen(headline=SANCTIONS, *, category=EventCategory.GEOPOLITICAL, severity=8.0, direction="adverse", entity=None, portfolio=None, cfg=PROP_CFG, overrides=None,
        event_sector="__auto__", issuer_known="__auto__", with_material=True):
    pf = portfolio or book()
    s, g = mapped(headline, entity=entity, category=category, portfolio=pf, cfg=cfg, overrides=overrides)
    m = assessor(cfg).assess(g, severity)
    sector = (s.scope.sector if s.scope.has_sector else None) if event_sector == "__auto__" else event_sector
    known = (s.scope.level is ScopeLevel.COMPANY and entity is not None) if issuer_known == "__auto__" else issuer_known
    return ScenarioGenerator(cfg, catalog(), AppConfig().stress, None).generate(
        signal_id=s.id, portfolio=pf, graph=g, materiality=m, category=category, severity=severity, direction=direction, event_sector=sector, issuer_known=known,
        mapper=mapper(cfg, overrides))


class TestGeneration:
    @pytest.mark.parametrize("category", list(EventCategory))
    def test_every_event_class_has_a_template(self, category):
        r = gen("JPMorgan Chase fined over compliance failures", category=category, entity=JPM)
        assert r.availability is Availability.AVAILABLE, r.reason
        assert r.label == SCENARIO_LABEL == "SCENARIO SIMULATION — NOT A PREDICTION"
        assert r.scenario.id.startswith(f"gen_{category.value.lower()}_") and SCENARIO_LABEL in r.scenario.description
        assert r.scenario.category is category and r.scenario.illustrative
        assert all(g.passed for g in r.gates)

    def test_base_shocks_are_the_catalog_scenarios_unchanged(self):
        r = gen(SANCTIONS)
        base = catalog().default_for(EventCategory.GEOPOLITICAL)
        generated = {(s.factor, s.scope): s.value for s in r.scenario.shocks if s.sector is None}
        assert generated == {(s.factor, s.scope): s.value for s in base.shocks}
        assert all(o.source == "CATALOG_BASE" and o.status is Status.SCENARIO_ASSUMPTION for o in r.origins if o.sector is None)

    def test_sector_shocks_are_propagated_from_the_risk_factors(self):
        r = gen(SANCTIONS)
        sec = {s.sector: s for s in r.scenario.shocks if s.sector and s.factor is RiskFactor.EQUITY}
        assert set(sec) == {"Energy", "Industrials", "Technology"}
        market = next(s.value for s in r.scenario.shocks if s.factor is RiskFactor.EQUITY and s.scope is ShockScope.MARKET)
        g = PROP_CFG.generation
        # Technology: only the geopolitical tech edge (weight 0.3)
        assert sec["Technology"].value == pytest.approx(market + g.propagated_equity_shock * 0.3)
        # Energy benefits: the weights add to below -1 and are clamped, so the market shock is softened by the full increment
        assert sec["Energy"].value == pytest.approx(market - g.propagated_equity_shock)
        # a sector the factor hurts also gets a spread widening on top of the market-wide one; one it benefits does not
        spreads = {s.sector for s in r.scenario.shocks if s.sector and s.factor is RiskFactor.CREDIT_SPREAD_BPS}
        assert "Technology" in spreads and "Energy" not in spreads
        assert all(o.source == "PROPAGATED" and o.risk_factor for o in r.origins if o.sector)

    def test_the_events_own_sector_is_not_propagated_over(self):
        r = gen("Oil supply disruption as OPEC cuts output", category=EventCategory.GEOPOLITICAL)
        # the text is about Energy: its sector shock is the scenario's own implicit one, not a propagated copy
        assert not any(s.sector == "Energy" for s in r.scenario.shocks)

    def test_deterministic_id_and_version(self):
        a, b = gen(), gen()
        assert a.scenario.id == b.scenario.id and a.scenario.version == b.scenario.version
        assert a.model_dump_json() == b.model_dump_json()

    def test_an_adjusted_value_is_a_different_scenario(self):
        base = gen()
        cfg = load_propagation_config(REPO_ROOT / "configs", {"generation.propagated_equity_shock": -0.06})
        other = gen(cfg=cfg)
        assert other.scenario.version != base.scenario.version

    def test_a_template_size_override_replaces_the_base_shock_and_is_labelled(self):
        ov = {"propagation.templates.GEOPOLITICAL.shock_overrides.EQUITY:MARKET": -0.2}
        cfg = load_propagation_config(REPO_ROOT / "configs", {"templates.GEOPOLITICAL.shock_overrides.EQUITY:MARKET": -0.2})
        r = gen(cfg=cfg, overrides=ov)
        s = next(s for s in r.scenario.shocks if s.factor is RiskFactor.EQUITY and s.scope is ShockScope.MARKET)
        assert s.value == -0.2
        o = next(o for o in r.origins if o.factor == "EQUITY" and o.scope == "MARKET")
        assert o.source == "USER" and o.status is Status.USER_ASSUMPTION
        # and the propagated sector shocks start from the adjusted market-wide shock
        assert all(x.value <= -0.2 + 0.03 for x in r.scenario.shocks if x.sector and x.factor is RiskFactor.EQUITY)

    def test_the_catalog_scenario_is_not_modified(self):
        before = catalog().default_for(EventCategory.GEOPOLITICAL).model_dump()
        gen()
        assert catalog().default_for(EventCategory.GEOPOLITICAL).model_dump() == before

    def test_propagation_scale_zero_leaves_only_the_base(self):
        cfg = load_propagation_config(REPO_ROOT / "configs", {"generation.propagation_scale": 0})
        r = gen(cfg=cfg)
        assert not any(s.sector for s in r.scenario.shocks)

    def test_history_check_is_attached_when_history_is_installed(self):
        from eventshock.stress.history_check import ShockHistory
        pf = book()
        s, g = mapped(SANCTIONS, category=EventCategory.GEOPOLITICAL)
        r = ScenarioGenerator(PROP_CFG, catalog(), StressConfig(), ShockHistory.load(REPO_ROOT)).generate(
            signal_id="s", portfolio=pf, graph=g, materiality=assessor().assess(g, 8.0), category=EventCategory.GEOPOLITICAL, severity=8.0, direction="adverse",
            event_sector=None, issuer_known=False, mapper=mapper())
        assert r.history_check is not None and r.history_check.scenario_id == r.scenario.id
        assert len(r.history_check.checks) == len(r.scenario.shocks)


class TestUnavailable:
    def test_no_event_class(self):
        r = gen(category=None)
        assert r.availability is Availability.UNAVAILABLE and r.scenario is None and r.reason.startswith("SCENARIO UNAVAILABLE")
        assert r.gates[0].id == "event" and not r.gates[0].passed

    def test_no_defensible_mapping(self):
        r = gen("Quarterly update posted", category=EventCategory.MA_CORPORATE_ACTION)
        assert r.availability is Availability.UNAVAILABLE and r.scenario is None
        assert any(g.id == "mapping" and not g.passed for g in r.gates)

    def test_nothing_held_is_reached(self):
        r = gen("Regional banks face tougher capital rules", category=EventCategory.CREDIT_FUNDING, portfolio=book(only=["ust_bd", "cash"]))
        assert r.availability is Availability.UNAVAILABLE and "holds nothing" in r.reason

    def test_template_switched_off(self):
        cfg = load_propagation_config(REPO_ROOT / "configs", {"templates.GEOPOLITICAL.enabled": False})
        r = gen(cfg=cfg)
        assert r.availability is Availability.UNAVAILABLE and any(g.id == "template" and not g.passed for g in r.gates)

    def test_no_shock_binds_to_this_event(self):
        # the M&A template only has sector (implicit) and issuer shocks: with neither a sector nor an issuer named, nothing binds
        r = gen("Regional banks face tougher capital rules", category=EventCategory.MA_CORPORATE_ACTION, event_sector=None, issuer_known=False)
        assert r.availability is Availability.UNAVAILABLE and any(g.id == "reach" and not g.passed for g in r.gates)

    @pytest.mark.parametrize(("kwargs", "gate"), [({"severity": 3.0}, "severity"), ({"severity": None}, "severity"), ({"direction": "favourable"}, "direction")])
    def test_a_soft_gate_blocks_but_can_be_run_as_a_what_if(self, kwargs, gate):
        r = gen(**kwargs)
        assert r.availability is Availability.ABSTAINED and r.can_force and r.scenario is not None
        assert any(g.id == gate and not g.passed for g in r.gates) and "SCENARIO UNAVAILABLE" in r.reason

    def test_low_relevance_is_a_soft_gate(self):
        cfg = load_propagation_config(REPO_ROOT / "configs", {"generation.min_materiality": "CRITICAL"})
        r = gen(severity=5.0, cfg=cfg, portfolio=book(only=["jpm_eq", "gs_eq", "msft_eq", "cash"]))
        assert r.availability is Availability.ABSTAINED and any(g.id == "materiality" and not g.passed for g in r.gates)

    def test_downside_only_can_be_switched_off(self):
        cfg = load_propagation_config(REPO_ROOT / "configs", {"generation.downside_only": False})
        assert gen(direction="favourable", cfg=cfg).availability is Availability.AVAILABLE

    def test_minimum_severity_is_adjustable(self):
        cfg = load_propagation_config(REPO_ROOT / "configs", {"generation.min_severity": 4})
        assert gen(severity=5.0, cfg=cfg).availability is Availability.AVAILABLE


def test_a_generated_scenario_runs_through_the_unchanged_engine():
    pf = book()
    r = gen()
    sig = make_signal("s1", category=EventCategory.GEOPOLITICAL, impact=8, entity_id="UNKNOWN_ENTITY")
    svc = StressService(InMemorySignalRepository([sig], NOW), InMemoryPortfolioRepository(pf, [Entity(entity_id=e, name=e, sector="x", country="US") for e in sorted({a.entity_id for a in pf.assets})]), catalog(), AppConfig())
    res = svc.run_scenario("s1", r.scenario, portfolio=pf)
    assert res.status is StressStatus.COMPLETED and res.scenario.id == r.scenario.id
    assert sum(p.delta for p in res.positions) == pytest.approx(res.summary.pnl)
    energy = next(p for p in res.positions if p.asset_id == "xom_eq")
    e_shock = next(s for s in res.shocks if s.sector == "Energy" and s.factor is RiskFactor.EQUITY)
    assert energy.delta == pytest.approx(150_000 * e_shock.scaled_value)  # the explicit sector shock, with no beta
    # a different scenario version is a different run
    other = r.scenario.model_copy(update={"version": "gen-other"})
    assert svc.run_scenario("s1", other, portfolio=pf).run_id != res.run_id
    assert svc.get_run(res.run_id) is res
