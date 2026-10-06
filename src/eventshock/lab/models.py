"""Contracts of the scenario lab and reverse stress. Derived and stateless: nothing is stored on a signal, and the engine arithmetic is the engine's own."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from ..decision.models import LABEL_ASSUMPTION, LABEL_SIMULATION, ProvenanceRef
from ..domain import StressResult
from ..domain.base import ContractModel
from ..propagation.models import StressAttribution
from ..stress.history_check import ScenarioHistoryCheck

VERSION = "lab-v1"
NOT_A_PREDICTION = "A hypothetical stress analysis under the assumptions above. It is not a prediction, a forecast or an expected return."


class ScenarioType(StrEnum):
    BASE = "BASE"          # no shock: the portfolio as it is
    ASSESSED = "ASSESSED"  # the scenario EventShock generated for an event (configured assumptions, not yours)
    CUSTOM = "CUSTOM"      # every size is a value the user chose


class AssumptionKind(StrEnum):
    EQUITY_MARKET = "EQUITY_MARKET"
    RATES = "RATES"
    CREDIT_SPREAD = "CREDIT_SPREAD"
    COMMODITY = "COMMODITY"
    FX = "FX"
    SECTOR = "SECTOR"
    ISSUER = "ISSUER"
    RISK_FACTOR = "RISK_FACTOR"


class Assumption(ContractModel):
    kind: AssumptionKind
    value: float = Field(description="fraction for equity / sector / issuer / oil / FX (-0.05 = -5%), basis points for rates and credit spread, a multiplier for default probability")
    target: str | None = Field(default=None, max_length=64, description="SECTOR: a sector; ISSUER: an entity id or ticker; FX: a currency code; CREDIT_SPREAD: an optional sector; RISK_FACTOR: a risk factor id ('FX:EUR' for a currency)")
    rationale: str = Field(default="", max_length=240)


class ScenarioRequest(ContractModel):
    scenario_type: ScenarioType = ScenarioType.CUSTOM
    name: str | None = Field(default=None, max_length=80)
    assumptions: list[Assumption] = Field(default_factory=list)
    signal_id: str | None = Field(default=None, description="ASSESSED: the signal whose generated scenario to run")
    portfolio_id: str | None = None
    exposure_priors: bool = Field(default=False, description="estimate an oil elasticity from the sector for equities and derivatives that have none: a judgement prior, shown beside the result")
    force: bool = Field(default=False, description="ASSESSED: run the generated scenario even when a soft gate (severity, relevance) fails, as a what-if")


class LabCompareRequest(ContractModel):
    scenarios: list[ScenarioRequest] = Field(min_length=2, max_length=5)
    portfolio_id: str | None = None


class ResolvedShock(ContractModel):
    factor: str
    scope: str
    sector: str | None = None
    currency: str | None = None
    entity_id: str | None = None
    value: float
    unit: str
    basis: str = Field(description="what made this engine shock: the user's choice, or the transmission edge that spread a risk-factor shock")


class AssumptionResult(ContractModel):
    index: int
    origin: str = Field(description="USER (you chose it) | ASSESSED (EventShock's configured scenario for the event)")
    kind: str
    label: str = LABEL_ASSUMPTION
    description: str
    value: float
    unit: str
    target: str | None
    target_label: str | None
    rationale: str
    shocks: list[ResolvedShock]
    reach: str = Field(description="APPLIED | NOT_REACHED (no position carries the exposure this shock acts on)")
    positions_reached: int
    value_reached: float
    share_reached: float
    pnl: float | None = Field(description="the modeled change this assumption alone accounts for (a simulation under the assumptions, not a forecast)")
    note: str | None = None


class PriorUse(ContractModel):
    sector: str
    sensitivity: float
    positions: int
    value: float
    label: str = "JUDGEMENT PRIOR"


class LabIssue(ContractModel):
    index: int | None
    field: str
    message: str


class LabPlan(ContractModel):
    """What a request resolves to before anything runs."""

    ok: bool
    scenario_type: ScenarioType
    scenario_id: str | None
    issues: list[LabIssue]
    assumptions: list[AssumptionResult]
    bounds: dict[str, dict[str, float | str]]
    label: str = LABEL_ASSUMPTION


class LabResult(ContractModel):
    version: str = VERSION
    scenario_id: str = Field(description="deterministic: the same assumptions on the same portfolio give the same id")
    scenario_type: ScenarioType
    name: str
    created_at: datetime
    portfolio_id: str
    portfolio_name: str
    status: str = Field(description="COMPLETED | NOT_APPLICABLE (nothing in the portfolio carries the exposure) | UNAVAILABLE (an assessed scenario that cannot be generated)")
    reason: str | None = None
    assumptions: list[AssumptionResult]
    result: StressResult | None
    attribution: StressAttribution | None
    exposure_priors: list[PriorUse] = Field(default_factory=list)
    history_check: ScenarioHistoryCheck | None = None
    provenance: list[ProvenanceRef]
    label: str = LABEL_SIMULATION
    note: str = NOT_A_PREDICTION
    labels: list[str]
    limitations: list[str]


class ComparisonRow(ContractModel):
    scenario_id: str
    name: str
    scenario_type: ScenarioType
    status: str
    baseline_value: float | None
    stressed_value: float | None
    pnl: float | None
    pnl_pct: float | None
    dominant_driver: str | None
    top_sectors: list[str]
    top_risk_factors: list[str]
    top_holdings: list[str]
    assumption_count: int


class AssumptionDiffRow(ContractModel):
    key: str
    label: str
    values: list[str | None] = Field(description="one entry per compared scenario, in order; null = the scenario does not set it")
    differs: bool


class Comparison(ContractModel):
    version: str = VERSION
    portfolio_id: str
    portfolio_name: str
    results: list[LabResult]
    rows: list[ComparisonRow]
    assumption_diff: list[AssumptionDiffRow]
    worst_scenario_id: str | None
    label: str = LABEL_SIMULATION
    note: str = NOT_A_PREDICTION


class OptionEntry(ContractModel):
    value: str
    label: str
    detail: str | None = None


class KindInfo(ContractModel):
    kind: AssumptionKind
    label: str
    unit: str
    min: float | None
    max: float | None
    needs_target: str | None = Field(description="what `target` must name for this kind (null = it takes none)")
    reaches: str = Field(description="what the shock reaches, in words")


class ReverseOptions(ContractModel):
    presets_pct: list[float]
    min_target_pct: float
    tolerance_pp: float
    method: str
    axes: list[OptionEntry]


class LabOptions(ContractModel):
    """What the editor can offer: the same vocabulary the validator enforces."""

    version: str = VERSION
    portfolio_id: str
    base_currency: str
    kinds: list[KindInfo]
    sectors: list[OptionEntry]
    issuers: list[OptionEntry]
    currencies: list[OptionEntry]
    risk_factors: list[OptionEntry]
    held_currencies: list[str]
    oil_priors: list[PriorUse]
    reverse: ReverseOptions
    max_assumptions: int
    max_compared: int
    label: str = LABEL_ASSUMPTION


# ------------------------------------------------------------------------------------------------------------------------------ reverse stress
class ReverseStressRequest(ContractModel):
    target_pct: float = Field(description="the loss to find a hypothetical combination for, in percent of the portfolio: -5 means -5%", lt=0)
    portfolio_id: str | None = None
    factors: list[str] | None = Field(default=None, description="restrict the search to these basket axes (by id, e.g. EQUITY_MARKET, CREDIT_SPREAD, RATES, COMMODITY, or a held sector); default: the configured basket")
    exposure_priors: bool = Field(default=False, description="let the oil axis use sector priors for positions with no measured oil elasticity (a judgement prior, shown beside the result)")


class RequiredShock(ContractModel):
    axis: str
    label: str
    kind: AssumptionKind
    target: str | None
    value: float
    unit: str
    bound: float = Field(description="the configured limit of this axis, in the same unit")
    share_of_bound: float = Field(description="how much of its limit this shock uses (0-1)")
    label_kind: str = LABEL_ASSUMPTION


class AxisBound(ContractModel):
    axis: str
    label: str
    unit: str
    bound: float
    direction: str = Field(description="ADVERSE_DOWN | ADVERSE_UP: the direction that loses")
    efficiency: float | None = Field(description="loss in percent of the book per 100% of the bound, from the probe; null when the axis was not probed")
    used: bool
    note: str | None = None


class ReverseStressResult(ContractModel):
    version: str = VERSION
    reverse_id: str
    status: str = Field(description="ACHIEVABLE | NOT_ACHIEVABLE (the bounds cannot reach it) | NO_EXPOSURE (no basket shock reaches the book)")
    portfolio_id: str
    portfolio_name: str
    target_pct: float
    achieved_pct: float | None
    difference_pp: float | None = Field(description="achieved minus target, in percentage points of the book")
    achieved_pnl: float | None
    baseline_value: float | None
    required_shocks: list[RequiredShock]
    dominant_drivers: list[str]
    affected_holdings: list[str]
    affected_sectors: list[str]
    affected_risk_factors: list[str]
    binding_bounds: list[str] = Field(description="when not achievable: the axes that were already at their limit")
    bounds: list[AxisBound]
    assumptions: list[str]
    search_method: str
    search_config: dict[str, str | float | int | list[str]]
    evaluations: int
    scenario: LabResult | None = Field(description="the complete engine run of the combination found (value before and after, attribution, history check)")
    open_in_lab: ScenarioRequest | None = Field(description="the same combination as a CUSTOM scenario, to fork into the lab")
    exposure_priors: list[PriorUse] = Field(default_factory=list)
    label: str = LABEL_ASSUMPTION
    note: str = "A hypothetical stress analysis: the shocks above are what it would take, under these bounds, to lose this much. It is not a prediction of future losses."
    labels: list[str]
    limitations: list[str]
