"""Builders for small, hand-checkable test objects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from eventshock.domain import (
    EventCategory,
    EventClassification,
    Evidence,
    ImpactAssessment,
    ModelVersions,
    Portfolio,
    PortfolioAsset,
    RawDocument,
    RiskSignal,
    SentimentResult,
    SignalScope,
    SignalStatus,
    SourceType,
)
from eventshock.domain.enums import AssetClass, DataOrigin, RiskFactor, ShockScope
from eventshock.domain.scenarios import Scenario, ShockSpec
from eventshock.domain.stress import AppliedShock

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def make_asset(**kw) -> PortfolioAsset:
    base = dict(asset_id="a", asset_type=AssetClass.EQUITY, entity_id="E1", name="n",
                sector="Fin", geography="US", notional=1_000_000.0, market_value=1_000_000.0)
    return PortfolioAsset(**{**base, **kw})


def make_portfolio(assets: list[PortfolioAsset]) -> Portfolio:
    return Portfolio(portfolio_id="pf_test", name="t", as_of=NOW, assets=assets)


def shock(factor: RiskFactor, scope: ShockScope, value: float, applicable: bool = True) -> AppliedShock:
    return AppliedShock(factor=factor, scope=scope, base_value=value, scaled_value=value,
                        applicable=applicable)


def make_event(primary: EventCategory) -> EventClassification:
    probs = {c: 0.02 for c in EventCategory}
    probs[primary] = 1 - 0.02 * 7
    return EventClassification(category=primary, probabilities=probs)


def make_signal(
    sid: str = "s1",
    *,
    category: EventCategory = EventCategory.REGULATORY_LEGAL,
    impact: int | None = 8,
    entity_id: str = "E1",
    sector: str = "Fin",
    scope: SignalScope | None = None,
) -> RiskSignal:
    unknown = entity_id == "UNKNOWN_ENTITY"
    return RiskSignal(
        id=sid,
        document=RawDocument(id=f"d_{sid}", source="S", source_type=SourceType.NEWS,
                             published_at=NOW - timedelta(hours=1), ingested_at=NOW,
                             headline="headline"),
        entity=({"entity_id": "UNKNOWN_ENTITY"} if unknown else
                {"entity_id": entity_id, "entity_name": entity_id, "sector": sector,
                 "link_confidence": 0.9}),
        scope=scope,
        sentiment=SentimentResult(positive=0.1, neutral=0.2, negative=0.7, score=-0.6),
        event=make_event(category),
        impact=None if impact is None else ImpactAssessment(score=impact, raw=impact / 10),
        evidence=Evidence(source_count=1, unique_domain_count=1, recent_mention_count=0,
                          coverage_velocity=0, novelty_score=0.5, model_confidence=0.5),
        status=SignalStatus.COMPLETE if impact is not None else SignalStatus.PARTIAL,
        status_reason=None if impact is not None else "impact model down",
        data_origin=DataOrigin.DEMO_FIXTURE,
        model_versions=ModelVersions(sentiment="t", event="t", impact="t", entity_resolver="t"),
        created_at=NOW,
    )


def make_scenario(category: EventCategory = EventCategory.REGULATORY_LEGAL, shocks=None,
                  sid: str = "scn_t") -> Scenario:
    shocks = shocks or [ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.ISSUER, value=-0.1)]
    return Scenario(id=sid, version="1.0", name="T", category=category, description="d",
                    reference_impact=7, shocks=shocks)
