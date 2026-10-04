"""Pasted text and the live feed: both are doors into the same engine. Fake transports, no network."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.domain import RawDocument, SourceType
from eventshock.ingestion.fetch import FetchError
from eventshock.ingestion.live import (
    CaptureSource,
    CaptureSourceConfig,
    GdeltLiveSource,
    GdeltSourceConfig,
    LivePoll,
    to_documents,
)
from eventshock.pipeline.engine import Outcome
from eventshock.services.analyze import AnalysisInputError, Analyzer, split_paste
from eventshock.services.live import Journal, LiveService, load_live_config
from eventshock.store import CombinedSignalRepository, InMemorySignalRepository
from tests.pipe_helpers import AS_OF, CFG
from tests.unit.test_risk_engine import make_engine

LIVE_CFG = load_live_config(REPO_ROOT / "configs")


# ------------------------------------------------------------------------------------------------------------ paste splitting
def test_a_short_first_line_is_the_headline() -> None:
    h, b, cut = split_paste("Fed holds rates\nPolicymakers said inflation is cooling.\nMarkets rose.", 2000)
    assert h == "Fed holds rates" and b == "Policymakers said inflation is cooling. Markets rose." and not cut


def test_a_single_block_is_split_at_its_first_sentence() -> None:
    h, b, cut = split_paste("Oil jumps 4% on supply fears. Traders cite OPEC cuts and a weaker dollar.", 2000)
    assert h == "Oil jumps 4% on supply fears." and b.startswith("Traders cite") and not cut


def test_a_long_unbroken_paragraph_is_cut_at_a_word_boundary() -> None:
    h, b, _ = split_paste("word " * 200, 2000)
    assert len(h) <= 240 and not h.endswith(" ") and b


def test_an_article_is_truncated_to_the_validation_limit_and_says_so() -> None:
    h, b, cut = split_paste("Headline here\n" + "Sentence about markets. " * 400, 2000)
    assert cut and len(h) + 1 + len(b) <= 2000


# ------------------------------------------------------------------------------------------------------------------ analyzer
def make_analyzer(clock_at=AS_OF):
    eng, store = make_engine()
    signals = CombinedSignalRepository(InMemorySignalRepository([], AS_OF), store)
    return Analyzer(eng, signals, CFG.validation, clock=lambda: clock_at), eng, store


def test_pasted_text_becomes_an_ordinary_signal_through_the_engine() -> None:
    an, _, store = make_analyzer()
    r = an.analyze("Goldman Sachs fined $50 million over trading violations")
    assert r.outcome.outcome is Outcome.NEW and r.signal.entity.entity_id == "ENT_GS"
    p = r.signal.provenance
    assert p.adapter == "manual-paste" and p.timestamp_origin.value == "ANALYSIS_TIME"
    assert store.meta(r.signal.id).channel == "MANUAL"
    assert any("time you pasted it" in n for n in r.notes)


def test_a_user_dated_paste_is_marked_user_asserted() -> None:
    an, _, _ = make_analyzer()
    r = an.analyze("Goldman Sachs fined $50 million over trading violations", published_at=AS_OF - timedelta(hours=3))
    assert r.signal.provenance.timestamp_origin.value == "USER_ASSERTED" and r.signal.document.published_at == AS_OF - timedelta(hours=3)
    assert not any("time you pasted it" in n for n in r.notes)


def test_pasting_the_same_text_again_is_the_same_signal() -> None:
    an, _, store = make_analyzer()
    a = an.analyze("Goldman Sachs fined $50 million over trading violations")
    b = an.analyze("Goldman Sachs fined $50 million over trading violations")
    assert b.outcome.outcome is Outcome.DUPLICATE and b.signal.id == a.signal.id and len(store) == 1


def test_an_unusable_paste_is_rejected_with_the_reason_and_no_scoring_notes() -> None:
    an, _, store = make_analyzer()
    r = an.analyze("ok")
    assert r.outcome.outcome is Outcome.QUARANTINED and r.outcome.code == "TOO_SHORT" and r.signal is None and r.notes == []
    assert len(store) == 0


def test_a_future_or_naive_time_is_an_input_error() -> None:
    an, _, _ = make_analyzer()
    with pytest.raises(AnalysisInputError, match="future"):
        an.analyze("Goldman Sachs fined $50 million", published_at=AS_OF + timedelta(hours=2))
    with pytest.raises(AnalysisInputError, match="time zone"):
        an.analyze("Goldman Sachs fined $50 million", published_at=datetime(2026, 10, 1, 9))
    with pytest.raises(AnalysisInputError, match="empty"):
        an.analyze("   \n ")


def test_a_paste_that_matches_a_live_story_joins_it_and_says_so() -> None:
    an, eng, store = make_analyzer()
    from tests.pipe_helpers import doc

    eng.ingest([doc("g", "Goldman Sachs fined $50 million over trading violations", source="wire.example.com", hours=2)],
               channel="LIVE", now=AS_OF)
    r = an.analyze("Goldman Sachs fined $50 million over trading violations", published_at=AS_OF - timedelta(minutes=30))
    assert r.outcome.outcome is Outcome.UPDATED and r.signal.evidence.source_count == 2
    assert any("already in the feed" in n for n in r.notes)


def test_social_source_type_is_carried() -> None:
    an, _, _ = make_analyzer()
    r = an.analyze("$AAPL guidance raised, very bullish", source_type=SourceType.SOCIAL)
    assert r.signal.document.source_type is SourceType.SOCIAL


# --------------------------------------------------------------------------------------------------------------------- journal
def _doc(i: int, hours: float) -> RawDocument:
    from tests.pipe_helpers import doc

    topics = ["a new iPhone", "record services revenue", "a chip supply deal", "a privacy lawsuit settlement", "a share buyback plan"]
    return doc(f"j{i}", f"Apple Inc. announces {topics[i % len(topics)]}", hours=hours)


def test_the_journal_round_trips_and_compacts_to_the_window(tmp_path: Path) -> None:
    j = Journal(tmp_path / "live" / "journal.jsonl")
    j.append("LIVE", [_doc(1, 1), _doc(2, 60)])
    j.append("MANUAL", [_doc(3, 2)])
    kept = j.load(AS_OF - timedelta(hours=48))
    assert [(c, d.id) for c, d in kept] == [("LIVE", "j1"), ("MANUAL", "j3")]
    j.compact(kept)
    assert len(j.path.read_text().splitlines()) == 2


def test_a_damaged_journal_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    j = Journal(tmp_path / "journal.jsonl")
    j.append("LIVE", [_doc(1, 1)])
    with j.path.open("a") as fh:
        fh.write("{not json}\n" + json.dumps({"channel": "LIVE", "doc": {"id": ""}}) + "\n")
    assert [d.id for _, d in j.load(AS_OF - timedelta(hours=48))] == ["j1"]


def test_warm_start_rebuilds_signals_from_journalled_inputs(tmp_path: Path) -> None:
    j = Journal(tmp_path / "journal.jsonl")
    j.append("LIVE", [_doc(1, 1)])
    j.append("MANUAL", [_doc(2, 2)])
    eng, store = make_engine()
    svc = LiveService(cfg=LIVE_CFG, engine=eng, store=store, source=None, journal=j, event_model_note=lambda: ("m", None),
                      market_through="2026-10-01", clock=lambda: AS_OF)
    assert svc.warm_start() == 2 and len(store) == 2
    assert sorted(m.channel for _, m in store.items()) == ["LIVE", "MANUAL"]


# ------------------------------------------------------------------------------------------------------------------ live source
def gdelt_record(i: int, title: str, minutes_ago: int = 20, domain: str = "wire.example.com") -> dict:
    seen = (AS_OF - timedelta(minutes=minutes_ago)).strftime("%Y%m%dT%H%M%SZ")
    return {"url": f"https://{domain}/a{i}", "title": title, "seendate": seen, "domain": domain, "language": "English",
            "sourcecountry": "United States"}


class FakeTransport:
    """Answers GDELT-shaped URLs from a script of responses: dicts become JSON, strings are sent as-is, exceptions are raised."""

    def __init__(self, *responses) -> None:
        self.responses, self.calls = list(responses), []

    def __call__(self, url: str, timeout: float):
        self.calls.append(url)
        r = self.responses.pop(0) if self.responses else {}
        if isinstance(r, Exception):
            raise r
        return 200, (r if isinstance(r, str) else json.dumps(r)).encode()


def make_source(transport, queries=("a", "b")) -> GdeltLiveSource:
    return GdeltLiveSource(GdeltSourceConfig(queries=list(queries), throttle_seconds=5.0), transport=transport,
                           sleep=lambda s: None, clock=lambda: AS_OF)


def make_service(source, tmp_path: Path, **kw):
    eng, store = make_engine()
    svc = LiveService(cfg=LIVE_CFG, engine=eng, store=store, source=source, journal=Journal(tmp_path / "j.jsonl"),
                      event_model_note=lambda: ("tfidf", None), market_through="2026-10-01", clock=lambda: AS_OF, **kw)
    return svc, store


def test_the_poll_asks_gdelt_for_the_trailing_window_with_a_throttle() -> None:
    t = FakeTransport({"articles": []}, {})
    poll = make_source(t).poll()
    assert len(t.calls) == 2 and "mode=artlist" in t.calls[0] and "sourcelang%3Aenglish" in t.calls[0]
    assert "startdatetime=20261001103000" in t.calls[0] and "enddatetime=20261001120000" in t.calls[0]
    assert poll.queries_ok == 2 and poll.records == [] and not poll.failed


def test_live_articles_go_through_the_one_gdelt_adapter() -> None:
    t = FakeTransport({"articles": [gdelt_record(1, "Apple Inc. beats estimates and raises guidance"), {"url": "https://x.com/z"}]}, {})
    poll = make_source(t).poll()
    docs = to_documents(poll)
    assert isinstance(docs[0], RawDocument) and docs[0].raw_metadata["adapter"] == "gdelt-live"
    assert docs[0].raw_metadata["timestamp_origin"] == "GDELT_FIRST_SEEN"
    assert not isinstance(docs[1], RawDocument)  # a record without a title is rejected by the adapter, not guessed


def test_a_good_poll_creates_signals_and_reports_ok(tmp_path: Path) -> None:
    t = FakeTransport({"articles": [gdelt_record(1, "Apple Inc. beats estimates and raises guidance"),
                                    gdelt_record(2, "Goldman Sachs fined $50 million over trading violations", domain="b.example.com")]}, {})
    svc, store = make_service(make_source(t), tmp_path)
    st = svc.refresh()
    assert st.state == "OK" and st.new_total == 2 and st.live_signal_count == 2 and st.last_error is None
    assert st.source_mode == "GDELT" and not st.simulated and st.seq == store.seq
    assert svc.journal.path.is_file() and len(svc.journal.path.read_text().splitlines()) == 2
    again = svc.refresh()  # the same articles again: nothing new, nothing duplicated
    assert again.new_total == 2 and again.live_signal_count == 2


def test_a_partial_failure_is_degraded_and_keeps_what_it_got(tmp_path: Path) -> None:
    t = FakeTransport({"articles": [gdelt_record(1, "Apple Inc. beats estimates and raises guidance")]},
                      FetchError("boom"), FetchError("boom"), FetchError("boom"))
    svc, _ = make_service(make_source(t), tmp_path)
    st = svc.refresh()
    assert st.state == "DEGRADED" and st.live_signal_count == 1 and "boom" in st.last_error


def test_total_failure_creates_no_signal_and_backs_off(tmp_path: Path) -> None:
    errs = [FetchError("down")] * 12
    svc, store = make_service(make_source(FakeTransport(*errs)), tmp_path)
    s1 = svc.refresh()
    assert s1.state == "ERROR" and s1.consecutive_failures == 1 and len(store) == 0 and s1.last_success_at is None
    first_gap = (s1.next_attempt_at - AS_OF).total_seconds()
    s2 = svc.refresh()
    assert s2.consecutive_failures == 2 and (s2.next_attempt_at - AS_OF).total_seconds() == 2 * first_gap
    for _ in range(8):
        svc.refresh()
    assert (svc.status().next_attempt_at - AS_OF).total_seconds() <= 1800


def test_rate_limit_text_and_malformed_json_are_failures_not_data(tmp_path: Path) -> None:
    svc, store = make_service(make_source(FakeTransport("Please limit requests to one every 5 seconds", "{not json"), queries=("a",)), tmp_path)
    st = svc.refresh()
    assert st.state == "ERROR" and len(store) == 0 and st.last_error


def test_recovery_after_failure_returns_to_ok(tmp_path: Path) -> None:
    svc, _ = make_service(make_source(FakeTransport(*([FetchError("down")] * 6), {"articles": [gdelt_record(1, "Apple Inc. beats estimates")]},
                                                    {}), queries=("a", "b")), tmp_path)
    assert svc.refresh().state == "ERROR"
    st = svc.refresh()
    assert st.state in {"OK", "DEGRADED"} and st.consecutive_failures in (0, 1)


def test_live_off_is_reported_and_refresh_is_inert(tmp_path: Path) -> None:
    svc, store = make_service(None, tmp_path)
    assert svc.status().state == "OFF" and not svc.status().enabled
    assert svc.refresh().state == "OFF" and len(store) == 0


def test_a_crashing_source_degrades_the_feed_instead_of_killing_the_poller(tmp_path: Path) -> None:
    class Bad:
        mode = "GDELT"

        def poll(self) -> LivePoll:
            raise RuntimeError("source bug")

    svc, store = make_service(Bad(), tmp_path)
    st = svc.refresh()
    assert st.state == "ERROR" and "source bug" in st.last_error and len(store) == 0


# ------------------------------------------------------------------------------------------------------------------ capture
def write_capture(path: Path, n: int) -> None:
    topics = ["a new iPhone", "record services revenue", "a chip supply deal", "a privacy lawsuit settlement", "a share buyback plan"]
    rows = [gdelt_record(i, f"Apple Inc. announces {topics[i % len(topics)]}", minutes_ago=100 - i, domain=f"s{i}.example.com")
            for i in range(n)]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_a_capture_replays_in_batches_on_its_own_clock_and_then_goes_idle(tmp_path: Path) -> None:
    p = tmp_path / "cap.jsonl"
    write_capture(p, 5)
    src = CaptureSource(CaptureSourceConfig(path=p, batch_size=3), base=tmp_path)
    svc, store = make_service(src, tmp_path)
    s1 = svc.refresh()
    assert s1.state == "OK" and s1.simulated and s1.source_mode == "CAPTURE" and len(store) == 3
    s2 = svc.refresh()
    assert s2.state == "IDLE" and len(store) == 5
    assert svc.journal.path.exists() is False  # a capture is its own replay: it is not journalled
    s3 = svc.refresh()
    assert s3.state == "IDLE" and len(store) == 5


def test_a_missing_capture_file_stops_start_up() -> None:
    with pytest.raises(ConfigError, match="capture file missing"):
        CaptureSource(CaptureSourceConfig(path=Path("nope.jsonl"), batch_size=3), base=Path("/tmp"))


def test_the_background_loop_polls_and_stops_cleanly(tmp_path: Path) -> None:
    write_capture(tmp_path / "cap.jsonl", 4)
    src = CaptureSource(CaptureSourceConfig(path=tmp_path / "cap.jsonl", batch_size=2, interval_seconds=1), base=tmp_path)
    svc, store = make_service(src, tmp_path)

    async def go() -> None:
        stop = asyncio.Event()
        await asyncio.wait_for(svc.run(stop), timeout=10)  # exhausts the capture and returns

    asyncio.run(go())
    assert len(store) == 4 and svc.status().state == "IDLE"


# ---------------------------------------------------------------------------------------------------------------------- config
def test_the_committed_live_config_is_valid_and_off() -> None:
    assert LIVE_CFG.enabled is False and LIVE_CFG.source.kind == "gdelt"
    assert LIVE_CFG.source.gdelt.throttle_seconds >= 5 and LIVE_CFG.dedup.unknown_same_event is not None


def test_live_config_rejects_unknown_keys_and_absolute_journals(tmp_path: Path) -> None:
    text = (REPO_ROOT / "configs" / "live.yaml").read_text()
    (tmp_path / "live.yaml").write_text(text + "\nsurprise: 1\n")
    with pytest.raises(ConfigError):
        load_live_config(tmp_path)
    (tmp_path / "live.yaml").write_text(text.replace("data/live/journal.jsonl", "/etc/journal.jsonl"))
    with pytest.raises(ConfigError, match="relative"):
        load_live_config(tmp_path)
