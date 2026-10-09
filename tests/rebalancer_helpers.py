"""Builders for the rebalancer tests: company signals with an exact ticker, source, time and sentiment, and a service over a small, hand-checkable index."""

from __future__ import annotations

from datetime import datetime, timedelta

from eventshock.config import REPO_ROOT
from eventshock.domain import Entity, RawDocument, RiskSignal, SentimentResult, SourceType, TimestampOrigin
from eventshock.domain.documents import EntityMention
from eventshock.domain.provenance import DedupAudit, EntityAudit, SignalProvenance
from eventshock.domain.scope import scope_from_entity
from eventshock.rebalancer.config import RebalancerConfig, load_rebalancer_config
from eventshock.rebalancer.risk import RiskInputs
from eventshock.rebalancer.service import RebalancerService
from eventshock.store import CHANNEL_LIVE, CombinedSignalRepository, InMemorySignalRepository, LiveSignalStore
from tests.helpers import NOW, make_signal

BASE = datetime(2026, 9, 1, 9, tzinfo=NOW.tzinfo)
TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "JPM", "BAC", "GS", "XOM", "CVX", "JNJ", "UNH", "PFE", "WMT"]
SECTORS = {"AAPL": "Technology", "JPM": "Financials", "XOM": "Energy", "JNJ": "Healthcare", "WMT": "Consumer"}
REAL_SECTORS = {"AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "GOOGL": "Technology", "AMZN": "Technology", "META": "Technology", "JPM": "Financials", "BAC": "Financials",
                "GS": "Financials", "XOM": "Energy", "CVX": "Energy", "JNJ": "Healthcare", "UNH": "Healthcare", "PFE": "Healthcare", "WMT": "Consumer"}   # as the entity master has it


def risk_inputs(*, sigma: dict[str, float] | None = None, adv: dict[str, float] | None = None) -> RiskInputs:
    """Volatility 2 % and $10 bn a day for every stock, except where overridden."""
    return RiskInputs({t: (sigma or {}).get(t, 0.02) for t in TICKERS}, {t: (adv or {}).get(t, 1e10) for t in TICKERS}, "2026-09-10", "2026-09-10")


def cfg(**overrides) -> RebalancerConfig:  # noqa: ANN003
    """The shipped config with dotted-path overrides, e.g. cfg(**{"turnover.max_per_cycle": 0.02})."""
    return load_rebalancer_config(REPO_ROOT / "configs", overrides or None)


def entities(real_sectors: bool = False) -> list[Entity]:
    sectors = REAL_SECTORS if real_sectors else SECTORS
    return [Entity(entity_id=f"ENT_{t}", name=f"{t} Corp", ticker=t, sector=sectors.get(t, "Technology"), country="US") for t in TICKERS]


def sentiment(x: float) -> SentimentResult:
    pos, neg = max(x, 0.0), max(-x, 0.0)
    return SentimentResult(positive=pos, neutral=1 - pos - neg, negative=neg, score=x)


def sig(sid: str, ticker: str | None, x: float, *, hours: float = 0.0, source: str = "Wire A", origin: TimestampOrigin = TimestampOrigin.SOURCE,
        link: float = 0.95, source_type: SourceType = SourceType.NEWS, complete: bool = True, headline: str | None = None, sentiment_origin: str = "MODEL",
        impact: int = 5) -> RiskSignal:
    """A COMPANY-scope signal about ``ticker`` (UNRESOLVED when None), published ``hours`` after BASE."""
    t = BASE + timedelta(hours=hours)
    s = make_signal(sid, entity_id=f"ENT_{ticker}" if ticker else "UNKNOWN_ENTITY", impact=impact if complete else None)
    ent = EntityMention(entity_id=f"ENT_{ticker}", entity_name=f"{ticker} Corp", ticker=ticker, sector="Technology", country="US", link_confidence=link) if ticker else EntityMention()
    doc = RawDocument(id=f"doc_{sid}", source=source, source_type=source_type, published_at=t, ingested_at=t, headline=headline or f"{ticker} headline {sid}", body="",
                      url=f"https://example.test/{sid}", raw_metadata={"adapter": "test", "record_ref": sid, "content_sha256": "0" * 64})
    prov = SignalProvenance(adapter="test", snapshot_id="snap", record_ref=sid, content_sha256="0" * 64, timestamp_origin=origin, pipeline_version="t", stage_origins={"sentiment": sentiment_origin},
                           entity_audit=EntityAudit(rule="ALIAS", matched_text=ticker), dedup=DedupAudit(cluster_id=f"cl_{sid}", member_count=1, exact_duplicates_folded=0, members=[]))
    out = s.model_copy(update={"document": doc, "entity": ent, "sentiment": sentiment(x), "provenance": prov, "created_at": t,
                               "scope": scope_from_entity(ent)})
    return out


def repo(signals: list[RiskSignal], *, as_of_hours: float = 96.0, live: list[RiskSignal] | None = None) -> CombinedSignalRepository:
    store = LiveSignalStore()
    for s in live or []:
        store.upsert(s, CHANNEL_LIVE)
    return CombinedSignalRepository(InMemorySignalRepository(signals, BASE + timedelta(hours=as_of_hours)), store)


def service(signals: list[RiskSignal], *, as_of_hours: float = 96.0, live: list[RiskSignal] | None = None, config: RebalancerConfig | None = None,
            risk: RiskInputs | None = None, real_sectors: bool = False) -> RebalancerService:
    return RebalancerService(config or cfg(), signals=repo(signals, as_of_hours=as_of_hours, live=live), entities=lambda: entities(real_sectors), risk=risk)
