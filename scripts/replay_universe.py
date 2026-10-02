"""The real-issuer universe for the replay profile and the GDELT query plan.

Names, tickers, sectors and countries are public facts. Aliases are hand-curated. The portfolio built on
these issuers is SYNTHETIC (see build_replay_pack.py); only the issuers are real.
"""

from __future__ import annotations

# id suffix, legal name, ticker, sector, country, aliases, GDELT phrases (quoted in queries), synthetic PD bucket
# GDELT phrases must be >= MIN_PHRASE_CHARS and never a bare ambiguous word ("Visa", "Target", "Ford", "Apple"...).
UNIVERSE: list[tuple[str, str, str, str, str, list[str], list[str], float]] = [
    ("JPM", "JPMorgan Chase & Co.", "JPM", "Financials", "US", ["JPMorgan", "JPMorgan Chase", "J.P. Morgan", "JP Morgan"], ["JPMorgan Chase", "JPMorgan"], 0.004),
    ("BAC", "Bank of America Corporation", "BAC", "Financials", "US", ["Bank of America", "BofA"], ["Bank of America"], 0.005),
    ("GS", "The Goldman Sachs Group, Inc.", "GS", "Financials", "US", ["Goldman Sachs", "Goldman"], ["Goldman Sachs"], 0.005),
    ("MS", "Morgan Stanley", "MS", "Financials", "US", ["Morgan Stanley"], ["Morgan Stanley"], 0.005),
    ("C", "Citigroup Inc.", "C", "Financials", "US", ["Citigroup", "Citi", "Citibank"], ["Citigroup"], 0.006),
    ("WFC", "Wells Fargo & Company", "WFC", "Financials", "US", ["Wells Fargo"], ["Wells Fargo"], 0.006),
    ("V", "Visa Inc.", "V", "Financials", "US", ["Visa"], ["Visa Inc"], 0.003),
    ("AAPL", "Apple Inc.", "AAPL", "Technology", "US", ["Apple", "iPhone", "iPad", "MacBook", "Apple Music", "Apple Watch", "Apple TV", "Apple Pay", "App Store", "watchOS"], ["Apple Inc"], 0.002),
    ("MSFT", "Microsoft Corporation", "MSFT", "Technology", "US", ["Microsoft", "Azure", "Windows 11"], ["Microsoft Corp"], 0.002),
    ("NVDA", "NVIDIA Corporation", "NVDA", "Technology", "US", ["Nvidia"], ["Nvidia Corp"], 0.004),
    ("GOOGL", "Alphabet Inc.", "GOOGL", "Technology", "US", ["Alphabet", "Google"], ["Alphabet Inc"], 0.003),
    ("META", "Meta Platforms, Inc.", "META", "Technology", "US", ["Meta Platforms", "Meta", "Facebook", "Instagram"], ["Meta Platforms"], 0.005),
    ("AMZN", "Amazon.com, Inc.", "AMZN", "Technology", "US", ["Amazon", "Amazon Web Services", "AWS"], ["Amazon.com"], 0.004),
    ("INTC", "Intel Corporation", "INTC", "Technology", "US", ["Intel"], ["Intel Corporation"], 0.012),
    ("ORCL", "Oracle Corporation", "ORCL", "Technology", "US", ["Oracle"], ["Oracle Corporation"], 0.008),
    ("XOM", "Exxon Mobil Corporation", "XOM", "Energy", "US", ["Exxon Mobil", "ExxonMobil", "Exxon"], ["Exxon Mobil"], 0.007),
    ("CVX", "Chevron Corporation", "CVX", "Energy", "US", ["Chevron"], ["Chevron Corp"], 0.007),
    ("SHEL", "Shell plc", "SHEL", "Energy", "GB", ["Shell"], ["Shell plc"], 0.008),
    ("BP", "BP p.l.c.", "BP", "Energy", "GB", ["BP", "BP plc"], ["BP plc"], 0.010),
    ("PFE", "Pfizer Inc.", "PFE", "Healthcare", "US", ["Pfizer"], ["Pfizer Inc"], 0.006),
    ("JNJ", "Johnson & Johnson", "JNJ", "Healthcare", "US", ["Johnson & Johnson", "J&J"], ["Johnson & Johnson"], 0.003),
    ("UNH", "UnitedHealth Group Incorporated", "UNH", "Healthcare", "US", ["UnitedHealth", "UnitedHealthcare", "UnitedHealth Group"], ["UnitedHealth Group"], 0.004),
    ("LLY", "Eli Lilly and Company", "LLY", "Healthcare", "US", ["Eli Lilly", "Lilly"], ["Eli Lilly"], 0.004),
    ("BA", "The Boeing Company", "BA", "Industrials", "US", ["Boeing"], ["Boeing Co"], 0.014),
    ("CAT", "Caterpillar Inc.", "CAT", "Industrials", "US", ["Caterpillar"], ["Caterpillar Inc"], 0.006),
    ("LMT", "Lockheed Martin Corporation", "LMT", "Industrials", "US", ["Lockheed Martin", "Lockheed"], ["Lockheed Martin"], 0.005),
    ("GE", "GE Aerospace", "GE", "Industrials", "US", ["General Electric", "GE Aerospace"], ["GE Aerospace"], 0.008),
    ("TSLA", "Tesla, Inc.", "TSLA", "Consumer", "US", ["Tesla"], ["Tesla Inc"], 0.012),
    ("WMT", "Walmart Inc.", "WMT", "Consumer", "US", ["Walmart"], ["Walmart Inc"], 0.003),
    ("KO", "The Coca-Cola Company", "KO", "Consumer", "US", ["Coca-Cola", "Coca Cola"], ["Coca-Cola Company"], 0.003),
    ("MCD", "McDonald's Corporation", "MCD", "Consumer", "US", ["McDonald's", "McDonalds"], ["McDonald's Corp"], 0.004),
    ("NKE", "NIKE, Inc.", "NKE", "Consumer", "US", ["Nike"], ["Nike Inc"], 0.005),
    ("TGT", "Target Corporation", "TGT", "Consumer", "US", ["Target"], ["Target Corporation"], 0.007),
    ("F", "Ford Motor Company", "F", "Consumer", "US", ["Ford Motor", "Ford"], ["Ford Motor"], 0.015),
]

