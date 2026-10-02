"""Validated modeling configuration (configs/modeling.yaml)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..config import ConfigError
from ..domain import EventCategory
from ..pipeline.config import _load


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImpactConfig(_Strict):
    market_symbol: str
    volatility_symbol: str
    exchange_timezone: str
    session_open: time
    session_close: time
    window_sessions: int = Field(ge=1, le=5)
    beta_window: int = Field(ge=30)
    sigma_window: int = Field(ge=20)
    min_history_sessions: int = Field(ge=30)
    sector_min_peers: int = Field(ge=1)
    min_link_confidence: float = Field(ge=0, le=1)
    exclude_multi_entity: bool
    require_dataset_ticker_agreement: bool
    score_cutpoints: list[float]
    placebo_offset_sessions: int = Field(le=-2)

    @field_validator("exchange_timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown time zone {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _valid(self) -> ImpactConfig:
        cuts = self.score_cutpoints
        if len(cuts) != 9 or any(c <= 0 for c in cuts) or cuts != sorted(set(cuts)):
            raise ValueError("score_cutpoints must be 9 strictly increasing positive numbers (scores 1..10)")
        if self.min_history_sessions > self.beta_window:
            raise ValueError("min_history_sessions cannot exceed beta_window")
        if self.sigma_window > self.beta_window:
            raise ValueError("sigma_window cannot exceed beta_window")
        if not self.session_open < self.session_close:
            raise ValueError("session_open must precede session_close")
        if self.placebo_offset_sessions + self.window_sessions > -1:
            raise ValueError("placebo window must end before the session before s0")
        return self


class ImpactSplitConfig(_Strict):
    embargo_sessions: int = Field(ge=0)
    train_end: date
    val_start: date
    val_end: date
    test_start: date
    test_end: date
    live_start: date

    @model_validator(mode="after")
    def _ordered(self) -> ImpactSplitConfig:
        if not (self.train_end < self.val_start <= self.val_end < self.test_start <= self.test_end < self.live_start):
            raise ValueError("split dates must be strictly ordered: train < val < test < live")
        return self


class TextSplitConfig(_Strict):
    seed: int
    fractions: dict[str, float]
    near_duplicate_threshold: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _fractions(self) -> TextSplitConfig:
        if set(self.fractions) != {"train", "valid", "test"} or abs(sum(self.fractions.values()) - 1) > 1e-9:
            raise ValueError("fractions must be train/valid/test and sum to 1")
        return self


class LeakageConfig(_Strict):
    max_near_duplicate_rate: float = Field(ge=0, le=1)
    placebo_warn_spearman: float = Field(ge=0, le=1)


class SplitsConfig(_Strict):
    impact: ImpactSplitConfig
    text: TextSplitConfig
    leakage: LeakageConfig


class GoldConfig(_Strict):
    seed: int
    near_duplicate_threshold: float = Field(gt=0, le=1)
    max_issuer_share: float = Field(gt=0, le=1)
    max_per_template: int = Field(ge=1)
    tfn_topic_per_topic: int = Field(ge=0)
    rare_class_per_class: dict[EventCategory, int]
    disagreement_event: int = Field(ge=0)
    disagreement_sentiment: int = Field(ge=0)
    hard_multi_entity: int = Field(ge=0)
    hard_weak_entity_rule: int = Field(ge=0)
    hard_date_only: int = Field(ge=0)
    random_per_source: int = Field(ge=0)
    adjudication_rows: int = Field(ge=0)
    consistency_rows: int = Field(ge=0)

    def planned_total(self, n_topics: int = 20, n_sources: int = 4) -> int:
        return (self.tfn_topic_per_topic * n_topics + sum(self.rare_class_per_class.values()) + self.disagreement_event
                + self.disagreement_sentiment + self.hard_multi_entity + self.hard_weak_entity_rule
                + self.hard_date_only + self.random_per_source * n_sources)


class ModelingConfig(_Strict):
    version: str
    impact: ImpactConfig
    splits: SplitsConfig
    gold: GoldConfig

    def digest(self) -> str:
        """Short hash of the whole config, stamped into every derived artefact."""
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


def load_modeling_config(config_dir: Path) -> ModelingConfig:
    path = config_dir / "modeling.yaml"
    try:
        return ModelingConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
