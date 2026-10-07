"""Synthetic wholesale-banking portfolio contracts (PRD §10, FR-11)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime

from pydantic import Field, field_validator, model_serializer, model_validator

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
    spread_sensitivity: float = Field(
        default=1.0, ge=0, le=3,
        description="share of a credit-spread shock a BOND takes: 1 corporate credit, 0 government debt")

    currency: str | None = Field(
        default=None, description="ISO code of the currency the position is denominated in when it is not the portfolio's base currency; unset = base currency (omitted from the JSON)")
    commodity_sensitivity: float | None = Field(
        default=None, ge=-5, le=5,
        description="elasticity of the position's value to the price of crude oil (0.5 = a 10% oil move moves it 5%); unset = not measured, so an oil shock does not move it (omitted from the JSON)")

    # Stage 13 mechanics. Every one is optional and omitted from the JSON while unset, so the default book's hash and every pinned run are unchanged.
    convexity: float | None = Field(
        default=None, ge=0, le=500,
        description="BOND: convexity in years squared; adds 0.5 x C x (yield change)^2 to the price change. Unset = duration only (first order)")
    maturity_years: float | None = Field(
        default=None, gt=0, le=40, description="LOAN: remaining tenor in years; the horizon of the hazard-rate link between a spread shock and PD")
    spread_passthrough: float | None = Field(
        default=None, ge=0, le=1.5,
        description="LOAN: share of a credit-spread shock that reaches this borrower's hazard rate (credit triangle: spread = hazard x LGD). Unset = a spread shock does not move the loan")
    gamma: float | None = Field(
        default=None, ge=-50, le=50,
        description="DERIVATIVE: change in delta per unit return of the underlying; adds 0.5 x gamma x underlying x s^2. Unset = delta only")
    counterparty_pd: float | None = Field(
        default=None, ge=0, le=1, description="DERIVATIVE: one-year default probability of the counterparty, for the credit-valuation adjustment")
    counterparty_lgd: float | None = Field(
        default=None, gt=0, le=1, description="DERIVATIVE: loss given default of the counterparty; required with counterparty_pd")
    rating: str | None = Field(
        default=None, max_length=8,
        description="external-style rating bucket (e.g. BBB). Carried for reporting and concentration only: no revaluation reads it")
    spread_bp: float | None = Field(
        default=None, ge=0, le=5000, description="BOND: current credit spread in basis points. Carried for reporting only: no revaluation reads it")

    @model_serializer(mode="wrap")
    def _omit_default_optional_fields(self, handler):  # noqa: ANN001, ANN202
        """Omit ``spread_sensitivity`` at its default and every unset optional exposure / mechanic: the synthetic book's JSON and hash are unchanged."""
        data = handler(self)
        if data.get("spread_sensitivity") == 1.0:
            data.pop("spread_sensitivity")
        for k in ("currency", "commodity_sensitivity", "convexity", "maturity_years", "spread_passthrough", "gamma",
                  "counterparty_pd", "counterparty_lgd", "rating", "spread_bp"):
            if data.get(k) is None:
                data.pop(k, None)
        return data

    @model_validator(mode="after")
    def _per_class(self) -> PortfolioAsset:
        t = self.asset_type
        valued = (AssetClass.EQUITY, AssetClass.BOND, AssetClass.CASH, AssetClass.OTHER)
        if t in valued and self.market_value <= 0:
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
        if self.currency is not None and not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("currency must be a three-letter ISO code such as EUR")
        only = {"convexity": AssetClass.BOND, "spread_bp": AssetClass.BOND, "maturity_years": AssetClass.LOAN,
                "spread_passthrough": AssetClass.LOAN, "gamma": AssetClass.DERIVATIVE, "counterparty_pd": AssetClass.DERIVATIVE,
                "counterparty_lgd": AssetClass.DERIVATIVE}
        for field, cls in only.items():
            if getattr(self, field) is not None and t is not cls:
                raise ValueError(f"{field} applies to {cls.value} positions only")
        if self.spread_passthrough is not None and self.maturity_years is None:
            raise ValueError("spread_passthrough needs maturity_years (the horizon of the hazard-rate link)")
        if (self.counterparty_pd is None) != (self.counterparty_lgd is None):
            raise ValueError("counterparty_pd and counterparty_lgd are set together (the credit-valuation adjustment needs both)")
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
