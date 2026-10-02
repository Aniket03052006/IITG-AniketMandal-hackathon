"""Generate the committed demo fixtures in data/fixtures/ (deterministic: fixed seed + fixed clock).

Everything here is SYNTHETIC. Companies, tickers, outlets, authors and headlines are invented; the
signals are hand-authored demo output (data_origin = DEMO_FIXTURE), not model predictions.

Usage:  python scripts/generate_fixtures.py        (rewrites data/fixtures/*.json)
"""

from __future__ import annotations

import json
import math
import random
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from eventshock.domain import (
    Entity,
    EventCategory,
    Portfolio,
    RiskSignal,
)

OUT = Path(__file__).resolve().parents[1] / "data" / "fixtures"
AS_OF = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SEED = 20261001

ENTITIES = [
    # id, name, ticker, sector, country, rating-bucket PD, aliases
    ("ENT_MRDN", "Meridian Bancorp", "MRDB", "Financials", "US", 0.008, ["Meridian"]),
    ("ENT_NRTH", "Northgate Capital", "NGCP", "Financials", "GB", 0.010, ["Northgate"]),
    ("ENT_ORCM", "Orchard Mutual", "ORCM", "Financials", "US", 0.012, ["Orchard"]),
    ("ENT_HLDN", "Halden Energy", "HLDE", "Energy", "GB", 0.022, ["Halden"]),
    ("ENT_TSPC", "Tessan Petroleum", "TSPC", "Energy", "AE", 0.018, ["Tessan"]),
    ("ENT_VNTR", "Vantor Semiconductors", "VNTR", "Technology", "TW", 0.015, ["Vantor"]),
    ("ENT_PRSM", "Prism Cloud Systems", "PRSM", "Technology", "US", 0.009, ["Prism Cloud"]),
    ("ENT_CRVL", "Corvale Therapeutics", "CRVT", "Healthcare", "US", 0.030, ["Corvale"]),
    ("ENT_ZNTB", "Zenith Biologics", "ZNTB", "Healthcare", "CH", 0.011, ["Zenith"]),
    ("ENT_ASHF", "Ashford Industrial Group", "ASHI", "Industrials", "DE", 0.026, ["Ashford"]),
    ("ENT_KSTR", "Kestrel Aerospace", "KSTR", "Industrials", "FR", 0.014, ["Kestrel"]),
    ("ENT_AMBL", "Amberline Logistics", "AMBL", "Industrials", "SG", 0.028, ["Amberline"]),
    ("ENT_LMNR", "Lumenar Retail", "LMNR", "Consumer", "US", 0.024, ["Lumenar"]),
    ("ENT_BWFD", "Brightwell Foods", "BWFD", "Consumer", "US", 0.013, ["Brightwell"]),
]
SECTOR_BETA = {"Financials": 1.2, "Technology": 1.35, "Energy": 1.1, "Healthcare": 0.8,
               "Industrials": 1.05, "Consumer": 0.85}
BOND_ENTITIES = ["MRDN", "NRTH", "ORCM", "HLDN", "TSPC", "VNTR", "PRSM", "CRVL", "ZNTB", "ASHF",
                 "KSTR", "AMBL", "LMNR", "BWFD"]
LOAN_ENTITIES = ["HLDN", "HLDN", "TSPC", "VNTR", "PRSM", "CRVL", "ASHF", "ASHF", "KSTR", "AMBL",
                 "AMBL", "LMNR", "BWFD", "NRTH", "ORCM"]
DERIV_ENTITIES = ["MRDN", "NRTH", "HLDN", "VNTR", "LMNR", "PRSM"]
BOND_EXTRA = ["MRDN", "NRTH"]  # second, longer-dated tranche


def r2(x: float) -> float:
    return round(x, 2)


def build_entities() -> list[Entity]:
    return [
        Entity(entity_id=i, name=n, ticker=t, sector=s, country=c, aliases=a)
        for i, n, t, s, c, _pd, a in ENTITIES
    ]


