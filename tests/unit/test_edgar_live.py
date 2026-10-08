"""SEC EDGAR as the second live source: the Atom feed -> documents, which filings are kept, failures, and the combined source. No network."""

from __future__ import annotations

from datetime import UTC, timedelta
from pathlib import Path

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.domain import RawDocument, SourceType
from eventshock.ingestion.edgar_live import (
    FEED_URL,
    EdgarLiveSource,
    FeedError,
    headline,
    parse_feed,
)
from eventshock.ingestion.fetch import FetchError
from eventshock.ingestion.live import (
    CombinedSource,
    EdgarSourceConfig,
    GdeltLiveSource,
    GdeltSourceConfig,
    LivePoll,
    to_documents,
)
from eventshock.pipeline.engine import Outcome
from eventshock.services.live import Journal, LiveService, LiveUnavailable, SourceChoice, load_live_config
from tests.pipe_helpers import AS_OF
from tests.unit.test_analyze_live import FakeTransport, gdelt_record, make_engine

LIVE_CFG = load_live_config(REPO_ROOT / "configs")
ITEMS = ["1.03", "2.04"]
CFG = EdgarSourceConfig(items=ITEMS, lookback_hours=6)
APPLE, SMALL, OTHER = 320193, 1712762, 1640384


def entry(name: str, cik: int, acc: str, minutes_ago: int, items: list[tuple[str, str]], form: str = "8-K", role: str = "Filer") -> str:
    when = (AS_OF - timedelta(minutes=minutes_ago)).astimezone(timezone_et())
    body = "".join(f"\n&lt;br&gt;Item {c}: {t}" for c, t in items)
    return f"""<entry>
<title>{form} - {name} ({cik:010d}) ({role})</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm"/>
<summary type="html">
 &lt;b&gt;Filed:&lt;/b&gt; 2026-10-01 &lt;b&gt;AccNo:&lt;/b&gt; {acc} &lt;b&gt;Size:&lt;/b&gt; 311 KB{body}
</summary>
<updated>{when.isoformat()}</updated>
<category scheme="https://www.sec.gov/" label="form type" term="{form}"/>
<id>urn:tag:sec.gov,2008:accession-number={acc}</id>
</entry>"""


def timezone_et():
    from datetime import timezone
    return timezone(timedelta(hours=-4))


def feed(*entries: str) -> bytes:
    return ('<?xml version="1.0" encoding="ISO-8859-1" ?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n<title>Latest Filings</title>\n'
            + "\n".join(entries) + "\n</feed>").encode("latin-1")


A1, A2, A3, A4 = "0000320193-26-000001", "0001493152-26-000002", "0001193125-26-000003", "0001213900-26-000004"
REAL_SHAPE = feed(
    entry("Apple Inc.", APPLE, A1, 10, [("2.02", "Results of Operations and Financial Condition"), ("9.01", "Financial Statements and Exhibits")]),
    entry("bioAffinity Technologies, Inc.", SMALL, A2, 20, [("8.01", "Other Events"), ("9.01", "Financial Statements and Exhibits")]),
    entry("POWERCOMPUTE, INC.", OTHER, A3, 30, [("2.04", "Triggering Events That Accelerate or Increase a Direct Financial Obligation")]),
    entry("POWERCOMPUTE, INC.", OTHER, A3, 30, [("2.04", "Triggering Events That Accelerate or Increase a Direct Financial Obligation")], role="Subject"),
    entry("Old Corp", 99, A4, 60 * 9, [("1.03", "Bankruptcy or Receivership")]),
)


def source(data: bytes, **kw) -> tuple[EdgarLiveSource, list[str]]:
    calls: list[str] = []

    def transport(url: str, timeout: float):
        calls.append(url)
        if isinstance(data, Exception):
            raise data
        return 200, data

    return EdgarLiveSource(kw.pop("cfg", CFG), tracked_ciks=kw.pop("tracked", frozenset({APPLE})), transport=transport,
                           clock=lambda: AS_OF, contact="test@example.com", **kw), calls


