"""Contracts of the external-market layer. Every value keeps the provenance of the external source it came from; nothing here is ever an input to a risk number."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from ..decision.models import LABEL_EXTERNAL_MARKET, ProvenanceRef
from ..domain.base import ContractModel

VERSION = "external-markets-v1"
NEVER_AN_INPUT = ("External market data is an observation. It is never an input to the risk signal, the severity score, sentiment, the event classification, portfolio mapping, portfolio stress "
                  "or reverse stress, and a market price is not a ground truth.")


class ProviderCategory(StrEnum):
    PREDICTION_MARKET = "PREDICTION_MARKET"
    EQUITY_MARKET = "EQUITY_MARKET"
    RATE_MARKET = "RATE_MARKET"
    CREDIT_MARKET = "CREDIT_MARKET"
    COMMODITY_MARKET = "COMMODITY_MARKET"
    FX_MARKET = "FX_MARKET"
    VOLATILITY_MARKET = "VOLATILITY_MARKET"


class MatchStatus(StrEnum):
    MATCHED = "MATCHED"
    LOW_CONFIDENCE_MATCH = "LOW_CONFIDENCE_MATCH"
    NO_MATCH = "NO_MATCH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MarketStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    UNKNOWN = "UNKNOWN"


class Interpretation(StrEnum):
    MARKET_REPRICED = "MARKET_REPRICED"
    ALIGNED = "ALIGNED"
    DIVERGENT = "DIVERGENT"
    LOW_INFORMATION = "LOW_INFORMATION"
    NOT_ASSESSED = "NOT_ASSESSED"


class ExternalMarketObservation(ContractModel):
    """One market at one moment, as an independent source reported it."""

    provider: str
    category: ProviderCategory
    source: str = Field(description="kalshi (live) | kalshi-snapshot (a captured copy) | fixture (SYNTHETIC: not market data)")
    market_id: str
    series_id: str | None
    question: str
    probability: float | None = Field(description="the market's implied probability of YES (0-1); null when the market is not priced (no trade and no usable quote)")
    previous_probability: float | None
    probability_change_pp: float | None = Field(description="percentage points since the previous observation; null when either is missing")
    observed_at: datetime
    previous_observed_at: datetime | None
    market_status: MarketStatus
    raw_status: str | None
    volume: float | None = Field(description="contracts traded in total, when the source reports it")
    volume_24h: float | None
    open_interest: float | None
    close_time: datetime | None
    source_url: str | None
    synthetic: bool = False
    provenance: list[ProvenanceRef]


class ProviderState(ContractModel):
    provider: str
    category: ProviderCategory
    state: str = Field(description="AVAILABLE | UNAVAILABLE | DISABLED")
    mode: str = Field(description="live | snapshot | fixture | off")
    reason: str | None = None
    observed_from: datetime | None = None
    observed_through: datetime | None = None
    synthetic: bool = False


class Gate(ContractModel):
    id: str
    label: str
    passed: bool
    detail: str


class Candidate(ContractModel):
    market_id: str
    question: str
    series_id: str | None
    probability: float | None
    open_interest: float | None
    volume: float | None
    close_time: datetime | None
    gates: list[Gate]
    chosen: bool


class MarketMatch(ContractModel):
    status: MatchStatus
    reason: str = Field(description="in words: which gates passed or failed and why this market (or none)")
    theme_id: str | None
    theme_label: str | None
    event_gates: list[Gate]
    market: ExternalMarketObservation | None
    candidates: list[Candidate]
    evidence: list[str] = Field(default_factory=list, description="what in the event made the theme apply: scope themes and the phrases found in its text")


class InterpretationView(ContractModel):
    code: Interpretation
    text: str = Field(description="a descriptive observation, never 'the market confirms EventShock'")
    reason: str
    rule: str
    eventshock_elevated: bool
    eventshock_direction: str | None = Field(description="UP | DOWN | FLAT | None: the change of EventShock's severity since the previous cycle, when there was one")
    market_direction: str | None = Field(description="TOWARD_RISK | AWAY_FROM_RISK | FLAT | UNMAPPED | None: relative to the market's own orientation")
    orientation: str = Field(description="UP | DOWN | NEUTRAL: which way a higher probability moves the world relative to risk, and how it was read")
    caveats: list[str]


class MarketTimelineItem(ContractModel):
    at: datetime
    kind: str = Field(description="EXTERNAL_MARKET_OBSERVATION | SOURCE_EVENT | EVENTSHOCK_ASSESSMENT | SCENARIO_ASSUMPTION | REALISED_OUTCOME")
    label: str
    detail: str
    probability: float | None = None
    change_pp: float | None = None
    provenance: list[ProvenanceRef]


class EventMarketView(ContractModel):
    version: str = VERSION
    event_id: str
    signal_id: str | None
    availability: str = Field(description="AVAILABLE | UNAVAILABLE")
    reason: str | None = None
    as_of: datetime | None
    provider: ProviderState
    match: MarketMatch | None
    interpretation: InterpretationView | None
    eventshock_severity: float | None
    eventshock_materiality: str | None
    label: str = LABEL_EXTERNAL_MARKET
    note: str = NEVER_AN_INPUT
    caveats: list[str]
    provenance: list[ProvenanceRef]


class MarketTimeline(ContractModel):
    version: str = VERSION
    event_id: str
    availability: str
    reason: str | None = None
    market_id: str | None
    items: list[MarketTimelineItem]
    kinds: dict[str, int]
    label: str = LABEL_EXTERNAL_MARKET
    note: str = NEVER_AN_INPUT
