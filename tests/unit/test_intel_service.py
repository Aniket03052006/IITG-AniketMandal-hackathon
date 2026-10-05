"""The intelligence service end to end over small hand-built signal sets: grouping, evidence, novelty class, contradiction, lifecycle,
abstention, as-of invariance and the guarantee that nothing is written onto a signal."""

from __future__ import annotations

from datetime import timedelta

import pytest

from eventshock.domain import DedupRelation, TimestampOrigin
from eventshock.intelligence.model import Availability, ConflictState, ScopeType
from tests.intel_helpers import BASE, JPM, XOM, member, service, sig

SALE_A = "Exxon Mobil confirms $4 billion refinery sale to Valero"
SALE_B = "Exxon Mobil denies $4 billion refinery sale to Valero"


def get(svc, signals, sid, **kw):  # noqa: ANN001, ANN201
    return svc.for_signal(next(s for s in signals if s.id == sid), include_stress=False, **kw)


# -------------------------------------------------------------------------------------------------------------------- the event
def test_reports_group_into_one_event_with_independent_sources_counted():
    sigs = [sig("a", SALE_A.replace("confirms", "agrees"), entity=XOM, url="https://a.example/1",
                members=[member("Wire C", 10, "Exxon sells refinery for $4 billion", url="https://c.example/1"),
                         member("Wire B", 12, "Exxon sells refinery for $4 billion", url="https://b.example/1", relation=DedupRelation.SYNDICATED)]),
            sig("b", "Exxon Mobil agrees $4 billion refinery sale to Valero, sources say", entity=XOM, minutes=90, source="Wire D", url="https://d.example/1")]
    r = get(service(sigs), sigs, "b")
    assert r.group.report_count == 4 and r.group.independent_sources == 3
    assert r.group.signal_ids == ["a", "b"] and r.group.first_seen == BASE and r.group.last_seen == BASE + timedelta(minutes=90)
    assert [x.independent for x in r.group.reports] == [True, True, False, True]
    assert r.evidence.syndicated_copies == 1 and r.evidence.source_diversity == 0.75


def test_event_id_is_stable_and_anchored_to_the_earliest_report():
    sigs = [sig("a", SALE_A, entity=XOM), sig("b", SALE_A + ", sources say", entity=XOM, minutes=20, source="Wire B")]
    svc = service(sigs)
    assert get(svc, sigs, "a").group.event_id == get(svc, sigs, "b").group.event_id
    assert get(svc, sigs, "b").group.anchor_signal_id == "a"


# -------------------------------------------------------------------------------------------------------------------- evidence
def test_evidence_tiers_follow_named_rules_and_never_use_model_confidence():
    one = sig("a", "Zeta Corp loses a contract", entity=None)
    r1 = get(service([one]), [one], "a")
    assert r1.evidence.evidence_strength.tier == "INSUFFICIENT" and r1.evidence.evidence_strength.rule == "SINGLE_SOURCE"
    two = sig("a", "JPMorgan Chase fined $920 million", entity=JPM, url="https://a.example/1", members=[member("W", 5, "JPM fined $920 million", url="https://b.example/1")])
    assert get(service([two]), [two], "a").evidence.evidence_strength.tier == "MODERATE"
    four = sig("a", "JPMorgan Chase fined $920 million", entity=JPM, url="https://a.example/1",
               members=[member(f"W{i}", 5 + i, "JPM fined $920 million", url=f"https://{c}.example/1") for i, c in enumerate("bcd")])
    e = get(service([four]), [four], "a").evidence
    assert e.evidence_strength.tier == "STRONG" and e.independent_sources == 4
    assert not any("confidence" in k for k in e.evidence_strength.components)  # model confidence is a separate list
    assert {m.stage for m in e.model_confidence} == {"event", "sentiment", "impact"}


def test_many_copies_do_not_make_a_strong_event():
    s = sig("a", "JPMorgan Chase fined $920 million", entity=JPM, url="https://a.example/1",
            members=[member(f"W{i}", i, "JPMorgan Chase fined $920 million", url=f"https://c{i}.example/1", relation=DedupRelation.SYNDICATED) for i in range(6)])
    e = get(service([s]), [s], "a").evidence
    assert e.independent_sources == 1 and e.syndicated_copies == 6 and e.evidence_strength.tier == "INSUFFICIENT"