# ------------------------------------------------------------------------------------------------------------------- the feed
def test_the_feed_is_read_into_filer_form_accession_items_and_a_utc_acceptance_time() -> None:
    rows = parse_feed(REAL_SHAPE)
    first = rows[0]
    assert (first["form"], first["name"], first["cik"], first["accession"]) == ("8-K", "Apple Inc.", APPLE, A1)
    assert first["items"] == [("2.02", "Results of Operations and Financial Condition"), ("9.01", "Financial Statements and Exhibits")]
    assert first["accepted"] == AS_OF - timedelta(minutes=10) and first["accepted"].tzinfo == UTC
    assert first["url"].endswith(f"{A1}-index.htm")


def test_an_entry_missing_its_accession_or_time_is_marked_invalid_not_guessed() -> None:
    broken = feed("<entry><title>8-K - X Corp (0000000001) (Filer)</title><updated>nope</updated></entry>")
    assert parse_feed(broken) == [{"invalid": "8-K - X Corp (0000000001) (Filer)"}]


@pytest.mark.parametrize("data,why", [(b"<html><body>blocked</body></html>", "Atom"), (b"not xml at all", "valid XML"), (b"x" * 2_000_001, "limit")])
def test_a_document_that_is_not_the_feed_is_an_error(data: bytes, why: str) -> None:
    with pytest.raises(FeedError, match=why):
        parse_feed(data)


def test_the_headline_is_composed_from_published_fields_and_cut_at_a_word() -> None:
    items = [("5.02", "Departure of Directors or Certain Officers; Election of Directors; Appointment"), ("9.01", "Financial Statements and Exhibits")]
    assert headline("Acme Corp.", "8-K", items, 220) == "Acme Corp. files Form 8-K: Item 5.02 Departure of Directors or Certain Officers; Item 9.01 Financial Statements and Exhibits"
    assert headline("Acme Corp.", "8-K", [], 220) == "Acme Corp. files Form 8-K"
    cut = headline("Acme Corp.", "8-K", items, 70)
    assert len(cut) <= 70 and cut.endswith("…") and " files Form 8-K" in cut


# --------------------------------------------------------------------------------------------------------------- which filings
def test_a_filing_is_kept_for_a_tracked_issuer_or_a_risk_item_and_everything_else_is_counted_and_dropped() -> None:
    src, calls = source(REAL_SHAPE)
    poll = src.poll()
    kept = {d.raw_metadata["accession"]: d for d in poll.documents if isinstance(d, RawDocument)}
    assert set(kept) == {A1, A3}  # Apple (tracked, routine item), POWERCOMPUTE (untracked, item 2.04); bioAffinity 8.01/9.01 dropped, Old Corp too old
    assert src.last_counts == {"entries": 5, "invalid": 0, "other_form": 0, "old": 1, "not_kept": 1, "duplicate": 1, "kept": 2}
    assert poll.queries_ok == 1 and not poll.failed and poll.mode == "EDGAR" and len(calls) == 1
    assert calls[0] == FEED_URL.format(form="8-K", count=100)


def test_a_poll_says_what_it_saw_so_a_quiet_poll_is_not_a_silent_one() -> None:
    src, _ = source(REAL_SHAPE)
    assert src.poll().note == "SEC filings: 5 listed, 4 in the last 6 h, 2 matched"
    quiet, _ = source(feed(entry("bioAffinity Technologies, Inc.", SMALL, A2, 20, [("8.01", "Other Events")])))
    poll = quiet.poll()
    assert poll.documents == [] and poll.note == "SEC filings: 1 listed, 1 in the last 6 h, 0 matched" and not poll.failed


def test_a_document_says_what_it_is_and_does_not_pose_as_a_news_article() -> None:
    src, _ = source(REAL_SHAPE)
    docs = {d.raw_metadata["accession"]: d for d in src.poll().documents}
    d = docs[A3]
    assert d.source == "sec.gov" and d.source_type is SourceType.NEWS and d.published_at == AS_OF - timedelta(minutes=30)
    assert d.headline == "POWERCOMPUTE, INC. files Form 8-K: Item 2.04 Triggering Events That Accelerate or Increase a Direct Financial Obligation"
    m = d.raw_metadata
    assert (m["adapter"], m["timestamp_origin"], m["form"], m["cik"], m["items"], m["synthesized_headline"]) == ("sec-edgar-live", "SOURCE", "8-K", OTHER, ["2.04"], True)
    assert d.ingested_at >= d.published_at and d.id.startswith("edgar-") and docs[A1].id != d.id


