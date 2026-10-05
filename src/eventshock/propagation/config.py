"""Validated configuration for the propagation layer (configs/propagation.yaml). Every number and every edge is a judgement prior, not a fit."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError, _read_yaml
from ..config_overrides import apply_overrides
from ..domain import EventCategory, RiskFactor, ShockScope, ShockSpec

LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
EXPOSURE_ROWS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")
Level = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
_ID = re.compile(r"^[a-z0-9_]+$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def level_rank(level: str) -> int:
    return LEVELS.index(level)


class GenerationCfg(_Strict):
    min_severity: float = Field(ge=1, le=10)
    min_materiality: Level
    downside_only: bool
    propagated_equity_shock: float = Field(ge=-0.5, le=0.0)
    propagated_spread_bps: float = Field(ge=0, le=500)
    max_propagated_sectors: int = Field(ge=1, le=6)
    propagation_scale: float = Field(ge=0, le=2)


class ExposureBands(_Strict):
    medium_share: float = Field(gt=0, lt=1)
    high_share: float = Field(gt=0, lt=1)
    very_high_share: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> ExposureBands:
        if not self.medium_share < self.high_share < self.very_high_share:
            raise ValueError("exposure_bands must satisfy medium_share < high_share < very_high_share")
        return self


class SeverityBands(_Strict):
    medium: float = Field(ge=1, le=10)
    high: float = Field(ge=1, le=10)
    critical: float = Field(ge=1, le=10)

    @model_validator(mode="after")
    def _ordered(self) -> SeverityBands:
        if not self.medium < self.high < self.critical:
            raise ValueError("severity_bands must satisfy medium < high < critical")
        return self


class MaterialityCfg(_Strict):
    exposure_bands: ExposureBands
    severity_bands: SeverityBands
    grid: dict[str, dict[str, Level]]
    concentration_bump_top_share: float = Field(gt=0, le=1)
    assumption_only_cap: Level
    severity_unavailable_cap: Level

    @model_validator(mode="after")
    def _grid_complete_and_monotone(self) -> MaterialityCfg:
        if set(self.grid) != set(EXPOSURE_ROWS):
            raise ValueError(f"materiality.grid rows must be exactly {list(EXPOSURE_ROWS)}")
        for r, row in self.grid.items():
            if set(row) != set(LEVELS):
                raise ValueError(f"materiality.grid.{r} columns must be exactly {list(LEVELS)}")
        for i, r in enumerate(EXPOSURE_ROWS):
            for j, c in enumerate(LEVELS):
                here = level_rank(self.grid[r][c])
                if j and here < level_rank(self.grid[r][LEVELS[j - 1]]):
                    raise ValueError(f"materiality.grid decreases along severity at {r}/{c}")
                if i and here < level_rank(self.grid[EXPOSURE_ROWS[i - 1]][c]):
                    raise ValueError(f"materiality.grid decreases along exposure at {r}/{c}")
        return self


class ConcentrationCfg(_Strict):
    min_share: float = Field(gt=0, le=1)
    equal_weight_multiple: float = Field(ge=1, le=50)
    min_items: int = Field(ge=2, le=50)
    hhi_flag: float = Field(gt=0, le=1)
    hhi_equal_weight_multiple: float = Field(ge=1, le=20)
    window_days: float = Field(gt=0, le=365)
    max_signals: int = Field(ge=2, le=1000)
    min_events: int = Field(ge=2, le=20)
    min_overlap_share: float = Field(gt=0, le=1)
    min_materiality: Level


class TemplateCfg(_Strict):
    enabled: bool
    label: str
    propagation_scale: float = Field(ge=0, le=2)
    shock_overrides: dict[str, float]

    @model_validator(mode="after")
    def _keys(self) -> TemplateCfg:
        for key, value in self.shock_overrides.items():
            try:
                factor, scope = key.split(":")
                ShockSpec(factor=RiskFactor(factor), scope=ShockScope(scope), value=value)
            except ValueError as exc:
                raise ValueError(f"shock_overrides.{key}: use FACTOR:SCOPE (e.g. EQUITY:MARKET) with a credible value ({exc})") from exc
        return self


class Edge(_Strict):
    kind: Literal["SECTOR", "INDUSTRY", "ASSET_CLASS", "REGION"]
    key: str = Field(min_length=1)
    weight: float = Field(ge=-1, le=1)
    enabled: bool
    shock: bool
    rationale: str

    @model_validator(mode="after")
    def _shock_only_for_sector(self) -> Edge:
        if self.shock and self.kind != "SECTOR":
            raise ValueError("only a SECTOR edge can write a propagated shock")
        if self.kind == "ASSET_CLASS" and self.key not in ("EQUITY", "BOND", "LOAN", "DERIVATIVE"):
            raise ValueError("an ASSET_CLASS edge's key must be EQUITY, BOND, LOAN or DERIVATIVE")
        return self


class RiskFactorCfg(_Strict):
    label: str
    modelled: Literal["ENGINE", "PROXY", "NOT_MODELLED"]
    engine_factor: RiskFactor | None
    terms: list[str]
    transmission: dict[str, Edge]

    @model_validator(mode="after")
    def _ids(self) -> RiskFactorCfg:
        for eid in self.transmission:
            if not _ID.match(eid):
                raise ValueError(f"edge id {eid!r} must be lower-case letters, digits and underscores")
        return self


class PropagationConfig(_Strict):
    version: str
    generation: GenerationCfg
    materiality: MaterialityCfg
    concentration: ConcentrationCfg
    category_risk_factors: dict[EventCategory, list[str]]
    theme_risk_factors: dict[str, list[str]]
    engine_factor_map: dict[RiskFactor, str]
    templates: dict[EventCategory, TemplateCfg]
    risk_factors: dict[str, RiskFactorCfg]

    @model_validator(mode="after")
    def _consistent(self) -> PropagationConfig:
        known = set(self.risk_factors)
        for where, ids in [*((f"category_risk_factors.{c.value}", v) for c, v in self.category_risk_factors.items()),
                           *((f"theme_risk_factors.{t}", v) for t, v in self.theme_risk_factors.items()),
                           *((f"engine_factor_map.{f.value}", [v]) for f, v in self.engine_factor_map.items())]:
            for rf in ids:
                if rf not in known:
                    raise ValueError(f"{where} names an unknown risk factor {rf!r}")
        if set(self.category_risk_factors) != set(EventCategory):
            raise ValueError("category_risk_factors must list every event class")
        if set(self.templates) != set(EventCategory):
            raise ValueError("templates must list every event class")
        return self

    def exposure_row(self, share: float) -> str:
        b = self.materiality.exposure_bands
        return ("VERY_HIGH" if share >= b.very_high_share else "HIGH" if share >= b.high_share else "MEDIUM" if share >= b.medium_share else "LOW")

    def severity_column(self, severity: float) -> str:
        b = self.materiality.severity_bands
        return "CRITICAL" if severity >= b.critical else "HIGH" if severity >= b.high else "MEDIUM" if severity >= b.medium else "LOW"


def load_propagation_config(config_dir: Path, overrides: Mapping[str, Any] | None = None) -> PropagationConfig:
    """The shipped config, with ``overrides`` (dotted path -> value, relative to this file) patched in before validation."""
    path = config_dir / "propagation.yaml"
    try:
        return PropagationConfig.model_validate(apply_overrides(_read_yaml(path), overrides))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
