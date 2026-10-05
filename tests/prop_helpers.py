"""Builders for the propagation tests: a small hand-checkable book, signals with exact texts, and the mapper / assessor / generator over the real configs."""

from __future__ import annotations

from datetime import UTC, datetime

from eventshock.config import REPO_ROOT, Settings, load_scenarios, load_taxonomy
from eventshock.domain import AssetClass, EventCategory, Portfolio, PortfolioAsset
from eventshock.propagation.concentration import ConcentrationAnalyzer
from eventshock.propagation.config import load_propagation_config
from eventshock.propagation.mapping import PropagationMapper
from eventshock.propagation.materiality import MaterialityAssessor
from eventshock.propagation.scenario_gen import ScenarioGenerator
from eventshock.stress.scenarios import ScenarioCatalog
from tests.helpers import make_asset
from tests.intel_helpers import CFG as INTEL_CFG
from tests.intel_helpers import JPM, XOM, scope_resolver, sig  # noqa: F401

CONFIG_DIR = REPO_ROOT / "configs"
PROP_CFG = load_propagation_config(CONFIG_DIR)
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
TICKERS = {"ENT_JPM": "JPM", "ENT_GS": "GS", "ENT_XOM": "XOM", "ENT_MSFT": "MSFT", "ENT_AAPL": "AAPL", "ENT_BA": "BA", "ENT_BP": "BP"}
NAMES = {"ENT_JPM": "JPMorgan Chase", "ENT_GS": "Goldman Sachs", "ENT_XOM": "Exxon Mobil", "ENT_MSFT": "Microsoft", "ENT_AAPL": "Apple",
         "ENT_BA": "Boeing", "ENT_BP": "BP", "ENT_UST": "US Treasuries"}
APPLE = {"entity_id": "ENT_AAPL", "entity_name": "Apple", "ticker": "AAPL", "sector": "Technology", "country": "US", "link_confidence": 0.95}


def asset(aid: str, ent: str, sector: str, value: float, kind: AssetClass = AssetClass.EQUITY, geography: str = "US", **kw) -> PortfolioAsset:
    extra: dict = {}
    if kind is AssetClass.BOND:
        extra = {"duration": kw.pop("duration", 5.0)}
    if kind is AssetClass.LOAN:
        pd, lgd = kw.pop("pd", 0.02), kw.pop("lgd", 0.4)
        return make_asset(asset_id=aid, entity_id=ent, name=NAMES.get(ent, ent) + " loan", sector=sector, geography=geography, asset_type=kind,
                          notional=value / (1 - pd * lgd), market_value=value, pd=pd, lgd=lgd, **kw)
    return make_asset(asset_id=aid, entity_id=ent, name=NAMES.get(ent, ent), sector=sector, geography=geography, asset_type=kind, notional=value, market_value=value,
                      **extra, **kw)


def book(extra: list[PortfolioAsset] | None = None, *, name: str = "Test book", only: list[str] | None = None) -> Portfolio:
    assets = [
        asset("jpm_eq", "ENT_JPM", "Financials", 200_000),
        asset("jpm_bd", "ENT_JPM", "Financials", 100_000, AssetClass.BOND, duration=5.0),
        asset("gs_eq", "ENT_GS", "Financials", 100_000),
        asset("xom_eq", "ENT_XOM", "Energy", 150_000),
        asset("xom_ln", "ENT_XOM", "Energy", 99_200, AssetClass.LOAN),
        asset("msft_eq", "ENT_MSFT", "Technology", 150_000),
        asset("aapl_eq", "ENT_AAPL", "Technology", 100_000),
        asset("ba_eq", "ENT_BA", "Industrials", 50_000),
        asset("bp_eq", "ENT_BP", "Energy", 50_000, geography="GB"),
        asset("ust_bd", "ENT_UST", "Other", 100_000, AssetClass.BOND, duration=10.0, spread_sensitivity=0.0),
        asset("cash", "ENT_CASH", "Cash", 50_000, AssetClass.CASH),
    ]
    if only is not None:
        assets = [a for a in assets if a.asset_id in only]
    return Portfolio(portfolio_id="pf_test", name=name, as_of=NOW, assets=assets + (extra or []))


def mapper(cfg=PROP_CFG, overrides=None, *, ticker_industry=None) -> PropagationMapper:  # noqa: ANN001
    return PropagationMapper(cfg, ticker_industry=ticker_industry or INTEL_CFG.scope.ticker_industry, region_names=INTEL_CFG.scope.region_names,
                             entity_tickers=lambda: TICKERS, overrides=overrides)


def assessor(cfg=PROP_CFG) -> MaterialityAssessor:  # noqa: ANN001
    return MaterialityAssessor(cfg)


def catalog() -> ScenarioCatalog:
    s = Settings(config_dir=CONFIG_DIR)
    _, scenarios = load_scenarios(s)
    return ScenarioCatalog(scenarios, {c.id: c.default_scenario for c in load_taxonomy(s).categories})


def generator(cfg=PROP_CFG) -> ScenarioGenerator:  # noqa: ANN001
    from eventshock.config import AppConfig
    return ScenarioGenerator(cfg, catalog(), AppConfig().stress, None)


def analyzer(cfg=PROP_CFG) -> ConcentrationAnalyzer:  # noqa: ANN001
    m = mapper(cfg)
    return ConcentrationAnalyzer(cfg, m.industry_of, lambda: NAMES)


def mapped(headline: str, *, body: str = "", entity: dict | None = None, category: EventCategory | None = EventCategory.REGULATORY_LEGAL, portfolio: Portfolio | None = None,
           cfg=PROP_CFG, overrides=None):  # noqa: ANN001
    """(signal, graph) for a report with exactly this text, over ``portfolio`` (the default hand-made book)."""
    s = sig("s1", headline, body, entity=entity, category=category or EventCategory.REGULATORY_LEGAL)
    scope = scope_resolver().resolve(s)
    g = mapper(cfg, overrides).map(s, portfolio or book(), scope, category)
    return s, g
