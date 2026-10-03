from __future__ import annotations

import io
import json
import zipfile

import pytest

from eventshock.domain import TimestampOrigin
from eventshock.ingestion.base import Rejected
from eventshock.ingestion.gkg import GkgAdapter, GkgFilter, filter_gkg, select_files
from eventshock.ingestion.gkg_fetch import fetch_gkg
from eventshock.ingestion.snapshot import iter_jsonl
from tests.pipe_helpers import AS_OF

FLT = GkgFilter(
    org_forms={"apple": "AAPL", "goldman sachs": "GS"},
    title_forms={"goldman sachs": "GS", "apple inc": "AAPL"},
    market_themes=frozenset({"ECON_STOCKMARKET"}),
    market_cap_per_file=1,
)


def row(gid="20260930120000-1", *, first="20260930120000", pub="20260930090000", title="Goldman Sachs lifts target",
        url="https://a.com/x", orgs="goldman sachs", themes="TAX_X,1;ECON_STOCKMARKET,9", tone="-2.5,1.0,3.5,4.5,20,3,300",
        translation="", extras=None):
    c = [""] * 27
    c[0], c[1], c[2], c[3], c[4] = gid, first, "1", "a.com", url
    c[8], c[13], c[15], c[25] = themes, orgs, tone, translation
    c[26] = extras if extras is not None else f"<PAGE_PRECISEPUBTIMESTAMP>{pub}</PAGE_PRECISEPUBTIMESTAMP><PAGE_TITLE>{title}</PAGE_TITLE>"
    return "\t".join(c)


def keep(*rows):
    return filter_gkg("\n".join(rows) + "\n", FLT, "f.zip")


class TestFilter:
    def test_issuer_row_kept_with_publisher_time_tone_and_orgs(self):
        recs, st = keep(row())
        r, = recs
        assert (st.rows, st.kept_issuer) == (1, 1)
        assert r["seendate"] == "20260930T090000Z" and r["x_time_origin"] == "SOURCE"  # publisher clock, not crawl time
        assert r["x_tone"]["tone"] == -2.5 and r["x_orgs"] == ["goldman sachs"] and r["x_issuers"] == ["GS"]

    def test_falls_back_to_first_seen_when_publisher_time_is_missing_or_impossible(self):
        recs, _ = keep(row("a", extras="<PAGE_TITLE>Goldman Sachs news</PAGE_TITLE>"),
                       row("b", url="https://a.com/y", pub="20261231000000"))  # "published" after it was first seen
        assert {r["x_time_origin"] for r in recs} == {"GDELT_FIRST_SEEN"}

    def test_org_match_without_name_in_title_is_kept_but_marked_not_in_title(self):
        recs, _ = keep(row(title="Why buyers are lining up", orgs="apple"))
        assert recs[0]["x_issuers"] == ["AAPL"] and recs[0]["x_in_title"] == []

    def test_accounting_for_dropped_rows(self):
        recs, st = keep(row("t", translation="srclc:fra; eng"), row("n", extras="<PAGE_TITLE></PAGE_TITLE>", url="https://a.com/z"),
                        "garbage\tline", row("ok", orgs="nobody", title="Local bake sale", themes="TAX_X,1"))
        assert recs == [] and (st.rows, st.translated, st.no_title, st.malformed) == (4, 1, 1, 1)

    def test_market_rows_are_capped_per_file_and_deterministic(self):
        rows = [row(f"m{i}", url=f"https://a.com/{i}", orgs="nobody", title=f"Markets story {i}") for i in range(5)]
        a, st = keep(*rows)
        b, _ = keep(*reversed(rows))
        assert len(a) == 1 == st.kept_market and a == b

    def test_html_entities_and_tokenised_spacing_are_cleaned(self):
        r, = keep(row(title="Goldman Sachs ( NYSE : GS ) Given $1 , 007 . 00 Target &amp; more"))[0]
        assert r["title"] == "Goldman Sachs (NYSE: GS) Given $1,007.00 Target & more"


class TestAdapter:
    def test_gkg_records_flow_through_the_doc_adapter_shape(self, tmp_path):
        rec = keep(row())[0][0]
        p = tmp_path / "g.jsonl"
        p.write_text(json.dumps(rec) + "\n")
        d, = list(GkgAdapter(snapshot_id="s", as_of=AS_OF).read(p, "g.jsonl"))
        assert d.raw_metadata["adapter"] == "gdelt-gkg" and d.raw_metadata["gkg_tone"]["tone"] == -2.5
        assert d.raw_metadata["timestamp_origin"] == TimestampOrigin.SOURCE.value
        assert d.raw_metadata["content_sha256"] and d.raw_metadata["record_ref"] == "g.jsonl:1"

    def test_unknown_time_origin_falls_back_to_first_seen(self, tmp_path):
        rec = {**keep(row())[0][0], "x_time_origin": "WHATEVER"}
        p = tmp_path / "g.jsonl"
        p.write_text(json.dumps(rec) + "\n")
        d, = list(GkgAdapter(snapshot_id="s", as_of=AS_OF).read(p, "g.jsonl"))
        assert d.raw_metadata["timestamp_origin"] == "GDELT_FIRST_SEEN"

    def test_bad_record_is_rejected_not_raised(self, tmp_path):
        p = tmp_path / "g.jsonl"
        p.write_text('{"url": "https://a.com", "title": "x", "seendate": "bad"}\n')
        r, = list(GkgAdapter(snapshot_id="s", as_of=AS_OF).read(p, "g.jsonl"))
        assert isinstance(r, Rejected)
        assert list(iter_jsonl(p, "g"))


