"""Wholesale Book v2: the default synthetic book with the Stage 13 mechanics filled in.

A pure, seeded function of a base portfolio. Everything it adds is SYNTHETIC and illustrative; none of it is calibrated to a real book or
a real agency rating:

* a rating bucket per issuer, read off the issuer's own loan PD in the book (an internal PD bucket, not an agency rating; an issuer
  without a loan takes its sector's median PD) and a bond spread from that bucket;
* bond convexity from duration (C ~ 0.9 x D x (D + 1), the textbook bullet-bond order of magnitude);
* loan tenors and a spread pass-through (0.0 = a fixed-price relationship loan that a market spread does not reach);
* derivative gamma on protective puts (long convexity) and a counterparty PD / LGD for the credit-valuation adjustment;
* foreign-currency denominations (GBP for UK, EUR for the euro area, CHF for Switzerland) on equities and bonds, and oil elasticities
  by sector (Energy high, Industrials low, Consumer slightly negative);
* a government sleeve (``spread_sensitivity`` 0: a credit-spread shock does not reach it) and a cash sleeve, one of it in euros.

The result keeps every position of the base book, so it is a superset: comparing the two shows what the extra mechanics change.
"""

from __future__ import annotations

import random
import statistics
from collections import defaultdict
from datetime import datetime

from ..domain import Portfolio

BOOK_V2_ID = "pf_wholesale_v2"
PD_TO_RATING = [(0.0025, "AA"), (0.005, "A"), (0.009, "BBB+"), (0.013, "BBB"), (0.020, "BBB-"), (1.0, "BB")]
SPREAD_BY_RATING = {"AA": 60.0, "A": 85.0, "BBB+": 115.0, "BBB": 140.0, "BBB-": 185.0, "BB": 290.0}
CURRENCY_BY_COUNTRY = {"GB": "GBP", "DE": "EUR", "FR": "EUR", "CH": "CHF"}
OIL_SENSITIVITY = {"Energy": 0.85, "Industrials": 0.15, "Consumer": -0.10}
GOVERNMENT = (("UST-2Y", "US Treasury 2Y", 1.9, 12e6), ("UST-5Y", "US Treasury 5Y", 4.6, 10e6), ("UST-10Y", "US Treasury 10Y", 8.4, 8e6))


def _rating(pd: float) -> str:
    return next(r for cut, r in PD_TO_RATING if pd < cut)


def issuer_pd(base: Portfolio) -> tuple[dict[str, float], dict[str, float]]:
    """(PD by issuer from its loans, median PD by sector): the only inputs the rating buckets read."""
    by_issuer: dict[str, list[float]] = defaultdict(list)
    by_sector: dict[str, list[float]] = defaultdict(list)
    for a in base.assets:
        if a.pd is not None:
            by_issuer[a.entity_id].append(a.pd)
            by_sector[a.sector].append(a.pd)
    overall = statistics.median([p for v in by_sector.values() for p in v]) if by_sector else 0.01
    return ({k: statistics.fmean(v) for k, v in by_issuer.items()},
            {k: statistics.median(v) for k, v in by_sector.items()} | {"": overall})


def build_book_v2(base: Portfolio, *, seed: int, as_of: datetime | None = None) -> Portfolio:
    rng = random.Random(seed)
    issuer, sector = issuer_pd(base)
    overall = sector[""]
    assets: list[dict] = []
    for a in base.assets:
        d = {k: v for k, v in a.model_dump(mode="json").items() if v is not None}
        rating = _rating(issuer.get(a.entity_id, sector.get(a.sector, overall)))
        kind = a.asset_type.value
        ccy = CURRENCY_BY_COUNTRY.get(a.geography)
        if ccy and kind in ("EQUITY", "BOND"):
            d["currency"] = ccy
        if kind == "EQUITY":
            d["rating"] = rating
            if a.sector in OIL_SENSITIVITY:
                d["commodity_sensitivity"] = round(OIL_SENSITIVITY[a.sector] * rng.uniform(0.8, 1.2), 2)
        elif kind == "BOND":
            dur = a.duration or 0.0
            d["rating"] = rating
            d["convexity"] = round(0.9 * dur * (dur + 1.0), 1)
            d["spread_bp"] = round(SPREAD_BY_RATING[rating] * rng.uniform(0.85, 1.2) * (1.0 + 0.04 * max(dur - 4.0, 0.0)), 1)
        elif kind == "LOAN":
            d["rating"] = rating
            d["maturity_years"] = round(rng.uniform(2.0, 7.0), 1)
            d["spread_passthrough"] = rng.choice([0.0, 0.6, 0.8, 1.0])
        elif kind == "DERIVATIVE":
            if (a.delta or 0.0) < 0:
                d["gamma"] = round(rng.uniform(1.5, 3.0), 2)
            d["counterparty_pd"] = round(rng.uniform(0.003, 0.012), 4)
            d["counterparty_lgd"] = 0.6
            if a.sector in OIL_SENSITIVITY:
                d["commodity_sensitivity"] = round(OIL_SENSITIVITY[a.sector] * rng.uniform(0.8, 1.2), 2)
        assets.append(d)
    for ident, name, dur, face in GOVERNMENT:
        assets.append(dict(asset_id=f"GV-{ident}", asset_type="BOND", entity_id="SOVEREIGN_US", name=name, sector="Government", geography="US",
                           notional=face, market_value=round(face * rng.uniform(0.97, 1.02), 2), duration=dur, spread_sensitivity=0.0,
                           convexity=round(0.9 * dur * (dur + 1.0), 1), rating="AAA", spread_bp=0.0))
    assets.append(dict(asset_id="CASH-USD", asset_type="CASH", entity_id="TREASURY_DESK", name="Cash and equivalents (USD)", sector="Cash",
                       geography="US", notional=15e6, market_value=15e6))
    assets.append(dict(asset_id="CASH-EUR", asset_type="CASH", entity_id="TREASURY_DESK", name="Cash and equivalents (EUR)", sector="Cash",
                       geography="DE", notional=6e6, market_value=6e6, currency="EUR"))
    return Portfolio(
        portfolio_id=BOOK_V2_ID,
        name="Synthetic Wholesale Banking Book v2",
        as_of=as_of or base.as_of,
        base_currency=base.base_currency,
        description=(
            "SYNTHETIC. The default book's positions with the Stage 13 mechanics filled in (bond convexity, loan spread-to-PD link, derivative gamma "
            "and counterparty credit, foreign-currency and oil exposures, internal PD-bucket ratings) plus a government and a cash sleeve. "
            "Illustrative parameters; not real positions and not agency ratings."
        ),
        assets=assets,
    )
