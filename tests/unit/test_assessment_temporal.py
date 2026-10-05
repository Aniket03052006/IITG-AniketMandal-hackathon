"""Temporal integrity: the severity score reads only what existed when the report appeared. Later coverage, later filings and the realised move may be
SHOWN (audit) but cannot change the score."""

from __future__ import annotations

from datetime import timedelta

from eventshock.api.schemas import FilingMoment, RealisedOutcome, SignalContext
from eventshock.assessment.model import Phase
from eventshock.assessment.views import build_timeline
from tests.assess_helpers import service, signal_for, with_later_reports
from tests.fakes import REGULATORY
from tests.helpers import NOW


def test_later_reports_do_not_change_the_score() -> None:
    s = signal_for(REGULATORY)
    later = with_later_reports(s, 6)
    a0, a1 = service([s]).assess(s), service([later]).assess(later)
    assert a1.later_reports_excluded == 6 and a1.corroborating_at_event_time == 0
    assert a0.severity.points == a1.severity.points and a0.severity.score == a1.severity.score
    assert [st.model_dump() for st in a0.severity.steps] == [st.model_dump() for st in a1.severity.steps]
    assert a0.severity.reliability == a1.severity.reliability, "later coverage must not even change the reliability line"


def test_reports_that_existed_at_the_time_raise_reliability_but_never_the_severity() -> None:
    s = signal_for(REGULATORY)
    t0 = s.document.published_at
    from eventshock.domain import CorroboratingSource, SourceType

    before = [CorroboratingSource(source=f"Early{i}", source_type=SourceType.NEWS, published_at=t0 - timedelta(hours=i + 1), headline="h") for i in range(3)]
    ev = s.evidence.model_copy(update={"corroborating": before, "source_count": 4})
    s2 = s.model_copy(update={"evidence": ev})
    a, base = service([s2]).assess(s2), service([s]).assess(s)
    assert a.corroborating_at_event_time == 3
    assert a.severity.reliability.score > base.severity.reliability.score
    assert (a.severity.score, a.severity.points) == (base.severity.score, base.severity.points), "corroboration is reliability, not severity"


def test_nothing_that_could_only_be_known_later_is_a_score_input() -> None:
    a = service([signal_for(REGULATORY)]).assess(signal_for(REGULATORY))
    ids = {st.id for st in a.severity.steps} | {o.id for o in a.severity.omitted}
    assert ids <= {"matrix", "certainty", "direction", "regime", "novelty", "clamp"}
    assert not ({"outcome", "later_coverage", "filings_after", "realised", "source_count"} & ids)


def _ctx(s) -> SignalContext:
    t0 = s.document.published_at
    return SignalContext(
        signal_id=s.id, report_time=t0, timestamp_origin="SOURCE", assessed_at=NOW, impact_scored=False, inputs=[], missing_inputs=[], not_used=[],
        filings=[FilingMoment(accession="a1", form="8-K", items=["2.02"], acceptance_utc=t0 + timedelta(hours=2), hours_from_report=2.0,
                              role="AFTER_REPORT", role_note="after", known_at_assessment=False),
                 FilingMoment(accession="a0", form="8-K", items=["7.01"], acceptance_utc=t0 - timedelta(hours=30), hours_from_report=-30.0,
                              role="BEFORE_NOT_USED", role_note="before", known_at_assessment=True)],
        filings_note=None,
        outcome=RealisedOutcome(scope="ISSUER", ticker="X", session="2026-10-02", window_sessions=2, abs_z=3.1, z=-3.1, score=8, note="the move"),
        outcome_note="realised")


def test_the_timeline_separates_what_was_known_from_what_came_later() -> None:
    s = with_later_reports(signal_for(REGULATORY), 2)
    a = service([s]).assess(s)
    tl = build_timeline(s, a, _ctx(s), NOW)
    after = [i for i in tl.items if i.phase is Phase.AFTER_REPORT]
    assert {i.kind for i in after} == {"FILING", "CORROBORATION", "OUTCOME"}
    assert all(not i.used_in_severity for i in after), "nothing after the report may be marked as used by the score"
    assert not any(i.used_in_severity for i in tl.items if i.kind in {"FILING", "OUTCOME"}), "filings are read only by the reference model"
    report = next(i for i in tl.items if i.kind == "REPORT")
    assert report.used_in_severity and report.phase is Phase.AT_REPORT
    order = [i.phase for i in tl.items]
    assert order == sorted(order, key=lambda p: ["BEFORE_REPORT", "AT_REPORT", "AFTER_REPORT"].index(p.value))
    assert any("realised" in e.lower() for e in tl.excluded) and any("later coverage" in e.lower() for e in tl.excluded)
    outcome = next(i for i in tl.items if i.kind == "OUTCOME")
    assert outcome.number_kind.value == "REALISED" and outcome.known_at_assessment is False


def test_an_unchanged_signal_gives_the_same_assessment() -> None:
    s = signal_for(REGULATORY)
    assert service([s]).assess(s).model_dump() == service([s]).assess(s).model_dump()