def test_authoritative_sources_are_counted_from_the_closed_list():
    s = sig("a", "Exxon Mobil discloses $4 billion refinery sale", entity=XOM, url="https://www.sec.gov/Archives/x")
    e = get(service([s]), [s], "a").evidence
    assert e.authoritative_sources == 1 and e.authoritative_supported and e.evidence_strength.tier == "WEAK"
    plain = sig("b", "Exxon Mobil discloses $4 billion refinery sale", entity=XOM, url="https://blog.example/x")
    assert not get(service([plain]), [plain], "b").evidence.authoritative_supported


# ---------------------------------------------------------------------------------------------------------------- contradiction
def test_contradicting_reports_surface_both_sides_and_cap_the_evidence():
    sigs = [sig("a", SALE_A, entity=XOM, url="https://a.example/1"), sig("b", SALE_B, entity=XOM, minutes=60, source="Wire B", url="https://b.example/1"),
            sig("c", "Exxon Mobil refinery sale to Valero for $4 billion draws scrutiny", entity=XOM, minutes=70, source="Wire C", url="https://c.example/1"),
            sig("d", "Exxon Mobil $4 billion refinery sale to Valero: what we know", entity=XOM, minutes=80, source="Wire D", url="https://d.example/1")]
    r = get(service(sigs), sigs, "a")
    assert r.contradiction.state is ConflictState.CONFLICTED and r.evidence.source_disagreement == "CONFLICTED"
    c = r.contradiction.conflicts[0]
    assert {c.side_a.polarity, c.side_b.polarity} == {"confirmed", "denied"} and c.side_a.source != c.side_b.source
    assert r.evidence.evidence_strength.tier == "WEAK" and "capped" in " ".join(r.evidence.evidence_strength.reasons)
    assert r.lifecycle.state.value == "DEVELOPING"  # an open contradiction blocks confirmation


def test_opposite_tone_alone_is_not_a_contradiction():
    sigs = [sig("a", "Exxon Mobil shares soar on stellar quarter, $4 billion buyback", entity=XOM, sentiment_negative=0.05),
            sig("b", "Exxon Mobil shares soar on quarter, $4 billion buyback; analysts gloomy", entity=XOM, minutes=30, source="Wire B", sentiment_negative=0.9)]
    r = get(service(sigs), sigs, "a")
    assert r.contradiction.state is ConflictState.NO_CONFLICT and r.evidence.source_disagreement == "NONE"
    assert r.contradiction.availability is Availability.PARTIAL and "absence of evidence" in r.contradiction.reason


# ------------------------------------------------------------------------------------------------------------------------ novelty
PRIOR = "JPMorgan Chase faces regulatory probe over trading practices"


def novelty_of(current, *, prior_minutes=-4000, **kw):  # noqa: ANN001, ANN201
    prior = sig("p", PRIOR, entity=JPM, minutes=prior_minutes, source="Wire P", url="https://p.example/1", **kw)
    cur = sig("c", current, entity=JPM, minutes=0, url="https://c.example/1")
    return get(service([prior, cur]), [prior, cur], "c").novelty


def test_new_when_nothing_earlier_matches():
    s = sig("c", PRIOR, entity=JPM)
    n = get(service([s]), [s], "c").novelty
    assert n.label == "NEW" and n.rule == "NO_PRIOR" and n.nearest_prior == []


def test_continuation_when_the_same_narrative_adds_nothing():
    n = novelty_of("JPMorgan Chase regulatory probe over trading practices continues")
    assert n.label == "CONTINUATION" and n.narrative_match is True and n.new_information == []
    assert n.nearest_prior[0].signal_id == "p" and n.nearest_prior[0].similarity >= 0.3


def test_update_when_the_same_narrative_carries_new_facts():
    n = novelty_of("JPMorgan Chase regulatory probe over trading practices: fine of $2 billion proposed")
    assert n.label == "UPDATE" and "$2billion" in n.new_information


def test_a_second_investigation_is_a_recurrence_not_a_new_event():
    n = novelty_of("JPMorgan Chase faces another regulatory probe over trading practices")
    assert n.label == "RECURRING" and "another" in n.recurrence_cues


def test_a_prior_that_went_quiet_long_ago_makes_it_recurring():
    n = novelty_of("JPMorgan Chase regulatory probe over trading practices continues", prior_minutes=-60 * 24 * 12)
    assert n.label == "RECURRING"


