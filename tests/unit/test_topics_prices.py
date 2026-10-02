from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.domain import EventCategory
from eventshock.ingestion.fetch import FetchError, fetch_tfn
from eventshock.ingestion.prices import (
    chart_url,
    fetch_prices,
    file_stem,
    parse_chart,
    read_price_csv,
    write_price_csv,
)
from eventshock.pipeline.topics import TopicMapping, load_topic_mapping

NO_SLEEP = lambda s: None  # noqa: E731


class TestTopicMapping:
    M = load_topic_mapping(REPO_ROOT / "configs")

    def test_all_twenty_topics_are_present_and_names_match_the_dataset_card(self):
        assert len(self.M.topics) == 20 and self.M.topics[0].name == "Analyst Update" and self.M.topics[19].name == "Stock Movement"

    def test_every_event_class_is_reachable_and_some_topics_are_deliberately_unmapped(self):
        reached = {t.category for t in self.M.topics.values() if t.category}
        assert reached == set(EventCategory)
        assert {t.name for t in self.M.topics.values() if t.category is None} >= {"General News | Opinion"}

    def test_distribution_counts_unmapped_separately(self):
        assert self.M.distribution([5, 5, 9, 16]) == {"EARNINGS_FINANCIAL_PERFORMANCE": 2, "GEOPOLITICAL": 1, "UNMAPPED": 1}
        with pytest.raises(KeyError):
            self.M.category(99)

    def test_gaps_in_topic_ids_fail_loudly(self):
        with pytest.raises(ValueError, match="gaps"):
            TopicMapping.model_validate({"version": "1", "dataset": "d", "topics": {0: {"name": "a", "category": None},
                                                                                     2: {"name": "b", "category": None}}})

    def test_missing_file_fails_with_a_config_error(self, tmp_path):
        with pytest.raises(ConfigError):
            load_topic_mapping(tmp_path)

    def test_topic_fetch_parses_csv_and_rejects_wrong_schema(self):
        ok = lambda url, t: (200, b'text,label\n"$AAPL - Buy, said analyst",0\nHello,14\n')  # noqa: E731
        rows = fetch_tfn("train", kind="topic", transport=ok)
        assert rows[0] == {"split": "train", "row": 0, "text": "$AAPL - Buy, said analyst", "label": 0}
        with pytest.raises(FetchError, match="schema"):
            fetch_tfn("train", kind="topic", transport=lambda u, t: (200, b"a,b\n1,2\n"))
        with pytest.raises(ValueError):
            fetch_tfn("test", kind="topic")


def chart(ts, o, h, lo, c, v, adj=None):
    return {"chart": {"result": [{"timestamp": ts, "indicators": {
        "quote": [{"open": o, "high": h, "low": lo, "close": c, "volume": v}],
        **({"adjclose": [{"adjclose": adj}]} if adj else {})}}], "error": None}}


