"""Contracts of the executive brief. A statement is a sentence made from structured fields and the sources it was read from; a statement with no resolvable source is a build error."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ..decision.models import LABEL_SIMULATION, ObservationKind
from ..domain.base import ContractModel

VERSION = "brief-v1"

SECTIONS: list[tuple[str, str]] = [
    ("EXECUTIVE_SUMMARY", "EXECUTIVE SUMMARY"),
    ("WHAT_HAPPENED", "WHAT HAPPENED"),
    ("CURRENT_STATUS", "CURRENT STATUS"),
    ("WHY_IT_MATTERS", "WHY IT MATTERS"),
    ("EVIDENCE", "EVIDENCE"),
    ("CONFLICTS", "CONFLICTS"),
    ("AFFECTED", "AFFECTED ENTITIES / SECTORS"),
    ("PORTFOLIO_EXPOSURE", "PORTFOLIO EXPOSURE"),
    ("PROPAGATION", "PROPAGATION"),
    ("STRESS", "STRESS"),
    ("TOP_DRIVERS", "TOP DRIVERS"),
    ("HISTORICAL_CONTEXT", "HISTORICAL CONTEXT"),
    ("EXTERNAL_MARKET_VIEW", "EXTERNAL MARKET VIEW"),
    ("ASSUMPTIONS", "ASSUMPTIONS"),
    ("UNCERTAINTY", "UNCERTAINTY"),
    ("WHAT_TO_MONITOR", "WHAT TO MONITOR"),
]

# the fixed sentences used when an input is absent: never replaced by an invented one
NO_MARKET = "No relevant external prediction market identified."
MARKET_UNAVAILABLE = "External market data unavailable."
NO_ANALOGUE = "No reliable historical analogue found."
NOT_RUN = "No stress scenario was generated for this event."


class SourceRef(ContractModel):
    id: str = Field(description="the key statements cite")
    kind: ObservationKind
    label: str
    endpoint: str | None = Field(default=None, description="the API path where the same structured output can be read")
    ref_id: str | None = None
    as_of: datetime | None = None


class Statement(ContractModel):
    text: str
    kind: ObservationKind = Field(description="what kind of statement it is: a source report, an EventShock assessment, an external market observation, a scenario assumption, a historical observation or a product rule")
    source_refs: list[str] = Field(min_length=1, description="ids in `sources`; at least one")


class BriefSection(ContractModel):
    id: str
    title: str
    availability: str = Field(description="AVAILABLE | PARTIAL | UNAVAILABLE")
    statements: list[Statement]


class Brief(ContractModel):
    version: str = VERSION
    event_id: str
    signal_id: str
    headline: str
    mode: str
    as_of: datetime | None
    cycle: int | None
    portfolio_id: str | None
    portfolio_name: str | None
    sections: list[BriefSection]
    sources: list[SourceRef]
    labels: list[str]
    note: str = f"Template-written from structured outputs; every statement lists its sources. Stress figures: {LABEL_SIMULATION}."
