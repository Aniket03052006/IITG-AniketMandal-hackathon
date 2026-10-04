"""Validated loaders for ``configs/semantics.yaml`` (the closed vocabulary) and ``configs/impact_hybrid.yaml`` (the severity weights).

Strict models (``extra="forbid"``): a typo in either file stops start-up instead of silently changing a score.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError
from ..domain import EventCategory
from ..pipeline.config import _load
from ..pipeline.normalize import match_form

SOURCE_TYPES = ("NEWS", "SOCIAL")
SCOPE_LEVELS = ("COMPANY", "SECTOR", "MARKET")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------------------------------------- semantics
class SentimentLabels(_Strict):
    negative_below: float = Field(lt=0)
    positive_above: float = Field(gt=0)
    intensity: dict[str, float]

    @model_validator(mode="after")
    def _keys(self) -> SentimentLabels:
        if set(self.intensity) != {"medium_from", "high_from"} or self.intensity["medium_from"] >= self.intensity["high_from"]:
            raise ValueError("intensity needs medium_from < high_from")
        return self


class Institution(_Strict):
    name: str
    kind: str
    region: str | None = None  # the jurisdiction naming it implies (a region code of scope.yaml)


class Indicator(_Strict):
    label: str
    weight: float = Field(ge=0, le=1)
    assets: list[str] = []
    cues: list[str] = Field(min_length=1)


class Subtype(_Strict):
    id: str
    label: str
    cues: list[str] = Field(min_length=1)


class SemanticsConfig(_Strict):
    version: str
    sentiment_label: SentimentLabels
    asset_classes: list[str]
    institutions: list[Institution]
    org_verbs: list[str]
    not_organisations: list[str] = []
    indicators: dict[str, Indicator]
    subtypes: dict[EventCategory, list[Subtype]]

    @model_validator(mode="after")
    def _consistent(self) -> SemanticsConfig:
        if set(self.subtypes) != set(EventCategory):
            raise ValueError("subtypes must cover every EventCategory")
        known = set(self.asset_classes)
        for k, ind in self.indicators.items():
            bad = set(ind.assets) - known
            if bad:
                raise ValueError(f"indicator {k}: unknown asset classes {sorted(bad)}")
            if any(not match_form(c) for c in ind.cues):
                raise ValueError(f"indicator {k}: a cue folds to nothing")
        ids = [s.id for subs in self.subtypes.values() for s in subs]
        if len(ids) != len(set(ids)):
            raise ValueError("subtype ids must be unique across categories")
        return self

    def subtype_ids(self, category: EventCategory) -> list[str]:
        return [s.id for s in self.subtypes[category]]

    def subtype(self, category: EventCategory, sid: str) -> Subtype | None:
        return next((s for s in self.subtypes[category] if s.id == sid), None)


def load_semantics_config(config_dir: Path) -> SemanticsConfig:
    path = config_dir / "semantics.yaml"
    try:
        return SemanticsConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc


# ------------------------------------------------------------------------------------------------------------------------ hybrid
class Weights(_Strict):
    category_prior: float = Field(ge=0)
    severity_indicators: float = Field(ge=0)
    tone: float = Field(ge=0)
    novelty: float = Field(ge=0)
    breadth: float = Field(ge=0)
    source_credibility: float = Field(ge=0)
    market_regime: float = Field(ge=0)

    @model_validator(mode="after")
    def _positive_total(self) -> Weights:
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("weights must not all be zero")
        return self


class ToneConfig(_Strict):
    favourable_weight: float = Field(ge=0, le=1)


class BreadthConfig(_Strict):
    scope_base: dict[str, float]
    per_extra_item: float = Field(ge=0, le=1)
    items_free: int = Field(ge=0)

    @model_validator(mode="after")
    def _levels(self) -> BreadthConfig:
        if set(self.scope_base) != set(SCOPE_LEVELS) or any(not 0 <= v <= 1 for v in self.scope_base.values()):
            raise ValueError(f"scope_base needs {SCOPE_LEVELS} in [0, 1]")
        return self


class SourceCredibilityConfig(_Strict):
    type_prior: dict[str, float]
    type_share: float = Field(ge=0, le=1)
    corroboration_cap: int = Field(ge=1)

    @model_validator(mode="after")
    def _types(self) -> SourceCredibilityConfig:
        if set(self.type_prior) != set(SOURCE_TYPES) or any(not 0 <= v <= 1 for v in self.type_prior.values()):
            raise ValueError(f"type_prior needs {SOURCE_TYPES} in [0, 1]")
        return self


class MarketRegimeConfig(_Strict):
    vix_points: list[tuple[float, float]] = Field(min_length=2)
    max_staleness_days: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> MarketRegimeConfig:
        xs = [p[0] for p in self.vix_points]
        if xs != sorted(xs) or len(set(xs)) != len(xs) or any(not 0 <= p[1] <= 1 for p in self.vix_points):
            raise ValueError("vix_points must be increasing in VIX with factor values in [0, 1]")
        return self


class SensitivityConfig(_Strict):
    delta: float = Field(gt=0, lt=1)


class ConflictConfig(_Strict):
    window_hours: float = Field(gt=0)
    min_abs_sentiment: float = Field(ge=0, le=1)


class HybridConfig(_Strict):
    version: str
    weights: Weights
    category_prior: dict[EventCategory, float]
    NO_EVENT_prior: float = Field(ge=0, le=1)
    tone: ToneConfig
    breadth: BreadthConfig
    source_credibility: SourceCredibilityConfig
    market_regime: MarketRegimeConfig
    uncertainty_discount: float = Field(ge=0, le=1)
    unknown_uncertainty: float = Field(ge=0, le=1)
    sensitivity: SensitivityConfig
    conflict: ConflictConfig

    @model_validator(mode="after")
    def _priors(self) -> HybridConfig:
        if set(self.category_prior) != set(EventCategory) or any(not 0 <= v <= 1 for v in self.category_prior.values()):
            raise ValueError("category_prior must cover every EventCategory with values in [0, 1]")
        return self


def load_hybrid_config(config_dir: Path) -> HybridConfig:
    path = config_dir / "impact_hybrid.yaml"
    try:
        return HybridConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
