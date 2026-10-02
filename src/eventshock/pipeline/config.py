"""Validated configuration for the ingestion pipeline (configs/pipeline.yaml, placeholder_enrichment.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError
from ..domain import EventCategory


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in YAML must fail loudly, not be ignored


class ValidationConfig(_Strict):
    min_text_chars: int = Field(default=15, ge=1)
    max_text_chars: int = Field(default=2000, ge=10)
    min_alpha_ratio: float = Field(default=0.45, ge=0, le=1)
    allowed_languages: list[str] = ["en"]
    future_skew_minutes: float = Field(default=5, ge=0)


class ConfidenceConfig(_Strict):
    cashtag: float = Field(ge=0, le=1)
    legal_name: float = Field(ge=0, le=1)
    alias: float = Field(ge=0, le=1)
    weak_alias: float = Field(ge=0, le=1)
    fuzzy: float = Field(ge=0, le=1)


class FuzzyConfig(_Strict):
    enabled: bool = True
    min_ratio: float = Field(default=0.92, ge=0.5, le=1)
    min_alias_chars: int = Field(default=7, ge=3)


class EntityResolutionConfig(_Strict):
    version: str
    min_link_confidence: float = Field(ge=0, le=1)
    multi_entity_cap: float = Field(ge=0, le=1)
    confidence: ConfidenceConfig
    fuzzy: FuzzyConfig = FuzzyConfig()
    weak_aliases: list[str] = []
    weak_alias_neutralisers: list[str] = []
    finance_context: list[str] = []


class DedupConfig(_Strict):
    window_hours: float = Field(default=72, gt=0)
    near_duplicate_threshold: float = Field(default=0.8, gt=0, le=1)
    same_event_threshold: float = Field(default=0.6, gt=0, le=1)
    same_event_min_shared_tokens: int = Field(default=4, ge=1)
    same_event_window_hours: float = Field(default=48, gt=0)
    max_posting_length: int = Field(default=1500, ge=10, description="tokens in more clusters than this are not used to find candidates")

    @model_validator(mode="after")
    def _ordered(self) -> DedupConfig:
        if self.same_event_threshold > self.near_duplicate_threshold:
            raise ValueError("same_event_threshold must be <= near_duplicate_threshold")
        return self


class PipelineConfig(_Strict):
    version: str
    validation: ValidationConfig = ValidationConfig()
    entity_resolution: EntityResolutionConfig
    dedup: DedupConfig = DedupConfig()


class EventProbabilityConfig(_Strict):
    matched_primary: float = Field(gt=0, lt=1)
    per_extra_hit: float = Field(ge=0, lt=1)
    max_primary: float = Field(gt=0, lt=1)
    unmatched_market_valuation: float = Field(gt=0, lt=1)


class ImpactConfig(_Strict):
    tone_weight: float = Field(ge=0, le=1)
    corroboration_weight: float = Field(ge=0, le=1)
    category_prior: dict[EventCategory, float]

    @model_validator(mode="after")
    def _complete(self) -> ImpactConfig:
        if set(self.category_prior) != set(EventCategory):
            raise ValueError("category_prior must cover every EventCategory")
        if any(not 0 <= v <= 1 for v in self.category_prior.values()):
            raise ValueError("category_prior values must be in [0, 1]")
        return self


class SentimentConfig(_Strict):
    neutral_mass: float = Field(gt=0)
    positive: list[str]
    negative: list[str]


class EnrichmentConfig(_Strict):
    version: str
    sentiment: SentimentConfig
    event_keywords: dict[EventCategory, list[str]]
    event_probability: EventProbabilityConfig
    impact: ImpactConfig

    @model_validator(mode="after")
    def _complete(self) -> EnrichmentConfig:
        if set(self.event_keywords) != set(EventCategory):
            raise ValueError("event_keywords must cover every EventCategory")
        return self


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"missing config file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def load_pipeline_config(config_dir: Path) -> PipelineConfig:
    path = config_dir / "pipeline.yaml"
    try:
        return PipelineConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc


def load_enrichment_config(config_dir: Path) -> EnrichmentConfig:
    path = config_dir / "placeholder_enrichment.yaml"
    try:
        return EnrichmentConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
