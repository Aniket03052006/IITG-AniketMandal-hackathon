"""The rules baseline of the rubric, and the evidence classes: a quote is never an inference, an inference is never a quote."""

from __future__ import annotations

import copy

import pytest

from eventshock.assessment.model import IndicatorBasis
from eventshock.assessment.reference import Reference
from eventshock.assessment.rubric import largest_amount_usd
from tests.assess_helpers import DERIVER, RULES, extractor
from tests.fakes import CASES, EARNINGS, GEOPOLITICAL, RBI, RBI_ANSWER, REGULATORY, FakeLLM


def base(text: str, ref: Reference | None = None):
    rd, _ = RULES.extract(text, ref or Reference())
    return {k: v[0] for k, v in DERIVER.baseline(text, rd).items()}, rd


# ------------------------------------------------------------------------------------------------------------------- the rules baseline
@pytest.mark.parametrize("text,mag", [
    ("Company to present at investor conference next month", "0"),
    ("Regional bank fined $2 million over late regulatory filings", "1"),
    (EARNINGS, "2"),
    ("Central bank raises its policy rate by 75 basis points, the largest increase in decades", "3"),  # an escalator word steps it up
])
def test_magnitude_baseline_follows_the_indicators_and_scale_words(text: str, mag: str) -> None:
    assert base(text)[0]["magnitude"] == mag


def test_a_large_money_amount_sets_a_floor_and_never_lowers() -> None:
    assert largest_amount_usd("a $18 billion deal and $200 million fees") == 18e9
    assert largest_amount_usd("costing it $2.5 trillion") == 2.5e12 and largest_amount_usd("no amounts here") is None
    assert base("Firm reports a $3 billion charge on claims")[0]["magnitude"] >= "2"
    assert base("Firm settles a small dispute for $2 million")[0]["magnitude"] <= "1"


def test_several_serious_indicators_together_are_one_step_worse_than_the_worst_alone() -> None:
    alone = base("The bank defaulted")[0]["magnitude"]
    together = base("The bank defaulted, suffered margin calls and regulators step in under a rescue")[0]["magnitude"]
    assert int(together) == min(4, int(alone) + 1)


def test_deescalating_words_lower_the_baseline_and_escalating_words_raise_it() -> None:
    assert int(base("Firm suffers a minor outage")[0]["magnitude"]) < int(base("Firm suffers an outage")[0]["magnitude"]) <= int(base("Firm suffers an unprecedented outage")[0]["magnitude"])


@pytest.mark.parametrize("text,reach", [
    ("Mid-sized regional bank misses a debt payment", "firm"),
    ("A major technology company cuts its revenue outlook", "firm"),
    ("Regulators finalize rules requiring large banks to hold more capital", "sector"),
    ("Stock markets fall as the central bank raises rates", "market"),
    ("Markets slide worldwide as emergency measures are announced", "global"),
])
def test_reach_separates_a_single_firm_from_a_sector_a_market_and_the_world(text: str, reach: str) -> None:
    assert base(text)[0]["reach"] == reach


def test_a_systemic_magnitude_is_never_confined_to_one_firm() -> None:
    b, _ = base("Bank run spreads as the lender collapses and funding freezes")
    assert b["magnitude"] == "4" and b["reach"] in ("market", "global")


@pytest.mark.parametrize("text,cert", [
    (REGULATORY, "speculative"),  # "potentially"
    ("Regulator proposes tighter disclosure rules for private funds", "proposed"),
    ("Firm reportedly in talks to buy a rival", "speculative"),
    ("Firm agrees to buy a rival", "confirmed"),
    ("Inflation data due in May shows prices rose", "confirmed"),  # "May" is a month, not a hedge
])
def test_certainty_baseline_reads_hedges_and_proposals(text: str, cert: str) -> None:
    assert base(text)[0]["certainty"] == cert


def test_direction_baseline_uses_indicator_polarity_then_the_tone_reading() -> None:
    assert base("Chipmaker raises full-year guidance on strong demand")[0]["direction"] == "favourable"
    assert base(EARNINGS)[0]["direction"] == "adverse"
    assert base("Firm agrees a merger but also warns of a profit hit from restructuring")[0]["direction"] in ("mixed", "adverse")
    neg = Reference(sentiment=-0.6)
    assert base("Quarterly update from the desk", neg)[0]["direction"] == "adverse" and base("Quarterly update from the desk")[0]["direction"] == "neutral"


def test_a_phrase_inside_a_longer_opposite_phrase_is_not_counted() -> None:
    inds = {h.id for h in RULES.extract("Two countries sign a trade agreement lowering tariffs on agricultural goods")[0].severity_indicators}
    assert "trade_liberalisation" in inds and "sanctions_trade_restriction" not in inds  # "lowering tariffs" is not a tariff