# Market-wide / unattributable stories: expected to resolve to UNKNOWN_ENTITY (first-class state).
MARKET_QUERIES = [
    '"Federal Reserve" interest rate',
    'OPEC oil output',
    'Treasury yields bond market',
    'stock market selloff',
    'credit rating downgrade',
    'tariffs trade war',
]

SECTORS = ["Financials", "Technology", "Energy", "Healthcare", "Industrials", "Consumer"]
MAX_RECORDS_SECTOR = 250  # GDELT's cap per request
MAX_RECORDS_MARKET = 50
MAX_QUERY_CHARS = 200  # GDELT answers "Your query was too short or too long." for the 233-char Technology query
MIN_PHRASE_CHARS = 5  # GDELT answers "The specified phrase is too short." for 4-character phrases such as Visa


def sector_queries() -> list[str]:
    """One parenthesised OR-query per sector (GDELT rejects un-parenthesised OR). Every phrase is quoted."""
    out = []
    for sector in SECTORS:
        phrases = [p for u in UNIVERSE if u[3] == sector for p in u[6]]
        out.append("(" + " OR ".join(f'"{p}"' for p in phrases) + ")")
    return out


def gdelt_queries() -> list[dict]:
    """The full request plan: 6 sector OR-queries + the market-wide queries."""
    return [{"query": q, "maxrecords": MAX_RECORDS_SECTOR} for q in sector_queries()] + [
        {"query": q, "maxrecords": MAX_RECORDS_MARKET} for q in MARKET_QUERIES
    ]


# ------------------------------------------------------------------ GKG bulk filter
MARKET_THEMES = ["ECON_STOCKMARKET", "ECON_CENTRALBANK", "ECON_INTEREST_RATE", "ECON_INFLATION", "ECON_OILPRICE"]


def gkg_filter() -> dict:
    """Terms for ingestion/gkg.py. GKG organisations are NER-tagged, so every alias (even "Apple") is safe there;
    titles are free text, so only the multi-word GDELT phrases and legal names are matched in them."""
    import re
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from eventshock.pipeline.normalize import match_form

    legal_suffix = re.compile(r",?\s+(?:Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Company|plc|p\.l\.c\.|Group|Holdings|Ltd\.?)$", re.I)
    org: dict[str, str] = {}
    title: dict[str, str] = {}
    for ident, name, _t, _s, _c, aliases, phrases, _pd in UNIVERSE:
        for form in {match_form(x) for x in [name, legal_suffix.sub("", name), *aliases] if len(match_form(x)) >= 2}:
            org.setdefault(form, ident)
        for form in {match_form(x) for x in [name, *phrases, *(a for a in aliases if " " in a)]}:
            if len(form) >= MIN_PHRASE_CHARS:
                title.setdefault(form, ident)
    return {"org_forms": org, "title_forms": title, "market_themes": MARKET_THEMES, "market_cap_per_file": 10}


# Yahoo symbols for price history: every issuer plus the market factors the stress scenarios talk about.
MARKET_SYMBOLS = ["^GSPC", "^VIX", "^TNX"]


def price_symbols() -> list[str]:
    return [u[2] for u in UNIVERSE] + MARKET_SYMBOLS
