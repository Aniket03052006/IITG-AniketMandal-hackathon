"""The GDELT request plan (scripts/replay_universe.py): few big sector queries, no bare short/ambiguous words."""

from __future__ import annotations

import re
import sys

import pytest

from eventshock.config import REPO_ROOT
from eventshock.ingestion.fetch import gdelt_url, plan_item

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import replay_universe as ru  # noqa: E402

PHRASE = re.compile(r'"([^"]+)"')
AMBIGUOUS_BARE = {"visa", "target", "ford", "shell", "meta", "apple", "intel", "oracle", "nike", "amazon", "bp", "ge"}


def test_plan_is_about_twelve_requests_with_six_sector_queries_first():
    plan = ru.gdelt_queries()
    assert len(plan) == 12
    assert [p["query"] for p in plan[:6]] == ru.sector_queries()
    assert all(p["maxrecords"] == 250 for p in plan[:6]) and all(p["maxrecords"] <= 250 for p in plan)


def test_market_queries_are_unchanged():
    assert ru.MARKET_QUERIES == ['"Federal Reserve" interest rate', 'OPEC oil output', 'Treasury yields bond market',
                                 'stock market selloff', 'credit rating downgrade', 'tariffs trade war']
    assert [p["query"] for p in ru.gdelt_queries()[6:]] == ru.MARKET_QUERIES


@pytest.mark.parametrize("query", ru.sector_queries())
def test_sector_queries_are_parenthesised_and_every_phrase_is_quoted_and_long_enough(query):
    assert query.startswith("(") and query.endswith(")"), "GDELT rejects un-parenthesised OR queries"
    phrases = PHRASE.findall(query)
    assert phrases and query == "(" + " OR ".join(f'"{p}"' for p in phrases) + ")"
    for p in phrases:
        assert len(p) >= ru.MIN_PHRASE_CHARS >= 4, f"{p!r} is too short for GDELT"
        assert p.lower() not in AMBIGUOUS_BARE, f"{p!r} is a bare ambiguous word"


@pytest.mark.parametrize("query", ru.sector_queries())
def test_sector_queries_stay_within_gdelts_length_limit(query):
    assert len(query) <= ru.MAX_QUERY_CHARS


def test_sector_queries_cover_every_issuer_in_its_own_sector():
    by_sector = dict(zip(ru.SECTORS, ru.sector_queries(), strict=True))
    for ident, name, _t, sector, _c, _a, phrases, _pd in ru.UNIVERSE:
        assert phrases, f"{ident} has no GDELT phrase"
        assert all(f'"{p}"' in by_sector[sector] for p in phrases), f"{name} missing from the {sector} query"
    assert {u[3] for u in ru.UNIVERSE} == set(ru.SECTORS)


def test_ambiguous_issuers_use_longer_phrases():
    want = {"V": "Visa Inc", "TGT": "Target Corporation", "F": "Ford Motor", "SHEL": "Shell plc",
            "META": "Meta Platforms", "AAPL": "Apple Inc", "INTC": "Intel Corporation"}
    got = {u[0]: u[6] for u in ru.UNIVERSE}
    for ident, phrase in want.items():
        assert phrase in got[ident]
        assert all(" " in p for p in got[ident]), f"{ident}: single-word phrase in {got[ident]}"


def test_plan_entries_may_be_strings_or_objects_and_urls_carry_the_limit():
    assert plan_item("abc", 30) == ("abc", 30) and plan_item({"query": "abc", "maxrecords": 250}, 30) == ("abc", 250)
    assert "maxrecords=250" in gdelt_url('("Visa Inc" OR "Ford Motor")', "s", "e", 250)
