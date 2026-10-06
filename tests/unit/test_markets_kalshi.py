"""Kalshi's public data: defensive parsing of the current shape (dollar strings, fixed-point sizes), a live provider that degrades instead of raising, rate-limit spacing, no network in tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from eventshock.ingestion.fetch import FetchError
from eventshock.markets.kalshi import (
    KalshiProvider,
    dollars,
    fixed,
    implied_probability,
    parse_candle,
    parse_market,
)
from eventshock.markets.models import MarketStatus
from tests.markets_helpers import MCFG

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
CFG = MCFG.providers.kalshi


def market(**kw):  # noqa: ANN003, ANN201
    base = {"ticker": "KXFEDCUT-28DEC31", "event_ticker": "KXFEDCUT-28DEC31", "title": "Will the Federal Reserve cut rates by December 31, 2028?", "market_type": "binary", "status": "active",
            "last_price_dollars": "0.7200", "previous_price_dollars": "0.4800", "yes_bid_dollars": "0.7000", "yes_ask_dollars": "0.7400", "volume_fp": "1200.00", "volume_24h_fp": "300.00",
            "open_interest_fp": "800.00", "close_time": "2028-12-31T00:00:00Z", "updated_time": "2026-10-06T11:00:00Z"}
    base.update(kw)
    return base


@pytest.mark.parametrize("raw,expected", [("0.1200", 0.12), ("1.0000", 1.0), ("0", 0.0), ("1.5", None), ("-0.2", None), ("abc", None), (None, None), (12, None), (0.12, None), ("", None)])
def test_dollar_strings_parse_and_everything_else_is_none(raw, expected):
    assert dollars(raw) == expected


@pytest.mark.parametrize("raw,expected", [("200.00", 200.0), ("0", 0.0), ("-1", None), ("x", None), (None, None), (5, None)])
def test_fixed_point_sizes(raw, expected):
    assert fixed(raw) == expected


def test_the_implied_probability_is_the_last_trade_else_a_tight_quote_else_nothing():
    assert implied_probability(0.72, 0.70, 0.74, True, 0.15) == 0.72
    assert implied_probability(0.0, 0.40, 0.50, False, 0.15) == pytest.approx(0.45)               # no trade: the midpoint of a tight two-sided quote
    assert implied_probability(0.12, 0.04, 0.12, False, 0.05) is None                              # a stale last price with no trade and an 8-cent-wide quote: not priced
    assert implied_probability(None, None, 0.5, False, 0.15) is None and implied_probability(None, 0.6, 0.5, False, 0.15) is None


def test_a_market_row_becomes_an_observation_with_provenance_and_the_exchanges_previous_price():
    o = parse_market(market(), series="KXFEDCUT", cfg=CFG, max_spread=0.15, now=NOW)
    assert o.probability == 0.72 and o.previous_probability == 0.48 and o.probability_change_pp == pytest.approx(24.0) and o.market_status is MarketStatus.OPEN
    assert o.volume == 1200 and o.volume_24h == 300 and o.open_interest == 800 and o.series_id == "KXFEDCUT" and o.source == "kalshi" and o.provider == "kalshi" and not o.synthetic
    assert o.observed_at == datetime(2026, 10, 6, 11, tzinfo=UTC) and o.close_time.year == 2028 and o.source_url == "https://kalshi.com/markets/kxfedcut"
    assert o.provenance[0].source == "kalshi" and o.provenance[0].ref_id == "KXFEDCUT-28DEC31"


def test_unexpected_shapes_and_legacy_cent_fields_never_become_a_number():
    assert parse_market({"ticker": "X"}, series=None, cfg=CFG, max_spread=0.15, now=NOW) is None                  # no title
    assert parse_market(market(market_type="scalar"), series=None, cfg=CFG, max_spread=0.15, now=NOW) is None
    legacy = parse_market({"ticker": "K", "title": "T", "status": "open", "last_price": 72, "previous_price": 48, "volume": 100}, series="S", cfg=CFG, max_spread=0.15, now=NOW)
    assert legacy is not None and legacy.probability is None and legacy.previous_probability is None and legacy.probability_change_pp is None     # integer cents are not the current contract: not read
    unpriced = parse_market(market(last_price_dollars="0.0000", volume_fp="0.00", yes_bid_dollars="0.0000", yes_ask_dollars="1.0000"), series="S", cfg=CFG, max_spread=0.05, now=NOW)
    assert unpriced.probability is None and unpriced.probability_change_pp is None


def test_candles_become_points_and_a_candle_without_a_timestamp_is_dropped():
    c = {"end_period_ts": 1790913600, "open_interest_fp": "1.00", "volume_fp": "5.00", "price": {"close_dollars": "0.2500"}, "yes_bid": {"close_dollars": "0.20"}, "yes_ask": {"close_dollars": "0.30"}}
    t, p, oi, vol = parse_candle(c, 0.15)
    assert t == datetime.fromtimestamp(1790913600, UTC) and p == 0.25 and oi == 1.0 and vol == 5.0
    quote = parse_candle({"end_period_ts": 1790913600, "volume_fp": "0.00", "price": {"previous_dollars": "0.12"}, "yes_bid": {"close_dollars": "0.20"}, "yes_ask": {"close_dollars": "0.24"}}, 0.05)
    assert quote[1] == pytest.approx(0.22)                                                              # no trade, tight quote: its midpoint
    wide = parse_candle({"end_period_ts": 1790913600, "volume_fp": "0.00", "price": {"previous_dollars": "0.12"}, "yes_bid": {"close_dollars": "0.04"}, "yes_ask": {"close_dollars": "0.12"}}, 0.05)
    assert wide[1] is None
    assert parse_candle({"price": {}}, 0.15) is None


class Fake:
    def __init__(self, *responses):  # noqa: ANN002
        self.responses, self.calls = list(responses), []

    def __call__(self, url: str, timeout: float):  # noqa: ANN201
        self.calls.append((url, timeout))
        r = self.responses.pop(0) if self.responses else (200, b"{}")
        if isinstance(r, Exception):
            raise r
        return r


def live(fake, sleeps=None):  # noqa: ANN001, ANN201
    return KalshiProvider(CFG, max_spread=0.15, transport=fake, sleep=(sleeps.append if sleeps is not None else lambda s: None), clock=lambda: NOW)


def ok(markets):  # noqa: ANN001, ANN201
    return 200, json.dumps({"markets": markets}).encode()


def test_the_live_provider_keeps_the_most_active_markets_of_a_series_and_asks_the_public_endpoint_without_a_key():
    rows = [market(ticker=f"K-{i}", volume_fp=str(100 * i), open_interest_fp=str(10 * i)) for i in range(1, 12)]
    fake = Fake(ok(rows))
    got = live(fake).markets("KXFEDCUT", NOW)
    assert len(got) == CFG.max_markets_per_series and {o.market_id for o in got} == {f"K-{i}" for i in range(4, 12)} and [o.market_id for o in got] == sorted(o.market_id for o in got)
    url = fake.calls[0][0]
    assert url.startswith("https://external-api.kalshi.com/trade-api/v2/markets?") and "series_ticker=KXFEDCUT" in url and "status=open" in url
    assert "key" not in url.lower() and "authorization" not in url.lower()


def test_a_failing_or_unrecognised_response_makes_the_provider_unavailable_and_returns_nothing():
    p = live(Fake(*[(503, b"busy")] * 6))
    assert p.markets("S", NOW) == [] and p.state().state == "UNAVAILABLE" and "unreachable or rate limited" in p.state().reason
    q = live(Fake((200, b'{"markets": "not a list"}')))
    assert q.markets("S", NOW) == [] and q.state().state == "UNAVAILABLE" and "does not recognise" in q.state().reason
    r = live(Fake(FetchError("network down")))
    assert r.markets("S", NOW) == [] and r.state().state == "UNAVAILABLE"
    good = live(Fake(ok([market()])))
    assert len(good.markets("S", NOW)) == 1 and good.state().state == "AVAILABLE" and good.state().mode == "live"


def test_requests_are_spaced(monkeypatch):  # noqa: ANN001
    ticks = iter([100.0, 100.0, 100.1, 100.1, 100.2])
    monkeypatch.setattr("eventshock.markets.kalshi.time.monotonic", lambda: next(ticks))
    sleeps: list[float] = []
    p = live(Fake(ok([market()]), ok([market()])), sleeps)
    p.markets("S", NOW)
    p.markets("S", NOW)
    assert any(s > 0 for s in sleeps) and max(sleeps) <= CFG.min_interval_seconds + 1e-9


def test_history_reads_candlesticks_and_degrades():
    c = {"end_period_ts": 1790913600, "volume_fp": "5.00", "price": {"close_dollars": "0.25"}}
    fake = Fake((200, json.dumps({"candlesticks": [c]}).encode()))
    h = live(fake).history("KXFEDCUT-28DEC31", NOW, NOW)
    assert h == [(datetime.fromtimestamp(1790913600, UTC), 0.25)] and "/series/KXFEDCUT/markets/KXFEDCUT-28DEC31/candlesticks" in fake.calls[0][0]
    assert live(Fake((200, b"{}"))).history("K-1", NOW, NOW) == [] and live(Fake(*[(500, b"x")] * 6)).history("K-1", NOW, NOW) == []
