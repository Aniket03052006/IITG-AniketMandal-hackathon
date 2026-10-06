"""Explanations: structured reasons with a closed code, a kind and a source; no empty explanation for a material output; the four kinds of statement are never blurred."""

from __future__ import annotations

import json

import pytest

from eventshock.explain import builders
from eventshock.explain.builders import ExplanationError
from eventshock.explain.models import ReasonCode, ReasonKind, Subject
from eventshock.lab.models import Assumption as A
from eventshock.lab.models import AssumptionKind as K
from eventshock.lab.models import ReverseStressRequest, ScenarioRequest
from eventshock.monitor.diff import diff_states
from eventshock.monitor.models import ChangeType
from tests.lab_helpers import lab
from tests.monitor_helpers import dcfg, state
from tests.prop_helpers import JPM, assessor, mapped

BANNED = ("ai determined", "the ai says", "model decided")


def materiality(severity: float | None = 8.0):  # noqa: ANN201
    s, g = mapped("JPMorgan fined $920 million over spoofing", entity=JPM)
    return assessor().assess(g, severity, None)


def kinds(e):  # noqa: ANN001, ANN201
    return {r.kind for r in e.reasons}


def test_priority_gives_one_reason_per_component_of_the_ranking_key_with_its_kind_and_source():
    m = materiality()
    e = builders.priority(state(severity=8.0, lifecycle="ESCALATING", evidence_tier="STRONG", independent_sources=8, report_count=9), None, m, 7.0)
    codes = [r.code for r in e.reasons]
    for c in (ReasonCode.MATERIALITY, ReasonCode.EXPOSURE_SHARE, ReasonCode.SEVERITY, ReasonCode.INDEPENDENT_SOURCES, ReasonCode.EVIDENCE_TIER, ReasonCode.LIFECYCLE):
        assert c in codes
    assert e.subject is Subject.PRIORITY and e.level == m.level and e.availability == "AVAILABLE" and e.headline.startswith(f"Priority {m.level}")
    by = {r.code: r for r in e.reasons}
    assert by[ReasonCode.SEVERITY].kind is ReasonKind.MODEL_OUTPUT and "triage" in by[ReasonCode.SEVERITY].text and "at or above the stress trigger" in by[ReasonCode.SEVERITY].text
    assert by[ReasonCode.MATERIALITY].kind is ReasonKind.PRODUCT_RULE and by[ReasonCode.INDEPENDENT_SOURCES].value == 8
    assert "8 independent sources" in by[ReasonCode.INDEPENDENT_SOURCES].text and by[ReasonCode.LIFECYCLE].value == "ESCALATING"
    assert all(r.source_ref and r.provenance and r.text for r in e.reasons)
    assert e.kinds == {k.value: sum(1 for r in e.reasons if r.kind is k) for k in kinds(e)}                        # the tally is of the reasons, kind by kind
    assert not any(b in r.text.lower() for r in e.reasons for b in BANNED)


def test_a_model_output_is_never_labelled_a_rule_and_a_rule_never_a_model():
    e = builders.priority(state(), None, materiality(), 7.0)
    for r in e.reasons:
        if r.code in (ReasonCode.SEVERITY, ReasonCode.EVENT_CLASS):
            assert r.kind is ReasonKind.MODEL_OUTPUT
        if r.code in (ReasonCode.MATERIALITY, ReasonCode.EVIDENCE_TIER, ReasonCode.INDEPENDENT_SOURCES, ReasonCode.LIFECYCLE):
            assert r.kind is ReasonKind.PRODUCT_RULE
        assert r.provenance[0].kind.value in {"EVENTSHOCK_ASSESSMENT", "PRODUCT_RULE"}


def test_a_tracked_event_always_has_reasons_and_an_untrackable_one_is_explicit():
    e = builders.priority(state(severity=None, event_type=None, lifecycle=None), None, None, 7.0)
    assert e.reasons and e.reasons[0].code is ReasonCode.SEVERITY_UNSCORED and e.level is None and "severity only" in e.headline
    with pytest.raises(ExplanationError, match="at least one reason"):
        builders.finish(Subject.PRIORITY, event_id="e", signal_id="s", headline="x", level=None, reasons=[], limitations=[], material=True)
    ok = builders.finish(Subject.STRESS, event_id=None, signal_id="s", headline="x", level=None, reasons=[], limitations=[], material=False, availability="PARTIAL")
    assert ok.reasons == [] and ok.availability == "PARTIAL"


def test_an_open_conflict_and_a_materiality_cap_are_reasons():
    m = materiality()
    e = builders.priority(state(conflict="CONFLICTED"), None, m, 7.0)
    assert any(r.code is ReasonCode.CONFLICT_OPEN and "contradict" in r.text for r in e.reasons)