def build_portfolio() -> Portfolio:
    rng = random.Random(SEED)
    info = {i: (n, s, c, pd) for i, n, _t, s, c, pd, _a in ENTITIES}
    assets: list[dict] = []

    def eid(short: str) -> str:
        return f"ENT_{short}"

    for ent_id, (name, sector, country, _pd) in info.items():
        assets.append(dict(
            asset_id=f"EQ-{ent_id[4:]}", asset_type="EQUITY", entity_id=ent_id,
            name=f"{name} - Common Equity", sector=sector, geography=country,
            notional=r2(rng.uniform(3e6, 18e6)), market_value=0.0,
            beta=r2(SECTOR_BETA[sector] + rng.uniform(-0.15, 0.15)),
        ))
        assets[-1]["market_value"] = assets[-1]["notional"]

    for n, short in enumerate(BOND_ENTITIES + BOND_EXTRA, start=1):
        ent_id = eid(short)
        name, sector, country, pd = info[ent_id]
        longer = n > len(BOND_ENTITIES)
        face = r2(rng.uniform(4e6, 14e6))
        price = rng.uniform(0.93, 1.03)
        assets.append(dict(
            asset_id=f"BD-{short}-{'B' if longer else 'A'}", asset_type="BOND", entity_id=ent_id,
            name=f"{name} {rng.choice([4.25, 4.75, 5.25, 5.75])}% {2036 if longer else 2030} Sr Notes",
            sector=sector, geography=country, notional=face, market_value=r2(face * price),
            duration=r2(rng.uniform(6.5, 9.0) if longer else rng.uniform(3.0, 5.5)),
        ))

    for n, short in enumerate(LOAN_ENTITIES, start=1):
        ent_id = eid(short)
        name, sector, country, pd = info[ent_id]
        ead = r2(rng.uniform(6e6, 30e6))
        pd_i = round(pd * rng.uniform(0.8, 1.3), 4)
        lgd = round(rng.uniform(0.35, 0.55), 2)
        kind = "Interbank Facility" if sector == "Financials" else rng.choice(
            ["Term Loan B", "Revolving Credit Facility", "Senior Term Loan"])
        assets.append(dict(
            asset_id=f"LN-{short}-{n:02d}", asset_type="LOAN", entity_id=ent_id,
            name=f"{name} - {kind}", sector=sector, geography=country, notional=ead,
            market_value=r2(ead * (1 - pd_i * lgd)), pd=pd_i, lgd=lgd,
            default_sensitivity=round(rng.uniform(0.7, 1.4), 2),
        ))

    for n, short in enumerate(DERIV_ENTITIES, start=1):
        ent_id = eid(short)
        name, sector, country, _pd = info[ent_id]
        und = r2(rng.uniform(4e6, 14e6))
        delta = round(rng.choice([-0.55, -0.4, 0.35, 0.5, 0.6]), 2)
        kind = "Equity Total Return Swap" if delta > 0 else "Protective Put Position"
        assets.append(dict(
            asset_id=f"DV-{short}-{n:02d}", asset_type="DERIVATIVE", entity_id=ent_id,
            name=f"{name} - {kind}", sector=sector, geography=country, notional=und,
            market_value=r2(und * rng.uniform(0.02, 0.07) * (1 if delta > 0 else 1)),
            delta=delta,
        ))

    return Portfolio(
        portfolio_id="pf_wholesale_demo",
        name="Synthetic Wholesale Banking Book",
        as_of=AS_OF,
        base_currency="USD",
        description=(
            "SYNTHETIC portfolio generated from issuer relationships (equity, bonds, loans, "
            "hedges per issuer; sector-correlated betas and PD). Not real positions."
        ),
        assets=assets,
    )


# ---------------------------------------------------------------- signals

SRC_LEDGER = ("Ledger Wire", "NEWS")
SRC_HARBOR = ("Harbor Daily", "NEWS")
SRC_CBJ = ("Continental Business Journal", "NEWS")
SRC_FT = ("FinTwit Replay", "SOCIAL")


def sentiment(score: float, neutral: float) -> dict:
    pos = (1 - neutral + score) / 2
    neg = (1 - neutral - score) / 2
    return {"positive": round(pos, 4), "neutral": round(neutral, 4), "negative": round(neg, 4),
            "score": round(pos - neg, 4)}


def event(primary: str, p: float, secondary: str | None = None, q: float = 0.0) -> dict:
    cats = [c.value for c in EventCategory]
    probs = dict.fromkeys(cats, 0.0)
    probs[primary] = p
    rest = [c for c in cats if c != primary]
    remaining = 1 - p
    if secondary:
        probs[secondary] = q
        remaining -= q
        rest = [c for c in rest if c != secondary]
    for c in rest:
        probs[c] = round(remaining / len(rest), 4)
    probs[primary] = round(1 - sum(v for k, v in probs.items() if k != primary), 4)
    return {"category": primary, "probabilities": probs}


