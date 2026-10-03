"""Risk-signal contracts: sentiment, event, impact, evidence, provenance (PRD §10, §12)."""

from __future__ import annotations

import math
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from .base import ContractModel
from .documents import EntityMention, RawDocument, _require_aware
from .enums import DataOrigin, EventCategory, EventStatus, SignalStatus, SourceType
from .provenance import SignalProvenance

_PROB_TOL = 1e-3


class SentimentResult(ContractModel):
    """Tone of the text — deliberately separate from event type and impact (PRD §2)."""

    positive: float = Field(ge=0, le=1)
    neutral: float = Field(ge=0, le=1)
    negative: float = Field(ge=0, le=1)
    score: float = Field(ge=-1, le=1, description="positive - negative")

    @model_validator(mode="after")
    def _consistent(self) -> SentimentResult:
        if not math.isclose(self.positive + self.neutral + self.negative, 1.0, abs_tol=_PROB_TOL):
            raise ValueError("sentiment probabilities must sum to 1")
        if not math.isclose(self.score, self.positive - self.negative, abs_tol=_PROB_TOL):
            raise ValueError("sentiment score must equal positive - negative")
        return self


class EventClassification(ContractModel):
    """What happened: a category plus a probability for every taxonomy class."""

    category: EventCategory
    probabilities: dict[EventCategory, float] = Field(
        description="over the eight classes; for a trained model, conditional on the text being an event")
    status: EventStatus = Field(
        default=EventStatus.CLASSIFIED,
        description="CLASSIFIED | NO_EVENT | UNCERTAIN: whether `category` is a finding (see EventStatus)")
    no_event_probability: float | None = Field(
        default=None, ge=0, le=1,
        description="calibrated P(not a market event); null where the stage cannot say so")

    @model_validator(mode="after")
    def _valid(self) -> EventClassification:
        if set(self.probabilities) != set(EventCategory):
            raise ValueError("probabilities must cover every EventCategory exactly once")
        if any(p < 0 or p > 1 for p in self.probabilities.values()):
            raise ValueError("probabilities must be in [0, 1]")
        if not math.isclose(sum(self.probabilities.values()), 1.0, abs_tol=_PROB_TOL):
            raise ValueError("event probabilities must sum to 1")
        if self.category != max(self.probabilities, key=self.probabilities.__getitem__):
            raise ValueError("category must be the arg-max of probabilities")
        return self

    @property
    def confidence(self) -> float:
        return self.probabilities[self.category]


class ImpactDriver(ContractModel):
    """One contribution to the impact estimate. Explains the model, not economic causation."""

    feature: str
    contribution: float
    note: str = ""
    value: float | None = Field(default=None, description="the feature's value, if it has one")


class ImpactAssessment(ContractModel):
    """Market-response *proxy* on a 1-10 scale (never a probability of loss).

    From the placeholder heuristic only ``score``/``raw``/``drivers`` are filled. From the trained model the
    rest is filled too: the continuous prediction, what comparable past events realised, and attributions.
    """

    score: int = Field(ge=1, le=10)
    raw: float = Field(ge=0, le=1, description="continuous, pre-quantisation output")
    drivers: list[ImpactDriver] = Field(default_factory=list)
    quantisation: str = "ceil(raw * 10), min 1"
    scope: str | None = Field(default=None, description="ISSUER | MARKET; null for the heuristic")
    predicted_severity: float | None = Field(
        default=None, ge=0, description="predicted |z|: the two-session abnormal move, in sigma units")
    comparable_events: int | None = Field(
        default=None, ge=0, description="out-of-fold historical ticker-sessions in this score bucket")
    score_low: int | None = Field(default=None, ge=1, le=10, description="10th pct of the score realised")
    score_high: int | None = Field(default=None, ge=1, le=10, description="90th pct of the score realised")
    realised_severity_low: float | None = Field(default=None, ge=0, description="their 10th percentile |z|")
    realised_severity_median: float | None = Field(default=None, ge=0)
    realised_severity_high: float | None = Field(default=None, ge=0, description="their 90th percentile |z|")
    p_extreme: float | None = Field(
        default=None, ge=0, le=1, description="share that realised an extreme move (score >= 7)")
    driver_basis: str | None = Field(
        default=None, description="units of the driver contributions, and how they add up to the prediction")


class CorroboratingSource(ContractModel):
    source: str
    source_type: SourceType
    published_at: datetime
    headline: str
    url: str | None = None
    relation: str = Field(default="SAME_EVENT", description="DedupRelation of this report to the signal")

    aware_check = field_validator("published_at")(_require_aware)


class Evidence(ContractModel):
    """Observable corroboration facts. Reported as separate qualifiers, never one blended score."""

    source_count: int = Field(ge=1)
    unique_domain_count: int = Field(ge=1)
    recent_mention_count: int = Field(ge=0)
    coverage_velocity: float = Field(ge=0, description="mentions per hour over the recent window")
    novelty_score: float = Field(ge=0, le=1)
    model_confidence: float = Field(ge=0, le=1)
    contradicted_by: list[str] = Field(
        default_factory=list, description="signal ids that report the opposite narrative"
    )
    corroborating: list[CorroboratingSource] = Field(default_factory=list)


class ModelVersions(ContractModel):
    sentiment: str
    event: str
    impact: str | None
    entity_resolver: str
    feature_schema: str = "1"


class RiskSignal(ContractModel):
    """The product's central object: one normalised, auditable signal per accepted document."""

    id: str = Field(min_length=1)
    document: RawDocument
    entity: EntityMention
    sentiment: SentimentResult
    event: EventClassification
    impact: ImpactAssessment | None
    evidence: Evidence
    status: SignalStatus
    status_reason: str | None = None
    data_origin: DataOrigin
    model_versions: ModelVersions
    created_at: datetime
    provenance: SignalProvenance | None = Field(
        default=None, description="present for signals built from real/replayed sources"
    )

    aware_check = field_validator("created_at")(_require_aware)

    @model_validator(mode="after")
    def _partial_has_no_impact(self) -> RiskSignal:
        if self.status is SignalStatus.PARTIAL and self.impact is not None:
            raise ValueError("a PARTIAL signal must not carry an impact score")
        if self.status is SignalStatus.COMPLETE and self.impact is None:
            raise ValueError("a COMPLETE signal requires an impact score")
        if self.status is SignalStatus.PARTIAL and not self.status_reason:
            raise ValueError("a PARTIAL signal must explain why")
        return self
