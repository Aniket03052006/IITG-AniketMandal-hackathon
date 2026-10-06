"""Validated configuration of the external-market layer (configs/external_markets.yaml). Every number and every theme is a judgement prior."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError
from ..config_overrides import apply_overrides
from ..pipeline.config import _load


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KalshiCfg(_Strict):
    base_url: str
    timeout_seconds: float = Field(gt=0)
    min_interval_seconds: float = Field(ge=0)
    page_limit: int = Field(ge=1, le=1000)
    max_markets_per_series: int = Field(ge=1, le=50)
    previous_gap_hours: float = Field(gt=0)

    @model_validator(mode="after")
    def _https(self) -> KalshiCfg:
        if not self.base_url.startswith("https://"):
            raise ValueError("base_url must be https")
        return self


class ProvidersCfg(_Strict):
    kalshi: KalshiCfg


class SnapshotCfg(_Strict):
    path: str
    history_days: int = Field(ge=1, le=400)
    candle_minutes: int = Field(ge=1)


class MatchingCfg(_Strict):
    horizon_max_days: float = Field(gt=0)
    staleness_days: float = Field(gt=0)
    max_spread: float = Field(gt=0, le=1)
    top_candidates: int = Field(ge=1, le=10)


class InterpretationCfg(_Strict):
    repriced_pp: float = Field(gt=0)
    aligned_pp: float = Field(gt=0)
    elevated_severity: float = Field(ge=1, le=10)
    elevated_materiality: list[str]
    min_open_interest: float = Field(ge=0)
    min_volume: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> InterpretationCfg:
        if self.aligned_pp >= self.repriced_pp:
            raise ValueError("aligned_pp must be smaller than repriced_pp")
        return self


class WhenCfg(_Strict):
    event_classes: list[str] = Field(min_length=1)
    scope_types: list[str] = Field(min_length=1)
    themes_any: list[str] = Field(default_factory=list)
    terms_any: list[str] = Field(default_factory=list)
    regions_any: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence(self) -> WhenCfg:
        if not self.themes_any and not self.terms_any:
            raise ValueError("a theme needs scope themes or text terms as evidence")
        return self


class OrientationCfg(_Strict):
    mode: str
    up: list[str] = Field(default_factory=list)
    down: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _mode(self) -> OrientationCfg:
        if self.mode not in ("UP", "DOWN", "NEUTRAL", "TITLE"):
            raise ValueError("orientation mode must be UP, DOWN, NEUTRAL or TITLE")
        if self.mode == "TITLE" and not (self.up or self.down):
            raise ValueError("a TITLE orientation needs up and/or down cues")
        return self


class ThemeCfg(_Strict):
    id: str
    label: str
    when: WhenCfg
    series: list[str] = Field(min_length=1)
    orientation: OrientationCfg


class MarketsConfig(_Strict):
    version: str
    providers: ProvidersCfg
    snapshot: SnapshotCfg
    matching: MatchingCfg
    interpretation: InterpretationCfg
    themes: list[ThemeCfg] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> MarketsConfig:
        ids = [t.id for t in self.themes]
        if len(set(ids)) != len(ids):
            raise ValueError("theme ids must be unique")
        return self


def load_markets_config(config_dir: Path, overrides: Mapping[str, Any] | None = None) -> MarketsConfig:
    path = config_dir / "external_markets.yaml"
    try:
        return MarketsConfig.model_validate(apply_overrides(_load(path), overrides))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
