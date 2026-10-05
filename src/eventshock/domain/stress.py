"""Stress-test result contracts (PRD §12 stress-test card + audit panel)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .enums import (
    AssetClass,
    DataOrigin,
    RiskFactor,
    RunMode,
    ShockScope,
    StressStatus,
)


class AppliedShock(ContractModel):
    """A scenario shock after severity scaling and entity binding."""

    factor: RiskFactor
    scope: ShockScope
    base_value: float
    scaled_value: float
    applicable: bool = Field(description="False when the scope needs an entity the signal lacks")
    not_applicable_reason: str | None = Field(
        default=None, description="why the shock was skipped, in terms of what the event is about")
    rationale: str = ""


class PositionShock(ContractModel):
    factor: RiskFactor
    scope: ShockScope
    value: float


class PositionResult(ContractModel):
    asset_id: str
    name: str
    asset_class: AssetClass
    entity_id: str
    sector: str
    baseline_value: float
    stressed_value: float
    delta: float
    delta_pct: float
    shocks: list[PositionShock]
    by_factor: dict[RiskFactor, float]
    formula: str


class Contribution(ContractModel):
    key: str
    label: str
    baseline_value: float
    delta: float
    share_of_loss: float | None = Field(
        description="delta / total delta; None when the total change is zero"
    )


class Contributions(ContractModel):
    by_asset_class: list[Contribution]
    by_sector: list[Contribution]
    by_entity: list[Contribution]
    by_factor: list[Contribution]
    top_positions: list[Contribution]


class StressSummary(ContractModel):
    baseline_value: float
    stressed_value: float
    pnl: float
    pnl_pct: float


class UncoveredExposure(ContractModel):
    asset_count: int
    market_value: float
    share_of_portfolio: float
    asset_ids: list[str]


class SeverityScaling(ContractModel):
    impact_used: float
    reference_impact: float
    min_scale: float
    max_scale: float
    raw_ratio: float
    scale: float
    formula: str


class ScenarioRef(ContractModel):
    id: str
    version: str
    name: str
    category: str
    illustrative: bool


class StressAudit(ContractModel):
    mode: RunMode
    data_origin: DataOrigin
    engine_version: str
    scenario_version: str | None
    portfolio_id: str
    portfolio_hash: str
    threshold: float
    forced: bool
    impact_overridden: bool
    impact_origin: str | None = Field(
        default=None, description="MODEL | PLACEHOLDER: what produced the impact this run used")
    impact_lifecycle: str | None = Field(
        default=None, description="lifecycle of the trained impact model for this signal (null: heuristic)")
    scope_level: str | None = Field(
        default=None, description="what the signal is about (COMPANY | SECTOR | MARKET | UNRESOLVED), which decides the shocks that bind")
    scope_note: str | None = Field(default=None, description="what that means for which shocks applied")
    severity_basis: str | None = Field(
        default=None, description="SCORECARD when the severity score of the risk assessment drove the trigger (null: the signal's own impact)")
    severity_version: str | None = Field(default=None, description="version of the hybrid weights that produced the score")
    assessed_sector: str | None = Field(
        default=None, description="a sector taken from the assessment (not the vocabulary scope) that sector shocks were bound to")
    extraction_mode: str | None = Field(default=None, description="LLM | RULES: what read the text behind the severity score")
    calculated_at: datetime
    calculation: str = "deterministic engine (no model, no randomness)"


class StressResult(ContractModel):
    run_id: str
    status: StressStatus
    reason: str | None = None
    signal_id: str
    scenario: ScenarioRef | None = None
    severity: SeverityScaling | None = None
    shocks: list[AppliedShock] = Field(default_factory=list)
    summary: StressSummary | None = None
    positions: list[PositionResult] = Field(default_factory=list)
    contributions: Contributions | None = None
    uncovered: UncoveredExposure | None = None
    audit: StressAudit
