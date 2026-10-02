from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from eventshock.domain import (
    EventCategory,
    EventClassification,
    Evidence,
    ImpactAssessment,
    ModelVersions,
    PortfolioAsset,
    RawDocument,
    RiskSignal,
    SentimentResult,
    SignalStatus,
    SourceType,
)
from eventshock.domain.enums import AssetClass, DataOrigin, RiskFactor, ShockScope
from eventshock.domain.scenarios import Scenario, ShockSpec

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def doc(**kw):
    base = dict(id="d1", source="S", source_type=SourceType.NEWS, published_at=NOW,
                ingested_at=NOW + timedelta(minutes=1), headline="h", body="b")
    return RawDocument(**{**base, **kw})


def event(primary=EventCategory.GEOPOLITICAL):
    probs = {c: 0.02 for c in EventCategory}
    probs[primary] = 1 - 0.02 * 7
    return EventClassification(category=primary, probabilities=probs)


def signal(**kw):
    base = dict(
        id="s1", document=doc(), entity={"entity_id": "UNKNOWN_ENTITY"},
        sentiment=SentimentResult(positive=0.1, neutral=0.2, negative=0.7, score=-0.6),
        event=event(), impact=ImpactAssessment(score=7, raw=0.66),
        evidence=Evidence(source_count=1, unique_domain_count=1, recent_mention_count=0,
                          coverage_velocity=0, novelty_score=0.5, model_confidence=0.5),
        status=SignalStatus.COMPLETE, data_origin=DataOrigin.DEMO_FIXTURE,
        model_versions=ModelVersions(sentiment="x", event="x", impact="x", entity_resolver="x"),
        created_at=NOW,
    )
    return RiskSignal(**{**base, **kw})


class TestRawDocument:
    def test_valid(self):
        assert doc().headline == "h"

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            doc(published_at=datetime(2026, 1, 1), ingested_at=NOW)

    def test_empty_text_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            doc(headline=" ", body="")

    def test_ingested_before_published_rejected(self):
        with pytest.raises(ValidationError, match="ingested_at"):
            doc(ingested_at=NOW - timedelta(hours=1))


class TestSentiment:
    def test_valid(self):
        assert SentimentResult(positive=0.5, neutral=0.2, negative=0.3, score=0.2).score == 0.2

    def test_probabilities_must_sum_to_one(self):
        with pytest.raises(ValidationError, match="sum to 1"):
            SentimentResult(positive=0.5, neutral=0.5, negative=0.5, score=0.0)

    def test_score_must_equal_pos_minus_neg(self):
        with pytest.raises(ValidationError, match="positive - negative"):
            SentimentResult(positive=0.5, neutral=0.2, negative=0.3, score=0.9)

    def test_score_range(self):
        with pytest.raises(ValidationError):
            SentimentResult(positive=1.0, neutral=0.0, negative=0.0, score=1.5)


class TestEventClassification:
    def test_confidence_is_argmax_probability(self):
        e = event(EventCategory.MACROECONOMIC)
        assert e.confidence == pytest.approx(0.86)

    def test_must_cover_every_category(self):
        with pytest.raises(ValidationError, match="every EventCategory"):
            EventClassification(category=EventCategory.GEOPOLITICAL,
                                probabilities={EventCategory.GEOPOLITICAL: 1.0})

    def test_category_must_be_argmax(self):
        probs = {c: 0.02 for c in EventCategory}
        probs[EventCategory.GEOPOLITICAL] = 0.86
        with pytest.raises(ValidationError, match="arg-max"):
            EventClassification(category=EventCategory.MACROECONOMIC, probabilities=probs)


class TestImpact:
    @pytest.mark.parametrize("score", [0, 11])
    def test_score_range(self, score):
        with pytest.raises(ValidationError):
            ImpactAssessment(score=score, raw=0.5)

    def test_raw_range(self):
        with pytest.raises(ValidationError):
            ImpactAssessment(score=5, raw=1.2)


class TestRiskSignal:
    def test_complete_requires_impact(self):
        with pytest.raises(ValidationError, match="requires an impact"):
            signal(impact=None)

    def test_partial_must_not_have_impact(self):
        with pytest.raises(ValidationError, match="must not carry an impact"):
            signal(status=SignalStatus.PARTIAL, status_reason="x")

    def test_partial_needs_reason(self):
        with pytest.raises(ValidationError, match="explain why"):
            signal(status=SignalStatus.PARTIAL, impact=None)

    def test_partial_without_impact_ok(self):
        s = signal(status=SignalStatus.PARTIAL, impact=None, status_reason="model down")
        assert s.impact is None

    def test_unknown_entity_is_first_class(self):
        assert signal().entity.is_unknown


def asset(**kw):
    base = dict(asset_id="a", asset_type=AssetClass.EQUITY, entity_id="E", name="n", sector="S",
                geography="US", notional=100.0, market_value=100.0)
    return PortfolioAsset(**{**base, **kw})


class TestPortfolioAsset:
    def test_bond_requires_duration(self):
        with pytest.raises(ValidationError, match="duration"):
            asset(asset_type=AssetClass.BOND)

    def test_loan_requires_pd_lgd(self):
        with pytest.raises(ValidationError, match="pd and lgd"):
            asset(asset_type=AssetClass.LOAN)

    def test_loan_value_must_equal_ead_minus_el(self):
        with pytest.raises(ValidationError, match="market_value must equal"):
            asset(asset_type=AssetClass.LOAN, notional=1e6, pd=0.02, lgd=0.5, market_value=1e6)
        ok = asset(asset_type=AssetClass.LOAN, notional=1e6, pd=0.02, lgd=0.5, market_value=990_000)
        assert ok.market_value == 990_000

    def test_derivative_requires_delta(self):
        with pytest.raises(ValidationError, match="delta"):
            asset(asset_type=AssetClass.DERIVATIVE)

    def test_derivative_mtm_may_be_negative(self):
        assert asset(asset_type=AssetClass.DERIVATIVE, delta=0.5, market_value=-3.0).market_value == -3.0

    def test_equity_value_must_be_positive(self):
        with pytest.raises(ValidationError):
            asset(market_value=-1.0)

    def test_pd_range(self):
        with pytest.raises(ValidationError):
            asset(asset_type=AssetClass.LOAN, pd=1.5, lgd=0.5, market_value=1.0)


class TestScenarioContract:
    def test_equity_shock_range(self):
        with pytest.raises(ValidationError, match="EQUITY"):
            ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-10)

    def test_bp_shock_range(self):
        with pytest.raises(ValidationError, match="credible"):
            ShockSpec(factor=RiskFactor.RATES_BPS, scope=ShockScope.MARKET, value=5000)

    def test_duplicate_factor_scope_rejected(self):
        s = ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=-0.1)
        with pytest.raises(ValidationError, match="duplicate"):
            Scenario(id="x", version="1", name="n", category=EventCategory.GEOPOLITICAL,
                     description="d", shocks=[s, s])
