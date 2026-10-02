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


class WordFeatures(_Strict):
    ngram_range: tuple[int, int] = (1, 2)
    min_df: int = Field(default=2, ge=1)


class CharFeatures(_Strict):
    ngram_range: tuple[int, int] = (2, 5)
    min_df: int = Field(default=3, ge=1)


class CandidateGrid(_Strict):
    preprocessing: list[str]
    C: list[float]
    class_weight: list[str | None]

    @model_validator(mode="after")
    def _valid(self) -> CandidateGrid:
        if not self.preprocessing or not self.C or not self.class_weight:
            raise ValueError("every grid axis needs at least one value")
        if any(p not in ("raw", "normalised") for p in self.preprocessing):
            raise ValueError("preprocessing must be 'raw' or 'normalised'")
        if any(c <= 0 for c in self.C):
            raise ValueError("C must be positive")
        if any(w not in (None, "balanced") for w in self.class_weight):
            raise ValueError("class_weight must be null or 'balanced'")
        return self


class SentimentEvalConfig(_Strict):
    ece_bins: int = Field(default=10, ge=2)
    bootstrap_resamples: int = Field(default=1000, ge=100)
    bootstrap_seed: int = 7
    lexicon_threshold: float = Field(default=0.12, gt=0, lt=1, description="same cut as modeling.probe, for a like-for-like baseline")
    product_threshold: float = Field(default=0.15, gt=0, lt=1, description="the UI's Negative/Positive cut (web/src/lib/severity.ts)")
    confident_errors: int = Field(default=12, ge=0)
    near_duplicate_threshold: float = Field(default=0.7, gt=0, le=1)


class SentimentModelConfig(_Strict):
    """configs/sentiment_model.yaml: how the sentiment model is trained, selected, evaluated and where it lives."""

    version: str
    model_dir: str
    table: str
    seed: int
    word: WordFeatures = WordFeatures()
    char: CharFeatures = CharFeatures()
    max_iter: int = Field(default=1000, ge=100)
    grid: CandidateGrid
    selection_rule: str = "valid_log_loss_after_temperature"
    temperature_grid: tuple[float, float, float] = (0.5, 4.0, 0.01)  # lo, hi, step
    evaluation: SentimentEvalConfig = SentimentEvalConfig()

    @model_validator(mode="after")
    def _valid(self) -> SentimentModelConfig:
        if self.selection_rule != "valid_log_loss_after_temperature":
            raise ValueError("unknown selection_rule")
        lo, hi, step = self.temperature_grid
        if not 0 < lo < hi or step <= 0:
            raise ValueError("temperature_grid must be (lo, hi, step) with 0 < lo < hi and step > 0")
        return self


def load_sentiment_model_config(config_dir: Path) -> SentimentModelConfig:
    path = config_dir / "sentiment_model.yaml"
    try:
        return SentimentModelConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc


class EventLabelsConfig(_Strict):
    """How the annotation pools are drawn (modeling.event_labels). Nothing here is a model hyper-parameter."""

    seed: int
    near_duplicate_threshold: float = Field(gt=0, le=1)
    population_per_source: dict[str, int]
    rare_per_class: int = Field(ge=0)
    tfn_topic_rows: dict[int, int]
    replay_check: dict[str, int]
    consistency_rows: int = Field(ge=0)
    dev_fraction: float = Field(gt=0, lt=0.5)

    @model_validator(mode="after")
    def _valid(self) -> EventLabelsConfig:
        for name, d in (("population_per_source", self.population_per_source), ("tfn_topic_rows", self.tfn_topic_rows),
                        ("replay_check", self.replay_check)):
            if any(n <= 0 for n in d.values()):
                raise ValueError(f"{name}: every quota must be positive")
        return self


class SilverConfig(_Strict):
    use: bool
    max_rows_per_class: int = Field(ge=1)
    sample_weight: float = Field(gt=0, le=1)


class AbstentionConfig(_Strict):
    commit_threshold: float = Field(gt=0, lt=1)
    min_train_examples: int = Field(ge=1)
    min_dev_support: int = Field(ge=1)
    dev_f1_floor: float = Field(ge=0, lt=1)
    route_unreliable_to_uncertain: bool


class EventEvalConfig(_Strict):
    ece_bins: int = Field(default=10, ge=2)
    bootstrap_resamples: int = Field(default=1000, ge=100)
    bootstrap_seed: int = 7
    confident_errors: int = Field(default=15, ge=0)
    near_duplicate_threshold: float = Field(default=0.7, gt=0, le=1)


class EventModelConfig(_Strict):
    """configs/event_model.yaml: how the event model is labelled, trained, selected, evaluated and where it lives."""

    version: str
    model_dir: str
    table: str
    labels_file: str
    manifest_file: str
    seed: int
    labels: EventLabelsConfig
    silver: SilverConfig
    word: WordFeatures = WordFeatures()
    char: CharFeatures = CharFeatures()
    max_iter: int = Field(default=1000, ge=100)
    grid: CandidateGrid
    selection_rule: str = "valid_log_loss_after_temperature"
    temperature_grid: tuple[float, float, float] = (0.5, 4.0, 0.01)
    abstention: AbstentionConfig
    evaluation: EventEvalConfig = EventEvalConfig()

    @model_validator(mode="after")
    def _valid(self) -> EventModelConfig:
        if self.selection_rule != "valid_log_loss_after_temperature":
            raise ValueError("unknown selection_rule")
        lo, hi, step = self.temperature_grid
        if not 0 < lo < hi or step <= 0:
            raise ValueError("temperature_grid must be (lo, hi, step) with 0 < lo < hi and step > 0")
        return self


def load_event_model_config(config_dir: Path) -> EventModelConfig:
    path = config_dir / "event_model.yaml"
    try:
        return EventModelConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