def test_a_severity_marker_is_itself_evidence_of_a_market_event() -> None:
    r, info = RULES.extract("Hedge fund suffers margin calls from its prime brokers")
    assert r.event_type != "NO_EVENT" and "severity indicator" in info.basis


# -------------------------------------------------------------------------------------------------------------------- evidence classes
def run(answer: dict, text: str):
    return extractor(FakeLLM(answer)).extract(text, Reference())


def test_an_inferred_indicator_is_labelled_an_inference_and_never_a_quote() -> None:
    """The RBI case: 'inflation pressure builds' became 'persistent inflation' with no matching phrase. The AI's quote is not in the text, so it is an inference."""
    r, info = run(RBI_ANSWER, RBI)
    inf = next(h for h in r.severity_indicators if h.id == "inflation_persistence")
    assert inf.basis is IndicatorBasis.KEYWORD or inf.basis is IndicatorBasis.INFERRED
    # "persistent inflation" is not in the text; whatever the label, the indicator must not present that phrase as a quote
    assert inf.quote != "persistent inflation" and (inf.quote is None or inf.quote in RBI)
    assert any("not in the text" in n for n in info.notes)
    # no highlighted evidence span may be a phrase that is not in the text
    assert all(RBI[s.start:s.end] == s.quote for s in r.evidence)


def test_an_indicator_with_no_phrase_at_all_is_inferred_with_the_ais_reason_and_no_quote() -> None:
    a = copy.deepcopy(RBI_ANSWER)
    a["severity_indicators"] = [dict(id="liquidity_stress", quote=None, reason="food-price pressure may squeeze liquidity")]
    r, _ = run(a, RBI)
    h = r.severity_indicators[0]
    assert h.basis is IndicatorBasis.INFERRED and h.quote is None and "squeeze liquidity" in h.reason
    assert not any(s.supports == "severity" for s in r.evidence), "an inference must not be highlighted as evidence"


def test_a_verbatim_quote_makes_it_quoted_and_a_configured_phrase_makes_it_keyword() -> None:
    a = copy.deepcopy(RBI_ANSWER)
    a["severity_indicators"] = [dict(id="inflation_persistence", quote="inflation pressure builds", reason="stated"),
                                dict(id="policy_tightening", quote=None, reason="x")]
    r, _ = run(a, "RBI keeps rates unchanged as inflation pressure builds in food prices; tightening is possible")
    q = next(h for h in r.severity_indicators if h.id == "inflation_persistence")
    assert q.basis is IndicatorBasis.QUOTED and q.quote == "inflation pressure builds"
    k = next(h for h in r.severity_indicators if h.id == "policy_tightening")
    assert k.basis is IndicatorBasis.KEYWORD and k.quote == "tightening"
    assert any(s.supports == "severity" and s.quote == "inflation pressure builds" for s in r.evidence)  # a quoted indicator is highlighted


def test_string_indicators_from_an_older_answer_still_work_and_are_graded_by_the_text() -> None:
    a = copy.deepcopy(CASES["regulatory"]["answer"])
    r, _ = run(a, REGULATORY)
    assert {h.id for h in r.severity_indicators} == {"capital_requirement_change", "funding_cost_increase"}
    assert all(h.basis is IndicatorBasis.KEYWORD for h in r.severity_indicators)  # both have a configured phrase in the text


def test_the_ai_rubric_is_grounded_quotes_verified_and_bad_levels_dropped() -> None:
    a = copy.deepcopy(CASES["geopolitical"]["answer"])
    a["rubric"]["magnitude"] = dict(value=4, reason="a shock to a key supply route", quote="oil supply routes")
    a["rubric"]["reach"] = dict(value="galaxy", reason="x" * 20)
    a["rubric"]["certainty"] = dict(value="confirmed", reason="stated", quote="not in the text at all")
    r, info = run(a, GEOPOLITICAL)
    assert r.ai_rubric.magnitude.quote_verified and r.ai_rubric.magnitude.quote == "oil supply routes"
    assert r.ai_rubric.reach is None and any("not an allowed level" in n for n in info.notes)
    assert r.ai_rubric.certainty.quote is None and not r.ai_rubric.certainty.quote_verified
    assert any("quote offered" in n and "certainty" in n for n in info.notes)


def test_rule_mode_carries_no_ai_rubric_and_says_its_indicators_are_keywords() -> None:
    r, _ = RULES.extract(GEOPOLITICAL)
    assert r.ai_rubric is None and all(h.basis is IndicatorBasis.KEYWORD for h in r.severity_indicators)
