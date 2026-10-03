"""Request/response models that are API-specific (domain objects are returned directly otherwise)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

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


class SignalPage(ContractModel):
    total: int
    items: list[SignalSummary]


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


class PortfolioExposure(ContractModel):
    by_asset_class: list[ExposureRow]
    by_sector: list[ExposureRow]
    by_entity: list[ExposureRow]
    by_geography: list[ExposureRow]


class EntityList(ContractModel):
    entities: list[Entity]


__all__ = [
    "EntityList", "ExposureRow", "Meta", "PortfolioExposure", "PortfolioSummary",
    "ReplayInfo", "RiskSignal", "ScenarioList", "ScenarioWithDefault", "SignalPage", "SignalSummary",
    "StressRequest", "TaxonomyItem",
]
