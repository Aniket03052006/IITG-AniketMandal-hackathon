"""The analyst review queue: named rules, an ordered (not scored) list, decisions kept append-only, reopening on changed evidence, and nothing that changes a served output."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from eventshock.monitor.models import Mode, MonitorCycle
from eventshock.monitor.service import CycleStates
from eventshock.review import rules
from eventshock.review.models import LABEL, ReasonCode, ReviewDecisionInput, ReviewStatus
from eventshock.review.service import ReviewInvalid, ReviewService
from eventshock.review.store import ReviewLimit, ReviewStore
from tests.intel_helpers import BASE
from tests.monitor_helpers import dcfg, state

CFG = dcfg().review
R = ReasonCode


def codes(st) -> list[ReasonCode]:  # noqa: ANN001
    return [r.code for r in rules.evaluate(st, CFG)]


# ------------------------------------------------------------------------------------------------------------------------------------ rules
def test_a_quiet_event_has_no_reason() -> None:
    assert codes(state(severity=4.0, materiality="LOW", independent_sources=3, conflict="NO_CONFLICT")) == []


@pytest.mark.parametrize("conflict,fires", [("CONFLICTED", True), ("POSSIBLE_CONFLICT", True), ("RESOLVED_CONFLICT", False), ("NO_CONFLICT", False)])
def test_conflicting_claims_queue_an_event_but_a_resolved_one_does_not(conflict, fires) -> None:
    assert (R.CONFLICTED_CLAIMS in codes(state(conflict=conflict, severity=3.0, materiality="LOW", independent_sources=3))) is fires


def test_a_high_severity_text_with_no_resolved_subject_is_queued_at_the_configured_floor_and_not_below() -> None:
    assert R.UNRESOLVED_HIGH_SEVERITY in codes(state(scope_type="UNRESOLVED", scope_value=None, severity=CFG.unresolved_min_severity, independent_sources=3, materiality="LOW"))
    assert R.UNRESOLVED_HIGH_SEVERITY not in codes(state(scope_type="UNRESOLVED", scope_value=None, severity=CFG.unresolved_min_severity - 0.5, independent_sources=3, materiality="LOW"))
    assert R.UNRESOLVED_HIGH_SEVERITY not in codes(state(scope_type="COMPANY", severity=9.0, independent_sources=3, materiality="LOW"))  # a resolved subject is not this rule


def test_a_high_severity_event_with_one_independent_source_is_queued_but_corroboration_clears_it() -> None:
    assert R.SINGLE_SOURCE_HIGH_SEVERITY in codes(state(severity=8.0, independent_sources=1, materiality="LOW"))
    assert R.SINGLE_SOURCE_HIGH_SEVERITY not in codes(state(severity=8.0, independent_sources=2, materiality="LOW"))
    assert R.SINGLE_SOURCE_HIGH_SEVERITY not in codes(state(severity=CFG.single_source_min_severity - 1, independent_sources=1, materiality="LOW"))


@pytest.mark.parametrize("level,fires", [("CRITICAL", True), ("HIGH", True), ("MEDIUM", False), ("LOW", False), ("NONE", False), (None, False)])
def test_materiality_to_the_book_queues_only_the_configured_levels(level, fires) -> None:
    assert (R.MATERIAL_TO_BOOK in codes(state(severity=4.0, materiality=level, independent_sources=3))) is fires


def test_a_large_modeled_loss_is_queued_at_the_floor_and_a_gain_or_a_missing_run_is_not() -> None:
    q = dict(severity=4.0, materiality="LOW", independent_sources=3)
    assert R.LARGE_STRESS_LOSS in codes(state(stress_pnl_pct=CFG.stress_loss_floor, **q))
    assert R.LARGE_STRESS_LOSS not in codes(state(stress_pnl_pct=CFG.stress_loss_floor / 2, **q))
    assert R.LARGE_STRESS_LOSS not in codes(state(stress_pnl_pct=0.03, **q))
    assert R.LARGE_STRESS_LOSS not in codes(state(stress_pnl_pct=None, **q))


def test_an_escalating_event_is_queued() -> None:
    assert codes(state(lifecycle="ESCALATING", severity=4.0, materiality="LOW", independent_sources=3)) == [R.ESCALATING]


def test_every_reason_names_the_values_that_fired_it_and_the_catalogue_covers_every_code() -> None:
    fired = rules.evaluate(state(severity=8.0, independent_sources=1, materiality="HIGH", exposure_share=0.31, conflict="CONFLICTED", stress_pnl_pct=-0.04, lifecycle="ESCALATING"), CFG)
    assert [r.code for r in fired] == [R.CONFLICTED_CLAIMS, R.SINGLE_SOURCE_HIGH_SEVERITY, R.MATERIAL_TO_BOOK, R.LARGE_STRESS_LOSS, R.ESCALATING]
    assert all(r.detail and r.label for r in fired)
    assert "31.0% of the book" in fired[2].detail and "-4.00%" in fired[3].detail and "simulation" in fired[3].detail
    assert {c.code for c in rules.rule_catalogue(CFG)} == set(ReasonCode)


def test_a_null_severity_never_raises_a_severity_rule() -> None:
    assert codes(state(severity=None, scope_type="UNRESOLVED", independent_sources=1, materiality=None, conflict="NO_CONFLICT")) == []


def test_the_fingerprint_ignores_the_book_and_notices_new_evidence() -> None:
    a = state(portfolio_id="pf_a", materiality="HIGH", exposure_share=0.3, stress_pnl_pct=-0.05)
    b = state(portfolio_id="pf_b", materiality="LOW", exposure_share=0.0, stress_pnl_pct=None)
    assert rules.intrinsic_fingerprint(a) == rules.intrinsic_fingerprint(b)  # reading the same event against another book is not a change
    for change in (dict(report_count=2), dict(independent_sources=2), dict(severity=7.0), dict(lifecycle="ESCALATING"), dict(evidence_tier="STRONG"), dict(conflict="CONFLICTED"), dict(lead_signal_id="z")):
        assert rules.intrinsic_fingerprint(state(**change)) != rules.intrinsic_fingerprint(a), change


# ------------------------------------------------------------------------------------------------------------------------------- the service
class FakeMonitor:
    """The little of the monitor the queue reads: tracked states at a replay cycle, the live states, event ids and the live status."""

    def __init__(self, replay=None, live=None, live_reason="the live feed is off") -> None:  # noqa: ANN001
        self.replay, self.live, self.live_reason = replay or [], live or [], live_reason
        self.cycle = MonitorCycle(index=3, at=BASE + timedelta(hours=36), baseline=False)

    def replay_states(self, cycle, portfolio=None):  # noqa: ANN001, ANN201
        if not self.replay and self.replay is None:
            raise LookupError("no cycles")
        return self.cycle, CycleStates(states={s.event_id: s for s in self.replay}, built=len(self.replay), untracked=0, truncated=False, excluded_untrusted=0)

    def live_states(self):  # noqa: ANN201
        return {s.event_id: s for s in self.live}

    def status(self, mode):  # noqa: ANN001, ANN201
        return SimpleNamespace(reason=self.live_reason)

    def resolve_event(self, ident):  # noqa: ANN001, ANN201
        for s in self.replay + self.live:
            if ident in (s.event_id, s.anchor_signal_id, s.lead_signal_id):
                return SimpleNamespace(id=s.event_id)
        raise LookupError(f"no event or signal {ident!r}")


def make(tmp_path, replay, live=None, **kw):  # noqa: ANN001, ANN003, ANN201
    ticks = iter(range(10_000))
    store = ReviewStore(tmp_path / "rv" / "decisions.jsonl", max_records=kw.pop("max_records", 100), clock=lambda: BASE + timedelta(minutes=next(ticks)))
    cfg = dcfg()
    if kw:
        cfg = cfg.model_copy(update={"review": cfg.review.model_copy(update=kw)})
    mon = FakeMonitor(replay, live)
    return ReviewService(cfg, store, mon, clock=lambda: BASE + timedelta(days=2)), mon


A = state(event_id="evt_a", anchor_signal_id="a", lead_signal_id="a", headline="Strait of Hormuz closed", severity=8.0, independent_sources=1, materiality="HIGH", exposure_share=0.3,
          last_seen=BASE + timedelta(hours=30))
B = state(event_id="evt_b", anchor_signal_id="b", lead_signal_id="b", headline="Bank denies funding rumour", severity=5.0, independent_sources=3, materiality="LOW", conflict="CONFLICTED",
          last_seen=BASE + timedelta(hours=35))
C = state(event_id="evt_c", anchor_signal_id="c", lead_signal_id="c", headline="Quarterly dividend declared", severity=3.0, independent_sources=4, materiality="LOW")  # nothing to review


def test_only_events_with_a_reason_are_queued_and_the_queue_says_how_it_ordered_them(tmp_path) -> None:
    svc, _ = make(tmp_path, [C, B, A])
    q = svc.queue()
    assert q.availability == "AVAILABLE" and q.label == LABEL and q.mode is Mode.REPLAY and q.as_of == BASE + timedelta(hours=36)
    assert [i.event_id for i in q.items] == ["evt_a", "evt_b"]  # HIGH materiality first; the dividend has no reason
    assert q.counts.model_dump() == {"open": 2, "reviewed": 0, "dismissed": 0, "in_queue": 2, "tracked_events": 3}
    first = q.items[0]
    assert [r.code for r in first.reasons] == [R.SINGLE_SOURCE_HIGH_SEVERITY, R.MATERIAL_TO_BOOK]
    assert [p.name for p in first.rank_key] == ["portfolio materiality tier", "severity", "rules fired", "last reported", "id"] and first.rank_key[0].value == "HIGH"
    assert "not scored" in q.ranking and len(q.rules) == len(ReasonCode) and q.limitations


def test_the_order_is_materiality_then_severity_then_rules_fired_then_recency_then_id(tmp_path) -> None:
    mk = lambda eid, **kw: state(event_id=eid, anchor_signal_id=eid, lead_signal_id=eid, independent_sources=3, **kw)  # noqa: E731
    pool = [
        mk("evt_1", materiality="HIGH", severity=6.0), mk("evt_2", materiality="CRITICAL", severity=3.0), mk("evt_3", materiality="HIGH", severity=9.0),
        mk("evt_4", materiality="HIGH", severity=9.0, lifecycle="ESCALATING"), mk("evt_5", materiality="HIGH", severity=9.0, lifecycle="ESCALATING", last_seen=BASE + timedelta(hours=1)),
        mk("evt_6", materiality="HIGH", severity=9.0, lifecycle="ESCALATING", last_seen=BASE + timedelta(hours=1)),
    ]
    q = make(tmp_path, pool)[0].queue()
    assert [i.event_id for i in q.items] == ["evt_2", "evt_5", "evt_6", "evt_4", "evt_3", "evt_1"]  # CRITICAL; then HIGH by severity, rules fired, newest, id
    assert make(tmp_path / "again", list(reversed(pool)))[0].queue().items[0].event_id == "evt_2"  # input order does not matter


def test_a_decision_moves_an_event_out_of_the_open_list_and_the_counts_follow(tmp_path) -> None:
    svc, _ = make(tmp_path, [B, A])
    d = svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.REVIEWED, note="  confirmed with desk  ", analyst_id="priya"))
    assert d.decision_id.startswith("rv_") and d.event_id == "evt_a" and d.analyst_id == "priya" and d.note == "confirmed with desk" and d.headline == A.headline and d.label == LABEL
    svc.decide(ReviewDecisionInput(event_id="b", status=ReviewStatus.DISMISSED))  # a signal id resolves to its event
    q = svc.queue()
    assert q.items == [] and q.counts.model_dump() == {"open": 0, "reviewed": 1, "dismissed": 1, "in_queue": 2, "tracked_events": 2}
    rev = svc.queue(status="REVIEWED").items
    assert [i.event_id for i in rev] == ["evt_a"] and rev[0].status is ReviewStatus.REVIEWED and rev[0].decision.note == "confirmed with desk" and not rev[0].changed_since_review
    assert [i.event_id for i in svc.queue(status="all").items] == ["evt_a", "evt_b"] and svc.queue(status="DISMISSED").items[0].event_id == "evt_b"


def test_a_decision_can_be_reversed_by_reopening_and_history_keeps_every_step(tmp_path) -> None:
    svc, _ = make(tmp_path, [A])
    svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.DISMISSED, note="noise"))
    svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.OPEN, note="actually no"))
    assert [i.event_id for i in svc.queue().items] == ["evt_a"] and svc.queue().items[0].decision.status is ReviewStatus.OPEN
    hist = svc.history("evt_a")
    assert hist.total == 2 and [d.status for d in hist.items] == [ReviewStatus.OPEN, ReviewStatus.DISMISSED]  # newest first, nothing overwritten


def test_history_is_newest_first_by_recording_order_even_when_the_timestamps_tie(tmp_path) -> None:
    store = ReviewStore(tmp_path / "rv" / "d.jsonl", max_records=100, clock=lambda: BASE)  # the same instant for every decision
    svc = ReviewService(dcfg(), store, FakeMonitor([A]))
    for st in (ReviewStatus.REVIEWED, ReviewStatus.DISMISSED, ReviewStatus.OPEN):
        svc.decide(ReviewDecisionInput(event_id="evt_a", status=st))
    assert [d.status for d in svc.history("evt_a").items] == [ReviewStatus.OPEN, ReviewStatus.DISMISSED, ReviewStatus.REVIEWED]
    assert svc.queue().items[0].decision.status is ReviewStatus.OPEN  # and the current decision is the last recorded


def test_an_event_whose_own_evidence_changed_reopens_with_a_reason_and_a_change_of_book_does_not(tmp_path) -> None:
    svc, mon = make(tmp_path, [A])
    svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.REVIEWED))
    other_book = state(**{**A.model_dump(), "portfolio_id": "pf_other", "materiality": "CRITICAL", "exposure_share": 0.9})
    mon.replay = [other_book]
    assert svc.queue().items == [] and svc.queue(status="REVIEWED").items[0].event_id == "evt_a"  # the same event read against another book stays reviewed
    mon.replay = [state(**{**A.model_dump(), "report_count": 4, "independent_sources": 2})]  # two more reports and a second source
    q = svc.queue()
    item = q.items[0]
    assert item.status is ReviewStatus.OPEN and item.changed_since_review and item.decision.status is ReviewStatus.REVIEWED
    assert item.reasons[-1].code is R.CHANGED_SINCE_REVIEW and "reviewed" in item.reasons[-1].detail and "changed" in item.reasons[-1].detail
    assert q.counts.open == 1 and q.counts.reviewed == 0


def test_a_reviewed_event_stays_listed_even_when_no_rule_fires_any_more(tmp_path) -> None:
    only_the_book = state(event_id="evt_d", anchor_signal_id="d", lead_signal_id="d", severity=4.0, independent_sources=3, materiality="HIGH")  # only MATERIAL_TO_BOOK fires
    svc, mon = make(tmp_path, [only_the_book])
    svc.decide(ReviewDecisionInput(event_id="evt_d", status=ReviewStatus.REVIEWED))
    mon.replay = [state(**{**only_the_book.model_dump(), "materiality": "LOW"})]  # its own evidence is unchanged; the book no longer cares
    item = svc.queue(status="REVIEWED").items[0]
    assert item.event_id == "evt_d" and item.reasons == [] and not item.changed_since_review
    assert svc.queue().items == []  # and it is not open


def test_the_cap_limits_the_items_but_not_the_counts(tmp_path) -> None:
    pool = [state(event_id=f"evt_{i}", anchor_signal_id=f"s{i}", lead_signal_id=f"s{i}", materiality="HIGH", independent_sources=3, severity=5.0) for i in range(5)]
    svc, _ = make(tmp_path, pool, max_items=3)
    q = svc.queue()
    assert len(q.items) == 3 and q.matching == 5 and q.counts.open == 5
    assert len(svc.queue(limit=2).items) == 2 and len(svc.queue(limit=50).items) == 3  # a request cannot exceed the configured maximum


def test_bad_input_is_refused_and_nothing_is_recorded_for_it(tmp_path) -> None:
    svc, _ = make(tmp_path, [A], max_note_chars=10)
    with pytest.raises(ReviewInvalid, match="at most 10"):
        svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.REVIEWED, note="x" * 11))
    with pytest.raises(LookupError):
        svc.decide(ReviewDecisionInput(event_id="evt_nope", status=ReviewStatus.REVIEWED))
    with pytest.raises(ReviewInvalid, match="status must be"):
        svc.queue(status="DONE")
    with pytest.raises(ValueError):
        ReviewDecisionInput(event_id="evt_a", status="MAYBE")
    assert svc.history().total == 0


def test_an_event_the_monitor_does_not_track_cannot_be_decided(tmp_path) -> None:
    svc, mon = make(tmp_path, [A])
    mon.replay = []
    mon.resolve_event = lambda ident: SimpleNamespace(id="evt_a")  # type: ignore[method-assign]
    with pytest.raises(LookupError, match="not tracked"):
        svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.REVIEWED))


def test_live_mode_reads_the_live_states_and_says_why_when_there_are_none(tmp_path) -> None:
    svc, _ = make(tmp_path, [A], live=[B])
    live = svc.queue(mode=Mode.LIVE)
    assert live.mode is Mode.LIVE and [i.event_id for i in live.items] == ["evt_b"] and live.as_of == BASE + timedelta(days=2)
    off, _ = make(tmp_path / "off", [A])
    q = off.queue(mode=Mode.LIVE)
    assert q.availability == "UNAVAILABLE" and q.reason == "the live feed is off" and q.items == [] and q.counts.in_queue == 0
    assert [i.event_id for i in off.queue(mode=Mode.REPLAY).items] == ["evt_a"]  # REPLAY never depends on the live feed


def test_the_decisions_survive_a_restart_and_a_damaged_line_is_skipped(tmp_path) -> None:
    svc, _ = make(tmp_path, [A])
    svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.REVIEWED, note="kept"))
    path = tmp_path / "rv" / "decisions.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    again = ReviewStore(path, max_records=100)
    assert len(again) == 1 and again.latest()["evt_a"].note == "kept"
    assert path.read_text().count("\n") == 2  # append-only: the damaged line is left alone, not rewritten


def test_the_log_has_a_limit_and_refuses_beyond_it(tmp_path) -> None:
    svc, _ = make(tmp_path, [A], max_records=2)
    svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.REVIEWED))
    svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.OPEN))
    with pytest.raises(ReviewLimit, match="at most 2"):
        svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.DISMISSED))


def test_analyst_id_comes_from_the_body_then_the_header_then_anonymous(tmp_path) -> None:
    svc, _ = make(tmp_path, [A])
    assert svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.REVIEWED, analyst_id="body"), header_analyst="header").analyst_id == "body"
    assert svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.REVIEWED), header_analyst="header").analyst_id == "header"
    assert svc.decide(ReviewDecisionInput(event_id="evt_a", status=ReviewStatus.REVIEWED)).analyst_id == "anonymous"


def test_the_config_rejects_a_misspelt_level_and_a_loss_floor_that_is_not_a_loss() -> None:
    with pytest.raises(ValueError, match="material_levels"):
        CFG.__class__.model_validate({**CFG.model_dump(), "material_levels": ["HUGE"]})
    with pytest.raises(ValueError):
        CFG.__class__.model_validate({**CFG.model_dump(), "stress_loss_floor": 0.02})