class TestPrices:
    def test_parse_drops_days_without_a_close_and_sorts(self):
        payload = chart([1700000000 + 86400, 1700000000, 1700000000 + 2 * 86400], [2, 1, None], [3, 2, None], [1, 1, None],
                        [2.5, 1.5, None], [100, 50, None], adj=[2.4, 1.4, None])
        rows, dropped = parse_chart(payload, "X")
        assert dropped == 1 and [r["close"] for r in rows] == [1.5, 2.5] and rows[0]["date"] < rows[1]["date"]
        assert rows[0]["adj_close"] == 1.4

    @pytest.mark.parametrize("payload", [{}, {"chart": None}, {"chart": {"result": None, "error": None}},
                                         {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data"}}}])
    def test_error_and_malformed_payloads_raise(self, payload):
        with pytest.raises(FetchError):
            parse_chart(payload, "X")

    def test_csv_round_trip_and_stem(self, tmp_path):
        rows, _ = parse_chart(chart([1700000000], [1], [2], [1], [1.5], [10]), "X")
        write_price_csv(tmp_path / "x.csv", rows)
        back = read_price_csv(tmp_path / "x.csv")
        assert back[0]["close"] == 1.5 and back[0]["volume"] == 10
        assert file_stem("^GSPC") == "_GSPC"
        assert "period1=" in chart_url("^TNX", datetime(2015, 1, 1, tzinfo=UTC), datetime(2016, 1, 1, tzinfo=UTC))

    def test_one_bad_symbol_does_not_stop_the_others_and_is_logged(self, tmp_path):
        good = json.dumps(chart([1700000000], [1], [2], [1], [1.5], [10])).encode()

        def transport(url, timeout):
            return (404, b"") if "BAD" in url else (200, good)

        res = fetch_prices(["AAA", "BAD", "CCC"], start=datetime(2015, 1, 1, tzinfo=UTC), end=datetime(2016, 1, 1, tzinfo=UTC),
                           out_dir=tmp_path, transport=transport, sleep=NO_SLEEP)
        assert res.failed == ["BAD"] and (tmp_path / "AAA.csv").exists() and (tmp_path / "CCC.csv").exists()
        assert not (tmp_path / "BAD.csv").exists()
        log = [json.loads(x) for x in (tmp_path / "prices.log.jsonl").read_text().split("\n") if x]
        assert {e["symbol"]: e["status"] for e in log} == {"AAA": "ok", "BAD": "error", "CCC": "ok"}


class TestKaggle:
    def make_zip(self, tmp_path, names=("a.csv",)):
        import zipfile
        p = tmp_path / "z.zip"
        with zipfile.ZipFile(p, "w") as z:
            for n in names:
                z.writestr(n, "x,y\n1,2\n")
        return p.read_bytes()

    def test_token_from_env_then_file_else_loud_error(self, tmp_path):
        from eventshock.ingestion.kaggle import find_token
        assert find_token({"KAGGLE_API_TOKEN": " tok "}, tmp_path) == "tok"
        (tmp_path / ".kaggle").mkdir()
        (tmp_path / ".kaggle" / "access_token").write_text("filetok\n")
        assert find_token({}, tmp_path) == "filetok"
        with pytest.raises(ConfigError, match="no Kaggle token"):
            find_token({}, tmp_path / "empty")

    def test_download_unpacks_discards_the_zip_skips_existing_and_never_leaks_the_token(self, tmp_path):
        from eventshock.ingestion.kaggle import download_dataset
        body = self.make_zip(tmp_path)
        seen = {}

        def dl(url, headers, dest, timeout):
            seen.update(url=url, headers=headers)
            dest.write_bytes(body)

        status, files = download_dataset("o/slug", tmp_path / "raw", "SECRET", downloader=dl)
        assert status == "downloaded" and files == ["a.csv"] and seen["headers"]["Authorization"] == "Bearer SECRET"
        assert not list((tmp_path / "raw").rglob("*.zip")) and "SECRET" not in seen["url"]
        assert download_dataset("o/slug", tmp_path / "raw", "SECRET", downloader=dl)[0] == "skipped"

    def test_bad_archives_are_refused(self, tmp_path):
        from eventshock.ingestion.kaggle import download_dataset

        def not_zip(url, headers, dest, timeout):
            dest.write_bytes(b"<html>login</html>")

        with pytest.raises(FetchError, match="not a zip"):
            download_dataset("o/s1", tmp_path, "t", downloader=not_zip)
        evil = self.make_zip(tmp_path, names=("../evil.csv",))
        with pytest.raises(FetchError, match="unsafe"):
            download_dataset("o/s2", tmp_path, "t", downloader=lambda u, h, d, t: d.write_bytes(evil))

    def test_plan_lists_licence_and_commit_policy_for_every_dataset(self):
        from eventshock.ingestion.kaggle import load_plan
        plan = load_plan()
        assert all(d["commit"] in {"never", "aggregate"} for d in plan)
        nc = [d for d in plan if "NC" in d["licence"]]
        assert nc and all(d["commit"] == "never" for d in nc)
