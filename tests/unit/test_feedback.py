"""Analyst feedback: validated pairs, an append-only log that survives a restart, honest statistics, and nothing that changes a served output."""

from __future__ import annotations

from datetime import timedelta

import pytest

from eventshock.feedback import stats
from eventshock.feedback.models import LABEL, FeedbackInput, FeedbackType, FeedbackValue
from eventshock.feedback.service import FeedbackInvalid, FeedbackService
from eventshock.feedback.store import FeedbackLimit, FeedbackStore
from tests.intel_helpers import BASE, JPM, sig
from tests.monitor_helpers import FakeAssess, dcfg, monitor

R, S, E = FeedbackType.RELEVANCE, FeedbackType.SCOPE, FeedbackType.EVENT
V = FeedbackValue


def service(tmp_path, **kw):  # noqa: ANN001, ANN003, ANN201
    sigs = [sig("a", "JPMorgan Chase fined $920 million over spoofing", entity=JPM, minutes=0, source="Wire A", url="https://a.example/1")]
    mon, _, _ = monitor(sigs, assess=FakeAssess(default=6), tmp=tmp_path / "m")
    cfg = dcfg().feedback.model_copy(update=kw)
    ticks = iter(range(10_000))
    store = FeedbackStore(tmp_path / "fb" / "feedback.jsonl", max_records=cfg.max_records, clock=lambda: BASE + timedelta(minutes=next(ticks)))
    return FeedbackService(cfg, store, mon), mon.resolve_event("a").id


def put(svc, eid, t, v, **kw):  # noqa: ANN001, ANN003, ANN201
    return svc.submit(FeedbackInput(event_id=eid, type=t, value=v, **kw))


# -------------------------------------------------------------------------------------------------------------------------------- validation
@pytest.mark.parametrize("t,v", [(R, V.CORRECT), (R, V.INCORRECT), (S, V.RELEVANT), (S, V.PARTIALLY_RELEVANT), (E, V.IRRELEVANT)])
def test_a_value_must_belong_to_its_type(t, v):
    with pytest.raises(ValueError, match="is not a"):
        FeedbackInput(event_id="evt_1", type=t, value=v)


@pytest.mark.parametrize("t,v", [(R, V.RELEVANT), (R, V.PARTIALLY_RELEVANT), (R, V.IRRELEVANT), (S, V.CORRECT), (S, V.INCORRECT), (E, V.CORRECT), (E, V.INCORRECT)])
def test_every_documented_pair_is_accepted(t, v):
    assert FeedbackInput(event_id="evt_1", type=t, value=v).value is v


def test_feedback_is_recorded_with_id_event_analyst_type_value_timestamp_and_comment(tmp_path):
    svc, eid = service(tmp_path)
    fb = put(svc, eid, R, V.PARTIALLY_RELEVANT, comment="  holds some JPM but not this entity  ", analyst_id="priya")
    assert fb.feedback_id.startswith("fb_") and fb.event_id == eid and fb.analyst_id == "priya" and fb.type is R and fb.value is V.PARTIALLY_RELEVANT
    assert fb.comment == "holds some JPM but not this entity" and fb.created_at == BASE and fb.label == LABEL and "not ground truth" in fb.label


def test_an_event_can_be_named_by_a_signal_and_unknown_events_are_refused(tmp_path):
    svc, eid = service(tmp_path)
    assert put(svc, "a", S, V.CORRECT).event_id == eid                       # a signal id resolves to its event
    with pytest.raises(LookupError):
        put(svc, "evt_nope", S, V.CORRECT)
    assert len(svc.list().items) == 1                                          # nothing was recorded for a thing that does not exist


def test_analyst_id_comes_from_the_body_then_the_header_then_anonymous(tmp_path):
    svc, eid = service(tmp_path)
    assert svc.submit(FeedbackInput(event_id=eid, type=S, value=V.CORRECT, analyst_id="body"), header_analyst="header").analyst_id == "body"
    assert svc.submit(FeedbackInput(event_id=eid, type=S, value=V.CORRECT), header_analyst="header").analyst_id == "header"
    assert svc.submit(FeedbackInput(event_id=eid, type=S, value=V.CORRECT)).analyst_id == "anonymous"
    assert svc.submit(FeedbackInput(event_id=eid, type=S, value=V.CORRECT, analyst_id="  "), header_analyst="  ").analyst_id == "anonymous"


def test_a_comment_is_capped_and_blank_means_none(tmp_path):
    svc, eid = service(tmp_path, max_comment_chars=20)
    assert put(svc, eid, R, V.RELEVANT, comment="   ").comment is None
    assert put(svc, eid, R, V.RELEVANT, comment="x" * 20).comment == "x" * 20
    with pytest.raises(FeedbackInvalid, match="at most 20"):
        put(svc, eid, R, V.RELEVANT, comment="x" * 21)


