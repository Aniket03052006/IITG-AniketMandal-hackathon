"""Scenario template contracts (PRD FR-12). Magnitudes are configuration, labelled illustrative."""

from __future__ import annotations

import re

from pydantic import Field, model_serializer, model_validator

from .base import ContractModel
from .enums import EventCategory, RiskFactor, ShockScope


class ShockSpec(ContractModel):
    """A shock at the scenario's *reference impact*; scaled by severity at run time."""

    factor: RiskFactor
    scope: ShockScope
    value: float
    rationale: str = ""
    sector: str | None = Field(
        default=None,
        description="SECTOR scope only: the sector this shock names. Unset, the shock binds to the sector the event is about "
                    "(every catalog scenario); set, it applies to that sector whatever the event is about (generated scenarios).")
    currency: str | None = Field(
        default=None, description="FX_PCT only: the ISO code of the currency whose value moves against the base currency (omitted from the JSON when unset)")
    entity_id: str | None = Field(
        default=None, description="ISSUER scope only: the issuer this shock names, whatever the event is about (scenario-lab shocks; omitted from the JSON when unset). Unset, it binds to the event's own issuer.")

    @model_serializer(mode="wrap")
    def _omit_unset_lab_fields(self, handler):  # noqa: ANN001, ANN202
        """``currency`` and ``entity_id`` are omitted while unset, so every catalog and generated scenario serialises exactly as before."""
        data = handler(self)
        for k in ("currency", "entity_id"):
            if data.get(k) is None:
                data.pop(k, None)
        return data

    @model_validator(mode="after")
    def _ranges(self) -> ShockSpec:
        v, f = self.value, self.factor
        if self.sector is not None and self.scope is not ShockScope.SECTOR:
            raise ValueError("only a SECTOR-scope shock can name a sector")
        if self.entity_id is not None and self.scope is not ShockScope.ISSUER:
            raise ValueError("only an ISSUER-scope shock can name an issuer")
        if (f is RiskFactor.FX_PCT) != (self.currency is not None):
            raise ValueError("an FX_PCT shock must name its currency, and no other shock may")
        if self.currency is not None and not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("currency must be a three-letter ISO code such as EUR")
        if f in (RiskFactor.FX_PCT, RiskFactor.COMMODITY_PCT):
            if self.scope is not ShockScope.MARKET:
                raise ValueError(f"{f.value} is a market-wide shock: a position carries the exposure, not the shock")
            if not -1.0 <= v <= 1.0:
                raise ValueError(f"{f.value} shock must be a fraction in [-1, 1]")
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
        keys = [(s.factor, s.scope, s.sector, s.currency, s.entity_id) for s in self.shocks]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate (factor, scope, sector, currency, issuer) shock")
        return self
