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
    level: int = Field(ge=0, le=4, description="the typical materiality level (rubric magnitude) of this kind of development for one issuer")
    polarity: str = Field(pattern="^(adverse|favourable|neutral)$")
    event_class: EventCategory
    assets: list[str] = []
    cues: list[str] = Field(min_length=1)


class AmountFloor(_Strict):
    min_usd: float = Field(gt=0)
    level: int = Field(ge=1, le=4)


class ReachVocab(_Strict):
    global_cues: list[str]
    market_cues: list[str]
    generic_firm_pattern: str


class CertaintyVocab(_Strict):
    speculative_cues: list[str]
    proposed_cues: list[str]


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
    scale_up: list[str]
    scale_down: list[str]
    reach: ReachVocab
    certainty: CertaintyVocab
    amount_floor: list[AmountFloor]
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


# ---------------------------------------------------------------------------------------------------------------------------- severity
REACH_ORDER = ("firm", "sector", "market", "global")
CERTAINTY_ORDER = ("confirmed", "proposed", "speculative")  # most to least certain
DIRECTION_ORDER = ("adverse", "mixed", "neutral", "favourable")  # most to least downside


class Band(_Strict):
    id: str
    label: str
    low: int
    high: int
    says: str


class MagnitudeLevel(_Strict):
    label: str
    anchor: float = Field(ge=1, le=10)
    says: str


class ReachLevel(_Strict):
    label: str
    offset: float
    says: str


class FactorLevel(_Strict):
    label: str
    factor: float = Field(gt=0, le=1)
    says: str


class RegimeConfig(_Strict):
    vix_points: list[tuple[float, float]] = Field(min_length=2)
    max_sessions_behind: int = Field(ge=0)
    session_close_utc_hour: int = Field(ge=0, le=23)

    @model_validator(mode="after")
    def _ordered(self) -> RegimeConfig:
        xs = [p[0] for p in self.vix_points]
        if xs != sorted(xs) or len(set(xs)) != len(xs):
            raise ValueError("vix_points must be increasing in VIX")
        return self


class NoveltyConfig(_Strict):
    neutral_point: float = Field(ge=0, le=1)
    strength: float = Field(ge=0)


class Compounding(_Strict):
    min_indicators: int = Field(ge=2)
    min_level: int = Field(ge=1, le=4)
    steps: int = Field(ge=0, le=2)


class BaselineConfig(_Strict):
    compounding: Compounding
    event_without_indicator_level: int = Field(ge=0, le=4)
    scale_step: int = Field(ge=0, le=2)


class AIAdjustment(_Strict):
    free_steps: int = Field(ge=0, le=2)
    require_reason: bool
    min_reason_chars: int = Field(ge=1)
    uninformed_baseline_accepts_quoted_answer: bool


class ReliabilityConfig(_Strict):
    type_prior: dict[str, float]
    type_share: float = Field(ge=0, le=1)
    corroboration_cap: int = Field(ge=1)
    high_from: float = Field(ge=0, le=1)
    moderate_from: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _types(self) -> ReliabilityConfig:
        if set(self.type_prior) != set(SOURCE_TYPES) or self.moderate_from > self.high_from:
            raise ValueError(f"type_prior needs {SOURCE_TYPES}; moderate_from must not exceed high_from")
        return self


class SensitivityConfig(_Strict):
    anchor_shift: float = Field(ge=0)
    factor_delta: float = Field(ge=0, lt=1)
    adjustment_scales: list[float]


class ConflictConfig(_Strict):
    window_hours: float = Field(gt=0)
    min_abs_sentiment: float = Field(ge=0, le=1)


class SeverityConfig(_Strict):
    version: str
    bands: list[Band]
    magnitude: dict[int, MagnitudeLevel]
    reach: dict[str, ReachLevel]
    certainty: dict[str, FactorLevel]
    direction: dict[str, FactorLevel]
    regime: RegimeConfig
    novelty: NoveltyConfig
    baseline: BaselineConfig
    ai_adjustment: AIAdjustment
    reliability: ReliabilityConfig
    sensitivity: SensitivityConfig
    conflict: ConflictConfig

    @model_validator(mode="after")
    def _complete(self) -> SeverityConfig:
        if sorted(self.magnitude) != [0, 1, 2, 3, 4]:
            raise ValueError("magnitude needs levels 0..4")
        if set(self.reach) != set(REACH_ORDER) or set(self.certainty) != set(CERTAINTY_ORDER) or set(self.direction) != set(DIRECTION_ORDER):
            raise ValueError("reach, certainty and direction must define exactly their levels")
        spans = [(b.low, b.high) for b in self.bands]
        if spans[0][0] != 1 or spans[-1][1] != 10 or any(spans[i][1] + 1 != spans[i + 1][0] for i in range(len(spans) - 1)):
            raise ValueError("bands must tile 1..10 without gaps")
        anchors = [self.magnitude[k].anchor for k in range(5)]
        if anchors != sorted(anchors):
            raise ValueError("magnitude anchors must not decrease")
        return self

    def band_of(self, score: int) -> Band:
        return next(b for b in self.bands if b.low <= score <= b.high)


def load_severity_config(config_dir: Path) -> SeverityConfig:
    path = config_dir / "severity.yaml"
    try:
        return SeverityConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
