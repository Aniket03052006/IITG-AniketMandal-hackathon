"""Structured claims and contradiction: closed lexicon, negation, hedging, the time window, resolution, and no contradiction from tone alone."""

from __future__ import annotations

import pytest

from eventshock.intelligence.claims import ClaimExtractor, overall_state
from eventshock.intelligence.model import ConflictState as S
from tests.intel_helpers import CFG, rep

AUTH = {"sec.gov"}
X = ClaimExtractor(CFG.claims, AUTH)


def claims(*reports):  # noqa: ANN002, ANN201
    out = []
    for r in reports:
        out += X.extract(r, None, None)
    return out


def detect(*reports):  # noqa: ANN002, ANN201
    return X.detect(claims(*reports))


@pytest.mark.parametrize("axis,pos,neg", [
    ("confirmation", "Beta confirms takeover offer from Acme", "Beta denies takeover offer from Acme"),
    ("status", "Gulf refinery remains open after storm", "Gulf refinery shuts down after storm"),
    ("deal", "Acme completes acquisition of Beta", "Acme cancels acquisition of Beta"),
    ("operations", "Houston terminal resumes operations after storm", "Houston terminal halts operations after storm"),
    ("guidance", "Acme raises guidance for full year", "Acme cuts guidance for full year"),
    ("approval", "Regulator approves Acme Beta merger", "Regulator blocks Acme Beta merger"),
])
def test_every_axis_detects_an_explicit_contradiction(axis, pos, neg):
    conflicts, seq = detect(rep("A", pos, minutes=0), rep("B", neg, minutes=60))
    assert len(conflicts) == 1 and not seq
    c = conflicts[0]
    assert c.axis == axis and c.state is S.CONFLICTED
    assert {c.side_a.report_id, c.side_b.report_id} == {"A", "B"}
    assert c.side_a.polarity != c.side_b.polarity
    assert c.side_a.evidence_span.quote and c.side_b.evidence_span.quote  # both sides carry their verbatim clause


def test_claims_carry_subject_object_polarity_source_and_time():
    (c,) = claims(rep("A", "Acme confirms merger deal with Beta", minutes=5, source="Wire One"))
    assert (c.claim.subject, c.claim.object) == ("Acme", "merger deal with Beta")
    assert c.claim.polarity == "confirmed" and c.claim.source == "Wire One" and c.claim.axis == "confirmation"
    assert c.claim.published_at == rep("A", "x", minutes=5).published_at and not c.claim.attributed


def test_a_negated_cue_asserts_nothing():
    assert claims(rep("A", "Acme has not confirmed the merger talks")) == []
    assert claims(rep("A", "Beta did not deny the takeover offer")) == []


def test_a_hedged_claim_is_attributed_and_only_possible():
    conflicts, _ = detect(rep("A", "Acme reportedly confirms merger deal with Beta"), rep("B", "Acme denies merger deal with Beta", minutes=30))
    assert conflicts[0].state is S.POSSIBLE_CONFLICT and "hedged" in conflicts[0].reason


def test_the_same_outlet_reversing_itself_is_only_possible():
    conflicts, _ = detect(rep("A", "Acme confirms merger deal with Beta", source="Wire", domain="w.example"),
                          rep("B", "Acme denies merger deal with Beta", minutes=30, source="Wire", domain="w.example"))
    assert conflicts[0].state is S.POSSIBLE_CONFLICT and "same outlet" in conflicts[0].reason


def test_opposite_claims_beyond_the_window_are_a_change_of_state_not_a_contradiction():
    conflicts, seq = detect(rep("A", "Gulf refinery shuts down after storm", minutes=0),
                            rep("B", "Gulf refinery reopens after storm repairs", minutes=60 * 40))
    assert conflicts == [] and len(seq) == 1 and seq[0].state is S.NO_CONFLICT and "change of state" in seq[0].reason


def test_an_untrusted_clock_cannot_support_a_firm_contradiction():
    conflicts, _ = detect(rep("A", "Acme confirms merger deal with Beta", trusted=False), rep("B", "Acme denies merger deal with Beta", minutes=30, trusted=False))
    assert conflicts[0].state is S.POSSIBLE_CONFLICT and "not trusted" in conflicts[0].reason


def test_unrelated_topics_do_not_conflict():
    conflicts, _ = detect(rep("A", "Acme confirms merger deal with Beta"), rep("B", "Gamma denies layoff rumours in Ohio", minutes=30))
    assert conflicts == []


def test_a_later_authoritative_report_resolves_the_conflict():
    conflicts, _ = detect(rep("A", "Acme confirms merger deal with Beta", minutes=0), rep("B", "Acme denies merger deal with Beta", minutes=30),
                          rep("C", "Acme confirms merger deal with Beta in a filing", minutes=120, domain="sec.gov"))
    c = [c for c in conflicts if {c.side_a.report_id, c.side_b.report_id} == {"A", "B"}][0]
    assert c.state is S.RESOLVED_CONFLICT and c.resolved_by.report_id == "C" and "authoritative" in c.resolution
    assert overall_state(conflicts) is not S.CONFLICTED


def test_a_third_non_authoritative_outlet_does_not_settle_it():
    conflicts, _ = detect(rep("A", "Acme confirms merger deal with Beta", minutes=0), rep("B", "Acme denies merger deal with Beta", minutes=30),
                          rep("C", "Acme confirms merger deal with Beta again", minutes=120))
    assert overall_state(conflicts) is S.CONFLICTED  # counting outlets is not establishing truth


def test_an_explicit_retraction_resolves_it():
    conflicts, _ = detect(rep("A", "Acme confirms merger deal with Beta", minutes=0), rep("B", "Acme denies merger deal with Beta", minutes=30),
                          rep("C", "Correction: Acme confirms merger deal with Beta, outlet retracts earlier report", minutes=90))
    assert any(c.state is S.RESOLVED_CONFLICT for c in conflicts)


def test_opposite_tone_without_a_claim_is_no_contradiction():
    assert detect(rep("A", "Acme shares soar on stunning, wonderful news"), rep("B", "Acme shares plunge on dreadful, terrible news", minutes=10)) == ([], [])


def test_overall_state_is_the_most_serious_open_one():
    assert overall_state([]) is S.NO_CONFLICT


def test_a_report_recounting_a_change_of_state_does_not_take_a_side():
    """The false positive found in the replay pack: 'back online after the outage' (recovery) against 'recovers after a brief outage'."""
    conflicts, _ = detect(rep("A", "Facebook and Instagram back online after sudden US outage shocks thousands", minutes=0),
                          rep("B", "Facebook and Instagram recover after brief Sunday outage", minutes=30))
    assert conflicts == []
    both = detect(rep("A", "Plant halts production, then resumes operations within hours", minutes=0), rep("B", "Plant resumes operations after storm", minutes=10))
    assert both[0] == []  # the first report asserts both poles of the operations axis: it is a sequence, not a stance


def test_a_cue_in_a_background_clause_is_not_an_assertion():
    assert claims(rep("A", "Shares rose after the company denies the report")) == []
    assert len(claims(rep("A", "The company denies the report"))) == 1