def test_only_the_configured_form_is_read() -> None:
    other = feed(entry("Foreign Co", 5, "0000000005-26-000001", 5, [], form="6-K"), entry("Apple Inc.", APPLE, A1, 5, []))
    src, _ = source(other)
    poll = src.poll()
    assert [d.raw_metadata["accession"] for d in poll.documents] == [A1] and src.last_counts["other_form"] == 1


def test_an_item_filter_alone_works_without_tracked_issuers() -> None:
    src, _ = source(REAL_SHAPE, cfg=EdgarSourceConfig(items=ITEMS, tracked_issuers=False))
    assert {d.raw_metadata["accession"] for d in src.poll().documents} == {A3}


# ------------------------------------------------------------------------------------------------------------------ failures
@pytest.mark.parametrize("data,expect", [(FetchError("HTTP 403"), "FetchError"), (b"<html>blocked</html>", "FeedError"), (b"garbage", "FeedError")])
def test_a_failed_request_or_a_bad_document_is_a_failed_poll_with_no_documents(data, expect) -> None:
    src, _ = source(data)
    poll = src.poll()
    assert poll.failed and poll.documents == [] and expect in poll.errors[0]


def test_it_will_not_start_without_a_declared_contact() -> None:
    with pytest.raises(FetchError, match="EVENTSHOCK_SEC_CONTACT"):
        EdgarLiveSource(CFG, contact="not-an-email")


# --------------------------------------------------------------------------------------------------------------- combination
def gdelt_source(*responses) -> GdeltLiveSource:
    return GdeltLiveSource(GdeltSourceConfig(queries=["a"], throttle_seconds=5.0), transport=FakeTransport(*responses), sleep=lambda s: None, clock=lambda: AS_OF)


def test_the_combined_source_merges_both_and_survives_one_failing() -> None:
    edgar, _ = source(REAL_SHAPE)
    both = CombinedSource([gdelt_source({"articles": [gdelt_record(1, "Goldman Sachs fined $50 million over trading violations")]}), edgar])
    assert both.kind == "both" and both.mode == "GDELT+EDGAR"
    poll = both.poll()
    docs = to_documents(poll)
    assert {d.raw_metadata["adapter"] for d in docs if isinstance(d, RawDocument)} == {"gdelt-live", "sec-edgar-live"}
    assert not poll.failed and poll.queries_failed == 0

    down, _ = source(FetchError("HTTP 503"))
    partial = CombinedSource([gdelt_source({"articles": [gdelt_record(2, "Goldman Sachs fined $50 million over trading violations")]}), down]).poll()
    assert not partial.failed and partial.queries_failed == 1 and partial.queries_ok == 1 and "EDGAR: FetchError" in partial.errors[0]
    assert any(isinstance(d, RawDocument) for d in to_documents(partial))

    both_down = CombinedSource([gdelt_source(*[FetchError("x")] * 3), source(FetchError("y"))[0]]).poll()
    assert both_down.failed


def test_a_source_that_raises_does_not_stop_the_other() -> None:
    class Bad:
        mode, kind = "GDELT", "gdelt"

        def poll(self) -> LivePoll:
            raise RuntimeError("bug")

    edgar, _ = source(REAL_SHAPE)
    poll = CombinedSource([Bad(), edgar]).poll()
    assert len(poll.documents) == 2 and poll.queries_failed == 1 and "RuntimeError: bug" in poll.errors[0]
    with pytest.raises(ValueError, match="at least two"):
        CombinedSource([edgar])


# ------------------------------------------------------------------------------------------------------- through the service
def service(src, tmp_path: Path):
    eng, store = make_engine()
    svc = LiveService(cfg=LIVE_CFG, engine=eng, store=store, source=src, journal=Journal(tmp_path / "j.jsonl"),
                      event_model_note=lambda: ("tfidf", None), market_through="2026-10-01", clock=lambda: AS_OF)
    return svc, store


