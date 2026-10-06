"""The executive digest: an ordered key that is shown on every card (never a score), per-section caps with honest totals, merged changes, drill-down steps, deterministic order."""

from __future__ import annotations

import random
from datetime import timedelta

import pytest

from eventshock.monitor.digest import SECTION_INFO, build_sections, drill, rank_key
from eventshock.monitor.models import ChangeType as C
from eventshock.monitor.models import Mode, RiskChange
from tests.monitor_helpers import T0, state


def cfg():  # noqa: ANN201
    from eventshock.config import REPO_ROOT
    from eventshock.decision.config import load_decision_config
    return load_decision_config(REPO_ROOT / "configs")


def wide():  # noqa: ANN201
    """The shipped config with a section cap large enough to see every card (the cap itself is tested separately)."""
    c = cfg()
    return c.model_copy(update={"digest": c.digest.model_copy(update={"per_section": 50})})


def chg(eid: str, ctype: C, *, prev: dict | None = None, curr: dict | None = None, minutes: int = 0, cid: str | None = None) -> RiskChange:
    cur = state(event_id=eid, lead_signal_id=f"s_{eid}", headline=f"headline {eid}", **(curr or {}))
    pre = state(event_id=eid, lead_signal_id=f"s_{eid}", **(prev or {})) if prev is not None else None
    return RiskChange(change_id=cid or f"chg_{eid}_{ctype.value}", event_id=eid, change_type=ctype, mode=Mode.REPLAY, cycle=3, at=T0 + timedelta(minutes=minutes), headline=cur.headline,
                      summary=f"{ctype.value} for {eid}", rule="TEST", previous=pre, current=cur, changed_fields=[], supporting_evidence=[], portfolio_impact=None, provenance=[])


def section(sections, sid):  # noqa: ANN001, ANN201
    return next(s for s in sections if s.id == sid)


def heads(sections, sid):  # noqa: ANN001, ANN201
    return [c.event_id for c in section(sections, sid).cards]


def test_the_order_is_materiality_then_severity_then_size_then_recency_then_id():
    c = wide()
    cs = [
        chg("hi_sev9", C.NEW_EVENT, curr=dict(materiality="HIGH", severity=9.0)),
        chg("crit_sev5", C.NEW_EVENT, curr=dict(materiality="CRITICAL", severity=5.0)),                 # a higher tier beats a higher severity
        chg("hi_sev7_a", C.NEW_EVENT, curr=dict(materiality="HIGH", severity=7.0), minutes=10),
        chg("hi_sev7_b", C.NEW_EVENT, curr=dict(materiality="HIGH", severity=7.0), minutes=20),         # same tier and severity: the more recent first
        chg("hi_sev7_c", C.NEW_EVENT, curr=dict(materiality="HIGH", severity=7.0), minutes=20),         # same recency: the id decides
        chg("none", C.NEW_EVENT, curr=dict(materiality="UNDETERMINED", severity=10.0)),                 # no relevance to the book ranks after every tier
    ]
    got = heads(build_sections(c, cs, Mode.REPLAY, [], []), "NEW_RISKS")
    assert got == ["crit_sev5", "hi_sev9", "hi_sev7_b", "hi_sev7_c", "hi_sev7_a", "none"]


def test_the_size_of_the_change_breaks_a_tie_within_a_section():
    c = cfg()
    cs = [chg("small", C.STRESS_CHANGED, prev=dict(stress_pnl_pct=-0.020), curr=dict(stress_pnl_pct=-0.025)),
          chg("big", C.STRESS_CHANGED, prev=dict(stress_pnl_pct=-0.020), curr=dict(stress_pnl_pct=-0.060)),
          chg("exp_small", C.PORTFOLIO_EXPOSURE_CHANGED, prev=dict(exposure_share=0.20), curr=dict(exposure_share=0.23)),
          chg("exp_big", C.PORTFOLIO_EXPOSURE_CHANGED, prev=dict(exposure_share=0.20), curr=dict(exposure_share=0.40)),
          chg("esc_small", C.EVENT_ESCALATED, prev=dict(severity=6.0), curr=dict(severity=7.0)),
          chg("esc_big", C.EVENT_ESCALATED, prev=dict(severity=6.0), curr=dict(severity=7.0 + 0.0), minutes=5)]
    s = build_sections(c, cs, Mode.REPLAY, [], [])
    assert heads(s, "STRESS_CHANGES") == ["big", "small"] and heads(s, "EXPOSURE_CHANGES") == ["exp_big", "exp_small"]
    assert heads(s, "ESCALATIONS") == ["esc_big", "esc_small"]                                          # equal size and tier: the more recent first


