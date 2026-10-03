"""The per-signal context: grouped model inputs, filings placed around the report (point-in-time), and the separate realised outcome."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.domain import EventCategory, RiskSignal
from eventshock.pipeline.event_context import EventCalendar
from eventshock.services.signal_context import (
    OUTCOMES_SCHEMA,
    Outcomes,
    availability_of,
    build_signal_context,
)

ITEMS = yaml.safe_load((REPO_ROOT / "configs" / "sec_items.yaml").read_text(encoding="utf-8"))


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def filing(tk, when, items, form="8-K"):
    return {"ticker": tk, "acceptance_utc": when, "accession": f"{tk}-{when}", "form": form, "items": items}


REPORT = "2026-09-30T03:00:00Z"
CAL = EventCalendar(
    [
        filing("AAA", "2025-09-25T20:00:00Z", ["2.02", "9.01"]),   # an earlier earnings release, feeds the earnings calendar
        filing("AAA", "2026-09-10T12:00:00Z", ["7.01"]),           # before the report, outside every window
        filing("AAA", "2026-09-29T20:00:00Z", ["5.02"]),           # within 24 h before: feeds the recent-filings flags
        filing("AAA", "2026-09-30T03:00:00Z", ["8.01"]),           # exactly at the report: NOT before
        filing("AAA", "2026-10-02T00:15:00Z", ["2.02", "2.05"]),   # after the report
        filing("AAA", "2026-10-01T08:00:00Z", ["9.01"]),           # exhibit-only: never an event
    ],
    [],
    ITEMS,
)


def signal(**over) -> RiskSignal:
    base = {
        "id": "sig_test", "status": "COMPLETE", "data_origin": "REAL_SOURCE_MIXED_NLP", "created_at": "2026-10-01T12:00:00Z",
        "document": {"id": "d1", "source": "x.com", "source_type": "NEWS", "published_at": REPORT, "ingested_at": "2026-10-01T12:00:00Z",
                     "headline": "AAA reports Q3", "language": "en"},
        "entity": {"entity_id": "AAA", "entity_name": "AAA Inc", "ticker": "AAA", "sector": "Tech", "country": "US", "link_confidence": 0.95},
        "sentiment": {"positive": 0.2, "neutral": 0.6, "negative": 0.2, "score": 0.0},
        "event": {"category": "EARNINGS_FINANCIAL_PERFORMANCE", "status": "CLASSIFIED", "probabilities": {**{c.value: 0.0 for c in EventCategory}, "EARNINGS_FINANCIAL_PERFORMANCE": 1.0},
                  "no_event_probability": 0.1},
        "impact": {"score": 7, "raw": 0.65, "drivers": [], "quantisation": "ceil(raw * 10), min 1", "predicted_severity": 1.6,
                   "scope": "ISSUER"},
        "evidence": {"source_count": 1, "unique_domain_count": 1, "recent_mention_count": 0, "coverage_velocity": 0.0, "novelty_score": 0.2,
                     "model_confidence": 0.9, "contradicted_by": [], "corroborating": []},
        "model_versions": {"sentiment": "s", "event": "e", "impact": "i", "entity_resolver": "r", "feature_schema": "f"},
        "provenance": {
            "adapter": "a", "snapshot_id": "s", "record_ref": "r:1", "content_sha256": "0" * 64, "timestamp_origin": "SOURCE",
            "pipeline_version": "p", "entity_audit": {"rule": "LEGAL_NAME", "matched_text": "AAA", "multi_entity": False, "candidates": [], "rejected": [],
                                                      "unmatched_cashtags": []},
            "dedup": {"cluster_id": "c", "member_count": 1, "exact_duplicates_folded": 0, "members": []},
            "stage_origins": {"sentiment": "MODEL", "event": "MODEL", "impact": "MODEL"},
            "impact": {"model_id": "impact-v2", "model_version": "2", "artifact_sha256": "1" * 64, "lifecycle": "CALIBRATED", "scope": "ISSUER",
                       "feature_schema": "impact-features-v2", "calibrated": True, "session": "2026-09-30", "timing": "OFF_HOURS",
                       "timing_reliable": True, "market_context_as_of": "2026-09-29",
                       "inputs": {"f_sigma_60": 0.014, "earn_days_since_last": 91.0, "f8k_count_24h": 1.0, "novelty": 0.2, "item_5_02": 1.0},
                       "missing_inputs": ["f_ret_20d"]},
        },
    }
    for k, v in over.items():
        base[k] = v
    return RiskSignal.model_validate(base)


OUT = Outcomes({("ISSUER", "AAA", "2026-09-30"): __import__("eventshock.services.signal_context", fromlist=["OutcomeRow"]).OutcomeRow(
    "ISSUER", "AAA", "2026-09-30", 0.41, -0.41, 1)}, 2, "definition")
ASOF = at("2026-10-01T12:00:00")


class TestInputs:
    def test_inputs_are_grouped_and_classified(self):
        ctx = build_signal_context(signal(), CAL, OUT, ASOF)
        by = {i.name: i for i in ctx.inputs}
        assert by["f_sigma_60"].availability == "t" and by["f_sigma_60"].group == "volatility regime"
        assert by["earn_days_since_last"].availability == "a" and "earnings calendar" in by["earn_days_since_last"].group
        assert by["f8k_count_24h"].availability == "b" and "SEC filings" in by["f8k_count_24h"].group
        assert availability_of("item_5_02") == "b"
        assert ctx.missing_inputs == ["f_ret_20d"] and ctx.impact_scored

    def test_never_lists_a_post_event_feature_as_an_input(self):
        ctx = build_signal_context(signal(), CAL, OUT, ASOF)
        assert {i.availability for i in ctx.inputs} <= {"a", "b", "t"}
        assert any("outlets" in n for n in ctx.not_used) and any("realised" in n for n in ctx.not_used)

    def test_placeholder_signal_has_no_inputs(self):
        s = signal()
        s = s.model_copy(update={"provenance": s.provenance.model_copy(update={"impact": None})})
        ctx = build_signal_context(s, CAL, OUT, ASOF)
        assert ctx.inputs == [] and not ctx.impact_scored and ctx.not_used == []
        assert ctx.outcome is None and "no model-scored impact" in ctx.outcome_note


class TestFilingsPointInTime:
    def test_before_at_and_after_the_report(self):
        ctx = build_signal_context(signal(), CAL, OUT, ASOF)
        rows = {f.items[0]: f for f in ctx.filings}
        assert rows["7.01"].role == "BEFORE_NOT_USED" and rows["7.01"].hours_from_report < 0
        assert rows["5.02"].role == "FEEDS_MODEL" and "24 hours" in rows["5.02"].role_note
        # the filing accepted EXACTLY at the report time is not "before" (strict), and never feeds the model
        assert rows["8.01"].role == "AFTER_REPORT" and rows["8.01"].hours_from_report == 0
        after = [f for f in ctx.filings if f.role == "AFTER_REPORT"]
        assert {f.items[0] for f in after} == {"8.01", "2.02"}
        assert all(f.hours_from_report >= 0 for f in after)
        assert all(f.hours_from_report < 0 for f in ctx.filings if f.role != "AFTER_REPORT")

    def test_the_latest_8k_before_the_report_feeds_hours_since_last(self):
        cal = EventCalendar([filing("AAA", "2026-09-17T00:21:00Z", ["5.02", "7.01"]), filing("AAA", "2026-10-02T00:15:00Z", ["2.02"])], [], ITEMS)
        ctx = build_signal_context(signal(), cal, OUT, ASOF)
        before = [f for f in ctx.filings if f.hours_from_report < 0]
        assert len(before) == 1 and before[0].role == "FEEDS_MODEL" and "hours since the last 8-K" in before[0].role_note
        # more than 30 days back the feature is capped, so a lone old filing is not read
        old = EventCalendar([filing("AAA", "2026-08-20T00:00:00Z", ["7.01"])], [], ITEMS)
        assert [f.role for f in build_signal_context(signal(), old, OUT, ASOF).filings] == ["BEFORE_NOT_USED"]

    def test_earnings_filing_before_feeds_the_earnings_calendar(self):
        ctx = build_signal_context(signal(), CAL, OUT, ASOF)
        e = [f for f in ctx.filings if f.accession == "AAA-2025-09-25T20:00:00Z"]
        # outside the 45-day display window, so it is not listed at all; the calendar still uses it (covered by the feature tests)
        assert e == []

    def test_exhibit_only_filings_are_never_listed(self):
        ctx = build_signal_context(signal(), CAL, OUT, ASOF)
        assert all(set(f.items) != {"9.01"} for f in ctx.filings)

    def test_known_at_assessment_follows_the_replay_clock(self):
        ctx = build_signal_context(signal(), CAL, OUT, ASOF)
        later = [f for f in ctx.filings if f.items == ["2.02", "2.05"]][0]
        assert later.role == "AFTER_REPORT" and not later.known_at_assessment  # accepted 10-02, after the 10-01 replay clock
        before = [f for f in ctx.filings if f.items == ["5.02"]][0]
        assert before.known_at_assessment

    def test_future_filings_do_not_change_the_inputs(self):
        """The inputs come from the stored audit, so perturbing every filing at/after the report cannot move them."""
        a = build_signal_context(signal(), CAL, OUT, ASOF)
        b = build_signal_context(signal(), CAL.perturbed_from(at(REPORT)), OUT, ASOF)
        assert [i.model_dump() for i in a.inputs] == [i.model_dump() for i in b.inputs]
        assert [f.accession for f in a.filings if f.role != "AFTER_REPORT"] == [f.accession for f in b.filings if f.role != "AFTER_REPORT"]

    @pytest.mark.parametrize("entity, note", [
        ({"entity_id": "UNKNOWN_ENTITY", "entity_name": None, "ticker": None, "sector": None, "country": None, "link_confidence": 0.0}, "no single company"),
        ({"entity_id": "ZZZ", "entity_name": "Z", "ticker": "ZZZ", "sector": "x", "country": "US", "link_confidence": 0.9}, "no SEC filings are held for ZZZ"),
    ])
    def test_no_issuer_means_an_explained_empty_list(self, entity, note):
        ctx = build_signal_context(signal(entity=entity), CAL, OUT, ASOF)
        assert ctx.filings == [] and note in (ctx.filings_note or "")

    def test_no_calendar_is_explained(self):
        ctx = build_signal_context(signal(), None, OUT, ASOF)
        assert ctx.filings == [] and "no SEC filing calendar" in ctx.filings_note


class TestOutcome:
    def test_outcome_is_separate_and_labelled(self):
        ctx = build_signal_context(signal(), CAL, OUT, ASOF)
        assert ctx.outcome is not None and ctx.outcome.abs_z == 0.41 and ctx.outcome.session == "2026-09-30"
        assert "not of this article" in ctx.outcome.note
        assert "outcome" not in RiskSignal.model_fields

    def test_next_session_has_no_outcome(self):
        s = signal()
        audit = s.provenance.impact.model_copy(update={"session": "NEXT"})
        s = s.model_copy(update={"provenance": s.provenance.model_copy(update={"impact": audit})})
        ctx = build_signal_context(s, CAL, OUT, ASOF)
        assert ctx.outcome is None and "had not traded" in ctx.outcome_note

    def test_missing_outcomes_file_is_explained(self):
        ctx = build_signal_context(signal(), CAL, None, ASOF)
        assert ctx.outcome is None and "not available in this profile" in ctx.outcome_note


class TestOutcomesFile:
    def test_committed_file_loads_and_is_well_formed(self):
        o = Outcomes.load(REPO_ROOT / "data" / "outcomes" / "replay_outcomes.json")
        assert o.window_sessions == 2 and len(o.rows) > 100
        for (scope, ticker, session), r in o.rows.items():
            assert scope in {"ISSUER", "MARKET"} and (ticker != "") == (scope == "ISSUER")
            assert r.abs_z == pytest.approx(abs(r.z), abs=1e-5) and 1 <= r.score <= 10 and len(session) == 10

    def test_bad_schema_fails_loudly(self, tmp_path: Path):
        p = tmp_path / "o.json"
        p.write_text(json.dumps({"schema": "other", "rows": []}))
        with pytest.raises(ConfigError, match="make outcomes"):
            Outcomes.load(p)
        p.write_text("{not json")
        with pytest.raises(ConfigError):
            Outcomes.load(p)

    def test_schema_constant(self):
        assert json.loads((REPO_ROOT / "data" / "outcomes" / "replay_outcomes.json").read_text())["schema"] == OUTCOMES_SCHEMA
