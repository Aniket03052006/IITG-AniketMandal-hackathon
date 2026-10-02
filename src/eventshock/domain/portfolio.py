"""Synthetic wholesale-banking portfolio contracts (PRD §10, FR-11)."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from .base import ContractModel
from .documents import _require_aware
from .enums import AssetClass


class PortfolioAsset(ContractModel):
    """One position. Which fields are required depends on ``asset_type`` (validated below).

    Conventions
    - ``market_value``: current carrying value in base currency.
    - ``notional``: face (BOND), exposure-at-default (LOAN), underlying notional (DERIVATIVE).
    - LOAN ``market_value`` = EAD - expected loss = ``notional * (1 - pd * lgd)``.
    """

    asset_id: str = Field(min_length=1)
    asset_type: AssetClass
    entity_id: str = Field(min_length=1, description="issuer / borrower / underlying entity")
    name: str
    sector: str
    geography: str
    notional: float = Field(gt=0)
    market_value: float
    beta: float = Field(default=1.0, ge=-1, le=3)
    duration: float | None = Field(default=None, ge=0, le=30)
    pd: float | None = Field(default=None, ge=0, le=1)
    lgd: float | None = Field(default=None, ge=0, le=1)
    default_sensitivity: float = Field(default=1.0, ge=0, le=3)
    delta: float | None = Field(default=None, ge=-1.5, le=1.5)

    @model_validator(mode="after")
    def _per_class(self) -> PortfolioAsset:
        t = self.asset_type
        if t in (AssetClass.EQUITY, AssetClass.BOND) and self.market_value <= 0:
            raise ValueError(f"{t} market_value must be > 0")
        if t is AssetClass.BOND and self.duration is None:
            raise ValueError("BOND requires duration")
        if t is AssetClass.LOAN:
            if self.pd is None or self.lgd is None:
                raise ValueError("LOAN requires pd and lgd")
            expected = self.notional * (1 - self.pd * self.lgd)
            if not math.isclose(self.market_value, expected, rel_tol=1e-4, abs_tol=1.0):
                raise ValueError("LOAN market_value must equal notional * (1 - pd * lgd)")
        if t is AssetClass.DERIVATIVE and self.delta is None:
            raise ValueError("DERIVATIVE requires delta")
        return self


class Portfolio(ContractModel):
    portfolio_id: str
    name: str
    as_of: datetime
    base_currency: str = "USD"
    description: str = ""
    assets: list[PortfolioAsset]

    aware_check = field_validator("as_of")(_require_aware)

    @model_validator(mode="after")
    def _unique_ids(self) -> Portfolio:
        ids = [a.asset_id for a in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("asset_id values must be unique")
        if not ids:
            raise ValueError("portfolio must contain assets")
        return self

    @property
    def total_value(self) -> float:
        return sum(a.market_value for a in self.assets)

    def content_hash(self) -> str:
        """Stable fingerprint of the holdings; part of every stress run id."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
