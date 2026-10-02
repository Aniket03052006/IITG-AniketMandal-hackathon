"""Trigger rule, severity scaling, scope binding, determinism — on tiny hand-checkable portfolios."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eventshock.config import AppConfig
from eventshock.domain import Entity, EventCategory, StressStatus
from eventshock.domain.enums import AssetClass, RiskFactor, ShockScope
from eventshock.domain.scenarios import ShockSpec
from eventshock.services.stress_service import ScenarioNotFound, SignalNotFound, StressService
from eventshock.store import InMemoryPortfolioRepository, InMemorySignalRepository
from eventshock.stress.scenarios import ScenarioCatalog
from tests.helpers import NOW, make_asset, make_portfolio, make_scenario, make_signal

REG = EventCategory.REGULATORY_LEGAL


def build(signals, assets, scenarios=None, mapping=None):
    scenarios = scenarios or [make_scenario(REG)]
    mapping = {REG: scenarios[0].id} if mapping is None else mapping
    cat = ScenarioCatalog(scenarios, mapping, require_complete=False)
    ents = [Entity(entity_id=e, name=e, sector="Fin", country="US")
            for e in sorted({a.entity_id for a in assets})]
    return StressService(
        InMemorySignalRepository(signals, NOW),
        InMemoryPortfolioRepository(make_portfolio(assets), ents),
        cat, AppConfig(),
    )


EQ1 = make_asset(asset_id="eq1", entity_id="E1")
EQ2 = make_asset(asset_id="eq2", entity_id="E2", sector="Tech")


class TestTriggerRule:
    def test_at_threshold_runs(self):
        svc = build([make_signal(impact=7)], [EQ1])
        assert svc.run("s1").status is StressStatus.COMPLETED

    def test_below_threshold_not_triggered_and_no_numbers(self):
        r = build([make_signal(impact=6)], [EQ1]).run("s1")
        assert r.status is StressStatus.NOT_TRIGGERED
        assert r.summary is None and r.positions == []
        assert "below the trigger threshold" in (r.reason or "")

    def test_force_runs_what_if_and_is_flagged(self):
        r = build([make_signal(impact=3)], [EQ1]).run("s1", force=True)
        assert r.status is StressStatus.COMPLETED
        assert r.audit.forced is True

    def test_impact_override_requires_force(self):
        r = build([make_signal(impact=3)], [EQ1]).run("s1", impact_override=9)
        assert r.status is StressStatus.NOT_TRIGGERED

    def test_partial_signal_unavailable_even_when_forced(self):
        svc = build([make_signal(impact=None)], [EQ1])
        r = svc.run("s1", force=True, impact_override=9)
        assert r.status is StressStatus.UNAVAILABLE
        assert r.summary is None

    def test_no_scenario_for_category(self):
        svc = build([make_signal(category=EventCategory.GEOPOLITICAL)], [EQ1])
        r = svc.run("s1")
        assert r.status is StressStatus.NO_SCENARIO and r.scenario is None

    def test_unknown_ids_raise(self):
        svc = build([make_signal()], [EQ1])
        with pytest.raises(SignalNotFound):
            svc.run("missing")
        with pytest.raises(ScenarioNotFound):
            svc.run("s1", "missing")


class TestSeverityScaling:
    def test_scale_is_impact_over_reference(self):
        r = build([make_signal(impact=7)], [EQ1]).run("s1")  # reference 7
        assert r.severity.scale == pytest.approx(1.0)
        assert r.summary.pnl == pytest.approx(-100_000)

    def test_scale_clamped_high(self):
        r = build([make_signal(impact=10)], [EQ1]).run("s1")  # 10/7 = 1.43 -> not clamped
        assert r.severity.scale == pytest.approx(10 / 7)
        r2 = build([make_signal(impact=10)], [EQ1],
                   [make_scenario(REG)]).run("s1", impact_override=10, force=True)
        assert r2.severity.scale <= 1.5

    def test_scale_clamped_low(self):
        r = build([make_signal(impact=1)], [EQ1]).run("s1", force=True)  # 1/7 -> 0.5
        assert r.severity.scale == pytest.approx(0.5)
        assert r.summary.pnl == pytest.approx(-50_000)

    def test_override_changes_scale_and_is_audited(self):
        r = build([make_signal(impact=8)], [EQ1]).run("s1", force=True, impact_override=3.5)
        assert r.severity.impact_used == 3.5 and r.audit.impact_overridden


class TestScopeBinding:
    SCN = make_scenario(REG, [
        ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-0.01),
        ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.ISSUER, value=-0.10),
    ])

    def test_issuer_shock_hits_only_issuer(self):
        r = build([make_signal(impact=7)], [EQ1, EQ2], [self.SCN]).run("s1")
        by = {p.asset_id: p for p in r.positions}
        assert by["eq1"].delta == pytest.approx(-100_000)
        assert by["eq2"].delta == pytest.approx(-10_000)  # market shock x beta 1.0

    def test_unknown_entity_marks_issuer_shock_not_applicable(self):
        sig = make_signal(impact=7, entity_id="UNKNOWN_ENTITY")
        r = build([sig], [EQ1, EQ2], [self.SCN]).run("s1")
        issuer = next(s for s in r.shocks if s.scope is ShockScope.ISSUER)
        assert issuer.applicable is False
        assert r.summary.pnl == pytest.approx(-20_000)  # market shock only, both assets

    def test_uncovered_exposure_is_reported(self):
        scn = make_scenario(REG, [ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.ISSUER, value=-0.1)])
        bond = make_asset(asset_id="bd", entity_id="E2", sector="Tech", asset_type=AssetClass.BOND,
                          duration=4.0)
        r = build([make_signal()], [EQ1, bond], [scn]).run("s1")
        assert r.uncovered.asset_ids == ["bd"]
        assert r.uncovered.share_of_portfolio == pytest.approx(0.5)


class TestAggregation:
    def test_totals_reconcile(self):
        r = build([make_signal()], [EQ1, EQ2]).run("s1")
        s = r.summary
        assert s.stressed_value == pytest.approx(s.baseline_value + s.pnl)
        assert sum(p.delta for p in r.positions) == pytest.approx(s.pnl)
        for group in (r.contributions.by_asset_class, r.contributions.by_sector,
                      r.contributions.by_entity, r.contributions.by_factor):
            assert sum(c.delta for c in group) == pytest.approx(s.pnl)

    def test_positions_sorted_worst_first(self):
        r = build([make_signal()], [EQ1, EQ2]).run("s1")
        deltas = [p.delta for p in r.positions]
        assert deltas == sorted(deltas)

    def test_shares_sum_to_one_when_loss(self):
        r = build([make_signal()], [EQ1, EQ2]).run("s1")
        assert sum(c.share_of_loss for c in r.contributions.by_entity) == pytest.approx(1.0)


class TestDeterminism:
    def test_same_inputs_same_run_id_and_result(self):
        svc = build([make_signal()], [EQ1, EQ2])
        a, b = svc.run("s1"), svc.run("s1")
        assert a.run_id == b.run_id and a == b

    def test_changed_input_changes_run_id(self):
        svc = build([make_signal()], [EQ1, EQ2])
        assert svc.run("s1").run_id != svc.run("s1", force=True, impact_override=9).run_id

    def test_calculated_at_is_pinned_to_replay_clock(self):
        r = build([make_signal()], [EQ1]).run("s1")
        assert r.audit.calculated_at == NOW and r.audit.calculated_at.tzinfo == UTC
        assert isinstance(r.audit.calculated_at, datetime)

    def test_run_is_retrievable_by_id(self):
        svc = build([make_signal()], [EQ1])
        r = svc.run("s1")
        assert svc.get_run(r.run_id) == r
