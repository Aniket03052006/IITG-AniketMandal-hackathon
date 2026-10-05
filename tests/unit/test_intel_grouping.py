"""Event grouping: related report clusters become one event; look-alikes, other issuers, other times and other classes do not."""

from __future__ import annotations

import random

from eventshock.domain import EventCategory as C
from eventshock.domain import TimestampOrigin
from eventshock.intelligence.grouping import EventIndex
from tests.intel_helpers import CFG, JPM, XOM, member, sig

FINE_A = "JPMorgan Chase fined $920 million over spoofing by US regulators"
FINE_B = "JPMorgan fined $920 million in spoofing probe, regulators say"


def idx(signals):  # noqa: ANN001, ANN201
    return EventIndex(signals, CFG)


def test_two_clusters_of_one_story_become_one_event():
    a = sig("a", FINE_A, entity=JPM, minutes=0, source="Wire A", url="https://a.example/x")
    b = sig("b", FINE_B, entity=JPM, minutes=90, source="Wire B", url="https://b.example/y")
    i = idx([a, b])
    assert len(i.events) == 1
    ev = i.event_of("b")
    assert ev.signal_ids == ["a", "b"] and ev.anchor.signal.id == "a"
    assert i.event_of("a") is ev


def test_every_report_stays_visible_beneath_the_event():
    a = sig("a", FINE_A, entity=JPM, members=[member("Wire C", 10, "JPMorgan fine: $920 million", url="https://c.example/z")])
    b = sig("b", FINE_B, entity=JPM, minutes=90, source="Wire B", url="https://b.example/y")
    reports = idx([a, b]).event_of("a").reports()
    assert [r.relation for r in reports] == ["CANONICAL", "SAME_EVENT", "CANONICAL"]
    assert {r.source for r in reports} == {"Wire A", "Wire B", "Wire C"}


def test_similar_text_about_another_issuer_is_not_merged():
    a = sig("a", FINE_A, entity=JPM)
    b = sig("b", "Exxon Mobil fined $920 million over spoofing by US regulators", entity=XOM, minutes=30)
    assert len(idx([a, b]).events) == 2


def test_the_same_issuer_far_apart_in_time_is_not_merged():
    a = sig("a", FINE_A, entity=JPM, minutes=0)
    b = sig("b", FINE_B, entity=JPM, minutes=60 * (int(CFG.grouping.window_hours) + 5))
    assert len(idx([a, b]).events) == 2


def test_a_different_event_class_is_not_merged():
    a = sig("a", FINE_A, entity=JPM, category=C.REGULATORY_LEGAL)
    b = sig("b", FINE_B, entity=JPM, category=C.EARNINGS_FINANCIAL_PERFORMANCE, minutes=30)
    assert len(idx([a, b]).events) == 2


def test_unrelated_wording_for_the_same_issuer_is_not_merged():
    a = sig("a", FINE_A, entity=JPM)
    b = sig("b", "JPMorgan names new head of wealth management in Asia", entity=JPM, minutes=30)
    assert len(idx([a, b]).events) == 2


def test_unresolved_reports_group_only_on_a_shared_scope_and_close_wording():
    a = sig("a", "Oil producers cut output by 1.2 million barrels a day after OPEC accord", minutes=0)
    b = sig("b", "OPEC accord: oil producers to cut 1.2 million barrels a day output", minutes=40, source="Wire B")
    c = sig("c", "Software makers cut 1.2 million barrels of coffee a day", minutes=50, source="Wire C")
    i = idx([a, b, c])
    assert i.event_of("a") is i.event_of("b") and i.event_of("c") is not i.event_of("a")


def test_one_named_issuer_and_one_unnamed_report_are_never_merged():
    a = sig("a", FINE_A, entity=JPM)
    b = sig("b", FINE_B, minutes=30)  # same words, no issuer resolved: not safely the same event
    assert len(idx([a, b]).events) == 2


def test_an_event_is_a_star_around_its_first_report_so_a_chain_cannot_grow():
    a = sig("a", "JPMorgan Chase fined $920 million over spoofing by US regulators", entity=JPM, minutes=0)
    b = sig("b", "JPMorgan fined $920 million over spoofing, regulators say; Chase shares dip 2%", entity=JPM, minutes=600)
    c = sig("c", "JPMorgan Chase shares dip 2% as investors weigh settlement terms", entity=JPM, minutes=2400)
    i = idx([a, b, c])
    assert i.event_of("b") is i.event_of("a")
    assert i.event_of("c") is not i.event_of("a")  # c only relates to b, never to the anchor within its window


def test_grouping_is_deterministic_whatever_order_the_signals_arrive_in():
    base = [sig("a", FINE_A, entity=JPM), sig("b", FINE_B, entity=JPM, minutes=90),
            sig("c", "Exxon Mobil fined $920 million over spoofing by US regulators", entity=XOM, minutes=30),
            sig("d", "Local festival draws record crowds", minutes=5)]
    want = {e.id: e.signal_ids for e in idx(base).events}
    for seed in range(5):
        shuffled = base[:]
        random.Random(seed).shuffle(shuffled)
        assert {e.id: e.signal_ids for e in idx(shuffled).events} == want


def test_an_untrusted_clock_is_never_grouped():
    a = sig("a", FINE_A, entity=JPM, origin=TimestampOrigin.SYNTHETIC_REPLAY_CLOCK)
    b = sig("b", FINE_B, entity=JPM, minutes=30, origin=TimestampOrigin.SYNTHETIC_REPLAY_CLOCK)
    i = idx([a, b])
    assert len(i.events) == 2 and not i.event_of("a").trusted


def test_independence_collapses_copies_and_same_outlet_reports():
    from eventshock.domain import DedupRelation
    from eventshock.intelligence.grouping import mark_independence
    a = sig("a", FINE_A, entity=JPM, url="https://a.example/x", members=[
        member("Wire B", 5, FINE_A, url="https://b.example/y", relation=DedupRelation.SYNDICATED),
        member("Wire A again", 8, "JPMorgan fine: $920 million", url="https://a.example/follow", relation=DedupRelation.SAME_EVENT),
        member("Wire D", 12, "JPMorgan fine: $920 million", url="https://d.example/z", relation=DedupRelation.SAME_EVENT)])
    marked = mark_independence(idx([a]).event_of("a").reports(), set(CFG.sources.copy_relations))
    assert [(r.domain, r.independent) for r in marked] == [
        ("a.example", True), ("b.example", False), ("a.example", False), ("d.example", True)]
