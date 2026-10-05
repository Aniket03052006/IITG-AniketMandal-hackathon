"""Builders for the personal-portfolio tests: a small instrument catalog and a resolver over the real configs/portfolio.yaml."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from eventshock.domain import Entity
from eventshock.portfolio.betas import SCHEMA, IssuerBetas
from eventshock.portfolio.catalog import InstrumentCatalog, Reference
from eventshock.portfolio.config import load_portfolio_config
from eventshock.portfolio.models import HoldingInput, PortfolioInput
from eventshock.portfolio.resolve import Resolver

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
ENTITIES = [
    Entity(entity_id="ENT_AAPL", name="Apple Inc.", ticker="AAPL", sector="Technology", country="US"),
    Entity(entity_id="ENT_JPM", name="JPMorgan Chase & Co.", ticker="JPM", sector="Financials", country="US"),
    Entity(entity_id="ENT_XOM", name="Exxon Mobil Corporation", ticker="XOM", sector="Energy", country="US"),
    Entity(entity_id="ENT_MSFT", name="Microsoft Corporation", ticker="MSFT", sector="Technology", country="US"),
]
BETAS = IssuerBetas({"schema": SCHEMA, "as_of": "2026-10-01", "window_sessions": 250, "betas": {
    "AAPL": {"beta": 1.2, "beta_ols": 1.25, "se": 0.1, "r2": 0.4, "n": 250},
    "JPM": {"beta": 0.9, "beta_ols": 0.9, "se": 0.1, "r2": 0.3, "n": 250},
    "XOM": {"beta": -0.5, "beta_ols": -0.56, "se": 0.12, "r2": 0.08, "n": 250},
}})
REFERENCE = {
    "TLT": Reference("TLT", "Long Treasury fund", "BOND", "Other", "US", duration=17.0, spread_sensitivity=0.0, basis="government debt"),
    "LQD": Reference("LQD", "IG corporate fund", "BOND", "Other", "US", duration=8.0, spread_sensitivity=1.0, basis="corporate"),
    "SPY": Reference("SPY", "S&P 500 fund", "EQUITY", "Other", "US", beta=1.0, basis="index"),
    "GLD": Reference("GLD", "Gold fund", "OTHER", "Other", "OTHER", basis="commodity"),
}


def make_resolver() -> Resolver:
    cfg = load_portfolio_config(ROOT / "configs")
    cat = InstrumentCatalog(ENTITIES, BETAS, REFERENCE, cfg.betas.floor, cfg.betas.cap)
    return Resolver(cat, cfg)


def weights(spec: dict[str, float], **kw) -> PortfolioInput:
    return PortfolioInput(name=kw.pop("name", "t"), holdings=[HoldingInput(ticker=t, weight_pct=w) for t, w in spec.items()], **kw)
