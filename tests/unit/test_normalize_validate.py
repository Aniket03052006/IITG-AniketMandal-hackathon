from __future__ import annotations

from datetime import timedelta

import pytest

from eventshock.domain import TimestampOrigin
from eventshock.ingestion.base import RejectCode
from eventshock.pipeline.normalize import (
    canonical_url,
    clean_text,
    content_tokens,
    dedup_key,
    jaccard,
    match_form,
)
from eventshock.pipeline.validate import validate_document
from tests.pipe_helpers import AS_OF, CFG, W0, doc

V = CFG.validation


def check(d, origin=TimestampOrigin.GDELT_FIRST_SEEN):
    return validate_document(d, cfg=V, as_of=AS_OF, window_start=W0, window_end=AS_OF, timestamp_origin=origin)


class TestNormalize:
    def test_clean_text(self):
        assert clean_text("  Apple&amp;Co ​\u0007 beats\n\n estimates  ") == "Apple&Co beats estimates"
        assert clean_text("ＡＰＰＬＥ") == "APPLE"  # NFKC

    @pytest.mark.parametrize("a,b", [
        ("HTTPS://www.Example.com/a/b/?utm_source=x&id=2#frag", "https://example.com/a/b?id=2"),
        ("http://example.com/a/", "https://example.com/a"),
        ("https://example.com/p?b=2&a=1&fbclid=zzz", "https://example.com/p?a=1&b=2"),
    ])
    def test_canonical_url(self, a, b):
        assert canonical_url(a) == b

    @pytest.mark.parametrize("bad", ["", "ftp://x.com/a", "javascript:alert(1)", "https://localhost/a", "not a url", "http://"])
    def test_canonical_url_rejects(self, bad):
        assert canonical_url(bad) is None

    def test_dedup_key_ignores_urls_case_punctuation_and_outlet_suffix(self):
        a = dedup_key("$BYND - JPMorgan reels in expectations! https://t.co/abc")
        b = dedup_key("$BYND – JPMorgan reels in expectations https://t.co/zzz")
        assert a == b
        assert dedup_key("Apple beats estimates - Reuters") == dedup_key("APPLE BEATS ESTIMATES | Yahoo Finance")

    def test_tokens_and_jaccard(self):
        a, b = content_tokens("Apple unveils iPhone 18 at event"), content_tokens("Apple unveils iPhone 18 lineup")
        assert 0.6 <= jaccard(a, b) < 1
        assert jaccard(frozenset(), a) == 0.0

    def test_match_form(self):
        assert match_form("J.P. Morgan & Co's") == "jp morgan and cos"


class TestValidate:
    def test_ok(self):
        assert check(doc("a", "Apple raises quarterly dividend after strong earnings")) is None

    @pytest.mark.parametrize("headline,code", [
        ("   ", RejectCode.EMPTY_TEXT),
        ("Too short", RejectCode.TOO_SHORT),
        ("x " * 1500, RejectCode.TOO_LONG),
        ("CafÃ© Ã¨ prices rise on the market today", RejectCode.MOJIBAKE),
        ("Prices �� on the market today and more words", RejectCode.MOJIBAKE),
        ("12345 67890 !!!! ???? ---- 1111 2222 3333", RejectCode.LOW_QUALITY),
    ])
    def test_text_rules(self, headline, code):
        d = doc("a", headline.strip() or "x").model_copy(update={"headline": headline})
        assert check(d)[0] is code

    def test_language(self):
        assert check(doc("a", "Apple raises quarterly dividend after strong earnings", language="es"))[0] is RejectCode.NON_ENGLISH

    def test_future_and_window(self):
        assert check(doc("a", "Apple raises quarterly dividend after strong earnings", hours=-1))[0] is RejectCode.FUTURE_TIMESTAMP
        assert check(doc("a", "Apple raises quarterly dividend after strong earnings", hours=24 * 40))[0] is RejectCode.OUTSIDE_WINDOW

    def test_after_window_but_before_replay_clock_is_outside_window(self):
        d = doc("a", "Apple raises quarterly dividend after strong earnings", hours=1)
        got = validate_document(d, cfg=V, as_of=AS_OF, window_start=W0, window_end=AS_OF - timedelta(hours=2),
                                timestamp_origin=TimestampOrigin.GDELT_FIRST_SEEN)
        assert got[0] is RejectCode.OUTSIDE_WINDOW

    def test_window_not_applied_to_synthetic_timestamps(self):
        d = doc("a", "Apple raises quarterly dividend after strong earnings", hours=24 * 40)
        assert check(d, TimestampOrigin.SYNTHETIC_REPLAY_CLOCK) is None
