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
    MODEL = "MODEL"  # reserved for later stages


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
