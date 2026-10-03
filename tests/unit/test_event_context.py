from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from eventshock.config import REPO_ROOT
from eventshock.modeling.leakage import (
    FEATURE_REGISTRY,
    availability_class,
    calendar_future_invariance,
    check_features,
)
from eventshock.pipeline.event_context import (
    ISSUER_CALENDAR,
    MARKET_CALENDAR,
    EventCalendar,
    filing_events,
    session_dates,
)
from eventshock.pipeline.impact_features import ALL_FEATURES
from eventshock.pipeline.impact_features_v2 import ALL_FEATURES_V2, RUNGS_V2, feature_names_v2

ITEMS = yaml.safe_load((REPO_ROOT / "configs" / "sec_items.yaml").read_text(encoding="utf-8"))


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def filing(tk, when, items, form="8-K", acc=None):
    return {"ticker": tk, "acceptance_utc": when, "accession": acc or f"{tk}-{when}", "form": form, "items": items}


# AAA reports results each year around 1 May (a Thursday after the close), plus some other filings
FILINGS = [
    filing("AAA", "2022-04-28T20:10:00Z", ["2.02", "9.01"]),
    filing("AAA", "2023-04-27T20:05:00Z", ["2.02", "9.01"]),
    filing("AAA", "2023-08-03T20:05:00Z", ["2.02", "9.01"]),
    filing("AAA", "2024-02-01T21:00:00Z", ["5.02"]),
    filing("AAA", "2024-02-01T21:30:00Z", ["9.01"]),                      # exhibit-only: never an event
    filing("AAA", "2024-02-02T12:00:00Z", ["1.01", "9.01"]),
    filing("AAA", "2024-02-02T12:30:00Z", [], form="10-Q"),
    filing("BBB", "2024-02-02T11:59:00Z", ["2.02"]),
]
FOMC = [{"decision_date": "2024-01-31", "scheduled": True}, {"decision_date": "2024-03-15", "scheduled": False}]


@pytest.fixture
def cal() -> EventCalendar:
    return EventCalendar(FILINGS, FOMC, ITEMS)


def test_only_filings_strictly_before_the_report_count(cal):
    f = cal.issuer_features("AAA", at("2024-02-02T12:00:00"), "2024-02-02", "2024-02-05")
    # the 1.01 filed at exactly 12:00:00 is not before the report; the earlier 5.02 (15h ago) is, the exhibit-only one is ignored
    assert f["f8k_count_24h"] == 1 and f["f8k_leadership_24h"] == 1 and f["f8k_deal_24h"] == 0
    assert f["f8k_hours_since_last"] == pytest.approx(15.0)
    later = cal.issuer_features("AAA", at("2024-02-02T12:00:01"), "2024-02-02", "2024-02-05")
    assert later["f8k_deal_24h"] == 1 and later["f8k_count_24h"] == 2 and later["f8k_hours_since_last"] == pytest.approx(1 / 3600)


def test_periodic_reports_and_other_issuers_never_count_as_recent_8ks(cal):
    f = cal.issuer_features("AAA", at("2024-02-02T13:00:00"), "2024-02-02", None)
    assert f["f8k_count_24h"] == 2  # 5.02 and 1.01 only: not the 10-Q, not BBB's earnings 8-K
    assert f["f8k_earnings_24h"] == 0
    assert cal.issuer_features("BBB", at("2024-02-02T13:00:00"), "2024-02-02", None)["f8k_earnings_24h"] == 1


def test_expected_earnings_is_projected_from_earlier_years_only(cal):
    # two days before the 2024 release that last year's date (27 Apr 2023, +364d = 25 Apr 2024) projects
    f = cal.issuer_features("AAA", at("2024-04-23T15:00:00"), None, None)
    assert f["earn_days_to_expected"] == pytest.approx(2.0 + (5 * 60 + 5) / 1440, abs=0.001) and f["earn_window"] == 0.0
    near = cal.issuer_features("AAA", at("2024-04-25T09:00:00"), None, None)
    assert near["earn_window"] == 1.0 and abs(near["earn_days_to_expected"]) < 1
    assert near["earn_days_since_last"] == 120.0  # capped: more than 120 days since the last release
    recent = cal.issuer_features("AAA", at("2023-08-10T20:05:00"), None, None)
    assert recent["earn_days_since_last"] == pytest.approx(7.0)


def test_no_history_means_unknown_not_zero(cal):
    f = cal.issuer_features("AAA", at("2022-04-01T12:00:00"), None, None)
    assert f["earn_days_to_expected"] != f["earn_days_to_expected"] and f["earn_days_since_last"] != f["earn_days_since_last"]
    ghost = cal.issuer_features("ZZZ", at("2024-02-02T13:00:00"), None, None)
    assert ghost["f8k_count_24h"] == 0 and ghost["f8k_hours_since_last"] != ghost["f8k_hours_since_last"]
    assert not cal.has_issuer("ZZZ")


