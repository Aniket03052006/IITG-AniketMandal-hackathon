"""The closed vocabularies a watch item may name, built from the live configs and the entity master (so the pickers and the validator can never disagree)."""

from __future__ import annotations

from collections.abc import Iterable

from ..config import Taxonomy
from ..decision.config import WatchlistCfg
from ..domain import Entity
from ..intelligence.config import IntelligenceConfig
from .models import VocabEntry, WatchVocabulary

THEME_LABEL = {
    "rates": "Interest rates", "inflation": "Inflation", "growth_and_jobs": "Growth and jobs", "credit_stress": "Credit stress", "trade_and_conflict": "Trade and conflict",
    "currencies_and_commodities": "Currencies and commodities", "equity_market": "Equity market",
}


def build_vocabulary(icfg: IntelligenceConfig, sectors: Iterable[str], taxonomy: Taxonomy, entities: Iterable[Entity], cfg: WatchlistCfg) -> WatchVocabulary:
    ents = sorted((e for e in entities if e.entity_id), key=lambda e: (e.name, e.entity_id))
    companies = [VocabEntry(value=e.entity_id, label=f"{e.name} ({e.ticker})" if e.ticker else e.name, detail=e.ticker) for e in ents]
    return WatchVocabulary(
        companies=companies,
        sectors=[VocabEntry(value=s, label=s) for s in sorted(sectors)],
        industries=[VocabEntry(value=n, label=n, detail=i.sector) for n, i in sorted(icfg.scope.industries.items())],
        geographies=[VocabEntry(value=c, label=n) for c, n in sorted(icfg.scope.region_names.items(), key=lambda kv: kv[1])],
        event_types=[VocabEntry(value=c.id.value, label=c.label, detail=c.description) for c in taxonomy.categories],
        risk_themes=[VocabEntry(value=t, label=THEME_LABEL.get(t, t.replace("_", " ").title())) for t in sorted(icfg.scope.theme_kinds)],
        portfolio_exposure=[VocabEntry(value="top:N", label=f"Top N holdings by value (N up to {cfg.top_holdings_max})"), *companies],
        max_watchlists=cfg.max_watchlists, max_items=cfg.max_items)
