"""Contracts for personal portfolios: what the user typed, what it resolved to, and what was wrong with it.

A personal portfolio is OPTIONAL. The synthetic wholesale book (``DEFAULT_ID``) stays the default everywhere; a stored portfolio only
takes part when a request names it.

Two shapes on purpose:
- ``PortfolioInput`` is what the user typed (weights or quantities, optional fields left empty). It is what is stored.
- ``ResolvedPortfolio`` is that input after a pure, deterministic resolution into the engine's ``Portfolio``, with every filled-in
  field tagged by where it came from (``FieldSource``), so nothing is silently invented.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field

from ..domain import AssetClass, Portfolio
from ..domain.base import ContractModel

DEFAULT_ID = "default"


class InputModel(ContractModel):
    """User-supplied payloads reject unknown keys (a misspelt field is an error, not silently ignored)."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class EntryMode(StrEnum):
    WEIGHT = "WEIGHT"      # each holding is a share of the portfolio; value = weight x total value
    QUANTITY = "QUANTITY"  # each holding is quantity x price; weights are derived


class FieldSource(StrEnum):
    USER = "USER"                              # typed by the user
    REFERENCE = "REFERENCE"                    # looked up: the entity master, the 34 issuers' trailing beta, or the reference instrument table
    DEFAULT_ASSUMPTION = "DEFAULT_ASSUMPTION"  # EventShock had nothing to look up and used a stated default (e.g. beta 1.0)
    DERIVED = "DERIVED"                        # computed from other fields (e.g. value = quantity x price)


class IssueLevel(StrEnum):
    ERROR = "ERROR"      # blocks saving / stressing
    WARNING = "WARNING"  # saved, but the user should know (e.g. an unknown sector, FX not modelled)
    INFO = "INFO"        # a note about something EventShock did (e.g. weights rescaled)


class Issue(ContractModel):
    level: IssueLevel
    code: str = Field(description="stable machine code, e.g. WEIGHTS_SUM, DUPLICATE_TICKER, UNKNOWN_SECTOR")
    message: str
    holding: int | None = Field(default=None, description="index of the holding it concerns; null for the whole portfolio")
    field: str | None = None


class HoldingInput(InputModel):
    ticker: str = Field(min_length=1, max_length=24, description="instrument identifier; CASH for cash")
    name: str | None = Field(default=None, max_length=120)
    weight_pct: float | None = Field(default=None, description="share of the portfolio in percent (WEIGHT mode)")
    quantity: float | None = Field(default=None, description="units held (QUANTITY mode); for cash, the amount")
    price: float | None = Field(default=None, description="current price per unit (QUANTITY mode); 1 for cash")
    cost_basis: float | None = Field(default=None, description="price paid per unit; informational (unrealised P&L), never used by the stress")
    asset_class: Literal["EQUITY", "BOND", "CASH", "OTHER"] | None = None
    sector: str | None = Field(default=None, max_length=60)
    region: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    beta: float | None = Field(default=None, description="market beta of an equity; overrides the looked-up one")
    duration: float | None = Field(default=None, description="modified duration in years of a bond; required for a bond with no reference")


class PortfolioInput(InputModel):
    name: str
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    mode: EntryMode = EntryMode.WEIGHT
    total_value: float | None = Field(default=None, description="WEIGHT mode: the portfolio's value in base currency (a default is used when empty)")
    remainder_as_cash: bool = Field(default=False, description="WEIGHT mode: when the weights sum to less than 100%, hold the rest as cash")
    notes: str = Field(default="", max_length=500)
    holdings: list[HoldingInput]


class StoredPortfolio(PortfolioInput):
    """A saved portfolio: the input plus identity and timestamps."""

    id: str
    created_at: datetime
    updated_at: datetime


class ResolvedHolding(ContractModel):
    index: int
    asset_id: str
    ticker: str
    name: str
    asset_class: AssetClass
    sector: str
    region: str
    currency: str
    value: float = Field(description="market value in base currency")
    weight: float = Field(description="share of the portfolio (0-1)")
    quantity: float | None = None
    price: float | None = None
    cost_basis: float | None = None
    unrealised_pnl: float | None = Field(default=None, description="(price - cost basis) x quantity; informational only")
    beta: float | None = None
    duration: float | None = None
    spread_sensitivity: float | None = None
    in_universe: bool = Field(description="True for one of the 34 issuers the event pipeline can name: only then can an issuer-level event reach it")
    sources: dict[str, FieldSource] = Field(description="field -> where its value came from")
    basis: list[str] = Field(default_factory=list, description="plain-words notes on the reference data used")


class ResolvedPortfolio(ContractModel):
    ok: bool = Field(description="False when any ERROR issue is present; then `portfolio` is null")
    mode: EntryMode
    total_value: float | None
    base_currency: str
    holdings: list[ResolvedHolding]
    issues: list[Issue]
    portfolio: Portfolio | None = None