def test_fomc_flags_use_scheduled_meetings_on_the_reaction_sessions(cal):
    assert cal.fomc_features("2024-01-31", "2024-02-01") == {"fomc_s0": 1.0, "fomc_s1": 0.0}
    assert cal.fomc_features("2024-01-30", "2024-01-31") == {"fomc_s0": 0.0, "fomc_s1": 1.0}
    assert cal.fomc_features("2024-03-15", None)["fomc_s0"] == 0.0   # unscheduled meetings were not known in advance
    nan = cal.fomc_features(None, None)
    assert nan["fomc_s0"] != nan["fomc_s0"]


def test_session_dates_handle_the_calendar_edge():
    dates = ["2024-01-02", "2024-01-03"]
    assert session_dates(dates, 0) == ("2024-01-02", "2024-01-03") and session_dates(dates, 1) == ("2024-01-03", None)
    assert session_dates(dates, 2) == (None, None)


def test_calendar_future_invariance_passes_and_would_catch_a_leak(cal):
    events = [("AAA", at("2024-02-02T12:00:00"), "2024-02-02", "2024-02-05"), ("AAA", at("2024-04-23T15:00:00"), "2024-04-24", "2024-04-25"),
              ("BBB", at("2024-02-02T11:00:00"), "2024-02-02", "2024-02-05"), (None, at("2024-01-31T09:00:00"), "2024-01-31", "2024-02-01")]
    assert not [f for f in calendar_future_invariance(cal, events) if f.severity == "ERROR"]

    class Leaky(EventCalendar):  # a feature that peeks at the next filing would move when the future is replaced
        def issuer_features(self, ticker, t, s0_date, s1_date):
            out = super().issuer_features(ticker, t, s0_date, s1_date)
            nxt = [f for f in self._filings.get(ticker, []) if f.acceptance >= t]
            out["f8k_count_24h"] = float(len(nxt))
            return out

    leaky = Leaky(FILINGS, FOMC, ITEMS)
    res = calendar_future_invariance(leaky, events[:1])
    assert any(f.severity == "ERROR" for f in res)


def test_every_calendar_feature_is_registered_with_a_class_and_post_event_ones_are_refused():
    assert set(ISSUER_CALENDAR) <= set(FEATURE_REGISTRY) and set(MARKET_CALENDAR) <= set(FEATURE_REGISTRY)
    assert {availability_class(n) for n in ISSUER_CALENDAR} == {"a", "b"}
    assert not [f for f in check_features(ALL_FEATURES_V2) if f.severity == "ERROR"]
    for banned in ("eps_surprise", "filing_at_or_after", "later_periodic_report", "filing_items_same_event"):
        assert any(f.severity == "ERROR" for f in check_features([banned])), banned


def test_v2_schema_extends_v1_without_touching_it():
    assert set(ALL_FEATURES) < set(ALL_FEATURES_V2)
    for scope in ("ISSUER", "MARKET"):
        r2, r2s, r3, r3s, r3h = (feature_names_v2(scope, r) for r in RUNGS_V2)
        assert set(r2) < set(r2s) and set(r2) < set(r3) and set(r3s) == set(r3) | set(r2s) and set(r3h) >= set(r3s)
        assert r2 == [n for n in r2s if n in r2] and len(set(r3h)) == len(r3h)
    with pytest.raises(ValueError):
        feature_names_v2("ISSUER", "R9")


def test_filing_events_exclude_exhibit_only_and_periodic(cal):
    assert [f.accession for f in filing_events(cal, "AAA")][-2:] == ["AAA-2024-02-01T21:00:00Z", "AAA-2024-02-02T12:00:00Z"]
    assert all(timedelta(0) < f.acceptance - at("2022-01-01T00:00:00") for f in filing_events(cal, "AAA"))


def test_committed_calendar_loads_and_has_the_expected_shape():
    d = REPO_ROOT / "data" / "events"
    if not (d / "sec_filings.jsonl").is_file():
        pytest.skip("run `make events-calendar` first")
    c = EventCalendar.load(Path(d), REPO_ROOT / "configs" / "sec_items.yaml")
    assert c.has_issuer("AAPL") and c.has_issuer("SHEL")
    # Apple's Q2 FY24 results 8-K was accepted 2024-05-03T00:30:34Z (8:30 pm ET on 2 May): not yet public at 22:00Z, public at 01:00Z
    before = c.issuer_features("AAPL", at("2024-05-02T22:00:00"), "2024-05-03", "2024-05-06")
    after = c.issuer_features("AAPL", at("2024-05-03T01:00:00"), "2024-05-03", "2024-05-06")
    assert before["f8k_earnings_24h"] == 0.0 and after["f8k_earnings_24h"] == 1.0
    assert before["earn_window"] == 1.0 and after["f8k_hours_since_last"] < 1