def test_filings_become_signals_through_the_engine_and_are_counted_per_adapter_and_journalled(tmp_path: Path) -> None:
    edgar, _ = source(REAL_SHAPE)
    both = CombinedSource([gdelt_source({"articles": [gdelt_record(1, "Goldman Sachs fined $50 million over trading violations")]}), edgar])
    svc, store = service(both, tmp_path)
    st = svc.refresh()
    assert st.state == "OK" and st.source_kind == "both" and st.source_mode == "GDELT+EDGAR" and not st.simulated
    assert st.fetched_by_adapter == {"gdelt-live": 1, "sec-edgar-live": 2} and st.fetched_total == 3
    sigs = [s for s, _ in store.items()]
    assert {s.document.source for s in sigs} >= {"sec.gov"} and len(sigs) == 3
    assert svc.journal.path.exists() and svc.journal.path.read_text().count("sec-edgar-live") == 2  # a restart can rebuild them
    assert st.last_poll_note == "SEC filings: 5 listed, 4 in the last 6 h, 2 matched"
    assert svc.refresh().new_total == st.new_total  # the same filings again are not new signals


def test_a_partial_poll_is_degraded_but_keeps_the_source_that_worked(tmp_path: Path) -> None:
    down, _ = source(FetchError("HTTP 503"))
    svc, store = service(CombinedSource([gdelt_source({"articles": [gdelt_record(1, "Goldman Sachs fined $50 million over trading violations")]}), down]), tmp_path)
    st = svc.refresh()
    assert st.state == "DEGRADED" and "EDGAR" in (st.last_error or "") and len(store) == 1


def test_the_switch_can_pick_the_new_sources_and_refuses_edgar_without_a_contact(tmp_path: Path) -> None:
    made: list[str] = []
    choices = [SourceChoice(kind=k, label=k, network=True, available=ok, reason=None if ok else "EVENTSHOCK_SEC_CONTACT is not set")
               for k, ok in (("both", False), ("gdelt", True), ("edgar", False))]
    eng, store = make_engine()
    svc = LiveService(cfg=LIVE_CFG, engine=eng, store=store, source=None, journal=None, event_model_note=lambda: ("m", None),
                      market_through="2026-10-01", clock=lambda: AS_OF,
                      source_factory=lambda kind: (made.append(kind), gdelt_source())[1], source_choices=lambda: choices)
    assert svc.set_state(True).source_kind == "gdelt"  # the first *available* choice when none is named
    svc.set_state(False)
    with pytest.raises(LiveUnavailable, match="SEC_CONTACT"):
        svc.set_state(True, "edgar")
    with pytest.raises(LiveUnavailable, match="SEC_CONTACT"):
        svc.set_state(True, "both")
    assert svc.status().state == "OFF" and made == ["gdelt"]


# ---------------------------------------------------------------------------------------------------------------------- config
def test_the_committed_edgar_config_is_valid_and_is_a_judgement_prior_with_known_items() -> None:
    e = LIVE_CFG.source.edgar
    assert e.form == "8-K" and e.tracked_issuers and e.count <= 100
    assert {"1.03", "2.04", "4.02"} <= set(e.items) and not {"2.02", "7.01", "8.01", "9.01"} & set(e.items)
    assert all(len(i) == 4 and i[1] == "." for i in e.items)


def test_a_wrong_source_kind_in_the_config_is_refused(tmp_path: Path) -> None:
    text = (REPO_ROOT / "configs" / "live.yaml").read_text()
    (tmp_path / "live.yaml").write_text(text.replace("kind: gdelt  ", "kind: rss  ", 1))
    with pytest.raises(ConfigError):
        load_live_config(tmp_path)
    (tmp_path / "live.yaml").write_text(text.replace("    count: 100\n", "    count: 100\n    surprise: 1\n", 1))
    with pytest.raises(ConfigError):
        load_live_config(tmp_path)


def test_the_tracked_issuers_come_from_the_committed_filing_table_by_cik() -> None:
    from eventshock.api.deps import _tracked_ciks

    ciks = _tracked_ciks()
    assert APPLE in ciks and 34088 in ciks and len(ciks) >= 30  # Apple and Exxon (its predecessor CIK) are in the entity master


def test_an_engine_run_over_filings_alone_works(tmp_path: Path) -> None:
    edgar, _ = source(REAL_SHAPE)
    eng, store = make_engine()
    outcomes = eng.ingest(to_documents(edgar.poll()), channel="LIVE", now=AS_OF)
    assert [o.outcome for o in outcomes] == [Outcome.NEW, Outcome.NEW] and len(store) == 2
