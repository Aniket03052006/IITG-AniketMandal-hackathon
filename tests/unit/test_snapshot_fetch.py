from __future__ import annotations

import json
import shutil

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.ingestion import fetch
from eventshock.ingestion.fetch import FetchError, fetch_gdelt, get_bytes, get_json, write_jsonl
from eventshock.ingestion.snapshot import atomic_write_text, load_snapshot

NO_SLEEP = lambda s: None  # noqa: E731


def scripted(*responses):
    calls = []
    it = iter(responses)

    def transport(url, timeout):
        calls.append(url)
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    transport.calls = calls
    return transport


class TestGetBytes:
    def test_retries_then_succeeds(self):
        t = scripted((429, b""), (503, b""), (200, b"ok"))
        assert get_bytes("https://x", transport=t, sleep=NO_SLEEP) == b"ok" and len(t.calls) == 3

    def test_gives_up_after_retries(self):
        t = scripted(*[(500, b"")] * 4)
        with pytest.raises(FetchError, match="gave up"):
            get_bytes("https://x", transport=t, sleep=NO_SLEEP)

    def test_client_error_is_not_retried(self):
        t = scripted((404, b""))
        with pytest.raises(FetchError, match="404"):
            get_bytes("https://x", transport=t, sleep=NO_SLEEP)
        assert len(t.calls) == 1

    def test_network_error_is_retried(self):
        t = scripted(FetchError("timeout"), (200, b"ok"))
        assert get_bytes("https://x", transport=t, sleep=NO_SLEEP) == b"ok"

    def test_https_only(self):
        with pytest.raises(FetchError, match="non-https"):
            fetch.urllib_transport("http://example.com", 1)


class TestGetJson:
    def test_200_with_html_body_is_an_error_not_data(self):
        with pytest.raises(FetchError, match="non-JSON"):
            get_json("https://x", transport=scripted((200, b"<html>oops</html>")), sleep=NO_SLEEP)

    def test_rate_limit_text_with_200_is_retried(self):
        t = scripted((200, b"Please limit requests to one every 5 seconds."), (200, b'{"articles": []}'))
        assert get_json("https://x", transport=t, sleep=NO_SLEEP) == {"articles": []}


class TestFetchGdelt:
    def art(self, n):
        return {"url": f"https://a.com/{n}", "title": f"t{n}", "seendate": "20260930T000000Z"}

    def test_dedups_across_queries_and_records_per_query_outcome(self):
        t = scripted((200, json.dumps({"articles": [self.art(1), self.art(2)]}).encode()),
                     (200, json.dumps({"articles": [self.art(2), self.art(3)]}).encode()))
        res = fetch_gdelt(["q1", "q2"], start="s", end="e", transport=t, sleep=NO_SLEEP)
        assert [r["url"][-1] for r in res.records] == ["1", "2", "3"]
        assert res.records[1]["x_query"] == "q1"
        assert [e["added"] for e in res.log] == [2, 1] and res.failed == 0

    def test_partial_failure_is_recorded_not_swallowed(self):
        t = scripted((200, b'{"articles": []}'), *[(500, b"")] * 3, (200, b'{"nope": 1}'))
        res = fetch_gdelt(["q1", "q2", "q3"], start="s", end="e", transport=t, sleep=NO_SLEEP)
        assert [e["status"] for e in res.log] == ["ok", "error", "error"] and res.failed == 2

    def test_write_jsonl_is_atomic_and_sorted(self, tmp_path):
        p = tmp_path / "o" / "a.jsonl"
        assert write_jsonl(p, [{"b": 1, "a": 2}]) == 1
        assert p.read_text() == '{"a": 2, "b": 1}\n'
        assert not list(p.parent.glob(".*.tmp"))

    def test_atomic_write_cleans_up_on_failure(self, tmp_path, monkeypatch):
        import os
        monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError):
            atomic_write_text(tmp_path / "x.txt", "hi")
        assert list(tmp_path.iterdir()) == []


class TestSnapshotIntegrity:
    @pytest.fixture()
    def pack(self, tmp_path):
        dst = tmp_path / "replay"
        shutil.copytree(REPO_ROOT / "data" / "replay", dst)
        return dst

    def test_shipped_pack_verifies(self):
        snap = load_snapshot(REPO_ROOT / "data" / "replay")
        assert snap.manifest.snapshot_id and len(snap.manifest.sources) >= 2

    def test_modified_source_file_fails_loudly(self, pack):
        f = pack / "gdelt" / "articles.jsonl"
        f.write_text(f.read_text().replace("a", "b", 1))
        with pytest.raises(ConfigError, match="sha256 mismatch"):
            load_snapshot(pack)

    def test_missing_file_fails_loudly(self, pack):
        (pack / "entities.json").unlink()
        with pytest.raises(ConfigError, match="missing"):
            load_snapshot(pack)

    def test_record_count_mismatch_fails(self, pack):
        m = json.loads((pack / "manifest.json").read_text())
        m["sources"][0]["records"] += 1
        (pack / "manifest.json").write_text(json.dumps(m))
        with pytest.raises(ConfigError, match="records"):
            load_snapshot(pack)

    def test_path_traversal_in_manifest_is_refused(self, pack):
        m = json.loads((pack / "manifest.json").read_text())
        m["sources"][0]["file"] = "../manifest.json"
        (pack / "manifest.json").write_text(json.dumps(m))
        with pytest.raises(ConfigError, match="escapes"):
            load_snapshot(pack)

    def test_no_manifest(self, tmp_path):
        with pytest.raises(ConfigError, match="manifest"):
            load_snapshot(tmp_path)

    def test_bad_manifest(self, pack):
        (pack / "manifest.json").write_text("{}")
        with pytest.raises(ConfigError, match="invalid manifest"):
            load_snapshot(pack)


class TestResumableCli:
    def test_interrupted_download_resumes_without_refetching_or_duplicating(self, tmp_path, monkeypatch):
        qf = tmp_path / "q.json"
        qf.write_text(json.dumps(["q1", "q2", "q3"]))
        out = tmp_path / "raw" / "a.jsonl"
        art = lambda n: {"url": f"https://a.com/{n}", "title": f"t{n}", "seendate": "20260930T000000Z"}  # noqa: E731
        asked: list[str] = []

        def transport_factory(fail_q2: bool):
            def transport(url, timeout):
                q = next(x for x in ("q1", "q2", "q3") if x in url)
                asked.append(q)
                if q == "q2" and fail_q2:
                    return 500, b""
                return 200, json.dumps({"articles": [art(1), art(ord(q[-1]))]}).encode()
            return transport

        monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
        args = ["gdelt", "--queries-file", str(qf), "--start", "s", "--end", "e", "--out", str(out)]
        monkeypatch.setattr(fetch, "urllib_transport", transport_factory(fail_q2=True))
        assert fetch.main(args) == 0  # one query failed, the others are checkpointed
        first = [json.loads(x) for x in out.read_text().split("\n") if x]
        assert len(first) == 3  # art(1) once + one per ok query
        asked.clear()
        monkeypatch.setattr(fetch, "urllib_transport", transport_factory(fail_q2=False))
        assert fetch.main(args) == 0
        assert set(asked) == {"q2"}, "only the failed query is retried"
        urls = [json.loads(x)["url"] for x in out.read_text().split("\n") if x]
        assert len(urls) == len(set(urls)) == 4
