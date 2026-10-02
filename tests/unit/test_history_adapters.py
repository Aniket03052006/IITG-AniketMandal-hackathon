from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import pytest

from eventshock.config import REPO_ROOT
from eventshock.domain import SourceType, TimestampOrigin
from eventshock.ingestion.base import RejectCode, Rejected
from eventshock.ingestion.history import (
    HeadlinesAdapter,
    StockTweetsAdapter,
    TopTweetsAdapter,
    parse_headline_time,
)
from tests.pipe_helpers import AS_OF, jsonl_path, run

KW = dict(snapshot_id="h", as_of=AS_OF)


def parse(adapter, tmp_path, *objs):
    p = jsonl_path(tmp_path, "h.jsonl", "\n".join(o if isinstance(o, str) else json.dumps(o) for o in objs) + "\n")
    return list(adapter.read(p, "h.jsonl"))


class TestHeadlineTimes:
    def test_cnbc_has_a_time_and_is_converted_from_eastern(self):
        dt, origin = parse_headline_time("cnbc", " 7:51  PM ET Fri, 17 July 2020")
        assert origin is TimestampOrigin.SOURCE and dt == datetime(2020, 7, 17, 23, 51, tzinfo=UTC)  # EDT = UTC-4

    def test_winter_time_uses_est(self):
        dt, _ = parse_headline_time("cnbc", "12:05  AM ET Mon, 6 January 2020")
        assert dt == datetime(2020, 1, 6, 5, 5, tzinfo=UTC)

    def test_reuters_and_guardian_are_date_only(self):
        assert parse_headline_time("reuters", "Jul 18 2020") == (datetime(2020, 7, 18, tzinfo=UTC), TimestampOrigin.SOURCE_DATE_ONLY)
        assert parse_headline_time("guardian", "18-Jul-20") == (datetime(2020, 7, 18, tzinfo=UTC), TimestampOrigin.SOURCE_DATE_ONLY)

    @pytest.mark.parametrize("outlet,raw", [("reuters", "Smarch 40 2020"), ("cnbc", "yesterday"), ("guardian", ""),
                                            ("cnbc", None), ("bbc", "Jul 18 2020"), ("reuters", 20200718)])
    def test_garbage_is_none(self, outlet, raw):
        assert parse_headline_time(outlet, raw) is None


class TestAdapters:
    def test_stock_tweet(self, tmp_path):
        d, = parse(StockTweetsAdapter(**KW), tmp_path, {"row": 3, "date": "2022-09-29 23:41:16+00:00", "text": "$TSLA to the moon",
                                                         "ticker": "TSLA", "company": "Tesla, Inc."})
        assert d.id == "stw-3" and d.source_type is SourceType.SOCIAL and d.published_at == datetime(2022, 9, 29, 23, 41, 16, tzinfo=UTC)
        assert d.raw_metadata["timestamp_origin"] == "SOURCE" and d.raw_metadata["x_ticker"] == "TSLA"

    def test_headline_uses_description_as_body(self, tmp_path):
        d, = parse(HeadlinesAdapter(**KW), tmp_path, {"outlet": "reuters", "row": 1, "time": "Jul 18 2020",
                                                       "text": "Apple unveils new phone", "description": "Details of the launch."})
        assert d.source == "reuters.com" and d.body == "Details of the launch." and d.raw_metadata["timestamp_origin"] == "SOURCE_DATE_ONLY"

    def test_top_tweet_unix_time(self, tmp_path):
        d, = parse(TopTweetsAdapter(**KW), tmp_path, {"tweet_id": "9", "post_date": 1420070457, "text": "$AAPL up", "tickers": ["AAPL"]})
        assert d.published_at == datetime(2015, 1, 1, 0, 0, 57, tzinfo=UTC) and d.id == "ttw-9"

    @pytest.mark.parametrize("adapter,rec,code", [
        (StockTweetsAdapter, {"row": 1, "date": "not a date", "text": "x y z"}, RejectCode.BAD_TIMESTAMP),
        (StockTweetsAdapter, {"row": 1, "date": "2022-01-01", "text": "   "}, RejectCode.EMPTY_TEXT),
        (StockTweetsAdapter, {"date": "2022-01-01", "text": "ok text"}, RejectCode.SCHEMA),
        (StockTweetsAdapter, {"row": 1, "date": "2090-01-01 00:00:00+00:00", "text": "from the future"}, RejectCode.FUTURE_TIMESTAMP),
        (HeadlinesAdapter, {"outlet": "bbc", "row": 1, "time": "Jul 18 2020", "text": "x"}, RejectCode.SCHEMA),
        (HeadlinesAdapter, {"outlet": "cnbc", "row": 1, "time": "?", "text": "A headline"}, RejectCode.BAD_TIMESTAMP),
        (HeadlinesAdapter, {"outlet": "reuters", "row": 1, "time": "Jul 18 2020", "text": ""}, RejectCode.EMPTY_TEXT),
        (TopTweetsAdapter, {"tweet_id": "1", "post_date": None, "text": "hello there"}, RejectCode.BAD_TIMESTAMP),
        (TopTweetsAdapter, {"tweet_id": "1", "post_date": "1420070457", "text": "hello there"}, RejectCode.BAD_TIMESTAMP),
        (TopTweetsAdapter, {"tweet_id": "", "post_date": 1420070457, "text": "hello there"}, RejectCode.SCHEMA),
    ])
    def test_malformed_records_are_rejected_with_a_code(self, tmp_path, adapter, rec, code):
        r, = parse(adapter(**KW), tmp_path, rec)
        assert isinstance(r, Rejected) and r.code is code

    def test_garbage_lines_never_raise(self, tmp_path):
        out = parse(StockTweetsAdapter(**KW), tmp_path, "not json", "[]", "null")
        assert all(isinstance(o, Rejected) for o in out)


