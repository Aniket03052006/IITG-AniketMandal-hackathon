from __future__ import annotations

import json

import pytest

from eventshock.domain import SourceType, TimestampOrigin
from eventshock.ingestion.base import RejectCode, Rejected
from eventshock.ingestion.gdelt import GdeltAdapter, untokenise
from eventshock.ingestion.snapshot import iter_jsonl
from eventshock.ingestion.tfn import TfnAdapter
from tests.pipe_helpers import AS_OF, W0, W1, jsonl_path

G = GdeltAdapter(snapshot_id="s1", as_of=AS_OF)
T = TfnAdapter(snapshot_id="s1", as_of=AS_OF, window_start=W0, window_end=W1)

GOOD = {"url": "https://9to5mac.com/a", "title": "Apple Music expands to four new countries",
        "seendate": "20260930T233000Z", "domain": "9to5mac.com", "language": "English", "sourcecountry": "US"}


def parse(adapter, tmp_path, *lines: str):
    p = jsonl_path(tmp_path, "r.jsonl", "\n".join(lines) + "\n")
    return list(adapter.read(p, "r.jsonl"))


class TestGdelt:
    def test_good_record_keeps_provenance(self, tmp_path):
        d, = parse(G, tmp_path, json.dumps(GOOD))
        assert d.source_type is SourceType.NEWS and d.source == "9to5mac.com" and d.language == "en"
        assert d.raw_metadata["timestamp_origin"] == TimestampOrigin.GDELT_FIRST_SEEN.value
        assert d.raw_metadata["record_ref"] == "r.jsonl:1" and len(d.raw_metadata["content_sha256"]) == 64
        assert d.published_at.tzinfo is not None and d.ingested_at == AS_OF

    @pytest.mark.parametrize("patch,code", [
        ({"seendate": "2026-09-30"}, RejectCode.BAD_TIMESTAMP),
        ({"seendate": None}, RejectCode.BAD_TIMESTAMP),
        ({"seendate": "20261101T000000Z"}, RejectCode.FUTURE_TIMESTAMP),
        ({"title": ""}, RejectCode.EMPTY_TEXT),
        ({"title": None}, RejectCode.SCHEMA),
        ({"title": 42}, RejectCode.SCHEMA),
        ({"url": ""}, RejectCode.SCHEMA),
        ({"url": None}, RejectCode.SCHEMA),
    ])
    def test_malformed_fields_are_rejected_with_a_code(self, tmp_path, patch, code):
        r, = parse(G, tmp_path, json.dumps({**GOOD, **patch}))
        assert isinstance(r, Rejected) and r.code is code and r.record_ref == "r.jsonl:1"

    def test_missing_keys_and_garbage_lines(self, tmp_path):
        out = parse(G, tmp_path, "{}", "not json at all", "[1,2,3]", '"string"', json.dumps(GOOD))
        assert [type(o).__name__ for o in out] == ["Rejected"] * 4 + ["RawDocument"]
        assert [o.code for o in out[:4]] == [RejectCode.SCHEMA, RejectCode.MALFORMED_RECORD,
                                              RejectCode.MALFORMED_RECORD, RejectCode.MALFORMED_RECORD]

    def test_non_utf8_bytes_do_not_crash(self, tmp_path):
        p = tmp_path / "b.jsonl"
        p.write_bytes(b'{"url": "https://a.com/x", "title": "caf\xe9"}\n')
        r, = list(G.read(p, "b.jsonl"))
        assert r.code is RejectCode.MALFORMED_RECORD

    def test_unknown_language_is_kept_for_validation_to_judge(self, tmp_path):
        d, = parse(G, tmp_path, json.dumps({**GOOD, "language": "Spanish"}))
        assert d.language == "spanish"

    def test_blank_lines_are_skipped_and_line_numbers_are_physical(self, tmp_path):
        p = jsonl_path(tmp_path, "r.jsonl", "\n\n" + json.dumps(GOOD) + "\n")
        assert [ln.line for ln in iter_jsonl(p, "r.jsonl")] == [3]


class TestTfn:
    REC = {"split": "train", "row": 7, "text": "$BYND - JPMorgan reels in expectations on Beyond Meat https://t.co/x", "label": 0}

    def test_good_record(self, tmp_path):
        d, = parse(T, tmp_path, json.dumps(self.REC))
        assert d.id == "tfn-train-7" and d.source_type is SourceType.SOCIAL
        assert d.raw_metadata["source_label"] == "bearish"
        assert d.raw_metadata["timestamp_origin"] == TimestampOrigin.SYNTHETIC_REPLAY_CLOCK.value
        assert W0 <= d.published_at <= W1

    def test_tco_shortlinks_are_not_shown_but_stay_in_the_hashed_record(self, tmp_path):
        d, = parse(T, tmp_path, json.dumps(self.REC))
        assert d.headline == "$BYND - JPMorgan reels in expectations on Beyond Meat" and "t.co" not in d.headline

    def test_replay_time_is_deterministic_and_order_independent(self, tmp_path):
        a = parse(T, tmp_path, json.dumps(self.REC))[0].published_at
        assert a == T.replay_time("tfn-train-7") == parse(T, tmp_path, json.dumps(self.REC))[0].published_at
        assert T.replay_time("tfn-train-8") != a

    @pytest.mark.parametrize("patch,code", [
        ({"label": 5}, RejectCode.SCHEMA), ({"label": "bullish"}, RejectCode.SCHEMA), ({"label": True}, RejectCode.SCHEMA),
        ({"text": None}, RejectCode.SCHEMA), ({"text": "   "}, RejectCode.EMPTY_TEXT),
        ({"row": "7"}, RejectCode.SCHEMA), ({"split": None}, RejectCode.SCHEMA),
    ])
    def test_malformed(self, tmp_path, patch, code):
        r, = parse(T, tmp_path, json.dumps({**self.REC, **patch}))
        assert isinstance(r, Rejected) and r.code is code


def test_gdelt_untokenise():
    assert untokenise("The Goldman Sachs Group ( NYSE : GS ) Given $1 , 007 . 00 Target") == \
        "The Goldman Sachs Group (NYSE: GS) Given $1,007.00 Target"
    assert untokenise("Court asks Apple to pay $5 . 7 billion ; Apple vows to appeal") == \
        "Court asks Apple to pay $5.7 billion; Apple vows to appeal"
    assert untokenise("Q2 growth up 2 . 5 % , says report") == "Q2 growth up 2.5%, says report"
