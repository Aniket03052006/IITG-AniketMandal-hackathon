"""The severity scorecard: a deterministic function of four rubric answers and two bounded data adjustments. What it must and must not depend on."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
import yaml

from eventshock.assessment.config import SeverityConfig
from eventshock.assessment.freshness import assess_market, last_completed_session, sessions_between
from eventshock.assessment.model import AIRubric, RubricProposal, SemanticReading
from eventshock.assessment.severity import SeverityInputs
from eventshock.config import ConfigError
from tests.assess_helpers import CONFIG_DIR, DERIVER, RULES, SCORER, SEVERITY
from tests.fakes import EARNINGS, REGULATORY

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)  # a Monday, before the close
NO_MARKET = assess_market(NOW, None, None, SEVERITY.regime)


def reading(text: str = REGULATORY, **upd) -> SemanticReading:
    r, _ = RULES.extract(text)
    return r.model_copy(update=upd) if upd else r


def fields(mag: str, reach: str, cert: str = "confirmed", dirn: str = "adverse"):
    """Rubric fields whose final answers are exactly these (no AI): isolates the scorecard arithmetic from the rubric derivation."""
    base = {"magnitude": (mag, ["test"]), "reach": (reach, ["test"]), "certainty": (cert, ["test"]), "direction": (dirn, ["test"])}
    return [DERIVER.apply_ai(k, base[k], None) for k in ("magnitude", "reach", "certainty", "direction")]


def score(mag, reach, cert="confirmed", dirn="adverse", *, market=NO_MARKET, novelty=None, rd=None, source="NEWS", corro=0):
    return SCORER.score(SeverityInputs(reading=rd or reading(), rubric=fields(mag, reach, cert, dirn), market=market, novelty=novelty,
                                       source_type=source, corroborating_at_event_time=corro))


# --------------------------------------------------------------------------------------------------------------- the scale is reachable
def test_every_score_from_one_to_ten_is_reachable_and_each_band_by_construction() -> None:
    seen = {score(m, r, c, d).score for m in "01234" for r in ("firm", "sector", "market", "global") for c in ("confirmed", "proposed", "speculative")
            for d in ("adverse", "mixed", "neutral", "favourable")}
    assert seen == set(range(1, 11)), f"unreachable scores: {sorted(set(range(1, 11)) - seen)}"


@pytest.mark.parametrize("mag,band", [("0", "negligible"), ("1", "low"), ("2", "moderate"), ("3", "high"), ("4", "extreme")])
def test_a_confirmed_adverse_event_at_sector_reach_lands_in_its_magnitudes_band(mag: str, band: str) -> None:
    assert score(mag, "sector").band == band


def test_the_extremes_are_reachable_the_old_formula_could_not_reach_them() -> None:
    assert score("4", "global").score == 10 and score("0", "firm").score == 1


def test_the_score_is_monotone_in_magnitude_and_in_reach() -> None:
    by_mag = [score(m, "sector").points for m in "01234"]
    by_reach = [score("2", r).points for r in ("firm", "sector", "market", "global")]
    assert by_mag == sorted(by_mag) and len(set(by_mag)) == 5
    assert by_reach == sorted(by_reach) and len(set(by_reach)) == 4


def test_certainty_and_direction_only_ever_lower_the_score() -> None:
    base = score("3", "market").points
    assert score("3", "market", "proposed").points < base and score("3", "market", "speculative").points < score("3", "market", "proposed").points
    assert score("3", "market", dirn="favourable").points < score("3", "market", dirn="neutral").points < score("3", "market", dirn="mixed").points < base


# ---------------------------------------------------------------------------------------------------------- what it must NOT depend on
def test_tone_confidence_source_count_and_reliability_do_not_change_the_score() -> None:
    a = score("3", "market")
    for kw in (dict(rd=reading(sentiment=-0.95, sentiment_label="negative")), dict(rd=reading(sentiment=0.9, sentiment_label="positive")),
               dict(rd=reading(uncertainty=0.95)), dict(rd=reading(uncertainty=0.0)), dict(source="SOCIAL"), dict(corro=40), dict(source="SOCIAL", corro=0)):
        b = score("3", "market", **kw)
        assert (b.score, b.points) == (a.score, a.points), kw
    # ...they only move the reliability line and (for uncertainty) the range
    assert score("3", "market", source="SOCIAL").reliability.level == "low" and score("3", "market", corro=4).reliability.level == "high"
    assert score("3", "market", rd=reading(uncertainty=0.9)).high >= a.high


def test_uncertainty_widens_the_range_but_never_lowers_the_score() -> None:
    sure, unsure = score("2", "sector", rd=reading(uncertainty=0.0)), score("2", "sector", rd=reading(uncertainty=1.0))
    assert unsure.score == sure.score and (unsure.high - unsure.low) >= (sure.high - sure.low)


def test_reliability_is_reported_beside_the_score_with_its_own_basis() -> None:
    r = score("2", "sector", source="NEWS", corro=2).reliability
    assert r.level in ("moderate", "high") and "independent report" in r.basis and "does not change the severity" in r.note


# ------------------------------------------------------------------------------------------------------------------ the build-up is honest
def test_the_steps_start_at_the_matrix_and_sum_to_the_points() -> None:
    sev = score("3", "market", "proposed", "adverse", novelty=0.9, market=assess_market(NOW, "2026-10-02", 30.0, SEVERITY.regime))
    assert sev.steps[0].id == "matrix" and sev.steps[0].effect_points == sev.steps[0].running
    assert abs(sum(s.effect_points for s in sev.steps) - sev.points) < 0.01
    assert [s.id for s in sev.steps] == ["matrix", "certainty", "direction", "regime", "novelty"]
    assert all(s.origin.value in ("HYBRID", "RULES", "AI", "DATA", "ASSUMPTION") for s in sev.steps)
    assert {s.id: s.origin.value for s in sev.steps}["regime"] == "DATA"


def test_a_missing_input_is_omitted_with_its_reason_and_never_guessed() -> None:
    sev = score("2", "sector")
    assert {o.id for o in sev.omitted} == {"regime", "novelty"}
    assert "No market state" in next(o.reason for o in sev.omitted if o.id == "regime")
    assert "regime" not in [s.id for s in sev.steps]


def test_the_regime_adjustment_is_bounded_and_goes_the_right_way() -> None:
    fresh = lambda vix: assess_market(NOW, "2026-10-02", vix, SEVERITY.regime)  # noqa: E731
    calm, normal, stressed = score("2", "sector", market=fresh(11.0)), score("2", "sector", market=fresh(20.0)), score("2", "sector", market=fresh(45.0))
    assert calm.points < normal.points < stressed.points
    assert -1.0 < calm.points - normal.points < 0 < stressed.points - normal.points <= 1.0


def test_novelty_moves_the_score_a_little_in_the_right_direction() -> None:
    assert score("2", "sector", novelty=0.1).points < score("2", "sector", novelty=0.5).points < score("2", "sector", novelty=1.0).points


def test_the_range_includes_the_score_and_the_rules_only_score() -> None:
    sev = score("3", "sector")
    assert sev.low <= sev.score <= sev.high and sev.low <= sev.baseline_score <= sev.high
    assert "not a statistical interval" in sev.range_basis


def test_a_non_event_is_not_scored() -> None:
    r, _ = RULES.extract("Lovely weather in the city this weekend, enjoy the sunshine everyone")
    assert SCORER.score(SeverityInputs(reading=r, rubric=fields("0", "firm"), market=NO_MARKET, novelty=None, source_type="NEWS", corroborating_at_event_time=0)) is None


# ---------------------------------------------------------------------------------------------------------------- market-data freshness
def test_the_last_completed_session_follows_the_weekday_calendar() -> None:
    d = lambda y, m, day, h: datetime(y, m, day, h, tzinfo=UTC)  # noqa: E731
    assert last_completed_session(d(2026, 10, 5, 12), 21).isoformat() == "2026-10-02"  # Monday before the close -> Friday
    assert last_completed_session(d(2026, 10, 5, 22), 21).isoformat() == "2026-10-05"  # Monday after the close
    assert last_completed_session(d(2026, 10, 4, 12), 21).isoformat() == "2026-10-02"  # Sunday -> Friday
    assert sessions_between(datetime(2026, 10, 1).date(), datetime(2026, 10, 5).date()) == 2  # Fri, Mon


def test_the_report_in_the_wild_one_session_behind_is_used_and_labelled_with_its_age() -> None:
    m = assess_market(datetime(2026, 10, 4, 20, 13, tzinfo=UTC), "2026-10-01", 16.4, SEVERITY.regime)  # a Sunday report, data to Thursday
    assert m.used and m.sessions_behind == 1 and m.as_of == "2026-10-01" and m.report_session == "2026-10-02" and "1 session behind" in m.reason


def test_two_sessions_stale_is_excluded_with_the_reason_never_silently_used() -> None:
    m = assess_market(datetime(2026, 10, 5, 22, tzinfo=UTC), "2026-10-01", 16.4, SEVERITY.regime)  # Monday after close: Thursday is 2 sessions behind
    assert not m.used and m.sessions_behind == 2 and "too stale" in m.reason and "at most 1" in m.reason
    sev = score("2", "sector", market=m)
    assert "regime" in {o.id for o in sev.omitted} and "regime" not in [s.id for s in sev.steps]


def test_a_market_state_dated_after_the_report_is_excluded_for_temporal_integrity() -> None:
    m = assess_market(datetime(2026, 10, 1, 12, tzinfo=UTC), "2026-10-02", 30.0, SEVERITY.regime)
    assert not m.used and "could not have been known" in m.reason


@pytest.mark.parametrize("as_of,vix", [(None, 20.0), ("2026-10-01", None), ("not-a-date", 20.0)])
def test_missing_or_unreadable_market_data_is_excluded_not_crashed_on(as_of, vix) -> None:
    assert not assess_market(NOW, as_of, vix, SEVERITY.regime).used


# --------------------------------------------------------------------------------------------------------------------- bounded AI adjustment
def prop(value: str, reason: str = "the report describes it plainly", quote: str | None = None, verified: bool = False) -> RubricProposal:
    return RubricProposal(value=value, reason=reason, quote=quote, quote_verified=verified)


def adjust(fid: str, base: str, p: RubricProposal | None):
    return DERIVER.apply_ai(fid, (base, ["rules"]), p)


def test_the_ai_may_move_an_answer_one_step_with_a_reason() -> None:
    f = adjust("magnitude", "2", prop("3"))
    assert f.final == "3" and f.adjustment == "AI_WITHIN_BOUND" and f.origin.value == "HYBRID" and f.baseline == "2" and f.ai == "3"
    assert adjust("magnitude", "2", prop("1")).final == "1"


def test_agreement_is_recorded_as_no_adjustment() -> None:
    f = adjust("reach", "sector", prop("sector"))
    assert f.final == "sector" and f.adjustment == "NONE" and "agrees" in f.note


def test_the_ai_is_held_to_one_step_where_the_rules_have_evidence_even_with_a_verified_quote() -> None:
    f = adjust("magnitude", "1", prop("4"))
    assert f.final == "2" and f.adjustment == "AI_CLAMPED" and "at most 1 step" in f.note
    assert adjust("magnitude", "4", prop("0", quote="made up", verified=False)).final == "3"
    q = adjust("magnitude", "1", prop("4", quote="freeze lending", verified=True))
    assert q.final == "2" and q.adjustment == "AI_CLAMPED", "a quote does not lift the bound where the rules have evidence (it scored worse: severity_ai_bound_ablation.json)"


def test_where_the_rules_found_no_evidence_a_verified_quote_lets_the_ais_answer_stand() -> None:
    """An unknown phrasing is not a reason to cap a correct answer at the default."""
    base = ("0", ["no event or severity marker found"], False)  # an uninformed default
    f = DERIVER.apply_ai("magnitude", base, prop("4", quote="freeze lending", verified=True))
    assert f.final == "4" and f.adjustment == "AI_QUOTE_BACKED" and f.ai_quote == "freeze lending" and not f.baseline_informed
    assert "no evidence" in f.note
    # without a verified quote it is still held to one step, and an informed baseline never lifts
    assert DERIVER.apply_ai("magnitude", base, prop("4")).final == "1"
    assert DERIVER.apply_ai("magnitude", base, prop("4", quote="made up", verified=False)).final == "1"
    assert DERIVER.apply_ai("magnitude", ("0", ["x"], True), prop("4", quote="freeze lending", verified=True)).final == "1"


def test_the_baseline_says_whether_it_had_any_evidence() -> None:
    from tests.assess_helpers import RULES

    informed = DERIVER.combine("Bank defaults and margin calls follow", RULES.extract("Bank defaults and margin calls follow")[0], None)
    assert next(f for f in informed if f.id == "magnitude").baseline_informed
    blank = DERIVER.combine("Quarterly update from the desk", RULES.extract("Quarterly update from the desk")[0], None)
    assert not next(f for f in blank if f.id == "magnitude").baseline_informed and not next(f for f in blank if f.id == "certainty").baseline_informed


def test_an_answer_without_a_reason_or_outside_the_levels_is_ignored() -> None:
    assert adjust("magnitude", "2", prop("4", reason="")).adjustment == "AI_IGNORED" and adjust("magnitude", "2", prop("4", reason="ok")).final == "2"
    f = adjust("reach", "firm", prop("galaxy"))
    assert f.final == "firm" and f.adjustment == "AI_IGNORED" and f.ai is None


def test_no_ai_means_the_answer_is_the_rules_answer_and_says_so() -> None:
    f = adjust("direction", "adverse", None)
    assert f.final == "adverse" and f.adjustment == "NONE" and f.origin.value == "RULES" and f.ai is None


def test_the_ai_effect_is_the_difference_from_the_rules_only_score() -> None:
    rd = reading(EARNINGS)
    ai = AIRubric(magnitude=prop("3"), reach=prop("market"))
    rubric = DERIVER.combine(EARNINGS, rd, ai)
    sev = SCORER.score(SeverityInputs(reading=rd, rubric=rubric, market=NO_MARKET, novelty=None, source_type="NEWS", corroborating_at_event_time=0))
    plain = SCORER.score(SeverityInputs(reading=rd, rubric=DERIVER.combine(EARNINGS, rd, None), market=NO_MARKET, novelty=None, source_type="NEWS", corroborating_at_event_time=0))
    assert sev.baseline_score == plain.score and sev.ai_effect == sev.score - plain.score and sev.ai_effect > 0
    assert plain.ai_effect == 0


# ---------------------------------------------------------------------------------------------------------------------------- the config
def test_the_shipped_config_is_valid_and_its_bands_tile_the_scale() -> None:
    assert [b.id for b in SEVERITY.bands] == ["negligible", "low", "moderate", "high", "extreme"]
    assert [SEVERITY.band_of(s).id for s in range(1, 11)] == ["negligible"] * 2 + ["low"] * 2 + ["moderate"] * 2 + ["high"] * 2 + ["extreme"] * 2
    anchors = [SEVERITY.magnitude[i].anchor for i in range(5)]
    for i, (lo, hi) in enumerate([(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)]):  # each anchor sits inside its band
        assert lo <= anchors[i] < hi + 1


def test_a_broken_config_fails_loudly() -> None:
    raw = yaml.safe_load((CONFIG_DIR / "severity.yaml").read_text())
    SeverityConfig.model_validate(raw)
    bad = copy.deepcopy(raw)
    bad["bands"][1]["low"] = 4
    with pytest.raises(ValueError):
        SeverityConfig.model_validate(bad)
    bad = copy.deepcopy(raw)
    del bad["reach"]["global"]
    with pytest.raises(ValueError):
        SeverityConfig.model_validate(bad)
    with pytest.raises(ValueError):
        SeverityConfig.model_validate({**raw, "typo_key": 1})
    from eventshock.assessment.config import load_severity_config

    with pytest.raises(ConfigError):
        load_severity_config(CONFIG_DIR.parent / "docs")  # no severity.yaml there


def test_every_judgement_parameter_is_documented_in_the_config() -> None:
    text = (CONFIG_DIR / "severity.yaml").read_text()
    for must in ("NOT a forecast", "judgement", "fixed before", "magnitude:", "reach:", "certainty:", "direction:", "regime:", "novelty:"):
        assert must in text
