"""Request/response models that are API-specific (domain objects are returned directly otherwise)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..assessment.model import RiskAssessment
from ..domain import (
    Entity,
    EventCategory,
    EventStatus,
    RiskSignal,
    RunMode,
    Scenario,
    SignalStatus,
    SourceType,
)
from ..domain.base import ContractModel


class StressRequest(BaseModel):  # request body: defaults stay optional for clients
    signal_id: str
    scenario_id: str | None = Field(default=None, description="defaults to the category's template")
    force: bool = Field(default=False, description="run as a what-if even below the trigger threshold")
    impact_override: float | None = Field(
        default=None, ge=1, le=10, description="what-if impact (requires force=true)"
    )
    portfolio_id: str | None = Field(
        default=None, description="a saved personal portfolio to stress; absent or 'default' = the synthetic wholesale book")


class SignalSummary(ContractModel):
    """Compact feed row (the feed does not need evidence arrays or drivers)."""

    id: str
    headline: str
    source: str
    source_type: SourceType
    published_at: datetime
    entity_id: str
    entity_name: str | None
    ticker: str | None
    sector: str | None
    category: EventCategory
    event_status: EventStatus = Field(
        description="CLASSIFIED: `category` is a finding; otherwise it is only a best guess")
    sentiment_score: float
    impact_score: int | None
    impact_origin: str | None = Field(
        default=None, description="MODEL | PLACEHOLDER: what produced impact_score")
    impact_lifecycle: str | None = Field(default=None, description="lifecycle of the impact model, if used")
    impact_score_low: int | None = None
    impact_score_high: int | None = None
    status: SignalStatus
    source_count: int
    data_origin: str
    scope_level: str = Field(description="COMPANY | SECTOR | MARKET | UNRESOLVED: what the signal is about")
    scope_sector: str | None = None
    scope_strength: str | None = Field(default=None, description="STRONG | WEAK for a SECTOR scope (a rule tier, not a probability)")
    scope_themes: list[str] = Field(default_factory=list)
    scope_regions: list[str] = Field(default_factory=list)
    channel: str = Field(description="REPLAY | LIVE | MANUAL: which door the signal came through")
    first_seq: int | None = Field(default=None, description="live overlay change counter when it first appeared (null for replay)")
    updated_seq: int | None = Field(default=None, description="…and when it last changed (more reports, rebuilt)")
    relevance_level: str = Field(description="DIRECT | SECTOR | MARKET_WIDE | NONE | UNDETERMINED: how the book is reached")
    relevance_share: float | None = Field(default=None, description="share of the book the most specific slice covers")
    relevance_band: str = Field(default="UNDETERMINED", description="NONE | LOW | MEDIUM | HIGH | UNDETERMINED display band on relevance_share; separate from severity")
    severity_score: int | None = Field(
        default=None, description="the headline score: the transparent hybrid severity (1-10) from the risk assessment; null when the text is not a market event or no assessment ran")
    severity_low: int | None = None
    severity_high: int | None = None
    severity_basis: str | None = Field(default=None, description="SCORECARD: anchored rubric answers and a fixed matrix, not a trained model, not validated")
    severity_band: str | None = Field(default=None, description="negligible | low | moderate | high | extreme")
    severity_band_label: str | None = None
    severity_ai_effect: int | None = Field(default=None, description="score minus the rules-only score: what the AI's bounded adjustments changed")
    assessed_category: str | None = Field(default=None, description="the event class the assessment reads (an EventCategory id or NO_EVENT)")
    assessed_sector: str | None = Field(default=None, description="the first sector the assessment reads from the text")
    extraction_mode: str | None = Field(default=None, description="LLM | RULES: what read the text")
    above_trigger: bool | None = Field(default=None, description="severity_score meets the automatic stress trigger")


class SignalPage(ContractModel):
    total: int
    seq: int = Field(description="the live overlay's change counter at the time of the response")
    items: list[SignalSummary]


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000, description="a headline, a short post, or the opening of an article")
    source_type: SourceType = SourceType.NEWS
    published_at: datetime | None = Field(
        default=None, description="when it was published (with a time zone); omitted = the moment of the request")
    source: str | None = Field(
        default=None, max_length=80, description="where the text came from (an outlet or account name); omitted = 'manual paste'")


class Rejection(ContractModel):
    code: str
    detail: str


class AnalyzeResponse(ContractModel):
    outcome: str = Field(description="NEW | UPDATED (joined an existing story) | DUPLICATE (already analysed) | QUARANTINED (not scorable)")
    signal_id: str | None
    signal: SignalSummary | None
    rejection: Rejection | None
    headline: str = Field(description="the part of the text read as the headline")
    analysed_chars: int
    truncated: bool
    notes: list[str]
    assessment: RiskAssessment | None = Field(
        default=None, description="the structured reading, severity, threshold state and caveats; null when the text was quarantined")


class ScenarioWithDefault(ContractModel):
    scenario: Scenario
    is_default_for: EventCategory


class ScenarioList(ContractModel):
    version: str
    default_by_category: dict[EventCategory, str]
    scenarios: list[Scenario]


class TaxonomyItem(ContractModel):
    id: EventCategory
    label: str
    description: str
    default_scenario: str


class ReplayInfo(ContractModel):
    """Present when the app serves a replay snapshot of real sources (profile=replay)."""

    snapshot_id: str
    description: str
    window_start: datetime
    window_end: datetime
    output_digest: str
    pipeline_version: str
    stage_origins: dict[str, str]
    sources: list[str]


class ImpactStatus(ContractModel):
    """What the impact stage is in this running app, derived from the loaded card (never hard-coded copy)."""

    mode: str = Field(description="MODEL (a trained model scores what it can) | PLACEHOLDER (heuristic only)")
    model_id: str | None
    scopes: dict[str, str] = Field(default_factory=dict, description="scope -> lifecycle of the model for it")
    served_scopes: list[str] = Field(default_factory=list)
    reason: str | None = Field(default=None, description="why the app is on the heuristic, when it is")


class LLMInfo(ContractModel):
    """How new text is read right now. ``mode`` is RULES when no language model is configured or it has no key: the app still works."""

    mode: str = Field(description="LLM | RULES")
    enabled: bool = Field(description="the language model is switched on (EVENTSHOCK_LLM)")
    model: str | None = None
    reason: str | None = Field(default=None, description="why the app is in RULES mode, when it is")
    llm_calls: int = 0
    cache_hits: int = 0
    fallbacks: int = 0
    last_fallback_reason: str | None = None
    sends_text_off_machine: bool = Field(description="true only in LLM mode: the report text goes to the model provider")


class Capabilities(ContractModel):
    analyze: bool = Field(description="POST /api/analyze is available (needs the replay profile's models)")
    live_enabled: bool = Field(description="a live source is configured and polling")
    assessment: bool = Field(default=False, description="the risk-assessment endpoints are available (replay profile)")
    llm: LLMInfo | None = Field(default=None, description="how new text is read; null where there is no assessment layer")
    analogues: bool = Field(default=False, description="historical analogues are served (an index is installed); GET /api/signals/{id}/analogues")
    history_check: bool = Field(default=False, description="scenario shocks can be ranked against history; GET /api/scenarios/{id}/history-check")
    custom_portfolios: bool = Field(default=True, description="optional personal portfolios can be created and used instead of the synthetic default; /api/portfolios")


class Meta(ContractModel):
    app: str
    version: str
    mode: RunMode
    profile: str
    data_origin: str
    replay: ReplayInfo | None
    as_of: datetime
    trigger_threshold: float
    base_currency: str
    signal_count: int
    asset_count: int
    scenario_set_version: str
    engine_version: str
    taxonomy: list[TaxonomyItem]
    notices: list[str]
    impact: ImpactStatus | None = Field(default=None, description="null for the demo-fixture profile")
    capabilities: Capabilities


class ExposureRow(ContractModel):
    key: str
    label: str
    market_value: float
    share: float
    asset_count: int


class PortfolioSummary(ContractModel):
    portfolio_id: str
    name: str
    description: str
    as_of: datetime
    base_currency: str
    total_value: float
    asset_count: int
    entity_count: int
    synthetic: bool = True
    kind: str = Field(default="DEFAULT", description="DEFAULT (the synthetic book) | USER (a saved personal portfolio)")


class PortfolioExposure(ContractModel):
    by_asset_class: list[ExposureRow]
    by_sector: list[ExposureRow]
    by_entity: list[ExposureRow]
    by_geography: list[ExposureRow]


class EntityList(ContractModel):
    entities: list[Entity]


__all__ = [
    "AnalyzeRequest", "AnalyzeResponse", "Capabilities", "LLMInfo", "Rejection",
    "EntityList", "ExposureRow", "Meta", "PortfolioExposure", "PortfolioSummary",
    "ReplayInfo", "RiskSignal", "ScenarioList", "ScenarioWithDefault", "SignalPage", "SignalSummary",
    "StressRequest", "TaxonomyItem",
]


# ------------------------------------------------------------ per-signal context (inputs + timeline)
class ContextInput(ContractModel):
    """One numeric input the impact model saw for this signal, with its family and availability class."""

    name: str = Field(description="the model's feature id")
    group: str = Field(description="the family the feature belongs to")
    availability: str = Field(
        description="a: known before the event | b: published at event time | "
                    "t: from the report's own text/timestamp or prices before it")
    value: float


class FilingMoment(ContractModel):
    """An SEC 8-K of the signal's issuer, placed relative to the report's own timestamp."""

    accession: str
    form: str
    items: list[str]
    acceptance_utc: datetime
    hours_from_report: float = Field(
        description="negative: accepted before the report; positive: at or after it")
    role: str = Field(
        description="FEEDS_MODEL: accepted before the report and read by a calendar feature | "
                    "BEFORE_NOT_USED: before the report, outside every feature window | "
                    "AFTER_REPORT: accepted at or after the report; the model never reads it")
    role_note: str
    known_at_assessment: bool = Field(
        description="accepted no later than the replay clock (the moment EventShock assessed the report)")


class RealisedOutcome(ContractModel):
    """What the market actually did after the report. Known only after the fact; never a model input."""

    scope: str = Field(description="ISSUER: the issuer's own abnormal move | MARKET: the S&P 500's move")
    ticker: str | None
    session: str = Field(description="reaction session the move is measured from (ISO date)")
    window_sessions: int
    abs_z: float = Field(description="size of the move in units of its usual volatility (the model's target)")
    z: float = Field(description="signed move; direction is observed here but never predicted")
    score: int = Field(description="the same 1-10 scale the prediction is stated on")
    note: str


class SignalContext(ContractModel):
    signal_id: str
    report_time: datetime
    timestamp_origin: str
    assessed_at: datetime = Field(description="the replay clock: the moment the signal was assessed")
    impact_scored: bool
    inputs: list[ContextInput] = Field(description="empty unless a trained model scored the impact")
    missing_inputs: list[str]
    not_used: list[str] = Field(description="things that exist but are deliberately not model inputs")
    filings: list[FilingMoment]
    filings_note: str | None = Field(description="why there are no filings to show, when there are none")
    outcome: RealisedOutcome | None
    outcome_note: str
