"""Provenance of a signal built from real/replayed sources: where it came from and what the pipeline did."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import ContractModel


class TimestampOrigin(StrEnum):
    """How trustworthy ``published_at`` is. Only SOURCE-grade clocks are used to correlate documents."""

    SOURCE = "SOURCE"  # publisher-supplied publication time
    SOURCE_DATE_ONLY = "SOURCE_DATE_ONLY"  # publisher date without a time of day (stored as 00:00 UTC)
    GDELT_FIRST_SEEN = "GDELT_FIRST_SEEN"  # when GDELT first crawled the page (>= publication time)
    SYNTHETIC_REPLAY_CLOCK = "SYNTHETIC_REPLAY_CLOCK"  # the source has no time; replay assigned one


TRUSTED_TIMESTAMPS = frozenset(
    {TimestampOrigin.SOURCE, TimestampOrigin.SOURCE_DATE_ONLY, TimestampOrigin.GDELT_FIRST_SEEN})


class StageOrigin(StrEnum):
    """Who produced a stage's output. Lets the UI say plainly what is real and what is a stand-in."""

    SOURCE_LABEL = "SOURCE_LABEL"  # a human label that shipped with the source data
    PLACEHOLDER_RULES = "PLACEHOLDER_RULES"  # deterministic rules, not a trained model
    MODEL = "MODEL"  # a trained, versioned, evaluated model (see ``SentimentAudit`` / the model card)


class ImpactLifecycle(StrEnum):
    """How far the impact stage has got. The UI maps it to three words: a heuristic is *placeholder*,
    TRAINED and CALIBRATED are *experimental*, only PRODUCTION (all checks passed) is *validated*."""

    NOT_AVAILABLE = "NOT_AVAILABLE"  # no model artifact: the placeholder heuristic is all there is
    DATASET = "DATASET"  # a leak-checked dataset exists, nothing is fitted
    BASELINE = "BASELINE"  # only baselines exist, or none was beaten: the heuristic keeps serving, labelled
    TRAINED = "TRAINED"  # a fitted, chronologically evaluated model, not calibrated
    CALIBRATED = "CALIBRATED"  # fitted + calibrated score and uncertainty, but an acceptance check failed
    PRODUCTION = "PRODUCTION"  # fitted, calibrated, and every pre-registered acceptance check passed


class ImpactScope(StrEnum):
    ISSUER = "ISSUER"  # one resolved listed issuer: the target is its abnormal return
    MARKET = "MARKET"  # no listed issuer (macro / geopolitical): the target is the S&P 500's own excess move


class DedupRelation(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"  # same article/text from the same outlet; folded, not counted
    SYNDICATED = "SYNDICATED"  # identical text on another outlet
    NEAR_DUPLICATE = "NEAR_DUPLICATE"  # rewritten / lightly edited copy
    SAME_EVENT = "SAME_EVENT"  # different report of the same story (entity + time + wording overlap)


class EntityCandidate(ContractModel):
    entity_id: str
    entity_name: str
    matched_text: str
    rule: str
    confidence: float = Field(ge=0, le=1)


class RejectedCandidate(ContractModel):
    entity_id: str
    matched_text: str
    reason: str


class EntityAudit(ContractModel):
    """Why the entity is what it is — including what was considered and refused."""

    rule: str = Field(description="rule that decided the primary entity, or NONE")
    matched_text: str | None = None
    multi_entity: bool = False
    candidates: list[EntityCandidate] = Field(default_factory=list)
    rejected: list[RejectedCandidate] = Field(default_factory=list)
    unmatched_cashtags: list[str] = Field(default_factory=list)


class DedupMember(ContractModel):
    document_id: str
    source: str
    url: str | None = None
    relation: DedupRelation
    similarity: float = Field(ge=0, le=1)


class DedupAudit(ContractModel):
    cluster_id: str
    member_count: int = Field(ge=1, description="distinct reports in the cluster, canonical included")
    exact_duplicates_folded: int = Field(ge=0)
    members: list[DedupMember] = Field(default_factory=list)


class SentimentAudit(ContractModel):
    """Which trained model scored this signal's sentiment, and how far to trust this particular score."""

    model_id: str
    model_version: str
    artifact_sha256: str = Field(min_length=64, max_length=64, description="sha256 of the scoring artifact")
    confidence: float = Field(ge=0, le=1, description="largest calibrated class probability")
    calibrated: bool
    seen_in_training: bool = Field(
        description="the exact text (case, punctuation, URLs ignored) was in the model's train/valid data")


class EventAudit(ContractModel):
    """Which trained model classified this signal's event, and how far to trust this particular output."""

    model_id: str
    model_version: str
    artifact_sha256: str = Field(min_length=64, max_length=64, description="sha256 of the scoring artifact")
    confidence: float = Field(
        ge=0, le=1, description="calibrated P(top event class) among all nine classes, NONE included")
    no_event_probability: float = Field(ge=0, le=1)
    calibrated: bool
    unreliable_class: bool = Field(
        description="the model card flags the top class as unreliable (never asserted)")
    seen_in_training: bool = Field(
        description="the exact text (case, punctuation, URLs ignored) was in the model's training data")


class ImpactAudit(ContractModel):
    """Which trained impact model scored this signal, on what inputs, and how far to trust this score."""

    model_id: str
    model_version: str
    artifact_sha256: str = Field(min_length=64, max_length=64, description="sha256 of the scoring artifact")
    lifecycle: ImpactLifecycle
    scope: ImpactScope
    feature_schema: str
    calibrated: bool
    session: str = Field(description="the session the reaction is measured from: an ISO date, or NEXT")
    timing: str = Field(description="OFF_HOURS | PRE_OPEN | IN_SESSION | DATE_ONLY | FIRST_SEEN")
    timing_reliable: bool = Field(
        description="false for a first-seen crawl time, a date-only stamp, or an in-session report: "
                    "part of the move may precede the report, so the score is less trustworthy")
    market_context_as_of: str = Field(description="last session of the frozen market context used")
    inputs: dict[str, float] = Field(default_factory=dict, description="the numeric features the model saw")
    missing_inputs: list[str] = Field(
        default_factory=list, description="features absent at event time (the model handles them natively)")


class SignalProvenance(ContractModel):
    adapter: str
    snapshot_id: str
    record_ref: str = Field(description="file:line of the raw record in the snapshot")
    content_sha256: str = Field(description="sha256 of the raw record bytes")
    timestamp_origin: TimestampOrigin
    pipeline_version: str
    entity_audit: EntityAudit
    dedup: DedupAudit
    stage_origins: dict[str, str] = Field(description="stage -> StageOrigin")
    sentiment: SentimentAudit | None = Field(
        default=None, description="present when the sentiment stage is a trained model")
    event: EventAudit | None = Field(
        default=None, description="present when the event stage is a trained model")
    impact: ImpactAudit | None = Field(
        default=None, description="present when this signal's impact comes from the trained impact model")
    impact_note: str | None = Field(
        default=None, description="why the trained model did not score this (the labelled heuristic did)")