def test_entity_resolution_ignores_gkg_organisations():
    """The NER org list is evidence for *filtering*; attribution must come from the text."""
    from tests.pipe_helpers import doc, run

    d = doc("g1", "Why buyers are lining up for the new device this autumn")
    d.raw_metadata.update({"gkg_orgs": ["apple"], "adapter": "gdelt-gkg"})
    assert run([d]).signals[0].entity.is_unknown


def test_select_files_by_kind_and_window():
    master = ["1 a http://d/gdeltv2/20260930120000.gkg.csv.zip", "1 a http://d/gdeltv2/20260930120000.export.CSV.zip",
              "1 a http://d/gdeltv2/20260901000000.gkg.csv.zip", "bad line", "1 a http://d/gdeltv2/20261001000000.gkg.csv.zip"]
    assert select_files(master, "20260917000000", "20260930235959") == ["https://d/gdeltv2/20260930120000.gkg.csv.zip"]


def make_zip(*rows: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.gkg.csv", "\n".join(rows) + "\n")
    return buf.getvalue()


class TestFetcher:
    @pytest.fixture()
    def env(self, tmp_path):
        master = tmp_path / "master.txt"
        stamps = ["20260930120000", "20260930121500", "20260930123000"]
        master.write_text("\n".join(f"1 h http://d/gdeltv2/{s}.gkg.csv.zip" for s in stamps) + "\n")
        return master, tmp_path / "out" / "f.jsonl", stamps

    def run(self, env, transport, **kw):
        master, out, _ = env
        return fetch_gkg(master, FLT, start="20260930000000", end="20260930235959", out=out, workers=2,
                         transport=transport, sleep=lambda s: None, **kw)

    def good(self, url, timeout):
        stamp = url.rsplit("/", 1)[-1][:14]
        return 200, make_zip(row(f"{stamp}-1", url=f"https://a.com/{stamp}"))

    def test_downloads_filters_and_leaves_no_zip_on_disk(self, env):
        res = self.run(env, self.good)
        _, out, stamps = env
        recs = [json.loads(x) for x in out.read_text().split("\n") if x]
        assert res.files_done == 3 and not res.files_failed and len(recs) == 3
        assert [r["url"] for r in recs] == [f"https://a.com/{s}" for s in stamps]  # stable order
        assert not list(out.parent.rglob("*.zip")), "zips must be discarded"

    def test_keep_zips_flag_retains_them(self, env, tmp_path):
        self.run(env, self.good, keep_dir=tmp_path / "zips")
        assert len(list((tmp_path / "zips").glob("*.zip"))) == 3

    def test_failed_files_are_logged_and_only_they_are_retried(self, env):
        calls: list[str] = []

        def flaky(url, timeout):
            calls.append(url)
            if "121500" in url:
                return 404, b""
            if "123000" in url:
                return 200, b"not a zip"
            return self.good(url, timeout)

        res = self.run(env, flaky)
        _, out, _ = env
        assert res.files_done == 1 and sorted(res.files_failed) == ["20260930121500.gkg.csv.zip", "20260930123000.gkg.csv.zip"]
        log = [json.loads(x) for x in out.with_suffix(".log.jsonl").read_text().split("\n") if x]
        assert {e["status"] for e in log} == {"ok", "error"}
        calls.clear()

        def recording(url, timeout):
            calls.append(url)
            return self.good(url, timeout)

        res2 = self.run(env, recording)
        assert all(("121500" in u or "123000" in u) for u in calls) and len(calls) == 2
        assert res2.files_done == 3 and len([x for x in out.read_text().split("\n") if x]) == 3  # no duplicates


def test_select_files_slots_sample_fixed_times_of_day():
    master = [f"1 x http://d/gdeltv2/202401{d:02d}{hhmm}00.gkg.csv.zip" for d in (1, 2) for hhmm in ("0000", "0015", "0400", "1200")]
    got = select_files(master, "20240101000000", "20240102235959", slots=frozenset({"0000", "1200"}))
    assert [u.rsplit("/", 1)[1][:12] for u in got] == ["202401010000", "202401011200", "202401020000", "202401021200"]
    # no slots: every file; an empty-intersection slot set: nothing (never silently "all")
    assert len(select_files(master, "20240101000000", "20240102235959")) == 8
    assert select_files(master, "20240101000000", "20240102235959", slots=frozenset({"0300"})) == []