def test_the_same_changes_in_any_order_give_the_same_digest():
    c = wide()
    cs = [chg(f"e{i}", t, prev=dict(severity=5.0 + (i % 3)), curr=dict(materiality=["LOW", "HIGH", "MEDIUM", "CRITICAL"][i % 4], severity=6.0 + (i % 5)), minutes=i * 7)
          for i, t in enumerate([C.NEW_EVENT, C.EVENT_ESCALATED, C.NEW_EVENT, C.EVIDENCE_STRENGTHENED, C.CONFLICT_APPEARED, C.NEW_EVENT, C.EVENT_ESCALATED, C.STRESS_CHANGED] * 3)]
    base = [s.model_dump_json() for s in build_sections(c, cs, Mode.REPLAY, [], [])]
    for seed in range(5):
        shuffled = cs[:]
        random.Random(seed).shuffle(shuffled)
        assert [s.model_dump_json() for s in build_sections(c, shuffled, Mode.REPLAY, [], [])] == base


def test_every_card_shows_its_key_and_the_rank_matches_the_position():
    c = cfg()
    cs = [chg(f"e{i}", C.NEW_EVENT, curr=dict(materiality="HIGH", severity=5.0 + i)) for i in range(4)]
    sec = section(build_sections(c, cs, Mode.REPLAY, [], []), "NEW_RISKS")
    assert [card.rank for card in sec.cards] == [1, 2, 3, 4]
    for card in sec.cards:
        assert [p.name for p in card.rank_key] == ["materiality", "severity", "size of change", "recency", "id"] and card.rank_key[0].value == "HIGH"
        assert card.provenance and "monitor.digest" in card.provenance[0].source


def test_sections_are_capped_with_an_honest_total_and_follow_the_configured_order():
    c = cfg()
    n = c.digest.per_section + 3
    cs = [chg(f"e{i:02d}", C.NEW_EVENT, curr=dict(materiality="MEDIUM", severity=6.0)) for i in range(n)]
    sections = build_sections(c, cs, Mode.REPLAY, [], [])
    assert [s.id for s in sections] == c.digest.sections
    new = section(sections, "NEW_RISKS")
    assert len(new.cards) == c.digest.per_section and new.total == n and new.truncated
    assert all(s.total == 0 and s.cards == [] and not s.truncated for s in sections if s.id != "NEW_RISKS")


def test_several_changes_of_one_event_in_a_section_are_one_card_naming_all_of_them():
    c = cfg()
    cs = [chg("e1", C.EVIDENCE_STRENGTHENED, prev=dict(evidence_tier="WEAK"), curr=dict(evidence_tier="MODERATE"), minutes=1),
          chg("e1", C.EVIDENCE_WEAKENED, prev=dict(evidence_tier="MODERATE"), curr=dict(evidence_tier="WEAK"), minutes=9)]
    sec = section(build_sections(c, cs, Mode.REPLAY, [], []), "EVIDENCE_CHANGES")
    assert len(sec.cards) == 1 and sec.cards[0].change_types == [C.EVIDENCE_STRENGTHENED, C.EVIDENCE_WEAKENED] and len(sec.cards[0].change_ids) == 2
    assert "EVIDENCE_WEAKENED" in sec.cards[0].summary                          # the latest change speaks


def test_one_event_can_appear_in_two_sections_each_for_its_own_reason():
    c = cfg()
    cs = [chg("e1", C.NEW_EVENT, curr=dict(severity=8.0)), chg("e1", C.CONFLICT_APPEARED, prev=dict(conflict="NO_CONFLICT"), curr=dict(conflict="CONFLICTED", severity=8.0))]
    s = build_sections(c, cs, Mode.REPLAY, [], [])
    assert heads(s, "NEW_RISKS") == ["e1"] and heads(s, "CONFLICTS") == ["e1"]


def test_a_card_drills_down_from_the_event_to_the_attribution_in_order():
    steps = drill("sig_1")
    assert [d.step for d in steps] == ["EVENT", "EVIDENCE", "SCOPE", "EXPOSURE", "PROPAGATION", "STRESS", "ATTRIBUTION"] and {d.signal_id for d in steps} == {"sig_1"}
    sec = section(build_sections(cfg(), [chg("e1", C.NEW_EVENT)], Mode.REPLAY, [], []), "NEW_RISKS")
    assert [d.step for d in sec.cards[0].drill] == [d.step for d in steps] and sec.cards[0].drill[0].signal_id == "s_e1"


def test_every_section_in_the_info_table_is_configurable_and_nothing_else():
    c = cfg()
    assert set(SECTION_INFO) == set(c.digest.sections)
    assert rank_key(c, state(materiality="CRITICAL", severity=3.0), 0.0, None)[0] < rank_key(c, state(materiality="HIGH", severity=10.0), 0.0, None)[0]


def test_the_digest_never_contains_a_score_field():
    sec = section(build_sections(cfg(), [chg("e1", C.NEW_EVENT)], Mode.REPLAY, [], []), "NEW_RISKS")
    assert not [k for k in sec.cards[0].model_dump() if "score" in k or "importance" in k or "priority_value" in k]


@pytest.mark.parametrize("bad", [["CRITICAL", "HIGH"], ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE", "UNDETERMINED", "EXTRA"]])
def test_the_materiality_order_must_be_exactly_the_known_levels(bad):
    from eventshock.decision.config import DigestCfg
    with pytest.raises(ValueError, match="materiality_order"):
        DigestCfg(per_section=5, materiality_order=bad, sections=["NEW_RISKS"])
