"""Contracts of the live monitor and event memory. Everything here is *derived* from signals and the existing side-cars and is never stored on a ``RiskSignal``.

An *event state* is what EventShock believed about one event at one moment (its severity, lifecycle, evidence tier, conflict, how much of the book it reaches, the
modeled stress). A *risk change* is the difference between two states of the same event, with the rule that detected it and the reports that support it. The
monitor never creates a second risk for a second article about the same event: articles belong to the event the grouping assigned them to, and a new article
is an update of that event (or nothing, when it is a copy).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from ..decision.models import ProvenanceRef
from ..domain.base import ContractModel

VERSION = "monitor-v1"

RANK_EVIDENCE = {"INSUFFICIENT": 0, "WEAK": 1, "MODERATE": 2, "STRONG": 3}
RANK_MATERIALITY = {"UNDETERMINED": -1, "NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
OPEN_CONFLICT = ("POSSIBLE_CONFLICT", "CONFLICTED")


class ChangeType(StrEnum):
    NEW_EVENT = "NEW_EVENT"
    EVENT_UPDATED = "EVENT_UPDATED"
    EVENT_ESCALATED = "EVENT_ESCALATED"
    EVENT_DE_ESCALATED = "EVENT_DE_ESCALATED"
    EVIDENCE_STRENGTHENED = "EVIDENCE_STRENGTHENED"
    EVIDENCE_WEAKENED = "EVIDENCE_WEAKENED"
    CONFLICT_APPEARED = "CONFLICT_APPEARED"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"
    PORTFOLIO_EXPOSURE_CHANGED = "PORTFOLIO_EXPOSURE_CHANGED"
    STRESS_CHANGED = "STRESS_CHANGED"
    LIFECYCLE_CHANGED = "LIFECYCLE_CHANGED"


class UpdateKind(StrEnum):
    NEW_EVENT = "NEW_EVENT"
    CONTINUATION = "CONTINUATION"
    UPDATE = "UPDATE"
    ESCALATION = "ESCALATION"
    DE_ESCALATION = "DE_ESCALATION"
    RESOLUTION = "RESOLUTION"


class Mode(StrEnum):
    REPLAY = "REPLAY"
    LIVE = "LIVE"


class EventState(ContractModel):
    """What EventShock held about one event at ``as_of``. Every field is read from an existing layer; none is computed here."""

    event_id: str
    anchor_signal_id: str
    lead_signal_id: str = Field(description="the report cluster of the event with the highest severity (then portfolio materiality, then earliest) at this moment")
    headline: str = Field(description="the lead report's headline")
    as_of: datetime
    tracked: bool = Field(description="severity or portfolio materiality reached the tracking floor in configs/decision.yaml")
    member_count: int = Field(description="report clusters (signals) of the event published by this moment")
    report_count: int
    independent_sources: int
    first_seen: datetime | None
    last_seen: datetime | None
    event_type: str | None
    scope_type: str
    scope_value: str | None
    severity: float | None = Field(description="the transparent 1-10 scorecard of the lead report; null when the text is not a market event")
    severity_band: str | None
    lifecycle: str | None = Field(description="DEVELOPING | CONFIRMED | ESCALATING | STABILIZING | RESOLVED | STALE; null when the clock is not trusted")
    evidence_tier: str = Field(description="INSUFFICIENT | WEAK | MODERATE | STRONG (how well corroborated; not model confidence)")
    conflict: str = Field(description="NO_CONFLICT | POSSIBLE_CONFLICT | CONFLICTED | RESOLVED_CONFLICT (claim contradiction, never tone)")
    velocity_per_hour: float | None
    portfolio_id: str | None
    materiality: str | None = Field(description="LOW | MEDIUM | HIGH | CRITICAL | NONE | UNDETERMINED (relevance to the book)")
    exposure_share: float | None = Field(description="share of the book the event reaches (0-1)")
    stress_status: str | None = Field(description="AVAILABLE | ABSTAINED | UNAVAILABLE for the generated scenario, then COMPLETED when it ran")
    stress_pnl_pct: float | None = Field(description="modeled P&L as a fraction of the book under the generated scenario: a simulation, not a forecast")
    stress_run_id: str | None
    clock_trusted: bool
    fingerprint: str = Field(description="hash of the fields a change is detected on; equal fingerprints mean no change")


FINGERPRINT_FIELDS = ("tracked", "member_count", "report_count", "independent_sources", "severity", "lifecycle", "evidence_tier", "conflict", "materiality",
                      "exposure_share", "stress_status", "stress_pnl_pct", "portfolio_id", "lead_signal_id")


def fingerprint_of(values: dict) -> str:
    """Stable hash of the fields a change is detected on (floats rounded so a recomputation never differs in the last bit)."""
    def norm(v: object) -> object:
        return round(v, 6) if isinstance(v, float) else v
    payload = json.dumps({k: norm(values.get(k)) for k in FINGERPRINT_FIELDS}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class FieldChange(ContractModel):
    field: str
    previous: str | float | int | bool | None
    current: str | float | int | bool | None


class SupportingEvidence(ContractModel):
    kind: str = Field(description="REPORT | LIFECYCLE_TRANSITION | CONFLICT | SCORE")
    text: str = Field(description="a report's headline, a transition's verbatim cue, or the claim that conflicts")
    at: datetime | None = None
    report_id: str | None = None
    signal_id: str | None = None
    source: str | None = None
    rule: str | None = None


class PortfolioImpact(ContractModel):
    portfolio_id: str | None
    materiality_previous: str | None
    materiality_current: str | None
    exposure_share_previous: float | None
    exposure_share_current: float | None
    stress_pnl_pct_previous: float | None
    stress_pnl_pct_current: float | None
    label: str = "Stress figures are a simulation under an illustrative scenario: not a prediction."


class RiskChange(ContractModel):
    change_id: str
    event_id: str
    change_type: ChangeType
    mode: Mode
    cycle: int | None = Field(description="REPLAY: the monitoring cycle that detected it; null in LIVE")
    at: datetime = Field(description="the clock of the cycle that detected it")
    headline: str
    summary: str
    rule: str = Field(description="the configured rule that fired, with its threshold")
    previous: EventState | None
    current: EventState
    changed_fields: list[FieldChange]
    supporting_evidence: list[SupportingEvidence]
    portfolio_impact: PortfolioImpact | None
    provenance: list[ProvenanceRef]


class ChangeDraft(ContractModel):
    """What the pure diff decides, before evidence and provenance are attached."""

    change_type: ChangeType
    rule: str
    summary: str
    fields: list[FieldChange]


class MonitorCycle(ContractModel):
    index: int
    at: datetime
    baseline: bool = Field(description="the first cycle: it records the starting states and reports no changes")


class MonitorStatus(ContractModel):
    version: str = VERSION
    mode: Mode
    available: bool
    state: str = Field(description="OK | DEGRADED | OFF | UNAVAILABLE: LIVE reflects the live feed; REPLAY is always OK when the replay is loaded")
    reason: str | None = None
    live_enabled: bool
    live_state: str | None
    live_source_mode: str | None
    replay_cycles: int
    replay_step_hours: float
    replay_first: datetime | None
    replay_last: datetime | None
    tracked_floor: str
    changes_logged: int
    labels: list[str]
    limitations: list[str]


class ChangeSet(ContractModel):
    version: str = VERSION
    mode: Mode
    availability: str = Field(description="AVAILABLE | UNAVAILABLE")
    reason: str | None = None
    portfolio_id: str | None
    cycle: int | None
    window: int
    from_at: datetime | None
    to_at: datetime | None
    tracked_events: int
    untracked_events: int
    excluded_untrusted_clock: int = Field(description="events whose report times were assigned by the replay: never placed on a timeline")
    truncated: bool
    changes: list[RiskChange]
    counts: dict[str, int]
    labels: list[str]
    limitations: list[str]


# --------------------------------------------------------------------------------------------------------------------------------- event memory
class MemoryItem(ContractModel):
    at: datetime | None
    kind: str = Field(description="REPORT | LIFECYCLE | EVIDENCE | SEVERITY | PORTFOLIO | STRESS | ASSESSMENT | OUTCOME")
    observation: str = Field(description="an ObservationKind: SOURCE_EVENT | EVENTSHOCK_ASSESSMENT | SCENARIO_ASSUMPTION | REALISED_OUTCOME | ...")
    label: str
    detail: str
    update_kind: UpdateKind | None = None
    rule: str | None = None
    signal_id: str | None = None
    report_id: str | None = None
    source: str | None = None
    independent: bool | None = None
    provenance: list[ProvenanceRef]


class HistoryPoint(ContractModel):
    cycle: int | None
    at: datetime
    severity: float | None
    lifecycle: str | None
    evidence_tier: str
    conflict: str
    materiality: str | None
    exposure_share: float | None
    stress_pnl_pct: float | None
    report_count: int
    independent_sources: int


class EventMemory(ContractModel):
    version: str = VERSION
    event_id: str
    anchor_signal_id: str
    headline: str
    availability: str = Field(description="AVAILABLE | PARTIAL | UNAVAILABLE")
    reason: str | None = None
    as_of: datetime | None
    mode: Mode
    portfolio_id: str | None
    clock_trusted: bool
    current: EventState | None
    items: list[MemoryItem]
    history: list[HistoryPoint] = Field(description="the event's state at each monitoring cycle: severity, relevance and stress history")
    update_counts: dict[str, int]
    signal_ids: list[str]
    labels: list[str]
    limitations: list[str]