def test_a_different_narrative_for_the_same_issuer_is_new():
    n = novelty_of("JPMorgan Chase opens new wealth management office in Singapore")
    assert n.label == "NEW" and n.narrative_match is False and n.rule == "DIFFERENT_NARRATIVE"


def test_novelty_is_unknown_when_there_is_no_subject_or_no_clock():
    s = sig("c", "Something happened somewhere today")
    n = get(service([s]), [s], "c").novelty
    assert n.label == "UNKNOWN" and n.availability is Availability.ABSTAINED
    u = sig("u", PRIOR, entity=JPM, origin=TimestampOrigin.SYNTHETIC_REPLAY_CLOCK)
    nu = get(service([u]), [u], "u").novelty
    assert nu.label == "UNKNOWN" and nu.availability is Availability.UNAVAILABLE


def test_the_pipeline_novelty_score_is_reported_unchanged_beside_the_label():
    prior = sig("p", PRIOR, entity=JPM, minutes=-4000)
    cur = sig("c", PRIOR + " continues", entity=JPM)
    cur = cur.model_copy(update={"evidence": cur.evidence.model_copy(update={"novelty_score": 0.5, "novelty_measured": True})})
    assert get(service([prior, cur]), [prior, cur], "c").novelty.novelty_score == 0.5


# -------------------------------------------------------------------------------------------------------- abstention and scope
def test_an_unresolved_event_abstains_field_by_field_with_reasons():
    s = sig("a", "Local festival draws record crowds")
    r = get(service([s]), [s], "a")
    fields = {a.field: a for a in r.abstentions}
    assert r.scope.scope_type is ScopeType.UNRESOLVED
    assert fields["company"].state == "UNKNOWN" and fields["sector"].state == "UNKNOWN" and "not guessed" in fields["scope"].reason
    assert fields["novelty"].state == "ABSTAINED"


def test_untrusted_clock_makes_time_dependent_sections_unavailable():
    s = sig("a", PRIOR, entity=JPM, origin=TimestampOrigin.SYNTHETIC_REPLAY_CLOCK)
    r = get(service([s]), [s], "a")
    assert r.velocity.availability is Availability.UNAVAILABLE and r.lifecycle.availability is Availability.UNAVAILABLE and r.lifecycle.state is None
    assert not r.provenance.clock_trusted and "timestamps were assigned" in " ".join(r.evidence.evidence_strength.reasons)


# ------------------------------------------------------------------------------------------------------------ as-of and purity
def story():  # noqa: ANN201
    return [sig("a", "Exxon Mobil refinery fire halts output, $4 billion plant", entity=XOM, url="https://a.example/1"),
            sig("b", "Exxon Mobil refinery fire at $4 billion plant widens", entity=XOM, minutes=60, source="Wire B", url="https://b.example/1"),
            sig("c", "Exxon Mobil refinery fire at $4 billion plant: output resumes", entity=XOM, minutes=600, source="Wire C", url="https://c.example/1")]


def test_everything_is_computed_from_reports_at_or_before_as_of():
    sigs = story()
    svc = service(sigs)
    early = get(svc, sigs, "a", as_of=BASE + timedelta(minutes=90))
    assert early.group.report_count == 2 and early.as_of_basis == "REQUESTED"
    late = get(svc, sigs, "a")
    assert late.group.report_count == 3 and late.as_of_basis == "LAST_REPORT"
    n = len(early.lifecycle.transitions)
    assert [(t.at, t.to_state) for t in late.lifecycle.transitions[:n]] == [(t.at, t.to_state) for t in early.lifecycle.transitions]
    assert early.velocity.window_end <= BASE + timedelta(minutes=90) and early.evidence.latest_observed <= BASE + timedelta(minutes=90)


def test_as_of_before_the_first_report_is_refused():
    sigs = story()
    with pytest.raises(ValueError, match="precedes"):
        get(service(sigs), sigs, "a", as_of=BASE - timedelta(hours=1))


def test_the_service_writes_nothing_onto_a_signal():
    sigs = story()
    before = [s.model_dump(mode="json") for s in sigs]
    svc = service(sigs)
    for s in sigs:
        svc.for_signal(s, include_stress=False)
        svc.scope_of(s)
    assert [s.model_dump(mode="json") for s in sigs] == before


def test_results_are_deterministic():
    sigs = story()
    a = get(service(sigs), sigs, "b").model_dump(mode="json")
    b = get(service(list(reversed(sigs))), sigs, "b").model_dump(mode="json")
    assert a == b
