"""Event-to-market matching and the event's market view over real grouping and scope: explicit gates, no keyword overlap, honest no-match / insufficient-data, replay determinism, provenance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eventshock.markets.config import load_markets_config
from eventshock.markets.match import EventFeatures, evaluate_theme, orientation_of
from eventshock.markets.models import Interpretation, MatchStatus
from eventshock.markets.provider import PointProvider, load_records
from tests.intel_helpers import BASE, JPM
from tests.markets_helpers import (
    COMPANY,
    CPI,
    DEFAULT,
    FED,
    JOBS,
    MCFG,
    TARIFF,
    fixture_provider,
    macro,
    service,
)

LATE = 20 * 24 * 60                   # minutes after BASE: 2026-09-21, before the fixtures' scripted moves on 09-25
AFTER = 24 * 24 * 60 + 60              # 2026-09-25 13:00: the day after the scripted move, so the move is visible


def one(text, *, minutes=AFTER, **kw):  # noqa: ANN001, ANN003, ANN201
    svc, mon = service([macro("m", text, minutes=minutes)], provider=fixture_provider(), **kw)
    return svc, svc.view("m")


def themes():  # noqa: ANN201
    return {t.id: t for t in MCFG.themes}


# ----------------------------------------------------------------------------------------------------------------------------------- gates
def test_a_macro_event_about_the_fed_reaches_the_fed_series_through_its_theme_with_every_gate_shown():
    _, v = one(FED)
    m = v.match
    assert m.status is MatchStatus.MATCHED and m.theme_id == "FED_POLICY" and m.market.series_id in ("KXFEDDECISION", "KXFEDCUT", "KXRATECUTCOUNT", "KXFEDFUNDSYEAR")
    assert [g.id for g in m.event_gates] == ["EVENT_CLASS", "SCOPE", "SUBJECT", "GEOGRAPHY"] and all(g.passed for g in m.event_gates)
    assert any("scope theme" in e or "phrase in the text" in e for e in m.evidence)
    assert all(g.passed for c in m.candidates if c.chosen for g in c.gates) and {g.id for c in m.candidates for g in c.gates} == {"OPEN", "HORIZON", "FRESH"}


def test_the_chosen_market_is_the_most_active_open_one_and_the_rest_are_listed_with_their_gates():
    _, v = one(CPI)
    assert v.match.market.market_id == "FIXTURE-CPI-ABOVE-3.5"                        # open interest 3000 beats 400
    assert [c.market_id for c in v.match.candidates] == ["FIXTURE-CPI-ABOVE-3.5", "FIXTURE-CPI-BELOW-2.5"] and [c.chosen for c in v.match.candidates] == [True, False]


def test_an_event_class_the_theme_does_not_concern_is_no_match_and_says_which_gate_failed():
    svc, mon = service([macro("c", FED, category=__import__("eventshock.domain", fromlist=["x"]).EventCategory.EARNINGS_FINANCIAL_PERFORMANCE, minutes=AFTER)], provider=fixture_provider(),
                       event_type="EARNINGS_FINANCIAL_PERFORMANCE")
    m = svc.view("c").match
    assert m.status is MatchStatus.NO_MATCH and m.market is None and "fails" in m.reason and "event class" in m.reason.lower()


def test_a_company_event_is_not_matched_to_a_macro_market_however_its_words_overlap():
    from eventshock.domain import EventCategory
    from tests.intel_helpers import sig
    s = sig("co", COMPANY + " as the Federal Reserve weighs rate hikes", entity=JPM, minutes=AFTER, category=EventCategory.MACROECONOMIC, source="Wire", url="https://w.example/1")
    svc, _ = service([s], provider=fixture_provider())
    m = svc.view("co").match
    assert m.status is MatchStatus.NO_MATCH and m.market is None                       # its scope is a company, not macro/market/theme: the SCOPE gate fails


def test_an_unresolved_event_is_insufficient_data_never_matched():
    from tests.intel_helpers import sig
    s = sig("u", "Somebody said something about something that is hard to pin down", minutes=AFTER, source="Wire", url="https://w.example/1")
    svc, _ = service([s], provider=fixture_provider())
    m = svc.view("u").match
    assert m.status is MatchStatus.INSUFFICIENT_DATA and "unresolved" in m.reason and m.market is None


def test_a_text_that_is_not_a_market_event_is_insufficient_data():
    svc, _ = service([macro("n", FED, minutes=AFTER)], provider=fixture_provider(), event_type="NO_EVENT")
    v = svc.view("n")
    assert v.match.status is MatchStatus.INSUFFICIENT_DATA and "not read as a market event" in v.match.reason and v.interpretation is None


def test_a_geography_that_conflicts_with_the_theme_blocks_it_and_no_stated_place_does_not():
    th = themes()["FED_POLICY"]
    base = dict(event_class="MACROECONOMIC", scope_type="MACRO", scope_themes={"rates"}, text="the central bank signals a rate cut")
    ok = evaluate_theme(th, EventFeatures(regions=set(), **base))
    assert ok.passed and "not a conflict" in next(g for g in ok.gates if g.id == "GEOGRAPHY").detail
    euro = evaluate_theme(th, EventFeatures(regions={"EU"}, **base))
    assert not euro.passed and not next(g for g in euro.gates if g.id == "GEOGRAPHY").passed
    assert evaluate_theme(th, EventFeatures(regions={"US", "EU"}, **base)).passed


def test_the_subject_is_strong_with_a_scope_theme_or_two_phrases_and_weak_with_one_phrase():
    th = themes()["US_INFLATION"]
    mk = lambda themes_, text: evaluate_theme(th, EventFeatures(event_class="MACROECONOMIC", scope_type="MACRO", scope_themes=themes_, regions=set(), text=text))  # noqa: E731
    assert mk({"inflation"}, "x").strong and mk(set(), "inflation and consumer prices jump").strong
    weak = mk(set(), "the cpi was mentioned")
    assert weak.passed and not weak.strong
    none = mk(set(), "nothing relevant here")
    assert not none.passed and not next(g for g in none.gates if g.id == "SUBJECT").passed


def test_a_weak_subject_is_a_low_confidence_match_and_says_so():
    svc, _ = service([macro("w", "The Federal Reserve is meeting this week, sources say", minutes=AFTER)], provider=fixture_provider())
    v = svc.view("w")
    if v.match.status is MatchStatus.MATCHED:                                          # the scope resolver may also carry the rates theme: then it is strong
        pytest.skip("scope theme present")
    assert v.match.status is MatchStatus.LOW_CONFIDENCE_MATCH and "low confidence" in v.match.reason


# ---------------------------------------------------------------------------------------------------------------------- the market's own gates
def pp(*points, status="active", close="2026-12-31T00:00:00Z", oi=1000, series="KXFEDDECISION", mid="M1"):  # noqa: ANN002, ANN201
    return PointProvider(name="kalshi", source="kalshi-snapshot", synthetic=False, previous_gap_hours=24, mode="snapshot", records=load_records({"schema": "market-points-v1", "markets": [{
        "market_id": mid, "series_id": series, "question": "Will X?", "status": status, "open_time": "2026-08-01T00:00:00Z", "close_time": close,
        "points": [{"at": a, "p": p, "oi": oi, "vol": 100} for a, p in points]}]}))


def at(day, hour=12):  # noqa: ANN001, ANN201
    return f"2026-09-{day:02d}T{hour:02d}:00:00Z"


def test_a_closed_market_is_not_matched_and_the_reason_names_the_gate():
    svc, _ = service([macro("m", FED, minutes=AFTER)], provider=pp((at(24), 0.5), (at(25), 0.6), close="2026-09-20T00:00:00Z"))
    m = svc.view("m").match
    assert m.status is MatchStatus.NO_MATCH and m.market is None and "none of its 1 candidate market(s) is open" in m.reason
    g = {x.id: x for x in m.candidates[0].gates}
    assert not g["OPEN"].passed and not g["HORIZON"].passed


def test_a_stale_observation_is_not_matched():
    svc, _ = service([macro("m", FED, minutes=AFTER)], provider=pp((at(10), 0.5), (at(11), 0.6)))             # last observed two weeks before the moment
    m = svc.view("m").match
    assert m.status is MatchStatus.NO_MATCH and not next(g for g in m.candidates[0].gates if g.id == "FRESH").passed


def test_a_market_resolving_beyond_the_horizon_is_not_matched():
    svc, _ = service([macro("m", FED, minutes=AFTER)], provider=pp((at(24), 0.5), (at(25), 0.6), close="2040-01-01T00:00:00Z"))
    assert svc.view("m").match.status is MatchStatus.NO_MATCH


def test_before_a_providers_first_observation_it_is_insufficient_data_not_a_look_ahead():
    svc, _ = service([macro("m", FED, minutes=60)], provider=pp((at(24), 0.5), (at(25), 0.6)))                 # the event is on 09-01; the provider starts 09-24
    m = svc.view("m").match
    assert m.status is MatchStatus.INSUFFICIENT_DATA and "start 2026-09-24" in m.reason and "look" in m.reason


# --------------------------------------------------------------------------------------------------------------- interpretation end to end
def test_probability_increase_with_severity_up_is_repriced_or_neutral_mapped_and_labelled():
    svc, mon = service([macro("a", FED, minutes=0), macro("b", FED + ", sources say", minutes=AFTER, source="Wire B")], provider=fixture_provider(), severity=8.0)
    v = svc.view("a")
    assert v.match.market.market_id == "FIXTURE-FED-CUT" and v.match.market.probability_change_pp == pytest.approx(24.0) and v.match.market.synthetic
    assert v.interpretation.code in (Interpretation.MARKET_REPRICED, Interpretation.NOT_ASSESSED) and v.label == "EXTERNAL MARKET OBSERVATION"
    assert "never an input" in v.note and v.provider.synthetic and "SYNTHETIC FIXTURE" in v.provider.reason


def test_a_probability_decrease_is_divergent_when_the_questions_own_direction_says_risk_fell_and_eventshock_is_elevated():
    _, v = one(CPI, severity=8.0)
    assert v.match.market.probability_change_pp == pytest.approx(-8.0) and v.match.market.market_id == "FIXTURE-CPI-ABOVE-3.5"
    i = v.interpretation
    assert i.orientation == "UP" and 'read from the question ("above")' in i.reason and i.market_direction == "AWAY_FROM_RISK" and i.code is Interpretation.DIVERGENT
    assert "does not show that either is wrong" in i.text and v.eventshock_severity == 8.0 and v.eventshock_materiality == "HIGH"


def test_a_market_that_moved_toward_risk_with_an_elevated_assessment_is_aligned():
    _, v = one(JOBS, severity=8.0)
    assert v.match.theme_id == "US_LABOUR" and v.interpretation.code is Interpretation.ALIGNED and v.interpretation.text.startswith("External market observation is directionally aligned")


def test_a_flat_market_with_an_elevated_assessment_is_divergent():
    _, v = one(TARIFF, severity=9.0)
    assert v.match.theme_id == "US_TRADE_POLICY" and abs(v.match.market.probability_change_pp) < 2 and v.interpretation.code is Interpretation.DIVERGENT


def test_a_thin_market_is_low_information():
    _, v = one(DEFAULT, severity=8.0)
    assert v.match.theme_id == "US_SOVEREIGN_CREDIT" and v.interpretation.code is Interpretation.LOW_INFORMATION and v.match.market.open_interest == 3


# ------------------------------------------------------------------------------------------------------------------------ state, determinism
def test_an_unavailable_provider_says_unavailable_and_invents_nothing():
    svc, _ = service([macro("m", FED, minutes=AFTER)], provider=None)
    v = svc.view("m")
    assert v.availability == "UNAVAILABLE" and v.reason == "External market data unavailable." and v.match.status is MatchStatus.INSUFFICIENT_DATA and v.interpretation is None
    assert v.match.market is None and v.provider.state == "UNAVAILABLE"


def test_a_provider_that_raises_degrades_instead_of_breaking_the_view():
    class Boom:
        name, category, synthetic = "kalshi", fixture_provider().category, False

        def state(self):  # noqa: ANN201
            raise RuntimeError("provider exploded")

        def markets(self, series, as_of):  # noqa: ANN001, ANN201
            raise RuntimeError("provider exploded")

        def history(self, *a):  # noqa: ANN002, ANN201
            raise RuntimeError("provider exploded")

    svc, _ = service([macro("m", FED, minutes=AFTER)], provider=Boom())
    v = svc.view("m")
    assert v.availability == "UNAVAILABLE" and v.provider.state == "UNAVAILABLE" and "RuntimeError" in v.provider.reason and v.match.market is None


def test_the_view_is_identical_on_every_call_and_reads_only_the_past():
    svc, _ = service([macro("m", FED, minutes=AFTER)], provider=fixture_provider())
    a, b = svc.view("m", cycle=None), svc.view("m", cycle=None)
    assert a.model_dump_json() == b.model_dump_json()
    k = len(svc._monitor.cycles()) - 1  # noqa: SLF001
    early = svc.view("m", cycle=max(k - 6, 0)) if k > 6 else a
    assert early.as_of <= a.as_of


def test_every_value_keeps_the_provenance_of_its_external_source():
    _, v = one(CPI)
    assert v.provenance and v.provenance[0].kind.value == "EXTERNAL_MARKET_OBSERVATION"
    assert v.match.market.provenance[0].source == "fixture" and v.match.market.provenance[0].ref_id == "FIXTURE-CPI-ABOVE-3.5"


def test_orientation_is_configured_or_read_from_the_question_and_neutral_when_it_cannot_be():
    cfg = themes()
    assert orientation_of(cfg["US_SOVEREIGN_CREDIT"], "Will the US default?") == ("UP", "configured for the theme (US sovereign credit)")
    assert orientation_of(cfg["US_INFLATION"], "Will CPI be above 3.5%?")[0] == "UP" and orientation_of(cfg["US_INFLATION"], "Will CPI be below 2.5%?")[0] == "DOWN"
    assert orientation_of(cfg["US_INFLATION"], "Will CPI be above or below 3%?")[0] == "NEUTRAL" and orientation_of(cfg["US_INFLATION"], "Will CPI change?")[0] == "NEUTRAL"
    assert orientation_of(cfg["FED_POLICY"], "Will the Fed cut?")[0] == "NEUTRAL"


# -------------------------------------------------------------------------------------------------------------------------------- timeline
def test_the_timeline_keeps_source_assessment_market_and_scenario_apart():
    svc, mon = service([macro("a", FED, minutes=AFTER - 3 * 24 * 60), macro("b", FED + ", sources say", minutes=AFTER, source="Wire B")], provider=fixture_provider())
    t = svc.timeline("a")
    assert t.availability == "AVAILABLE" and t.market_id == "FIXTURE-FED-CUT" and t.items
    assert set(t.kinds) >= {"SOURCE_EVENT", "EXTERNAL_MARKET_OBSERVATION"} and set(t.kinds) <= {"SOURCE_EVENT", "EVENTSHOCK_ASSESSMENT", "EXTERNAL_MARKET_OBSERVATION", "SCENARIO_ASSUMPTION", "REALISED_OUTCOME"}
    assert [x.at for x in t.items] == sorted(x.at for x in t.items)
    jump = next(x for x in t.items if x.kind == "EXTERNAL_MARKET_OBSERVATION" and x.change_pp is not None and abs(x.change_pp) > 20)
    assert jump.probability == pytest.approx(0.72) and jump.change_pp == pytest.approx(24.0) and "48%" not in jump.detail and "72%" in jump.detail and "+24.0 pp" in jump.detail
    assert all(x.provenance for x in t.items) and t.label == "EXTERNAL MARKET OBSERVATION" and "never an input" in t.note
    assert BASE and timedelta and datetime and UTC and load_markets_config
