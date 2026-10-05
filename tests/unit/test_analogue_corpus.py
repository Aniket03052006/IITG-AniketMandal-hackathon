"""Stage 8: which past reports may serve as analogues (clock trust) and how documents are chosen per scope."""

from __future__ import annotations

import json

import pytest

from eventshock.config import ConfigError
from eventshock.retrieval.corpus import TRUSTED_TIMINGS, _pick_rows, clock_of, load_corpus


@pytest.mark.parametrize("origin,timing,expected", [
    ("SOURCE", "PRE_OPEN", "TRUSTED"), ("SOURCE", "OFF_HOURS", "TRUSTED"),
    ("SOURCE", "IN_SESSION", "WEAK"),            # part of the move may precede the report
    ("GDELT_FIRST_SEEN", "OFF_HOURS", "WEAK"),   # a crawl time, not a publication time
    ("SOURCE_DATE_ONLY", "DATE_ONLY", "WEAK"), ("GDELT_FIRST_SEEN", "FIRST_SEEN", "WEAK"),
])
def test_only_exact_publisher_times_outside_trading_hours_are_trusted(origin, timing, expected):
    assert clock_of(origin, timing) == expected


def test_the_trusted_timings_are_exactly_those_with_a_whole_reaction_window_after_the_report():
    assert set(TRUSTED_TIMINGS) == {"PRE_OPEN", "OFF_HOURS"}


def row(i, scope, episode, published, *, news=1.0, ticker="AAA"):
    return {"id": f"d{i}", "scope": scope, "episode": episode, "published_at": published, "is_news": news, "ticker": ticker, "s0": i, "text": f"t{i}"}


def test_issuer_episodes_keep_their_earliest_news_report_and_market_keeps_every_document(tmp_path):
    rows = [row(1, "ISSUER", "AAA|2024-01-02", "2024-01-02T21:00:00+00:00"), row(2, "ISSUER", "AAA|2024-01-02", "2024-01-02T20:00:00+00:00"),
            row(3, "ISSUER", "AAA|2024-01-02", "2024-01-02T19:00:00+00:00", news=0.0),       # a tweet: never an analogue
            row(4, "MARKET", "MKT|2024-01-03", "2024-01-03T21:00:00+00:00", ticker=None), row(5, "MARKET", "MKT|2024-01-03", "2024-01-03T22:00:00+00:00", ticker=None),
            row(6, "MARKET", "MKT|2024-01-03", "2024-01-03T23:00:00+00:00", news=0.0, ticker=None)]
    p = tmp_path / "t.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = _pick_rows(p)
    assert [r["id"] for r in out] == ["d2", "d4", "d5"]


def test_ties_on_time_are_broken_by_id_so_the_corpus_is_reproducible(tmp_path):
    rows = [row(9, "ISSUER", "AAA|x", "2024-01-02T21:00:00+00:00"), row(3, "ISSUER", "AAA|x", "2024-01-02T21:00:00+00:00")]
    p = tmp_path / "t.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert [r["id"] for r in _pick_rows(p)] == ["d3"]


def test_a_missing_corpus_says_how_to_build_it(tmp_path):
    with pytest.raises(ConfigError, match="analogue-corpus"):
        load_corpus(tmp_path / "nope.jsonl")
