"""Contracts of the event-intelligence layer.

Everything here is *derived* from a ``RiskSignal`` (and the signals around it) and is never stored on one, so the replay digests, the
fixtures and the golden stress run stay valid. Each section carries its own ``availability`` and, when it cannot answer, the reason:
abstention is a first-class result, never a guessed value. Evidence about an event (how many independent sources, how fast the story
spreads, whether reports disagree, where it is in its life) is kept apart from the model's confidence and from the severity score.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from ..assessment.model import Conflict
from ..domain.base import ContractModel
from ..services.relevance import PortfolioRelevance

VERSION = "intelligence-v1"


class Availability(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"  # some of the section could be stated; `reason` says what could not
    ABSTAINED = "ABSTAINED"  # the evidence does not support an answer (a finding, not a failure)
    UNAVAILABLE = "UNAVAILABLE"  # the input needed does not exist (an untrusted clock, no layer running)


# ------------------------------------------------------------------------------------------------------------------------ scope
class ScopeType(StrEnum):
    COMPANY = "COMPANY"
    INDUSTRY = "INDUSTRY"
    SECTOR = "SECTOR"
    GEOGRAPHY = "GEOGRAPHY"
    MACRO = "MACRO"
    MARKET = "MARKET"
    THEME = "THEME"  # a risk-factor theme: credit stress, trade and conflict, currencies and commodities
    UNRESOLVED = "UNRESOLVED"


class ResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"  # the subject is named by a company match or by enough vocabulary evidence
    PARTIAL = "PARTIAL"  # a weaker subject (one sector term, a region only, the event class alone)
    AMBIGUOUS = "AMBIGUOUS"  # several equally supported subjects: none is chosen over the others
    UNRESOLVED = "UNRESOLVED"  # nothing defensible: kept as reported, not guessed about


class ConfidenceTier(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class ScopeNode(ContractModel):
    type: ScopeType
    value: str
    basis: str = Field(description="how this level is known: ENTITY_RESOLVER | ENTITY_MASTER | TICKER_MAP | VOCABULARY | EVENT_MODEL | HIERARCHY_ROOT")


class ScopeEvidenceSpan(ContractModel):
    dimension: str = Field(description="company | industry | sector | theme | region | event_class")
    term: str
    quote: str | None = Field(default=None, description="the term as it appears in the text; null when it cannot be located (folded match)")
    start: int | None = Field(default=None, ge=0, description="character offset into the analysed text (headline, then body)")
    end: int | None = Field(default=None, ge=0)


class ScopeConfidence(ContractModel):
    tier: ConfidenceTier
    basis: str
    measured: str | None = Field(
        default=None, description="what a sector-vocabulary check measured for this tier (docs/evidence/scope_eval.json), if anything was")


class EventScope(ContractModel):
    scope_type: ScopeType
    scope_value: str | None = Field(description="the name of the subject; null when UNRESOLVED")
    scope_path: list[ScopeNode] = Field(description="the hierarchy, most specific first, ending at MARKET. A level without evidence is omitted, never filled.")
    scope_confidence: ScopeConfidence = Field(description="a rule tier, not a probability")
    scope_evidence: list[ScopeEvidenceSpan]
    resolution_status: ResolutionStatus
    candidates: list[str] = Field(default_factory=list, description="the tied subjects, when AMBIGUOUS")
    secondary: list[ScopeNode] = Field(default_factory=list, description="other subjects the text also points to (regions, themes)")
    reason: str = Field(description="in plain words why the scope is what it is; always set when it is not RESOLVED")
    resolver_version: str


# ----------------------------------------------------------------------------------------------------------------- the event
class ReportRef(ContractModel):
    """One report of an event, kept individually beneath the event."""

    id: str = Field(description="the document id when known")
    signal_id: str
    source: str
    source_type: str
    domain: str
    url: str | None = None
    published_at: datetime
    headline: str
    relation: str = Field(description="CANONICAL | SAME_EVENT | NEAR_DUPLICATE | SYNDICATED: how it relates to its cluster's first report")
    independent: bool = Field(description="a distinct outlet reporting for itself: a copy of another outlet's text is not")
    clock_trusted: bool
    phase: str = Field(description="BEFORE_REPORT | AT_REPORT | AFTER_REPORT relative to the report this view is about")


class EventGroup(ContractModel):
    event_id: str
    anchor_signal_id: str = Field(description="the earliest report's signal: the event is anchored to it")
    signal_ids: list[str] = Field(description="the report clusters (signals) grouped into this event")
    headline: str
    report_count: int = Field(description="distinct reports, copies included")
    independent_sources: int
    first_seen: datetime | None
    last_seen: datetime | None
    reports: list[ReportRef]
    grouping_note: str


# --------------------------------------------------------------------------------------------------------------------- evidence
class ModelConfidenceItem(ContractModel):
    stage: str = Field(description="event | sentiment | impact")
    value: float | None = Field(default=None, ge=0, le=1)
    basis: str
    status: str = Field(description="what the stage is: a trained model, a placeholder, or abstaining")


class EvidenceStrength(ContractModel):
    tier: str = Field(description="STRONG | MODERATE | WEAK | INSUFFICIENT: how much independent evidence there is that this happened")
    rule: str = Field(description="the rule that fired")
    reasons: list[str]
    components: dict[str, float | int | str | bool | None]


class EvidenceProfile(ContractModel):
    availability: Availability
    reason: str | None = None
    source_count: int = Field(description="reports, copies included")
    independent_sources: int
    unique_domains: int
    source_diversity: float | None = Field(description="independent sources / reports; null with no reports")
    syndicated_copies: int
    authoritative_sources: int
    authoritative_supported: bool = Field(description="false when no source of the event is on the known-authoritative list (so 0 is 'not known', not 'none')")
    authoritative_domains: list[str]
    first_observed: datetime | None
    latest_observed: datetime | None
    entity_confidence: float | None = Field(description="the entity resolver's link confidence; null with no company")
    entity_basis: str
    scope_confidence: ConfidenceTier
    model_confidence: list[ModelConfidenceItem]
    evidence_strength: EvidenceStrength
    source_disagreement: str = Field(description="NONE | POSSIBLE | CONFLICTED | RESOLVED: from claim contradiction, never from sentiment spread")
    note: str = Field(default="Evidence strength says how well the event is corroborated. Model confidence says how sure a model is of its own output. They are different questions and are never combined.")


# -------------------------------------------------------------------------------------------------------------------- novelty
class PriorEvent(ContractModel):
    event_id: str
    signal_id: str
    headline: str
    first_seen: datetime
    last_seen: datetime
    similarity: float = Field(ge=0, le=1)
    same_event_class: bool
    lifecycle_then: str | None = Field(description="the earlier event's lifecycle state when this one began")


class NoveltyAssessment(ContractModel):
    availability: Availability
    reason: str | None = None
    label: str = Field(description="NEW | CONTINUATION | UPDATE | RECURRING | UNKNOWN")
    rule: str
    novelty_score: float = Field(ge=0, le=1, description="the pipeline's score (1 / (1 + log2(1 + earlier clusters of the same issuer in 72 h))): unchanged and unrelated to the label")
    novelty_measured: bool
    nearest_prior: list[PriorEvent]
    narrative_match: bool | None = Field(description="the nearest earlier event is the same narrative (same class, similar wording); null when nothing was comparable")
    new_information: list[str] = Field(description="numbers and names in this event that the nearest earlier event did not carry")
    continuation_indicators: list[str]
    recurrence_cues: list[str]


# ------------------------------------------------------------------------------------------------------------------- velocity
class VelocityPoint(ContractModel):
    at: datetime
    independent_sources: int = Field(description="cumulative")
    reports: int = Field(description="cumulative")


class VelocityView(ContractModel):
    availability: Availability
    reason: str | None = None
    series: list[VelocityPoint]
    window_start: datetime | None
    window_end: datetime | None
    window_hours: float | None
    source_growth: str | None = Field(description="e.g. '2 → 11 independent sources'")
    velocity_per_hour: float | None = Field(description="independent sources added per hour over the window")
    acceleration: float | None = Field(description="change in that rate between the two halves of the window, per hour; null when the data are too thin")
    acceleration_reason: str | None = None
    note: str = "Velocity is evidence of how a story spreads. It is not an input to the severity score."


# ------------------------------------------------------------------------------------------------------------ claims, conflicts
class EvidenceQuote(ContractModel):
    quote: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class Claim(ContractModel):
    id: str
    report_id: str
    signal_id: str
    source: str
    published_at: datetime
    axis: str
    predicate: str = Field(description="the axis this claim is about (confirmation, status, deal, operations, guidance, approval)")
    verb: str = Field(description="the cue as written")
    polarity: str = Field(description="the pole asserted, e.g. 'confirmed' or 'denied'")
    subject: str | None
    object: str | None
    attributed: bool = Field(description="hedged or second-hand ('reportedly', 'according to')")
    evidence_span: EvidenceQuote
    full_text: bool = Field(description="true when read from the report's headline and body; false when only its headline was kept")


class ConflictState(StrEnum):
    NO_CONFLICT = "NO_CONFLICT"
    POSSIBLE_CONFLICT = "POSSIBLE_CONFLICT"
    CONFLICTED = "CONFLICTED"
    RESOLVED_CONFLICT = "RESOLVED_CONFLICT"


class ClaimConflict(ContractModel):
    id: str
    axis: str
    axis_label: str
    state: ConflictState
    side_a: Claim
    side_b: Claim
    shared_topic: list[str]
    hours_apart: float | None
    reason: str
    resolved_by: Claim | None = None
    resolution: str | None = None


class ContradictionView(ContractModel):
    availability: Availability
    reason: str | None = None
    state: ConflictState
    claims_extracted: int
    conflicts: list[ClaimConflict]
    sequential_changes: list[ClaimConflict] = Field(description="opposite claims too far apart to contradict: a change of state over time")
    tone_divergence: Conflict | None = Field(default=None, description="a report on the same issuer with the opposite tone: shown for context, NOT a contradiction")
    method: str


# -------------------------------------------------------------------------------------------------------------------- lifecycle
class LifecycleState(StrEnum):
    DEVELOPING = "DEVELOPING"
    CONFIRMED = "CONFIRMED"
    ESCALATING = "ESCALATING"
    STABILIZING = "STABILIZING"
    RESOLVED = "RESOLVED"
    STALE = "STALE"


class LifecycleTransition(ContractModel):
    at: datetime
    from_state: LifecycleState | None
    to_state: LifecycleState
    rule: str
    rule_text: str
    evidence_report_ids: list[str]
    evidence_quote: str | None = None


class LifecycleView(ContractModel):
    availability: Availability
    reason: str | None = None
    state: LifecycleState | None
    since: datetime | None
    first_seen: datetime | None
    last_updated: datetime | None
    as_of: datetime | None
    as_of_basis: str = Field(description="NOW | LAST_REPORT (replay: the state at the last report, not at the snapshot end) | REQUESTED")
    transitions: list[LifecycleTransition]
    note: str = "State follows explicit evidence (independent sources, cue phrases in reports, elapsed time without a report). A fall in news volume is never read as resolution."


# --------------------------------------------------------------------------------------------------- affected, relevance, stress
class AffectedEntity(ContractModel):
    name: str
    kind: str
    role: str
    resolved: bool
    entity_id: str | None = None
    ticker: str | None = None
    origin: str = Field(description="RULES | AI | DATA: who identified it")


class AffectedSector(ContractModel):
    sector: str
    origin: str
    basis: str


class AffectedRiskFactor(ContractModel):
    factor: str
    origin: str = Field(description="VOCABULARY (a theme the text names) | SCENARIO (a shock the default scenario applies): an assumption, never a measured exposure")
    basis: str


class AffectedView(ContractModel):
    entities: list[AffectedEntity]
    sectors: list[AffectedSector]
    regions: list[str]
    risk_factors: list[AffectedRiskFactor]
    note: str


class StressPreview(ContractModel):
    availability: Availability
    status: str | None = Field(default=None, description="a StressStatus: COMPLETED | NOT_TRIGGERED | NO_SCENARIO | UNAVAILABLE | NOT_APPLICABLE")
    reason: str | None = None
    scenario_id: str | None = None
    scenario_name: str | None = None
    severity_score: int | None = None
    trigger_threshold: float | None = None
    baseline_value: float | None = None
    stressed_value: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
    run_id: str | None = None
    note: str = "A modeled outcome under a configured, illustrative scenario: not a forecast."


class Abstention(ContractModel):
    field: str
    state: str = Field(description="UNKNOWN | UNAVAILABLE | NOT_APPLICABLE | NOT_TRIGGERED | ABSTAINED")
    reason: str


class IntelligenceProvenance(ContractModel):
    channel: str = Field(description="REPLAY | LIVE | MANUAL")
    adapter: str
    timestamp_origin: str
    clock_trusted: bool
    content_sha256: str
    snapshot_id: str | None


class EventHeadline(ContractModel):
    headline: str
    event_type: str | None = Field(description="the assessed event class id (or NO_EVENT); the trained model's class when no assessment ran")
    event_label: str | None
    event_subtype_label: str | None
    event_status: str
    sentiment: float
    sentiment_label: str | None
    severity_score: int | None
    severity_band: str | None
    impact_score: int | None = Field(description="the trained/placeholder impact stage's score, a separate quantity from severity")
    impact_origin: str | None
    extraction_mode: str | None


class EventIntelligence(ContractModel):
    signal_id: str
    version: str
    as_of: datetime
    as_of_basis: str
    event: EventHeadline
    group: EventGroup
    provenance: IntelligenceProvenance
    scope: EventScope
    evidence: EvidenceProfile
    novelty: NoveltyAssessment
    velocity: VelocityView
    contradiction: ContradictionView
    lifecycle: LifecycleView
    affected: AffectedView
    relevance: PortfolioRelevance | None
    stress: StressPreview
    abstentions: list[Abstention]
    labels: list[str] = Field(description="what kind of number or statement each section is")
    limitations: list[str]
