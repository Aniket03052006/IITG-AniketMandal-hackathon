"""The scenario lab over the real replay pack: nothing is written onto a signal, every assessed scenario that Stage 11 generates runs and reconciles through the lab, and a rebuilt
side-car gives byte-identical results."""

from __future__ import annotations

from eventshock.api.deps import rebuild_sidecars
from eventshock.lab.models import Assumption, AssumptionKind, ScenarioRequest, ScenarioType
from eventshock.pipeline.run import _digest
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST

K = AssumptionKind


def generating(c):  # noqa: ANN001, ANN201
    """The signals that can generate a scenario at all (severity at the trigger): scanning every signal's scenario is minutes of work for nothing."""
    thr = c.assessments.threshold
    for s in c.signals.list():
        a = c.assessments.assess(s)
        if a.severity is not None and a.severity.score >= thr and c.propagation.scenario(s).availability.value == "AVAILABLE":
            yield s


def customs():  # noqa: ANN201
    return [ScenarioRequest(assumptions=[Assumption(kind=K.EQUITY_MARKET, value=-0.10), Assumption(kind=K.RATES, value=100), Assumption(kind=K.CREDIT_SPREAD, value=80)]),
            ScenarioRequest(assumptions=[Assumption(kind=K.SECTOR, target="Healthcare", value=-0.2), Assumption(kind=K.RISK_FACTOR, target="GEOPOLITICAL", value=-0.1)]),
            ScenarioRequest(assumptions=[Assumption(kind=K.COMMODITY, value=-0.3), Assumption(kind=K.FX, target="EUR", value=-0.1)], exposure_priors=True)]


def test_every_assessed_scenario_runs_and_reconciles_and_the_signals_are_untouched(replay_container):
    c = replay_container
    n = 0
    for s in generating(c):
        r = c.lab.run(ScenarioRequest(scenario_type=ScenarioType.ASSESSED, signal_id=s.id))
        assert r.status == "COMPLETED" and r.attribution.reconciled and r.assumptions and all(a.origin == "ASSESSED" for a in r.assumptions)
        n += 1
    assert n >= 10
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST


def test_custom_scenarios_are_deterministic_across_a_sidecar_rebuild(replay_container):
    c = replay_container
    before = [c.lab.run(r).model_dump_json() for r in customs()]
    rebuild_sidecars(c, {})
    assert [c.lab.run(r).model_dump_json() for r in customs()] == before
    for r in customs():
        out = c.lab.run(r)
        assert out.status in ("COMPLETED", "NOT_APPLICABLE") and (out.attribution is None or out.attribution.reconciled)
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST


def test_reverse_stress_over_the_real_book_is_deterministic_reconciles_and_leaves_the_signals_alone(replay_container):
    from eventshock.lab.models import ReverseStressRequest as R
    c = replay_container
    outs = [c.lab.reverse(R(target_pct=t)) for t in (-2, -5, -10)]
    for o, _t in zip(outs, (-2, -5, -10), strict=True):
        assert o.status == "ACHIEVABLE" and abs(o.difference_pp) <= c.lab.reverse_cfg.tolerance_pp and o.scenario.attribution.reconciled and o.required_shocks
        assert c.lab.run(o.open_in_lab).result.summary == o.scenario.result.summary
    rebuild_sidecars(c, {})
    assert [c.lab.reverse(R(target_pct=t)).model_dump_json() for t in (-2, -5, -10)] == [o.model_dump_json() for o in outs]
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST
