"""Builders for the scenario-lab tests: a hand-checkable book with a foreign-currency and an oil-sensitive position, a real StressService, and a lab over the real propagation config."""

from __future__ import annotations

from datetime import datetime

from eventshock.config import REPO_ROOT, AppConfig
from eventshock.decision.config import load_decision_config
from eventshock.domain import AssetClass, Entity, Portfolio
from eventshock.lab.service import LabService
from eventshock.propagation.attribution import build_attribution
from eventshock.services.stress_service import StressService
from eventshock.store import InMemoryPortfolioRepository, InMemorySignalRepository
from eventshock.stress.scenarios import ScenarioCatalog
from tests.helpers import NOW, make_asset, make_portfolio
from tests.prop_helpers import PROP_CFG, mapper

DCFG = load_decision_config(REPO_ROOT / "configs")
LAB_CFG = DCFG.lab


def lab_book() -> Portfolio:
    return make_portfolio([
        make_asset(asset_id="xom", entity_id="ENT_XOM", name="Exxon Mobil", sector="Energy", market_value=300_000, notional=300_000, beta=1.0),
        make_asset(asset_id="jpm", entity_id="ENT_JPM", name="JPMorgan Chase", sector="Financials", market_value=400_000, notional=400_000, beta=1.2),
        make_asset(asset_id="msft", entity_id="ENT_MSFT", name="Microsoft", sector="Technology", market_value=200_000, notional=200_000, beta=1.0),
        make_asset(asset_id="sap", entity_id="ENT_SAP", name="SAP (EUR line)", sector="Technology", market_value=100_000, notional=100_000, beta=1.0, currency="EUR"),
        make_asset(asset_id="ust", entity_id="ENT_UST", name="US Treasury 10y", sector="Other", asset_type=AssetClass.BOND, duration=8.0, spread_sensitivity=0.0,
                   market_value=200_000, notional=200_000),
        make_asset(asset_id="cash", entity_id="ENT_CASH", name="Cash", sector="Cash", asset_type=AssetClass.CASH, market_value=100_000, notional=100_000),
    ])


class FakeProp:
    """The two things the lab reads of the propagation layer: its config and the attribution of a finished run."""

    cfg = PROP_CFG

    def attribution(self, run, pf, *, extra_factor_map=None):  # noqa: ANN001, ANN201
        return build_attribution(run, pf, industry_of=mapper().industry_of, engine_factor_map={**PROP_CFG.engine_factor_map, **(extra_factor_map or {})},
                                 risk_factor_labels={k: v.label for k, v in PROP_CFG.risk_factors.items()}, entity_names={})


ENTITIES = [Entity(entity_id="ENT_XOM", name="Exxon Mobil", ticker="XOM", sector="Energy", country="US"),
            Entity(entity_id="ENT_JPM", name="JPMorgan Chase", ticker="JPM", sector="Financials", country="US"),
            Entity(entity_id="ENT_MSFT", name="Microsoft", ticker="MSFT", sector="Technology", country="US"),
            Entity(entity_id="ENT_KO", name="Coca-Cola", ticker="KO", sector="Consumer", country="US")]


def lab(book: Portfolio | None = None, clock: datetime | None = None) -> LabService:
    pf = book or lab_book()
    signals = InMemorySignalRepository([], NOW)
    catalog = ScenarioCatalog([], {}, require_complete=False)
    known = {e.entity_id for e in ENTITIES}
    ents = [*ENTITIES, *[Entity(entity_id=a.entity_id, name=a.name, sector=a.sector, country="US") for a in pf.assets if a.entity_id not in known]]   # the repository wants every held entity in the master
    stress = StressService(signals, InMemoryPortfolioRepository(pf, ents), catalog, AppConfig())
    return LabService(LAB_CFG, reverse_cfg=DCFG.reverse, stress=stress, propagation=lambda: FakeProp(), signals=signals, book=lambda p: p or pf, entities=lambda: ENTITIES,
                      sectors=lambda: ["Financials", "Technology", "Energy", "Healthcare", "Industrials", "Consumer"], shock_history=lambda: None, clock=lambda: clock or NOW)
