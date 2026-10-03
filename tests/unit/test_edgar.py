from __future__ import annotations

import json

import pytest

from eventshock.ingestion.edgar import (
    PREDECESSOR_CIKS,
    cik10,
    fetch_edgar,
    filing_rows,
    load_filings,
    sec_contact,
    ticker_to_cik,
)
from eventshock.ingestion.fetch import FetchError

NO_SLEEP = lambda s: None  # noqa: E731


def page(**cols):
    n = len(cols["accessionNumber"])
    base = {"form": [""] * n, "filingDate": ["2020-01-02"] * n, "acceptanceDateTime": ["2020-01-02T21:30:00.000Z"] * n,
            "items": [""] * n, "primaryDocument": ["d.htm"] * n, "primaryDocDescription": [""] * n}
    return {**base, **cols}


def test_ticker_map_and_cik_padding():
    m = ticker_to_cik({"0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple"}, "1": {"cik_str": 1, "ticker": "AAPL", "title": "dup"}})
    assert m == {"AAPL": 320193}  # first wins, upper-cased
    assert cik10(320193) == "0000320193"
    with pytest.raises(FetchError, match="malformed"):
        ticker_to_cik({"0": {"ticker": "X"}})


def test_filing_rows_keep_forms_with_a_clock_and_split_items():
    p = page(accessionNumber=["a1", "a2", "a3", "a4"], form=["8-K", "4", "10-Q", "8-K"], items=["2.02,9.01", "", "", "5.02"],
             acceptanceDateTime=["2024-05-02T20:15:03.000Z", "2024-05-02T20:15:03.000Z", "2024-05-03T10:00:00.000Z", ""],
             filingDate=["2024-05-02", "2024-05-02", "2024-05-03", "2024-05-02"])
    rows = filing_rows(p, ticker="AAPL", cik=320193)
    assert [r["accession"] for r in rows] == ["a1", "a3"]  # Form 4 is not kept; the 8-K without an acceptance time is dropped, never invented
    assert rows[0]["items"] == ["2.02", "9.01"] and rows[0]["acceptance_utc"] == "2024-05-02T20:15:03Z" and rows[1]["items"] == []


def test_filing_rows_reject_shape_problems_and_drop_pre_2014():
    with pytest.raises(FetchError):
        filing_rows({"nope": []}, ticker="X", cik=1)
    with pytest.raises(FetchError, match="expected"):
        filing_rows({"accessionNumber": ["a", "b"], "form": ["8-K"]}, ticker="X", cik=1)
    old = page(accessionNumber=["a"], form=["8-K"], filingDate=["2010-01-01"])
    assert filing_rows(old, ticker="X", cik=1) == []


def test_contact_is_required_and_read_from_env_or_dotenv(tmp_path):
    with pytest.raises(FetchError, match="EVENTSHOCK_SEC_CONTACT"):
        sec_contact(env={}, dotenv=None)
    assert sec_contact(env={"EVENTSHOCK_SEC_CONTACT": "a@b.co"}, dotenv=None) == "a@b.co"
    f = tmp_path / ".env"
    f.write_text("OTHER=1\nEVENTSHOCK_SEC_CONTACT='me@x.org'\n")
    assert sec_contact(env={}, dotenv=f) == "me@x.org"
    f.write_text("EVENTSHOCK_SEC_CONTACT=not-an-email\n")
    with pytest.raises(FetchError):
        sec_contact(env={}, dotenv=f)


def _submissions(accs, items):
    return {"filings": {"recent": page(accessionNumber=accs, form=["8-K"] * len(accs), items=items,
                                       acceptanceDateTime=[f"2021-0{i + 1}-05T21:00:00.000Z" for i in range(len(accs))],
                                       filingDate=[f"2021-0{i + 1}-05" for i in range(len(accs))]), "files": []}}


def test_fetch_edgar_downloads_resumes_and_merges_predecessors(tmp_path):
    calls: list[str] = []
    store = {
        "https://www.sec.gov/files/company_tickers.json": {"0": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet"}},
        "https://data.sec.gov/submissions/CIK0001652044.json": _submissions(["n1"], ["2.02"]),
        "https://data.sec.gov/submissions/CIK0001288776.json": _submissions(["o1", "o2"], ["1.01", "5.02"]),
    }

    def transport(url, timeout):
        calls.append(url)
        return (200, json.dumps(store[url]).encode()) if url in store else (404, b"")

    res = fetch_edgar(["GOOGL", "ZZZZ"], out_dir=tmp_path, transport=transport, sleep=NO_SLEEP)
    assert res["failed"] == ["ZZZZ"] and 1288776 in PREDECESSOR_CIKS["GOOGL"]
    n = len(calls)
    fetch_edgar(["GOOGL"], out_dir=tmp_path, transport=transport, sleep=NO_SLEEP)
    assert len(calls) == n  # everything cached: a re-run downloads nothing
    rows = load_filings(tmp_path, "GOOGL", 1652044)
    assert sorted(r["accession"] for r in rows) == ["n1", "o1", "o2"] and {r["cik"] for r in rows} == {1652044, 1288776}
    assert [r["acceptance_utc"] for r in rows] == sorted(r["acceptance_utc"] for r in rows)


def test_a_server_error_is_a_logged_failure_not_a_partial_download(tmp_path):
    store = {"https://www.sec.gov/files/company_tickers.json": {"0": {"cik_str": 5, "ticker": "AB", "title": "x"}}}

    def transport(url, timeout):
        return (200, json.dumps(store[url]).encode()) if url in store else (500, b"boom")

    res = fetch_edgar(["AB"], out_dir=tmp_path, transport=transport, sleep=NO_SLEEP)
    assert res["failed"] == ["AB"] and not (tmp_path / "CIK0000000005.json").exists()
