from __future__ import annotations

import random
import string

from eventshock.domain import DataOrigin, EventCategory, RawDocument, SourceType
from eventshock.ingestion.base import RejectCode, Rejected
from eventshock.pipeline.enrich import EnrichmentInput, PlaceholderEnricher
from tests.pipe_helpers import ENRICH, ENTITIES, doc, run

E = PlaceholderEnricher(ENRICH)


def enrich(text, label=None, domains=1):
    return E.enrich(EnrichmentInput(text=text, source_label=label, unique_domains=domains))


class TestPlaceholderEnricher:
    def test_source_label_wins_and_is_labelled(self):
        e = enrich("anything at all", label="bearish")
        assert (e.sentiment.score, e.stage_origins["sentiment"]) == (-1.0, "SOURCE_LABEL")
        assert enrich("x", label="neutral").sentiment.score == 0.0

    def test_lexicon_sentiment_direction_and_bounds(self):
        assert enrich("Shares surge as company beats estimates").sentiment.score > 0
        assert enrich("Stock plunges after probe and lawsuit").sentiment.score < 0
        assert enrich("Company holds annual meeting").sentiment.score == 0

    def test_event_keywords(self):
        assert enrich("Fed signals rate cut as inflation cools").event.category is EventCategory.MACROECONOMIC
        assert enrich("Regulator opens antitrust probe").event.category is EventCategory.REGULATORY_LEGAL
        none = enrich("Quiet day in the village").event
        assert none.category is EventCategory.MARKET_VALUATION and none.confidence < 0.5

    def test_impact_in_range_and_explained_as_placeholder(self):
        hi = enrich("War sanctions plunge markets as conflict escalates", domains=8).impact
        lo = enrich("Analyst initiates coverage with neutral rating", label="neutral").impact
        assert 1 <= lo.score < hi.score <= 10
        assert all("placeholder" in d.note.lower() or d.note for d in hi.drivers)
        assert enrich("x").versions["impact"].startswith("placeholder")


class TestPipelineAccounting:
    def records(self):
        return [
            doc("a1", "Apple shares jump after record iPhone quarter", source="a.com", hours=20),
            doc("a2", "Apple shares jump after record iPhone quarter", source="a.com", hours=19),       # exact dup
            doc("a3", "Apple shares jump after record iPhone quarter - Reuters", source="b.com", hours=18),  # syndicated
            doc("m1", "Microsoft faces antitrust probe in Europe over cloud licensing", hours=10),
            doc("u1", "Global bond markets steady ahead of central bank meeting", hours=9),
            doc("t1", "$MSFT - Jefferies raises price target on Microsoft https://t.co/a", source="Twitter Financial News",
                url=None, stype=SourceType.SOCIAL, origin="SYNTHETIC_REPLAY_CLOCK", label="bullish", hours=30),
            doc("bad1", "Short", hours=5),
            doc("bad2", "Nuevo informe de resultados trimestrales publicado hoy", language="es", hours=5),
            Rejected("gdelt-doc", "x.jsonl:99", RejectCode.MALFORMED_RECORD, "bad json", "{oops"),
        ]

    def test_every_record_is_accounted_for(self):
        res = run(self.records())
        c = res.report.counts
        assert c.records_read == 9 and c.quarantined == 3
        assert c.accepted == c.exact_duplicates_folded + c.reports_in_signals == 6
        assert res.report.quarantine_by_code == {"MALFORMED_RECORD": 1, "NON_ENGLISH": 1, "TOO_SHORT": 1}
        assert sum(s.records for s in res.report.sources) == c.records_read

    def test_apple_cluster_becomes_one_signal_with_evidence(self):
        res = run(self.records())
        aapl, = [s for s in res.signals if s.entity.entity_id == "ENT_AAPL"]
        assert aapl.document.id == "a1" and aapl.evidence.source_count == 2 == 1 + len(aapl.evidence.corroborating)
        assert aapl.evidence.unique_domain_count == 2
        assert aapl.evidence.corroborating[0].relation == "SYNDICATED"
        assert aapl.provenance.dedup.exact_duplicates_folded == 1
        assert aapl.data_origin is DataOrigin.REAL_SOURCE_PLACEHOLDER_NLP

    def test_unknown_entity_signal_is_still_valid_and_flagged(self):
        res = run(self.records())
        u, = [s for s in res.signals if s.document.id == "u1"]
        assert u.entity.is_unknown and u.provenance.entity_audit.rule == "NONE"

    def test_tweet_uses_source_label_and_is_flagged_synthetic_time(self):
        res = run(self.records())
        t, = [s for s in res.signals if s.document.id == "t1"]
        assert t.sentiment.score == 1.0 and t.provenance.stage_origins["sentiment"] == "SOURCE_LABEL"
        assert t.provenance.timestamp_origin.value == "SYNTHETIC_REPLAY_CLOCK"
        assert t.evidence.recent_mention_count == 0 and t.evidence.coverage_velocity == 0

    def test_output_is_deterministic_and_order_independent(self):
        recs = self.records()
        shuffled = recs[:]
        random.Random(3).shuffle(shuffled)
        a, b = run(recs), run(shuffled)
        assert a.report.output_digest == b.report.output_digest
        assert [s.id for s in a.signals] == [s.id for s in b.signals]
        assert run(recs).report.output_digest == a.report.output_digest