# ----------------------------------------------------------------------------------------------------------------------------- persistence
def test_the_log_is_append_only_and_survives_a_restart(tmp_path):
    svc, eid = service(tmp_path)
    a = put(svc, eid, R, V.RELEVANT, analyst_id="a")
    b = put(svc, eid, S, V.INCORRECT, analyst_id="a", comment="wrong company")
    lines = (tmp_path / "fb" / "feedback.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and a.feedback_id in lines[0] and b.feedback_id in lines[1]
    reopened = FeedbackStore(tmp_path / "fb" / "feedback.jsonl", max_records=100)
    assert [f.feedback_id for f in reopened.all()] == [a.feedback_id, b.feedback_id] and reopened.all()[1].comment == "wrong company"
    reopened.add(event_id=eid, signal_id=None, analyst_id="c", type_=E, value=V.CORRECT, comment=None, portfolio_id=None, cycle=None)
    assert len((tmp_path / "fb" / "feedback.jsonl").read_text(encoding="utf-8").splitlines()) == 3     # earlier lines were not rewritten
    assert (tmp_path / "fb" / "feedback.jsonl").read_text(encoding="utf-8").startswith(lines[0])


def test_a_damaged_line_is_skipped_not_fatal_and_the_limit_is_enforced(tmp_path):
    p = tmp_path / "fb" / "feedback.jsonl"
    svc, eid = service(tmp_path)
    put(svc, eid, R, V.RELEVANT)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    again = FeedbackStore(p, max_records=2)
    assert len(again.all()) == 1
    again.add(event_id=eid, signal_id=None, analyst_id="x", type_=S, value=V.CORRECT, comment=None, portfolio_id=None, cycle=None)
    with pytest.raises(FeedbackLimit):
        again.add(event_id=eid, signal_id=None, analyst_id="x", type_=S, value=V.CORRECT, comment=None, portfolio_id=None, cycle=None)


# ------------------------------------------------------------------------------------------------------------------------------ statistics
def test_statistics_count_volume_and_agreement_per_type(tmp_path):
    svc, eid = service(tmp_path)
    for v in (V.RELEVANT, V.RELEVANT, V.PARTIALLY_RELEVANT, V.IRRELEVANT):
        put(svc, eid, R, v, analyst_id=f"a{v.value}{id(v)}")
    put(svc, eid, S, V.CORRECT, analyst_id="p")
    put(svc, eid, S, V.INCORRECT, analyst_id="q")
    put(svc, eid, E, V.CORRECT, analyst_id="p")
    st = svc.statistics()
    assert st.volume == 7 and st.events == 1 and st.label == LABEL and "not ground truth" in st.note.lower() and "does not learn" in st.note
    assert st.relevance.total == 4 and st.relevance.agreement == 0.5 and st.relevance.at_least_partly_relevant == 0.75 and st.relevance.by_value == {"IRRELEVANT": 1, "PARTIALLY_RELEVANT": 1, "RELEVANT": 2}
    assert st.scope.total == 2 and st.scope.agreement == 0.5 and st.event.total == 1 and st.event.agreement == 1.0
    assert st.first_at == BASE and st.last_at == BASE + timedelta(minutes=6) and st.analysts >= 3


def test_an_empty_log_has_no_percentages_rather_than_zero_agreement(tmp_path):
    st = service(tmp_path)[0].statistics()
    assert st.volume == 0 and st.relevance.agreement is None and st.scope.agreement is None and st.event.agreement is None and st.first_at is None and st.needs_review == 0


def test_needs_review_and_disagreements_read_each_analysts_latest_answer(tmp_path):
    svc, eid = service(tmp_path)
    put(svc, eid, S, V.INCORRECT, analyst_id="x")
    put(svc, eid, S, V.CORRECT, analyst_id="y")                               # two analysts disagree
    assert (svc.statistics().needs_review, svc.statistics().disagreements) == (1, 1)
    put(svc, eid, S, V.CORRECT, analyst_id="x")                               # x changes their mind: their latest answer is what counts
    assert (svc.statistics().needs_review, svc.statistics().disagreements) == (0, 0)
    put(svc, eid, R, V.IRRELEVANT, analyst_id="x")
    assert svc.statistics().needs_review == 1 and svc.statistics().disagreements == 0


def test_list_is_newest_first_filterable_and_capped(tmp_path):
    svc, eid = service(tmp_path, max_list=3)
    ids = [put(svc, eid, S, V.CORRECT, analyst_id=f"a{i}").feedback_id for i in range(5)]
    got = svc.list()
    assert got.total == 5 and [f.feedback_id for f in got.items] == ids[::-1][:3] and got.label == LABEL
    assert svc.list(event_id="a", limit=2).total == 5 and len(svc.list(event_id="a", limit=2).items) == 2
    assert svc.list(event_id="evt_other").total == 0


def test_the_statistics_module_is_pure_and_deterministic(tmp_path):
    svc, eid = service(tmp_path)
    for i in range(6):
        put(svc, eid, [R, S, E][i % 3], [V.RELEVANT, V.INCORRECT, V.CORRECT][i % 3], analyst_id=f"a{i}")
    items = svc._store.all()  # noqa: SLF001
    assert stats.compute(items).model_dump_json() == stats.compute(list(reversed(items))).model_dump_json()