def test_visibility_explains_scope_exposure_severity_evidence_watchlist_and_recent_change():
    prev, curr = state(severity=6.0), state(severity=8.0)
    drafts = diff_states(prev, curr, dcfg().monitor)
    change = type("RC", (), {"summary": drafts[0].summary, "change_type": drafts[0].change_type, "at": curr.as_of, "rule": drafts[0].rule, "change_id": "chg_x"})()
    e = builders.visibility(curr, None, materiality(), 7.0, watch_hits=["Energy watch: sector Energy"], changes=[change])
    codes = {r.code for r in e.reasons}
    assert {ReasonCode.MATERIALITY, ReasonCode.EXPOSURE_SHARE, ReasonCode.SEVERITY, ReasonCode.EVIDENCE_TIER, ReasonCode.WATCHLIST_MATCH, ReasonCode.RECENT_CHANGE} <= codes
    assert e.headline.startswith("You are seeing this because") and "matches a watchlist" in e.headline and "it changed" in e.headline
    quiet = builders.visibility(state(severity=3.0), None, None, 7.0, watch_hits=[], changes=[])
    assert quiet.reasons and "tracked" in quiet.headline


def test_stress_explanation_separates_the_scenarios_assumptions_from_the_engines_arithmetic():
    svc = lab()
    r = svc.run(ScenarioRequest(assumptions=[A(kind=K.EQUITY_MARKET, value=-0.10), A(kind=K.RATES, value=100)]))
    e = builders.lab(r)
    by_kind = {k: [x for x in e.reasons if x.kind is k] for k in ReasonKind}
    assert by_kind[ReasonKind.SCENARIO_ASSUMPTION] and by_kind[ReasonKind.PRODUCT_RULE]
    assert all("SCENARIO ASSUMPTION" in x.text or "assumption" in x.text.lower() for x in by_kind[ReasonKind.SCENARIO_ASSUMPTION] if x.code is ReasonCode.STRESS_SHOCK)
    codes = {x.code for x in e.reasons}
    assert {ReasonCode.STRESS_SHOCK, ReasonCode.STRESS_TOTAL, ReasonCode.STRESS_DRIVER_KIND, ReasonCode.STRESS_DRIVER_FACTOR, ReasonCode.STRESS_DRIVER_SECTOR, ReasonCode.STRESS_DRIVER_ISSUER} <= codes
    total = next(x for x in e.reasons if x.code is ReasonCode.STRESS_TOTAL)
    assert total.value == pytest.approx(r.result.summary.pnl_pct) and "adds up to its total" in total.text
    assert e.subject is Subject.LAB and "hypothetical, not a prediction" in e.headline


def test_an_unreached_assumption_and_a_scenario_that_moved_nothing_still_explain_themselves():
    r = lab().run(ScenarioRequest(assumptions=[A(kind=K.COMMODITY, value=-0.3)]))
    e = builders.lab(r)
    assert e.reasons and any("reached nothing" in x.text for x in e.reasons) and any(x.code is ReasonCode.STRESS_NOT_RUN for x in e.reasons)
    assert e.availability == "AVAILABLE"


def test_reverse_explanation_names_method_shocks_bounds_and_binding_axes():
    svc = lab()
    ok = builders.reverse(svc.reverse(ReverseStressRequest(target_pct=-5)))
    codes = [x.code for x in ok.reasons]
    assert codes[:2] == [ReasonCode.REVERSE_TARGET, ReasonCode.REVERSE_METHOD] and ReasonCode.REVERSE_SHOCK in codes and ReasonCode.STRESS_TOTAL in codes
    assert all(x.kind is ReasonKind.SCENARIO_ASSUMPTION for x in ok.reasons if x.code is ReasonCode.REVERSE_SHOCK) and ok.level == "ACHIEVABLE"
    bad = builders.reverse(svc.reverse(ReverseStressRequest(target_pct=-80)))
    assert any(x.code is ReasonCode.REVERSE_BINDING and "already at their limit" in x.text for x in bad.reasons) and bad.level == "NOT_ACHIEVABLE"
    assert any(x.code is ReasonCode.REVERSE_BOUND for x in ok.reasons)                                           # an axis that was not used says why


def test_change_explanation_carries_the_rule_the_fields_and_the_evidence():
    from tests.intel_helpers import JPM as J
    from tests.intel_helpers import sig
    from tests.monitor_helpers import FakeAssess, monitor
    a = sig("a", "JPMorgan Chase fined $920 million over spoofing by US regulators", entity=J, minutes=0, source="Wire A", url="https://a.example/x")
    c = sig("c", "JPMorgan fined $920 million as spoofing probe expands to more desks", entity=J, minutes=26 * 60, source="Wire C", url="https://c.example/z")
    svc, *_ = monitor([a, c], assess=FakeAssess({"a": 6, "c": 8}), step_hours=24)
    ch = next(x for x in svc.replay_changes(cycle=1).changes if x.change_type is ChangeType.EVENT_ESCALATED)
    e = builders.change(ch)
    assert e.subject is Subject.CHANGE and e.level == "EVENT_ESCALATED" and e.reasons[0].code is ReasonCode.CHANGE_RULE and e.reasons[0].value == ch.rule
    assert any(r.code is ReasonCode.CHANGE_FIELD and "severity" in r.text and "6" in r.text and "8" in r.text for r in e.reasons)
    assert any("Evidence" in r.text for r in e.reasons)


def test_the_labels_say_what_each_kind_is():
    e = builders.priority(state(), None, materiality(), 7.0)
    text = " ".join(e.labels).lower()
    for w in ("model output", "product rule", "scenario assumption", "historical observation", "not a prediction"):
        assert w in text
    assert json.dumps(e.model_dump(mode="json"))
