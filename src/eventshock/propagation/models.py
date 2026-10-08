"""Contracts of the propagation layer. All of it is *derived* from a signal and a portfolio and is never stored on a ``RiskSignal``.

Four things are kept apart everywhere: what is OBSERVED (a holding, a ticker's industry, a quoted phrase, a formula the engine applies), what is a SCENARIO
ASSUMPTION (a transmission edge, a shock size), what the USER adjusted, and what the stress engine computed from them (a modeled change, never a forecast).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from ..adjust.models import AdjustmentNotice
from ..domain import Scenario, StressResult
from ..domain.base import ContractModel
from ..intelligence.model import Availability
from ..portfolio.models import CrossTab, ExposureChain
from ..stress.history_check import ScenarioHistoryCheck

VERSION = "propagation-v1"
SCENARIO_LABEL = "SCENARIO SIMULATION — NOT A PREDICTION"
MAPPING_LABEL = "A mapping of how an event could reach holdings under stated assumptions. It is not causal inference."


class Status(StrEnum):
    OBSERVED = "OBSERVED"                        # a holding, a formula, a quoted phrase, a ticker's industry
    SCENARIO_ASSUMPTION = "SCENARIO_ASSUMPTION"  # a configured transmission edge or shock size: a judgement prior
    USER_ASSUMPTION = "USER_ASSUMPTION"          # a value the user adjusted or added


class MappingBasis(StrEnum):
    DIRECT_FACT = "DIRECT_FACT"            # the book holds the named issuer
    EVIDENCED_SCOPE = "EVIDENCED_SCOPE"    # a sector / industry / region the text or the entity master names, or a structural sensitivity to a factor the text is about
    ASSUMPTION_ONLY = "ASSUMPTION_ONLY"    # only a configured transmission edge reaches it
    NONE = "NONE"


# --------------------------------------------------------------------------------------------------------------------- graph
class GraphNode(ContractModel):
    id: str
    kind: str = Field(description="EVENT | SCOPE | SECTOR | INDUSTRY | GEOGRAPHY | RISK_FACTOR | ASSET_CLASS | PORTFOLIO | POSITION | STRESS_DRIVER")
    label: str
    detail: str | None = None
    value: float | None = Field(default=None, description="market value of the holdings the node stands for, when it stands for holdings")
    share: float | None = None


class GraphEdge(ContractModel):
    source: str
    target: str
    relationship: str = Field(description="EVIDENCED_BY | MEMBER_OF | ABOUT | SENSITIVE_TO | ASSUMED_TRANSMISSION | HELD_BY | DRIVES")
    rule_id: str = Field(description="the config key or rule that made this edge")
    basis: str = Field(description="the quoted evidence, the fact, or the assumption in words")
    status: Status
    weight: float | None = Field(default=None, description="a transmission edge's weight (positive hurts, negative benefits)")


class ActiveRiskFactor(ContractModel):
    id: str
    label: str
    modelled: str = Field(description="ENGINE | PROXY | NOT_MODELLED")
    origin: str = Field(description="TEXT (the text uses its vocabulary) | CATEGORY (assumed for this class of event)")
    status: Status
    evidence: list[str] = Field(default_factory=list, description="the phrases or themes that make it active")
    note: str | None = None


class ReachedHolding(ContractModel):
    asset_id: str
    name: str
    entity_id: str
    asset_type: str
    sector: str
    industry: str | None
    geography: str
    market_value: float
    share: float
    basis: MappingBasis
    routes: list[str] = Field(description="every rule that reaches it; the holding is counted once however many")


class PropagationGraph(ContractModel):
    signal_id: str
    version: str = VERSION
    availability: Availability
    reason: str | None = None
    portfolio_id: str
    portfolio_name: str
    event_category: str | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    active_factors: list[ActiveRiskFactor]
    reached: list[ReachedHolding]
    reached_value: float
    reached_share: float
    direct_share: float
    indirect_share: float
    evidenced_share: float
    assumed_share: float
    mapping_basis: MappingBasis
    not_reached: list[str] = Field(default_factory=list, description="mapped targets the book holds nothing in, in words")
    labels: list[str]
    limitations: list[str]
    adjustments: AdjustmentNotice | None = None


# ----------------------------------------------------------------------------------------------------------------- materiality
class MaterialityComponent(ContractModel):
    id: str
    label: str
    display: str
    value: float | str | None = None
    band: str | None = None
    detail: str


class MaterialityRule(ContractModel):
    kind: str = Field(description="GRID | BUMP | CAP")
    id: str
    fired: bool
    effect: str


class PortfolioMateriality(ContractModel):
    signal_id: str
    version: str = VERSION
    portfolio_id: str
    portfolio_name: str
    availability: Availability
    reason: str | None = None
    level: str = Field(description="LOW | MEDIUM | HIGH | CRITICAL; NONE when the book holds nothing the event reaches; UNDETERMINED when no defensible mapping exists")
    level_from_grid: str | None
    exposure_row: str | None
    severity_column: str | None
    components: list[MaterialityComponent]
    rules: list[MaterialityRule]
    why: list[str] = Field(description="Why is this event relevant to this portfolio? In order, in words")
    summary: str
    mapping_basis: MappingBasis
    reached_share: float
    labels: list[str]
    adjustments: AdjustmentNotice | None = None


# ------------------------------------------------------------------------------------------------------------------ scenario
class Gate(ContractModel):
    id: str
    label: str
    passed: bool
    detail: str


class ShockOrigin(ContractModel):
    factor: str
    scope: str
    sector: str | None
    source: str = Field(description="CATALOG_BASE (the catalog scenario's own shock) | PROPAGATED (written from a transmission edge) | USER (overridden size)")
    risk_factor: str | None
    status: Status
    base_value: float
    basis: str


class GeneratedScenario(ContractModel):
    signal_id: str
    version: str = VERSION
    label: str = SCENARIO_LABEL
    availability: Availability
    reason: str | None = Field(default=None, description="SCENARIO UNAVAILABLE: why, when it is")
    template: str | None
    template_label: str | None
    gates: list[Gate]
    can_force: bool = Field(default=False, description="only soft gates failed (severity, relevance, direction): the scenario below is a preview that can be run as a what-if")
    scenario: Scenario | None
    origins: list[ShockOrigin]
    history_check: ScenarioHistoryCheck | None = None
    portfolio_id: str
    adjustments: AdjustmentNotice | None = None


# ---------------------------------------------------------------------------------------------------------------- attribution
class AttributionRow(ContractModel):
    key: str
    label: str
    delta: float
    share_of_total: float | None = Field(description="delta / total change; null when the total is zero")
    baseline_value: float
    position_count: int
    detail: str | None = None


class AttributionTable(ContractModel):
    dimension: str
    label: str
    rows: list[AttributionRow]
    total: float = Field(description="the run's total modeled change")
    sum: float = Field(description="the rows added up")
    residual: float = Field(description="total - sum; within tolerance by construction")
    reconciled: bool


class StressAttribution(ContractModel):
    run_id: str
    version: str = VERSION
    portfolio_id: str
    total_pnl: float
    baseline_value: float
    pnl_pct: float
    headline: str
    drivers: AttributionTable
    tables: list[AttributionTable]
    tolerance: float
    reconciled: bool
    matrix: CrossTab | None = Field(default=None, description="sector by market factor: where each shock landed, both ways at once; adds up to the same total")
    note: str
    labels: list[str]


# -------------------------------------------------------------------------------------------------------------- concentration
class ConcentrationRow(ContractModel):
    key: str
    label: str
    value: float
    share: float
    position_count: int
    flagged: bool


class DimensionConcentration(ContractModel):
    dimension: str
    label: str
    rows: list[ConcentrationRow]
    item_count: int
    hhi: float
    effective_n: float
    top_share: float
    flagged: bool
    reason: str | None = None
    note: str | None = None


class ConcentrationView(ContractModel):
    portfolio_id: str
    portfolio_name: str
    version: str = VERSION
    total_value: float
    dimensions: list[DimensionConcentration]
    flags: list[str] = Field(description="only the concentration that is meaningful, in words")
    note: str
    adjustments: AdjustmentNotice | None = None


class OverlapEvent(ContractModel):
    signal_id: str
    event_id: str
    headline: str
    published_at: datetime | None
    materiality: str
    severity: float | None


class OverlapCluster(ContractModel):
    risk_factor: str
    risk_factor_label: str
    events: list[OverlapEvent]
    shared_holdings: list[ReachedHolding]
    shared_value: float
    shared_share: float
    sentence: str


class OverlapView(ContractModel):
    portfolio_id: str
    version: str = VERSION
    availability: Availability
    reason: str | None = None
    window_days: float
    considered: int = Field(description="signals looked at after the window and materiality filters")
    clusters: list[OverlapCluster]
    note: str
    adjustments: AdjustmentNotice | None = None


# ------------------------------------------------------------------------------------------------------------------------ flow
class PortfolioFlow(ContractModel):
    signal_id: str
    version: str = VERSION
    portfolio_id: str
    portfolio_name: str
    graph: PropagationGraph
    materiality: PortfolioMateriality
    scenario: GeneratedScenario
    existing_run_id: str | None = Field(default=None, description="a run of the generated scenario already made for this portfolio, if any")
    adjustments: AdjustmentNotice | None = None


class AutoStressRequest(ContractModel):
    portfolio_id: str | None = None
    force: bool = Field(default=False, description="run even when a gate fails (a what-if); the failed gates are still reported")
    impact_override: float | None = Field(default=None, ge=1, le=10)


class AutoStressResult(ContractModel):
    signal_id: str
    version: str = VERSION
    portfolio_id: str
    materiality: PortfolioMateriality
    scenario: GeneratedScenario
    run: StressResult | None
    chain: ExposureChain | None
    attribution: StressAttribution | None
    note: str | None = None
    adjustments: AdjustmentNotice | None = None


Json = dict[str, Any]