def impact(raw: float, drivers: list[tuple[str, float, str]]) -> dict:
    return {
        "score": max(1, min(10, math.ceil(raw * 10))),
        "raw": raw,
        "drivers": [{"feature": f, "contribution": c, "note": n} for f, c, n in drivers],
    }


def ts(hours_ago: float) -> str:
    return (AS_OF - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def corro(items: list[tuple[tuple[str, str], float, str]]) -> list[dict]:
    return [
        {"source": s[0], "source_type": s[1], "published_at": ts(h), "headline": hl,
         "url": f"https://demo.eventshock.invalid/{s[0].lower().replace(' ', '-')}/{zlib.crc32(hl.encode()) % 9999}"}
        for s, h, hl in items
    ]


def stable_url(src: tuple[str, str], slug: str) -> str:
    return f"https://demo.eventshock.invalid/{src[0].lower().replace(' ', '-')}/{slug}"


def mention(ent_id: str | None, conf: float) -> dict:
    if ent_id is None:
        return {"entity_id": "UNKNOWN_ENTITY", "link_confidence": 0.0}
    n, t, s, c = next((e[1], e[2], e[3], e[4]) for e in ENTITIES if e[0] == ent_id)
    return {"entity_id": ent_id, "entity_name": n, "ticker": t, "sector": s, "country": c,
            "link_confidence": conf}


def signal(n: int, *, src, hours_ago: float, author: str | None, headline: str, body: str, slug: str,
           ent: str | None, conf: float, sent: dict, ev: dict, imp: dict | None, evidence: dict,
           status: str = "COMPLETE", reason: str | None = None) -> dict:
    published = AS_OF - timedelta(hours=hours_ago)
    created = published + timedelta(minutes=2)
    return {
        "id": f"sig_{n:04d}",
        "document": {
            "id": f"doc_{n:04d}", "source": src[0], "source_type": src[1],
            "published_at": published.isoformat().replace("+00:00", "Z"),
            "ingested_at": (published + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "author": author, "headline": headline, "body": body, "url": stable_url(src, slug),
            "language": "en", "raw_metadata": {"demo": True},
        },
        "entity": mention(ent, conf),
        "sentiment": sent,
        "event": ev,
        "impact": imp,
        "evidence": evidence,
        "status": status,
        "status_reason": reason,
        "data_origin": "DEMO_FIXTURE",
        "model_versions": {
            "sentiment": "fixture-v0 (hand-authored)", "event": "fixture-v0 (hand-authored)",
            "impact": None if imp is None else "fixture-v0 (hand-authored)",
            "entity_resolver": "fixture-v0 (alias table)", "feature_schema": "1",
        },
        "created_at": created.isoformat().replace("+00:00", "Z"),
    }


def evidence(sources: int, domains: int, mentions: int, velocity: float, novelty: float, conf: float,
             corroborating: list[dict] | None = None, contradicted_by: list[str] | None = None) -> dict:
    return {"source_count": sources, "unique_domain_count": domains, "recent_mention_count": mentions,
            "coverage_velocity": velocity, "novelty_score": novelty, "model_confidence": conf,
            "contradicted_by": contradicted_by or [], "corroborating": corroborating or []}


def build_signals() -> list[dict]:
    s = []
    s.append(signal(
        1, src=SRC_LEDGER, hours_ago=3.5, author="Ledger Wire Banking Desk",
        headline="Meridian Bancorp flags funding gap as wholesale deposits fall 18% in a week",
        body=("Meridian Bancorp told investors it faces a funding shortfall after wholesale depositors "
              "withdrew roughly 18% of balances over seven days, and said it is in talks with the "
              "central bank about emergency liquidity. Analysts warned of contagion to regional lenders."),
        slug="meridian-funding-gap", ent="ENT_MRDN", conf=0.99, sent=sentiment(-0.72, 0.14),
        ev=event("CREDIT_FUNDING", 0.78, "REGULATORY_LEGAL", 0.08),
        imp=impact(0.88, [("event_type = CREDIT_FUNDING", 0.22, "Funding events historically move prices most"),
                          ("sentiment = -0.72", 0.14, "Strongly negative tone"),
                          ("source_corroboration (5 sources)", 0.12, "Independent outlets confirm"),
                          ("novelty = 0.86", 0.09, "First report of the shortfall"),
                          ("sector = Financials", 0.06, "Sector sensitive to funding news")]),
        evidence=evidence(5, 4, 14, 3.5, 0.86, 0.81, corro([
            (SRC_HARBOR, 3.1, "Meridian seeks central bank liquidity as deposits flee, sources say"),
            (SRC_CBJ, 2.4, "Deposit run at Meridian Bancorp raises regional-bank contagion fears"),
            (SRC_FT, 2.0, "$MRDB deposit outflow is real, three desks confirming"),
            (SRC_FT, 1.2, "Meridian funding gap: credit desk widening MRDB bonds hard")]))))
    s.append(signal(
        2, src=SRC_HARBOR, hours_ago=6.0, author=None,
        headline="Regulator proposes higher capital buffer for mid-sized lenders; Northgate Capital among most affected",
        body=("A draft rule would lift minimum capital buffers for mid-sized lenders by 150 basis points. "
              "Northgate Capital was singled out as among the institutions with the thinnest cushion."),
        slug="capital-buffer-proposal", ent="ENT_NRTH", conf=0.96, sent=sentiment(-0.38, 0.3),
        ev=event("REGULATORY_LEGAL", 0.74, "CREDIT_FUNDING", 0.12),
        imp=impact(0.78, [("event_type = REGULATORY_LEGAL", 0.20, "Capital rules reprice lenders"),
                          ("sentiment = -0.38", 0.07, "Moderately negative tone"),
                          ("sector = Financials", 0.09, "Rule applies to the whole sector"),
                          ("source_corroboration (3 sources)", 0.08, "Reported by several outlets")]),
        evidence=evidence(3, 3, 7, 1.4, 0.74, 0.77, corro([
            (SRC_LEDGER, 5.5, "Draft capital rule would hit thinly-capitalised lenders"),
            (SRC_FT, 5.2, "capital buffer +150bp for mid-size banks, NGCP the obvious loser")]))))
    s.append(signal(
        3, src=SRC_LEDGER, hours_ago=9.0, author="Ledger Wire Energy Desk",
        headline="Strait shipping disruption: Halden Energy suspends two export terminals",
        body=("Halden Energy suspended loadings at two export terminals after vessels were rerouted away "
              "from a contested shipping lane. Crude benchmarks jumped as traders priced in supply risk."),
        slug="halden-terminals", ent="ENT_HLDN", conf=0.98, sent=sentiment(-0.28, 0.4),
        ev=event("GEOPOLITICAL", 0.71, "PRODUCT_OPERATIONS", 0.1),
        imp=impact(0.74, [("event_type = GEOPOLITICAL", 0.19, "Supply-route shocks move energy names"),
                          ("sector = Energy", 0.10, "High sensitivity to supply news"),
                          ("novelty = 0.78", 0.07, "New development"),
                          ("source_corroboration (4 sources)", 0.09, "Widely reported")]),
        evidence=evidence(4, 3, 9, 1.9, 0.78, 0.79, corro([
            (SRC_CBJ, 8.2, "Oil jumps as shipping lane closure idles Halden terminals"),
            (SRC_HARBOR, 7.6, "Halden halts exports at two terminals amid rerouting"),
            (SRC_FT, 7.0, "HLDE terminals offline, Brent bid. watch the tanker rates")]))))
    s.append(signal(
        4, src=SRC_CBJ, hours_ago=12.0, author="Continental Business Journal Markets Desk",
        headline="Central bank signals faster tightening; futures price an extra 100 bp by spring",
        body=("The central bank said inflation is proving stickier than expected and opened the door to a "
              "faster pace of tightening. Rate futures now imply roughly 100 basis points of additional hikes."),
        slug="central-bank-tightening", ent=None, conf=0.0, sent=sentiment(-0.41, 0.35),
        ev=event("MACROECONOMIC", 0.81, "MARKET_VALUATION", 0.08),
        imp=impact(0.66, [("event_type = MACROECONOMIC", 0.18, "Policy shifts reprice every asset class"),
                          ("sentiment = -0.41", 0.08, "Hawkish tone"),
                          ("source_corroboration (6 sources)", 0.12, "Broad coverage"),
                          ("entity = UNKNOWN", -0.03, "No single issuer; market-wide event")]),
        evidence=evidence(6, 5, 21, 2.7, 0.62, 0.86, corro([
            (SRC_LEDGER, 11.5, "Rate futures price 100bp more as central bank turns hawkish"),
            (SRC_HARBOR, 11.0, "Bonds slide after central bank flags quicker tightening"),
            (SRC_FT, 10.5, "hawkish pivot confirmed. curve bear-flattening hard")]))))
    s.append(signal(
        5, src=SRC_FT, hours_ago=5.0, author="@chipwatcher_k",
        headline="Hearing from a contact that Vantor's main fab just had a fire. Output halted?? $VNTR",
        body="Unconfirmed. Contact at a supplier says smoke visible at the main fab and shifts sent home. $VNTR",
        slug="vntr-fab-rumor", ent="ENT_VNTR", conf=0.97, sent=sentiment(-0.6, 0.1),
        ev=event("PRODUCT_OPERATIONS", 0.58, "MARKET_VALUATION", 0.2),
        imp=impact(0.55, [("event_type = PRODUCT_OPERATIONS", 0.15, "Plant incidents move chip names"),
                          ("sentiment = -0.60", 0.10, "Alarmed tone"),
                          ("source_corroboration (1 source)", -0.10, "Single unverified social post"),
                          ("novelty = 0.90", 0.08, "First mention")]),
        evidence=evidence(1, 1, 3, 0.8, 0.9, 0.35, contradicted_by=["sig_0006"]),
    ))
    s.append(signal(
        6, src=SRC_LEDGER, hours_ago=3.0, author="Ledger Wire Technology Desk",
        headline="Vantor Semiconductors says fab incident contained, output unaffected",
        body=("Vantor Semiconductors said a small equipment fire at its main fab was extinguished within "
              "minutes with no injuries and no impact on wafer output."),
        slug="vantor-fab-contained", ent="ENT_VNTR", conf=0.99, sent=sentiment(0.1, 0.6),
        ev=event("PRODUCT_OPERATIONS", 0.62, "EARNINGS_FINANCIAL_PERFORMANCE", 0.1),
        imp=impact(0.27, [("event_type = PRODUCT_OPERATIONS", 0.08, "Plant incidents move chip names"),
                          ("company statement", -0.12, "Issuer says output unaffected"),
                          ("source_corroboration (2 sources)", 0.03, "Issuer statement carried by wires")]),
        evidence=evidence(2, 2, 4, 1.1, 0.4, 0.74, contradicted_by=["sig_0005"], corroborating=corro([
            (SRC_HARBOR, 2.6, "Vantor: fab fire put out, no production impact")]))))
    s.append(signal(
        7, src=SRC_HARBOR, hours_ago=18.0, author=None,
        headline="Prism Cloud Systems to acquire DataWeft in $4.2bn all-stock deal",
        body=("Prism Cloud Systems agreed to acquire DataWeft for $4.2bn in stock, adding analytics "
              "tooling to its platform. The deal is expected to close in the second quarter."),
        slug="prism-dataweft", ent="ENT_PRSM", conf=0.98, sent=sentiment(-0.05, 0.75),
        ev=event("MA_CORPORATE_ACTION", 0.84, "EARNINGS_FINANCIAL_PERFORMANCE", 0.05),
        imp=impact(0.55, [("event_type = MA_CORPORATE_ACTION", 0.14, "Large deals reprice the acquirer"),
                          ("deal size vs market cap", 0.10, "Material relative to acquirer"),
                          ("sentiment = -0.05", 0.01, "Neutral tone")]),
        evidence=evidence(3, 3, 6, 0.6, 0.55, 0.83, corro([
            (SRC_LEDGER, 17.5, "Prism Cloud buys DataWeft for $4.2bn in stock"),
            (SRC_CBJ, 16.0, "Prism's all-stock DataWeft deal: what analysts say")]))))
    s.append(signal(
        8, src=SRC_CBJ, hours_ago=20.0, author=None,
        headline="Corvale Therapeutics' lead drug misses primary endpoint in Phase III trial",
        body=("Corvale Therapeutics said its lead oncology candidate failed to meet the primary endpoint in a "
              "Phase III study and that it will review the programme. The drug accounted for most of the "
              "company's projected pipeline value."),
        slug="corvale-phase3", ent="ENT_CRVL", conf=0.99, sent=sentiment(-0.82, 0.1),
        ev=event("PRODUCT_OPERATIONS", 0.69, "EARNINGS_FINANCIAL_PERFORMANCE", 0.1),
        imp=impact(0.66, [("event_type = PRODUCT_OPERATIONS", 0.15, "Trial failures can reset valuations"),
                          ("sentiment = -0.82", 0.16, "Very negative tone"),
                          ("pipeline concentration", 0.11, "One asset drives most value"),
                          ("sector = Healthcare", 0.04, "Binary outcomes common")]),
        evidence=evidence(4, 4, 11, 0.9, 0.7, 0.8, corro([
            (SRC_LEDGER, 19.4, "Corvale shares set to plunge after Phase III miss"),
            (SRC_HARBOR, 19.0, "Corvale's oncology drug fails main trial goal"),
            (SRC_FT, 18.7, "CRVT lead asset dead. pipeline value gone")]))))
    s.append(signal(
        9, src=SRC_HARBOR, hours_ago=26.0, author=None,
        headline="Lumenar Retail cuts full-year guidance on weak holiday pre-orders",
        body=("Lumenar Retail lowered its full-year revenue and margin guidance, citing weak holiday "
              "pre-orders and heavier promotions. The company also flagged higher inventory levels."),
        slug="lumenar-guidance-cut", ent="ENT_LMNR", conf=0.98, sent=sentiment(-0.7, 0.2),
        ev=event("EARNINGS_FINANCIAL_PERFORMANCE", 0.8, "PRODUCT_OPERATIONS", 0.06),
        imp=impact(0.68, [("event_type = EARNINGS_FINANCIAL_PERFORMANCE", 0.17, "Guidance cuts are priced fast"),
                          ("sentiment = -0.70", 0.13, "Negative tone"),
                          ("sector = Consumer", 0.05, "Consumer names react to demand signals"),
                          ("inventory flag", 0.04, "Extra margin pressure")]),
        evidence=evidence(3, 3, 8, 0.5, 0.68, 0.82, corro([
            (SRC_LEDGER, 25.2, "Lumenar slashes outlook as holiday orders disappoint"),
            (SRC_CBJ, 24.0, "Retailer Lumenar trims guidance, flags inventory build")]))))
    s.append(signal(
        10, src=SRC_FT, hours_ago=8.0, author="@gamma_gwen",
        headline="Retail traders piling into Brightwell weekly calls, short interest squeezing. Meme energy.",
        body="BWFD weekly call volume 4x normal, borrow cost spiking. Nothing fundamental, pure flow. $BWFD",
        slug="bwfd-call-frenzy", ent="ENT_BWFD", conf=0.95, sent=sentiment(0.55, 0.2),
        ev=event("MARKET_VALUATION", 0.6, "EARNINGS_FINANCIAL_PERFORMANCE", 0.15),
        imp=impact(0.35, [("event_type = MARKET_VALUATION", 0.10, "Flow-driven moves can mean-revert"),
                          ("source type = SOCIAL", -0.05, "Social-only signal"),
                          ("coverage_velocity = 2.1", 0.06, "Fast attention build")]),
        evidence=evidence(1, 1, 12, 2.1, 0.6, 0.42)))
    s.append(signal(
        11, src=SRC_LEDGER, hours_ago=30.0, author=None,
        headline="Ashford Industrial prices $1.1bn refinancing, pushes maturity wall to 2031",
        body=("Ashford Industrial Group priced a $1.1bn refinancing that extends its debt maturity profile to "
              "2031 and reduces near-term rollover risk."),
        slug="ashford-refinancing", ent="ENT_ASHF", conf=0.98, sent=sentiment(0.62, 0.3),
        ev=event("CREDIT_FUNDING", 0.77, "MA_CORPORATE_ACTION", 0.05),
        imp=impact(0.24, [("event_type = CREDIT_FUNDING", 0.08, "Funding events matter"),
                          ("sentiment = +0.62", -0.04, "Positive tone lowers downside"),
                          ("novelty = 0.5", 0.03, "Expected refinancing")]),
        evidence=evidence(2, 2, 4, 0.3, 0.5, 0.84, corro([
            (SRC_HARBOR, 29.4, "Ashford extends maturities with $1.1bn bond deal")]))))
    s.append(signal(
        12, src=SRC_HARBOR, hours_ago=34.0, author=None,
        headline="Kestrel Aerospace unveils NX-9 regional jet; order book up 12%",
        body=("Kestrel Aerospace unveiled the NX-9 regional jet and said its order book grew 12% since the "
              "last quarter on early customer commitments."),
        slug="kestrel-nx9", ent="ENT_KSTR", conf=0.99, sent=sentiment(0.7, 0.22),
        ev=event("PRODUCT_OPERATIONS", 0.73, "EARNINGS_FINANCIAL_PERFORMANCE", 0.1),
        imp=impact(0.12, [("event_type = PRODUCT_OPERATIONS", 0.05, "Launches rarely move credit"),
                          ("sentiment = +0.70", -0.03, "Positive tone")]),
        evidence=evidence(2, 2, 5, 0.3, 0.45, 0.85, corro([
            (SRC_LEDGER, 33.0, "Kestrel launches NX-9 jet with fresh orders")]))))
    s.append(signal(
        13, src=SRC_FT, hours_ago=4.0, author="@anon_alpha_77",
        headline="a big European bank is about to gap down tomorrow, trust me",
        body="Not naming it. You'll see. Cover your longs.",
        slug="anon-bank-gap", ent=None, conf=0.0, sent=sentiment(-0.55, 0.25),
        ev=event("MARKET_VALUATION", 0.46, "CREDIT_FUNDING", 0.3),
        imp=impact(0.22, [("entity = UNKNOWN", -0.10, "No resolvable issuer"),
                          ("source type = SOCIAL", -0.06, "Anonymous, unverifiable"),
                          ("sentiment = -0.55", 0.07, "Alarmist tone")]),
        evidence=evidence(1, 1, 2, 0.5, 0.95, 0.2)))
    s.append(signal(
        14, src=SRC_CBJ, hours_ago=2.0, author=None,
        headline="Amberline Logistics halts two Asian hubs as port strike spreads",
        body=("Amberline Logistics halted operations at two Asian hubs as a port workers' strike spread. "
              "The company did not give a timeline for resuming service."),
        slug="amberline-port-strike", ent="ENT_AMBL", conf=0.98, sent=sentiment(-0.5, 0.3),
        ev=event("PRODUCT_OPERATIONS", 0.52, "GEOPOLITICAL", 0.2), imp=None,
        evidence=evidence(2, 2, 3, 0.9, 0.8, 0.0, corro([
            (SRC_HARBOR, 1.0, "Port strike spreads, Amberline idles two hubs")])),
        status="PARTIAL",
        reason="Impact model unavailable at ingestion time (replayed failure case). No score was fabricated."))
    s.append(signal(
        15, src=SRC_HARBOR, hours_ago=14.0, author=None,
        headline="Rating agency moves Orchard Mutual outlook to negative on reserve adequacy",
        body=("A rating agency revised Orchard Mutual's outlook to negative, citing concerns that claims "
              "reserves may be insufficient after a run of large losses."),
        slug="orchard-outlook-negative", ent="ENT_ORCM", conf=0.97, sent=sentiment(-0.5, 0.3),
        ev=event("CREDIT_FUNDING", 0.66, "EARNINGS_FINANCIAL_PERFORMANCE", 0.14),
        imp=impact(0.58, [("event_type = CREDIT_FUNDING", 0.15, "Outlook changes shift spreads"),
                          ("sentiment = -0.50", 0.09, "Negative tone"),
                          ("sector = Financials", 0.05, "Sector sensitive to credit news")]),
        evidence=evidence(2, 2, 5, 0.6, 0.66, 0.78, corro([
            (SRC_CBJ, 13.0, "Orchard Mutual outlook cut to negative over reserves")]))))
    return s


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    entities = build_entities()
    portfolio = build_portfolio()
    signals = [RiskSignal.model_validate(x) for x in build_signals()]  # fail loudly on bad fixtures
    ids = {e.entity_id for e in entities}
    for sig in signals:
        assert sig.entity.is_unknown or sig.entity.entity_id in ids, sig.id

    def dump(name: str, payload: object) -> None:
        (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    dump("entities.json", [e.model_dump(mode="json") for e in entities])
    dump("portfolio.json", portfolio.model_dump(mode="json"))
    dump("signals.json", {
        "as_of": AS_OF.isoformat().replace("+00:00", "Z"),
        "data_origin": "DEMO_FIXTURE",
        "note": "Synthetic, hand-authored demo signals. Not model output.",
        "signals": [s.model_dump(mode="json", exclude_none=False) for s in signals],
    })
    print(f"entities={len(entities)} assets={len(portfolio.assets)} signals={len(signals)} "
          f"value={portfolio.total_value:,.0f}")


if __name__ == "__main__":
    main()