def test_date_only_headlines_flow_through_the_pipeline_and_cluster_across_outlets():
    """Reuters + Guardian + CNBC on the same day about the same issuer: one story, trusted (date-level) clocks."""
    from datetime import timedelta

    from tests.pipe_helpers import doc

    a = doc("reuters-1", "Apple unveils new iPhone lineup at autumn event", source="reuters.com", hours=30, url=None,
            origin="SOURCE_DATE_ONLY")
    b = doc("guardian-1", "Apple unveils new iPhone lineup at autumn event", source="theguardian.com", hours=30, url=None,
            origin="SOURCE_DATE_ONLY")
    for d in (a, b):
        d.raw_metadata["domain"] = d.source
    res = run([a, b])
    s, = res.signals
    assert s.evidence.source_count == 2 and s.provenance.timestamp_origin is TimestampOrigin.SOURCE_DATE_ONLY
    assert AS_OF - s.document.published_at > timedelta(hours=1)


class TestSectorMix:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

    def test_keyword_mapping_first_match_wins_and_unmatched_is_other(self):
        import derive_sector_mix as d

        sectors = {"Technology": ["Electronics Stores"], "Consumer": ["Stores"], "Energy": ["Service Stations"]}
        assert d.sector_of("Electronics Stores", sectors) == "Technology"  # specific before generic
        assert d.sector_of("Shoe Stores", sectors) == "Consumer"
        assert d.sector_of("Legal Services", sectors) == "OTHER"

    def test_shipped_aggregate_is_sane_and_contains_no_transaction_rows(self):
        mix = json.loads((REPO_ROOT / "data" / "replay" / "sector_mix.json").read_text())
        assert abs(sum(mix["sector_share_of_mapped_spend"].values()) - 1) < 1e-3
        assert set(mix["sector_share_of_mapped_spend"]) == {"Energy", "Healthcare", "Technology", "Financials", "Industrials", "Consumer"}
        assert mix["mapped_share_of_spend"] > 0.9 and mix["rows_used"] > 10_000_000
        assert (REPO_ROOT / "data" / "replay" / "sector_mix.json").stat().st_size < 50_000

    def test_the_book_is_tilted_by_the_mix(self):
        mix = json.loads((REPO_ROOT / "data" / "replay" / "sector_mix.json").read_text())
        pf = json.loads((REPO_ROOT / "data" / "replay" / "portfolio.json").read_text())
        by = {}
        for a in pf["assets"]:
            by[a["sector"]] = by.get(a["sector"], 0) + a["market_value"]
        # the biggest spend sector is the biggest book sector, the smallest spend sector the smallest
        spend = mix["sector_share_of_mapped_spend"]
        assert max(by, key=by.get) == max(spend, key=spend.get)
        assert "transaction" in pf["description"].lower()
