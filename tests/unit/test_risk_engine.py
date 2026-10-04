"""The incremental engine: same stages as the batch run, one report at a time, bounded memory, no invented values."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from eventshock.config import REPO_ROOT
from eventshock.domain import SourceType
from eventshock.ingestion.base import RejectCode, Rejected
from eventshock.pipeline.config import UnknownSameEventConfig
from eventshock.pipeline.embeddings import EmbeddingUnavailable
from eventshock.pipeline.engine import Outcome, RiskEngine
from eventshock.pipeline.enrich import PlaceholderEnricher
from eventshock.pipeline.scope import ScopeResolver, load_scope_config
from eventshock.store import LiveSignalStore
from tests.pipe_helpers import AS_OF, CFG, ENRICH, ENTITIES, doc

SCOPE = ScopeResolver(load_scope_config(REPO_ROOT / "configs"))


def make_engine(*, retention=48.0, max_signals=1500, unknown_same_event=None, enricher=None, fallback=None, start_on_fallback=False):
    cfg = CFG.model_copy(update={"dedup": CFG.dedup.model_copy(update={"unknown_same_event": unknown_same_event})})
    store = LiveSignalStore(retention, max_signals)
    eng = RiskEngine(entities=ENTITIES, pipeline_cfg=cfg, enrich_cfg=ENRICH, scope_resolver=SCOPE,
                     enricher=enricher or PlaceholderEnricher(ENRICH), fallback_enricher=fallback, store=store,
                     event_model_id="primary", fallback_event_model_id="fallback", start_on_fallback=start_on_fallback)
    return eng, store


def test_a_new_report_becomes_a_signal_in_the_live_overlay() -> None:
    eng, store = make_engine()
    [o] = eng.ingest([doc("a", "Apple Inc. beats estimates and raises guidance")], channel="LIVE", now=AS_OF)
    assert o.outcome is Outcome.NEW and o.signal_id
    s = store.get(o.signal_id)
    assert s.entity.entity_id == "ENT_AAPL" and s.scope.level.value == "COMPANY" and s.created_at == AS_OF
    assert store.meta(o.signal_id).channel == "LIVE" and store.seq == 1


def test_the_same_document_twice_changes_nothing() -> None:
    eng, store = make_engine()
    eng.ingest([doc("a", "Apple Inc. beats estimates")], channel="LIVE", now=AS_OF)
    seq = store.seq
    [o] = eng.ingest([doc("a", "Apple Inc. beats estimates")], channel="LIVE", now=AS_OF)
    assert o.outcome is Outcome.DUPLICATE and store.seq == seq and len(store) == 1


def test_a_second_outlet_joins_the_story_and_the_signal_gains_a_source() -> None:
    eng, store = make_engine()
    [a] = eng.ingest([doc("a", "Goldman Sachs fined $50 million over trading violations", source="one.example.com", hours=5)],
                     channel="LIVE", now=AS_OF)
    first_seq = store.meta(a.signal_id).first_seq
    [b] = eng.ingest([doc("b", "Goldman Sachs fined $50 million over trading violations", source="two.example.com", hours=4)],
                     channel="MANUAL", now=AS_OF)
    assert b.outcome is Outcome.UPDATED and b.signal_id == a.signal_id and b.relation == "SYNDICATED"
    s = store.get(a.signal_id)
    assert s.evidence.source_count == 2 and s.evidence.unique_domain_count == 2
    meta = store.meta(a.signal_id)
    assert meta.first_seq == first_seq and meta.updated_seq > first_seq and meta.channel == "LIVE"  # arrived live, then grew
    assert len(store) == 1


def test_an_earlier_report_that_arrives_late_takes_over_and_the_old_link_still_resolves() -> None:
    eng, store = make_engine()
    [late] = eng.ingest([doc("late", "Goldman Sachs fined $50 million over trading violations", source="two.example.com", hours=4)],
                        channel="LIVE", now=AS_OF)
    [early] = eng.ingest([doc("early", "Goldman Sachs fined $50 million over trading violations", source="one.example.com", hours=6)],
                         channel="LIVE", now=AS_OF)
    assert early.signal_id != late.signal_id and len(store) == 1
    assert store.get(late.signal_id).id == early.signal_id  # the old id still opens the merged signal
    assert store.get(early.signal_id).evidence.source_count == 2


def test_exact_url_repeat_is_folded_not_counted() -> None:
    eng, store = make_engine()
    eng.ingest([doc("a", "Microsoft Corporation unveils a new cloud region", url="https://one.example.com/x")], channel="LIVE", now=AS_OF)
    [o] = eng.ingest([doc("b", "Microsoft Corporation unveils a new cloud region", url="https://one.example.com/x?utm_source=z")],
                     channel="LIVE", now=AS_OF)
    assert o.outcome is Outcome.DUPLICATE and o.relation == "EXACT_DUPLICATE"
    assert store.get(o.signal_id).evidence.source_count == 1


def test_an_unscorable_or_invalid_record_is_quarantined_with_its_reason_and_creates_nothing() -> None:
    eng, store = make_engine()
    rej = Rejected("gdelt-live", "x:1", RejectCode.BAD_TIMESTAMP, "unparseable seendate", "{}")
    out = eng.ingest([doc("short", "Hi"), rej], channel="LIVE", now=AS_OF)
    assert [o.outcome for o in out] == [Outcome.QUARANTINED, Outcome.QUARANTINED]
    assert out[0].code == RejectCode.TOO_SHORT.value and out[1].code == RejectCode.BAD_TIMESTAMP.value
    assert len(store) == 0 and eng.status.quarantined == 2


def test_a_report_older_than_retention_is_rejected_as_outside_the_window() -> None:
    eng, store = make_engine(retention=24)
    [o] = eng.ingest([doc("old", "Apple Inc. beats estimates and raises guidance", hours=30)], channel="LIVE", now=AS_OF)
    assert o.outcome is Outcome.QUARANTINED and o.code == RejectCode.OUTSIDE_WINDOW.value and len(store) == 0


def test_signals_expire_with_retention_and_memory_stays_bounded() -> None:
    eng, store = make_engine(retention=24, max_signals=10)
    eng.ingest([doc("a", "Apple Inc. beats estimates and raises guidance", hours=20)], channel="LIVE", now=AS_OF)
    assert len(store) == 1
    later = AS_OF + timedelta(hours=10)  # "a" is now 30 h old
    eng.ingest([doc("b", "Microsoft Corporation unveils a new cloud region", hours=-9.5)], channel="LIVE", now=later)
    assert len(store) == 1 and eng.window_size == 1
    texts = [f"Visa Inc. announces quarterly result number {i} with record volumes" for i in range(15)]
    eng.ingest([doc(f"v{i}", t, hours=-9 + i * 0.01) for i, t in enumerate(texts)], channel="LIVE", now=later)
    assert len(store) <= 10


def test_unresolved_macro_reports_cluster_only_when_the_live_rule_is_on() -> None:
    a = doc("a", "Federal Reserve holds interest rates steady as inflation cools and labour market softens", source="one.example.com", hours=5)
    b = doc("b", "Federal Reserve holds interest rates steady as inflation cools, labour market softens", source="two.example.com", hours=4)
    off, store_off = make_engine()
    off.ingest([a, b], channel="LIVE", now=AS_OF)
    on, store_on = make_engine(unknown_same_event=UnknownSameEventConfig(threshold=0.7, min_shared_tokens=5, window_hours=24))
    on.ingest([a, b], channel="LIVE", now=AS_OF)
    (s,) = [s for s, _ in store_on.items()]
    assert s.evidence.source_count == 2 and s.scope.level.value == "MARKET"
    assert len(store_on) <= len(store_off)  # the rule can only add merges


def test_a_looser_reworded_macro_story_merges_only_with_the_rule() -> None:
    a = doc("a", "Federal Reserve holds interest rates steady as inflation cools and the labour market softens", source="one.example.com", hours=5)
    b = doc("b", "Fed keeps interest rates steady as inflation cools and the labour market softens further", source="two.example.com", hours=4)
    off, store_off = make_engine()
    off.ingest([a, b], channel="LIVE", now=AS_OF)
    on, store_on = make_engine(unknown_same_event=UnknownSameEventConfig(threshold=0.5, min_shared_tokens=5, window_hours=24))
    on.ingest([a, b], channel="LIVE", now=AS_OF)
    assert len(store_off) == 2 and len(store_on) == 1


def test_channel_is_kept_from_the_first_report() -> None:
    eng, store = make_engine()
    [a] = eng.ingest([doc("a", "Goldman Sachs fined $50 million over trading violations", source="one.example.com", hours=5)],
                     channel="MANUAL", now=AS_OF)
    eng.ingest([doc("b", "Goldman Sachs fined $50 million over trading violations", source="two.example.com", hours=4)],
               channel="LIVE", now=AS_OF)
    assert store.meta(a.signal_id).channel == "MANUAL"


class _Broken(PlaceholderEnricher):
    version = "broken"

    def enrich(self, item):
        raise EmbeddingUnavailable("no encoder installed")


def test_when_the_served_model_cannot_embed_the_engine_falls_back_once_and_says_so() -> None:
    eng, store = make_engine(enricher=_Broken(ENRICH), fallback=PlaceholderEnricher(ENRICH))
    [o] = eng.ingest([doc("a", "Apple Inc. beats estimates and raises guidance")], channel="LIVE", now=AS_OF)
    assert o.outcome is Outcome.NEW and eng.status.event_model == "fallback"
    assert "no encoder installed" in eng.status.event_fallback_reason
    [o2] = eng.ingest([doc("b", "Visa Inc. announces record volumes in a new quarter")], channel="LIVE", now=AS_OF)
    assert o2.outcome is Outcome.NEW and len(store) == 2


def test_without_a_fallback_the_failure_is_loud_not_invented() -> None:
    eng, store = make_engine(enricher=_Broken(ENRICH))
    with pytest.raises(EmbeddingUnavailable):
        eng.ingest([doc("a", "Apple Inc. beats estimates and raises guidance")], channel="LIVE", now=AS_OF)
    assert len(store) == 0


def test_start_on_fallback_never_calls_the_primary() -> None:
    eng, store = make_engine(enricher=_Broken(ENRICH), fallback=PlaceholderEnricher(ENRICH), start_on_fallback=True)
    [o] = eng.ingest([doc("a", "Apple Inc. beats estimates and raises guidance")], channel="LIVE", now=AS_OF)
    assert o.outcome is Outcome.NEW and eng.status.event_model == "fallback"


def test_social_posts_and_news_share_the_engine() -> None:
    eng, store = make_engine()
    [o] = eng.ingest([doc("t", "$AAPL guidance raised, bullish", stype=SourceType.SOCIAL, origin="SOURCE", url=None)],
                     channel="MANUAL", now=AS_OF)
    assert store.get(o.signal_id).document.source_type is SourceType.SOCIAL


def test_concurrent_ingests_do_not_corrupt_the_store() -> None:
    eng, store = make_engine()
    errors: list[Exception] = []

    def worker(k: int) -> None:
        try:
            for i in range(8):
                eng.ingest([doc(f"w{k}-{i}", f"Apple Inc. announces update number {k}-{i} for developers", source=f"s{k}.example.com")],
                           channel="LIVE", now=AS_OF)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    ids = {s.id for s, _ in store.items()}
    assert ids == {eng._doc_signal[d] for d in eng._doc_signal}  # noqa: SLF001 (every signal belongs to a window document, and vice versa)
