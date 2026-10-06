"""Event memory: every report is classified against the ones before it, by explicit rules, and a new article can only ever update an existing event."""

from __future__ import annotations

from eventshock.intelligence.lifecycle import LifecycleEngine
from eventshock.monitor.memory import classify_reports
from eventshock.monitor.models import UpdateKind as U
from tests.intel_helpers import CFG, rep
from tests.monitor_helpers import dcfg

ENGINE = LifecycleEngine(CFG.lifecycle, {"sec.gov"})
MEM = dcfg().memory
COPIES = {"SYNDICATED", "NEAR_DUPLICATE"}


def classify(*reports):  # noqa: ANN002, ANN201
    reports = sorted(reports, key=lambda r: (r.published_at, r.id))
    _, _, trans = ENGINE.run(reports, lambda t: False, max(r.published_at for r in reports))
    return classify_reports(reports, trans, MEM, COPIES)


def kinds(*reports):  # noqa: ANN002, ANN201
    return [c.kind for c in classify(*reports)]


def test_the_first_report_is_the_new_event():
    (c,) = classify(rep("A", "Acme fined $5 million over spoofing"))
    assert c.kind is U.NEW_EVENT and c.rule == "FIRST_REPORT"


def test_a_copy_of_an_earlier_report_is_a_continuation_never_a_risk_of_its_own():
    out = classify(rep("A", "Acme fined $5 million over spoofing"), rep("B", "Acme fined $5 million over spoofing", minutes=10, relation="SYNDICATED", independent=False))
    assert [c.kind for c in out] == [U.NEW_EVENT, U.CONTINUATION] and out[1].rule == "COPY:SYNDICATED"


def test_a_report_with_new_numbers_or_names_is_an_update():
    out = classify(rep("A", "Acme fined $5 million over spoofing"), rep("B", "Acme fined $5 million; Bluecoat Capital also named in the spoofing case", minutes=30))
    assert out[1].kind is U.UPDATE and out[1].rule.startswith("NEW_FACTS:") and "bluecoat" in out[1].detail.lower()


def test_more_of_the_same_is_a_continuation():
    out = classify(rep("A", "Acme fined $5 million over spoofing"), rep("B", "acme fined over spoofing", minutes=30))
    assert out[1].kind is U.CONTINUATION and out[1].rule == "SAME_COVERAGE"


def test_an_escalation_cue_classifies_the_report_that_carried_it_and_quotes_the_cue():
    out = classify(rep("A", "Acme fined $5 million over spoofing", minutes=0), rep("B", "Acme under probe, regulator says", minutes=20),
                   rep("C", "Acme spoofing probe expands to more desks", minutes=120))
    c = out[2]
    assert c.kind is U.ESCALATION and c.rule == "LIFECYCLE:ESCALATION_CUE" and "expands" in c.detail


def test_de_escalation_and_resolution_are_classified_from_their_cues():
    reports = [rep("A", "Acme fined $5 million over spoofing", minutes=0), rep("B", "Acme under probe, regulator says", minutes=20),
               rep("C", "Acme spoofing probe expands to more desks", minutes=120), rep("D", "Acme spoofing probe contained, regulator says", minutes=300)]
    assert kinds(*reports)[-1] is U.DE_ESCALATION
    reports += [rep("E", "Acme settlement reached with regulator, case resolved", minutes=600, domain="sec.gov"),
                rep("F", "Regulator says Acme case resolved", minutes=640)]
    assert U.RESOLUTION in kinds(*reports)


def test_a_report_is_classified_the_same_whether_or_not_later_reports_exist():
    early = [rep("A", "Acme fined $5 million over spoofing", minutes=0), rep("B", "Acme under probe, regulator says", minutes=20), rep("C", "Acme spoofing probe expands", minutes=120)]
    later = [*early, rep("D", "Acme also sued by shareholders over the $5 million fine", minutes=900)]
    assert [(c.report.id, c.kind, c.rule) for c in classify(*early)] == [(c.report.id, c.kind, c.rule) for c in classify(*later)][:3]


def test_classification_is_deterministic_and_input_order_does_not_matter():
    rs = [rep("A", "Acme fined $5 million over spoofing", minutes=0), rep("B", "Acme under probe, regulator says", minutes=20), rep("C", "Acme spoofing probe expands", minutes=120)]
    assert kinds(*rs) == kinds(*reversed(rs))
