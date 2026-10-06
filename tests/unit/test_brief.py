"""The brief builder over real grouping and scope: fixed order, every statement sourced, fixed fallback sentences for absent inputs, the three market states, deterministic output."""

from __future__ import annotations

import pytest

from eventshock.brief.builder import BriefError, BriefInputs, _Writer, build_brief, to_markdown
from eventshock.brief.models import MARKET_UNAVAILABLE, NO_MARKET, SECTIONS
from tests.markets_helpers import COMPANY, CPI, FED, fixture_provider, macro, service

AFTER = 24 * 24 * 60 + 60


def inputs(text=FED, *, provider=None, with_market=True, with_intel=False, minutes=AFTER, **kw):  # noqa: ANN001, ANN003, ANN201
    svc, mon = service([macro("a", text, minutes=minutes)], provider=provider, **kw)
    ev = mon.resolve_event("a")
    as_of = mon.cycles()[-1].at
    built = mon.builder.build(ev, as_of, None, force_full=True)
    market = svc.view("a") if with_market else None
    return BriefInputs(event_id=ev.id, mode="REPLAY", cycle=len(mon.cycles()) - 1, as_of=as_of, portfolio_id=None, portfolio_name=None, state=built.state, intel=built.intel if with_intel else None,
                       lead=ev.anchor.signal, materiality=None, graph=None, stress=None, analogues=None, market=market, memory=None)


def texts(b, sid):  # noqa: ANN001, ANN201
    return " ".join(s.text for s in next(x for x in b.sections if x.id == sid).statements)


def test_with_every_optional_input_missing_all_sixteen_sections_still_exist_with_fixed_sentences():
    b = build_brief(inputs(with_market=False))
    assert [s.id for s in b.sections] == [i for i, _ in SECTIONS]
    assert "No stress scenario was generated" in texts(b, "EXECUTIVE_SUMMARY") and "not assessed" in texts(b, "EXECUTIVE_SUMMARY")
    assert MARKET_UNAVAILABLE in texts(b, "EXTERNAL_MARKET_VIEW")
    assert "unavailable in this profile" in texts(b, "HISTORICAL_CONTEXT")
    assert "no event-intelligence layer ran" in texts(b, "EVIDENCE")
    assert {s.availability for s in b.sections if s.id in ("STRESS", "TOP_DRIVERS", "PORTFOLIO_EXPOSURE", "PROPAGATION", "WHY_IT_MATTERS")} == {"UNAVAILABLE"}


def test_every_statement_cites_a_known_source():
    for kw in ({}, {"with_intel": True}, {"with_market": False}):
        b = build_brief(inputs(**kw))
        ids = {s.id for s in b.sources}
        assert all(st.source_refs and set(st.source_refs) <= ids for sec in b.sections for st in sec.statements)


def test_a_statement_with_no_resolvable_source_is_a_build_error():
    w = _Writer(inputs())
    with pytest.raises(BriefError):
        w.say("An unsupported claim.", __import__("eventshock.decision.models", fromlist=["x"]).ObservationKind.PRODUCT_RULE, "nonexistent")
    with pytest.raises(BriefError):
        w.close("X", "X")                                                   # a section with no statement is a bug, not an empty section


def test_the_market_section_has_three_states_with_fixed_wording():
    matched = build_brief(inputs(FED, provider=fixture_provider()))
    t = texts(matched, "EXTERNAL_MARKET_VIEW")
    assert "EXTERNAL MARKET OBSERVATION" in t and "SYNTHETIC FIXTURE" in t and "never an input" in t and "confirms" not in t.lower()
    nomatch = build_brief(inputs(COMPANY, provider=fixture_provider()))
    assert texts(nomatch, "EXTERNAL_MARKET_VIEW").startswith(NO_MARKET)
    down = build_brief(inputs(FED, provider=None))
    assert texts(down, "EXTERNAL_MARKET_VIEW") == MARKET_UNAVAILABLE


def test_the_market_never_enters_any_other_section():
    b = build_brief(inputs(CPI, provider=fixture_provider()))
    for sec in b.sections:
        if sec.id != "EXTERNAL_MARKET_VIEW":
            assert not any("market" in s.source_refs for s in sec.statements) or sec.id in ("WHAT_TO_MONITOR",), sec.id


def test_monitor_rules_follow_the_state_and_each_names_its_rule():
    b = build_brief(inputs(FED, provider=fixture_provider()))
    t = texts(b, "WHAT_TO_MONITOR")
    assert "(rule M" in t and "rule M5" in t and "unverified" not in t


def test_markdown_is_deterministic_numbered_and_lists_its_sources():
    a, b = build_brief(inputs(FED, provider=fixture_provider())), build_brief(inputs(FED, provider=fixture_provider()))
    assert a.model_dump_json() == b.model_dump_json() and to_markdown(a) == to_markdown(b)
    md = to_markdown(a)
    assert md.startswith("# Executive risk brief:") and md.count("\n## ") == 17 and "## Sources" in md and "[1]" in md
    for n, (_, title) in enumerate(SECTIONS, 1):
        assert f"## {n}. {title}" in md
