"""Contracts of the analyst review queue."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from ..domain.base import ContractModel
from ..monitor.digest import RankPart
from ..monitor.models import Mode

VERSION = "review-v1"
LABEL = "ANALYST REVIEW QUEUE: a triage list derived from existing signals. A decision here is a note: never ground truth, and it never changes a model, a score, a threshold or any served output"


class ReviewStatus(StrEnum):
    OPEN = "OPEN"
    REVIEWED = "REVIEWED"
    DISMISSED = "DISMISSED"


class ReasonCode(StrEnum):
    CONFLICTED_CLAIMS = "CONFLICTED_CLAIMS"
    UNRESOLVED_HIGH_SEVERITY = "UNRESOLVED_HIGH_SEVERITY"
    SINGLE_SOURCE_HIGH_SEVERITY = "SINGLE_SOURCE_HIGH_SEVERITY"
    MATERIAL_TO_BOOK = "MATERIAL_TO_BOOK"
    LARGE_STRESS_LOSS = "LARGE_STRESS_LOSS"
    ESCALATING = "ESCALATING"
    CHANGED_SINCE_REVIEW = "CHANGED_SINCE_REVIEW"


class ReviewReason(ContractModel):
    code: ReasonCode
    label: str
    detail: str = Field(description="the values that fired the rule, in words")


class RuleInfo(ContractModel):
    code: ReasonCode
    label: str
    rule: str = Field(description="the rule and its threshold, as configured in configs/decision.yaml")


class ReviewDecisionInput(ContractModel):
    event_id: str = Field(min_length=1, max_length=64, description="an event id (evt_...) or the id of any signal in it")
    status: ReviewStatus
    note: str | None = None
    analyst_id: str | None = None


class ReviewDecision(ContractModel):
    decision_id: str
    event_id: str
    status: ReviewStatus
    note: str | None
    analyst_id: str
    created_at: datetime
    fingerprint: str = Field(description="hash of the event's own evidence when it was decided (report count, sources, severity, lifecycle, evidence tier, conflict); a change reopens it")
    headline: str
    label: str = LABEL


class QueueItem(ContractModel):
    event_id: str
    signal_id: str
    headline: str
    scope_type: str
    scope_value: str | None
    severity: float | None
    severity_band: str | None
    materiality: str | None
    exposure_share: float | None
    independent_sources: int
    report_count: int
    evidence_tier: str
    conflict: str
    lifecycle: str | None
    stress_pnl_pct: float | None
    last_seen: datetime | None
    reasons: list[ReviewReason]
    rank_key: list[RankPart]
    status: ReviewStatus
    changed_since_review: bool = Field(description="it was reviewed or dismissed, and its evidence has changed since: it is open again")
    decision: ReviewDecision | None = Field(description="the latest decision on this event, if any")


class QueueCounts(ContractModel):
    open: int
    reviewed: int
    dismissed: int
    in_queue: int = Field(description="events with at least one reason, before any status filter")
    tracked_events: int = Field(description="events the monitor tracks at this moment (the pool the rules read)")


class ReviewQueue(ContractModel):
    version: str = VERSION
    label: str = LABEL
    mode: Mode
    availability: str = Field(description="AVAILABLE | UNAVAILABLE")
    reason: str | None = None
    as_of: datetime | None
    portfolio_id: str | None
    status_filter: str = Field(description="OPEN | REVIEWED | DISMISSED | ALL")
    counts: QueueCounts
    matching: int = Field(description="items matching the filter before the cap")
    items: list[QueueItem]
    ranking: str
    rules: list[RuleInfo]
    limitations: list[str]


class ReviewDecisionList(ContractModel):
    label: str = LABEL
    total: int
    items: list[ReviewDecision]
