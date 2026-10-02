"""Scenario template contracts (PRD FR-12). Magnitudes are configuration, labelled illustrative."""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import ContractModel
from .enums import EventCategory, RiskFactor, ShockScope


class ShockSpec(ContractModel):
    """A shock at the scenario's *reference impact*; scaled by severity at run time."""

    factor: RiskFactor
    scope: ShockScope
    value: float
    rationale: str = ""

    @model_validator(mode="after")
    def _ranges(self) -> ShockSpec:
        v, f = self.value, self.factor
        if f is RiskFactor.EQUITY and not -1.0 <= v <= 1.0:
            raise ValueError("EQUITY shock must be a fraction in [-1, 1]")
        if f is RiskFactor.PD_MULTIPLIER and v < 0:
            raise ValueError("PD_MULTIPLIER must be >= 0")
        if f is RiskFactor.LGD_ADD and not -1.0 <= v <= 1.0:
            raise ValueError("LGD_ADD must be a fraction in [-1, 1]")
        if f in (RiskFactor.RATES_BPS, RiskFactor.CREDIT_SPREAD_BPS) and abs(v) > 2000:
            raise ValueError("rate/spread shock outside +/-2000 bp is not credible")
        return self


class Scenario(ContractModel):
    id: str = Field(min_length=1)
    version: str
    name: str
    category: EventCategory
    description: str
    illustrative: bool = True
    reference_impact: float = Field(default=7.0, gt=0, le=10)
    shocks: list[ShockSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_duplicate_shocks(self) -> Scenario:
        keys = [(s.factor, s.scope) for s in self.shocks]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate (factor, scope) shock")
        return self
