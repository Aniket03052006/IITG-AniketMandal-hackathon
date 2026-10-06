"""Contracts of the explanation service."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ..decision.models import ProvenanceRef
from ..domain.base import ContractModel

VERSION = "explain-v1"


class Subject(StrEnum):
    PRIORITY = "PRIORITY"          # why is this event ranked where it is?
    STRESS = "STRESS"              # why is the modeled stress what it is?
    VISIBILITY = "VISIBILITY"      # why am I seeing this event?
    CHANGE = "CHANGE"              # why was this event flagged as changed?
    LAB = "LAB"                    # why did a lab scenario move the portfolio this much?
    REVERSE = "REVERSE"            # why these shocks for this loss?
    MARKET = "MARKET"              # what does an independent prediction market say, and why was it matched?


class ReasonKind(StrEnum):
    """What KIND of statement a reason is. Never blurred: a model output is not an observation, a scenario assumption is not a fact, a rule is not a model."""

    MODEL_OUTPUT = "MODEL_OUTPUT"                              # EventShock's own scorecard, classifier or reading
    HISTORICAL_OBSERVATION = "HISTORICAL_OBSERVATION"          # what already happened in past data (aggregate, not a forecast)
    EXTERNAL_MARKET_OBSERVATION = "EXTERNAL_MARKET_OBSERVATION"  # what an independent market is pricing (never an input)
    SCENARIO_ASSUMPTION = "SCENARIO_ASSUMPTION"                # a chosen shock or configured edge: a hypothetical
    PRODUCT_RULE = "PRODUCT_RULE"                              # a deterministic rule applied to counted facts or to the engine's arithmetic


class ReasonCode(StrEnum):
    SEVERITY = "SEVERITY"
    SEVERITY_UNSCORED = "SEVERITY_UNSCORED"
    EVENT_CLASS = "EVENT_CLASS"
    SCOPE = "SCOPE"
    SCOPE_UNRESOLVED = "SCOPE_UNRESOLVED"
    EVIDENCE_TIER = "EVIDENCE_TIER"
    INDEPENDENT_SOURCES = "INDEPENDENT_SOURCES"
    LIFECYCLE = "LIFECYCLE"
    CONFLICT_OPEN = "CONFLICT_OPEN"
    NOVELTY = "NOVELTY"
    MATERIALITY = "MATERIALITY"
    EXPOSURE_SHARE = "EXPOSURE_SHARE"
    MAPPING_BASIS = "MAPPING_BASIS"
    MATERIALITY_RULE = "MATERIALITY_RULE"
    WATCHLIST_MATCH = "WATCHLIST_MATCH"
    RECENT_CHANGE = "RECENT_CHANGE"
    CHANGE_RULE = "CHANGE_RULE"
    CHANGE_FIELD = "CHANGE_FIELD"
    STRESS_TOTAL = "STRESS_TOTAL"
    STRESS_SCENARIO = "STRESS_SCENARIO"
    STRESS_SHOCK = "STRESS_SHOCK"
    STRESS_NOT_RUN = "STRESS_NOT_RUN"
    STRESS_DRIVER_KIND = "STRESS_DRIVER_KIND"
    STRESS_DRIVER_SECTOR = "STRESS_DRIVER_SECTOR"
    STRESS_DRIVER_FACTOR = "STRESS_DRIVER_FACTOR"
    STRESS_DRIVER_RISK_FACTOR = "STRESS_DRIVER_RISK_FACTOR"
    STRESS_DRIVER_ISSUER = "STRESS_DRIVER_ISSUER"
    STRESS_HISTORY = "STRESS_HISTORY"
    REVERSE_TARGET = "REVERSE_TARGET"
    REVERSE_METHOD = "REVERSE_METHOD"
    REVERSE_SHOCK = "REVERSE_SHOCK"
    REVERSE_BOUND = "REVERSE_BOUND"
    REVERSE_BINDING = "REVERSE_BINDING"
    MARKET_MATCH = "MARKET_MATCH"
    MARKET_MOVE = "MARKET_MOVE"
    MARKET_INTERPRETATION = "MARKET_INTERPRETATION"
    MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"


class Reason(ContractModel):
    code: ReasonCode
    kind: ReasonKind
    text: str = Field(description="the reason in words, from the structured value below")
    value: str | float | None = Field(default=None, description="the value the reason is about, when it has one")
    unit: str | None = None
    detail: str | None = None
    source_ref: str = Field(description="the output this was read from: 'intelligence.lifecycle', 'propagation.materiality', 'monitor.state', 'stress.attribution', ...")
    provenance: list[ProvenanceRef] = Field(default_factory=list)


class Explanation(ContractModel):
    version: str = VERSION
    subject: Subject
    event_id: str | None
    signal_id: str | None
    headline: str
    level: str | None = Field(default=None, description="the level being explained (e.g. HIGH), when it has one")
    availability: str = Field(description="AVAILABLE | PARTIAL | UNAVAILABLE")
    unavailable_reason: str | None = None
    reasons: list[Reason]
    kinds: dict[str, int] = Field(description="how many reasons of each kind: a model output is never counted as an observation")
    limitations: list[str]
    labels: list[str]
