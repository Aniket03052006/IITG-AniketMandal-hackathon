from __future__ import annotations

import pytest

from eventshock.ingestion.fetch import FetchError
from eventshock.ingestion.fomc import fetch_fomc, parse_current, parse_historical

CURRENT = """
<h4>2025 FOMC Meetings</h4>
<div class="fomc-meeting__month col"><strong>January</strong></div><div class="fomc-meeting__date col">28-29</div>
<div class="fomc-meeting__month col"><strong>March</strong></div><div class="fomc-meeting__date col">18-19*</div>
<div class="fomc-meeting__month col"><strong>Apr/May</strong></div><div class="fomc-meeting__date col">30-1</div>
<div class="fomc-meeting__month col"><strong>June</strong></div><div class="fomc-meeting__date col">22 (notation vote)</div>
<h4>2024 FOMC Meetings</h4>
<div class="fomc-meeting__month col"><strong>January</strong></div><div class="fomc-meeting__date col">30-31</div>
"""

HIST = ("<p>January 28-29 Meeting - 2020</p><p>March 2 (unscheduled) Meeting - 2020</p><p>March 17-18 (cancelled) Meeting - 2020</p>"
        "<p>April 30-May 1 Meeting - 2020</p><p>December 15-16 Meeting - 2019</p>")


def test_current_page_decision_is_the_last_day_and_cross_month_rolls_over():
    rows = parse_current(CURRENT)
    assert [r["decision_date"] for r in rows] == ["2025-01-29", "2025-03-19", "2025-05-01", "2024-01-31"]  # the notation vote is not a meeting
    assert rows[1]["projections"] is True and rows[0]["projections"] is False and all(r["scheduled"] for r in rows)


def test_historical_page_flags_unscheduled_and_drops_cancelled_and_other_years():
    rows = parse_historical(HIST, 2020)
    got = {r["decision_date"]: r["scheduled"] for r in rows}
    assert got == {"2020-01-29": True, "2020-03-02": False, "2020-05-01": True}


def test_mismatched_cells_are_an_error_not_a_guess():
    with pytest.raises(FetchError, match="cells"):
        parse_current('<h4>2025 FOMC Meetings</h4><div class="fomc-meeting__month"><strong>May</strong></div>')


def test_fetch_uses_the_cache_and_refuses_empty_years(tmp_path):
    (tmp_path / "fomchistorical2019.htm").write_text("<p>December 10-11 Meeting - 2019</p>")
    (tmp_path / "fomchistorical2020.htm").write_text(HIST)
    (tmp_path / "fomccalendars.htm").write_text(CURRENT)

    def offline(url, timeout):
        raise FetchError("no network in this test")

    rows = fetch_fomc(2019, 2025, raw_dir=tmp_path, transport=offline, sleep=lambda s: None)
    assert [r["decision_date"] for r in rows] == ["2019-12-11", "2020-01-29", "2020-03-02", "2020-05-01", "2024-01-31", "2025-01-29",
                                                  "2025-03-19", "2025-05-01"]
    (tmp_path / "fomchistorical2018.htm").write_text("<p>nothing here</p>")
    with pytest.raises(FetchError, match="no FOMC meetings"):
        fetch_fomc(2018, 2018, raw_dir=tmp_path, transport=offline, sleep=lambda s: None)