class PortfolioListItem(ContractModel):
    id: str
    name: str
    kind: Literal["DEFAULT", "USER"]
    base_currency: str
    total_value: float
    holding_count: int
    description: str
    updated_at: datetime | None = None


class PortfolioView(ContractModel):
    """A stored portfolio together with its resolution (holdings with sources, issues)."""

    id: str
    kind: Literal["DEFAULT", "USER"]
    stored: StoredPortfolio | None = None
    resolved: ResolvedPortfolio | None = None
    list_item: PortfolioListItem


class ParseRequest(InputModel):
    text: str = Field(max_length=20000)
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    name: str = "My portfolio"


class ParseResult(ContractModel):
    draft: PortfolioInput | None
    issues: list[Issue] = Field(description="line-level problems (holding = the line index) and mode conflicts")
    resolved: ResolvedPortfolio | None = Field(default=None, description="the draft resolved, so the user sees weights, sources and issues immediately")


class CompareRequest(InputModel):
    signal_id: str
    portfolio_ids: list[str] = Field(min_length=2, max_length=2, description="two portfolio ids (DEFAULT_ID selects the synthetic book)")
    scenario_id: str | None = None
    force: bool = False
    impact_override: float | None = Field(default=None, ge=1, le=10)


class DiffRow(ContractModel):
    key: str
    label: str
    a_pct: float = Field(description="change as a fraction of portfolio A's value")
    b_pct: float
    gap_pct: float = Field(description="a_pct - b_pct")
    a_value: float
    b_value: float


class PortfolioComparison(ContractModel):
    signal_id: str
    scenario_id: str | None
    a: PortfolioListItem
    b: PortfolioListItem
    run_a: str
    run_b: str
    status_a: str
    status_b: str
    pnl_pct_a: float | None
    pnl_pct_b: float | None
    pnl_a: float | None
    pnl_b: float | None
    by_sector: list[DiffRow]
    by_factor: list[DiffRow]
    by_asset_class: list[DiffRow]
    difference: str = Field(description="one sentence, templated from the largest gap in the contributions; no model wrote it")
    note: str


# ----------------------------------------------------------------------------------------------------- exposure
class Metric(ContractModel):
    key: str
    label: str
    value: float | None
    unit: Literal["fraction", "years", "ratio", "currency", "count", "bp"]
    formula: str = Field(description="how it is computed, in plain words")


class ExposureRowV2(ContractModel):
    key: str
    label: str
    market_value: float
    share: float
    position_count: int


class PositionWeight(ContractModel):
    asset_id: str
    name: str
    asset_class: AssetClass
    sector: str
    region: str
    market_value: float
    weight: float


class PortfolioExposureDetail(ContractModel):
    portfolio_id: str
    name: str
    kind: Literal["DEFAULT", "USER"]
    base_currency: str
    total_value: float
    position_count: int
    by_asset_class: list[ExposureRowV2]
    by_sector: list[ExposureRowV2]
    by_region: list[ExposureRowV2]
    by_issuer: list[ExposureRowV2]
    split: list[ExposureRowV2] = Field(description="equity / bonds / cash / other (loans and derivatives)")
    largest_positions: list[PositionWeight]
    metrics: list[Metric]
    not_stressed: list[ExposureRowV2] = Field(description="value the engine cannot shock at all (OTHER): shown, never counted as safe")
    notes: list[str]


# ------------------------------------------------------------------------------------------------ exposure chain
class ChainStep(ContractModel):
    factor: str
    factor_label: str
    scope: str
    scope_label: str
    applied_shock: float = Field(description="scaled shock value in its own unit")
    unit: str
    exposed_value: float
    exposed_share: float = Field(description="of the portfolio's baseline value")
    position_count: int
    sensitivity: str = Field(description="the portfolio's own sensitivity to this factor, e.g. 'weighted beta 1.12' or 'weighted duration 6.4 y'")
    impact: float = Field(description="modeled change in portfolio currency, from the engine's per-factor attribution")
    impact_pct: float = Field(description="as a fraction of the portfolio's baseline value")
    sentence: str


class SkippedShock(ContractModel):
    factor_label: str
    scope_label: str
    reason: str


class ExposureChain(ContractModel):
    run_id: str
    portfolio_id: str
    portfolio_name: str
    event_line: str = Field(description="what the event is about, from its scope")
    scope_level: str
    steps: list[ChainStep]
    skipped: list[SkippedShock]
    not_reached: ExposureRowV2 | None = Field(default=None, description="holdings no applied shock moved (cash, unsupported instruments, unreached equity)")
    total_impact: float
    total_impact_pct: float
    summary: str
    note: str