class TestMessyInputCannotCorruptSignals:
    """Seeded fuzz: whatever garbage arrives, the pipeline neither crashes nor emits an invalid/inconsistent signal."""

    ALPHABET = string.ascii_letters + string.digits + " $%&.,;:!?-–—_'\"()[]{}<>/\\|\n\t​éÃ©�中"

    def junk(self, rng):
        words = ["Apple", "Microsoft", "Visa", "Target", "$AAPL", "$ZZZZ", "NYSE: V", "JPMorgan", "shares", "plunge",
                 "http://x.co/a", "<b>bold</b>", "&amp;", "J.P.", "Goldman", "iPhone", "earnings", "probe", "​"]
        return " ".join(rng.choice(words) if rng.random() < 0.5 else
                        "".join(rng.choice(self.ALPHABET) for _ in range(rng.randint(1, 9)))
                        for _ in range(rng.randint(0, 30)))

    def test_fuzz(self):
        rng = random.Random(20261001)
        recs = []
        for i in range(400):
            text = self.junk(rng)
            try:
                recs.append(doc(f"f{i}", text, source=rng.choice(["a.com", "b.com", "Twitter Financial News"]),
                                url=rng.choice(["auto", None, "javascript:x", "ht!tp://bad", "https://a.com/x?utm_x=1"]),
                                hours=rng.uniform(-3, 24 * 20), language=rng.choice(["en", "en", "en", "fr", ""])))
            except ValueError:
                continue  # RawDocument itself refused it (empty text): the adapter layer would have rejected it
        res = run(recs)
        c = res.report.counts
        assert c.records_read == len(recs) == c.quarantined + c.accepted
        assert c.accepted == c.exact_duplicates_folded + c.reports_in_signals
        assert len({s.id for s in res.signals}) == len(res.signals)
        known = {e.entity_id for e in ENTITIES}
        for s in res.signals:
            RawDocument.model_validate(s.document.model_dump())          # still a valid document
            assert s.entity.is_unknown or s.entity.entity_id in known
            assert s.evidence.source_count == 1 + len(s.evidence.corroborating)
            assert s.evidence.unique_domain_count <= s.evidence.source_count
            assert 1 <= s.impact.score <= 10 and -1 <= s.sentiment.score <= 1
            assert s.document.published_at <= s.created_at
            assert "​" not in s.document.headline and "  " not in s.document.headline
        assert run(recs).report.output_digest == res.report.output_digest


def test_entity_comes_from_the_text_never_from_the_fetch_query():
    """GDELT's relevance ranking returns unrelated pages; the query that fetched a record must not attribute it."""
    d = doc("q1", "Local council approves new bridge repairs for the autumn season")
    d.raw_metadata["gdelt_query"] = '("Apple Inc" OR "Microsoft Corp")'
    d2 = doc("q2", "Apple Inc raises iPhone price after tariff change")
    d2.raw_metadata["gdelt_query"] = '("Tesla Inc")'
    res = run([d, d2])
    by = {s.document.id: s for s in res.signals}
    assert by["q1"].entity.is_unknown
    assert by["q2"].entity.entity_id == "ENT_AAPL"


def test_fetch_log_collapses_attempts_and_keeps_failures():
    from eventshock.pipeline.run import summarise_fetch_log

    rows = summarise_fetch_log([
        {"query": "a", "status": "error", "error": "HTTP 429"},
        {"query": "b", "status": "error", "error": "HTTP 429"},
        {"query": "a", "status": "ok", "returned": 250, "added": 201},
    ])
    by = {r.query: r for r in rows}
    assert (by["a"].status, by["a"].attempts, by["a"].added) == ("ok", 2, 201)
    assert (by["b"].status, by["b"].last_error) == ("error", "HTTP 429")
    assert rows[0].query == "b", "failures are listed first"
