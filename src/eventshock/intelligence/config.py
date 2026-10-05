"""Validated configuration for the event-intelligence layer (configs/intelligence.yaml). Every number is a judgement prior, not a fit."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError
from ..pipeline.config import _load
from ..pipeline.normalize import match_form


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Industry(_Strict):
    sector: str
    terms: list[str] = Field(min_length=1)


class ScopeVocab(_Strict):
    industry_min_terms: int = Field(default=1, ge=1)
    industries: dict[str, Industry]
    ticker_industry: dict[str, str]
    theme_kinds: dict[str, str]
    theme_risk_factors: dict[str, list[str]]
    region_names: dict[str, str]

    @model_validator(mode="after")
    def _consistent(self) -> ScopeVocab:
        owner: dict[str, str] = {}
        for name, ind in self.industries.items():
            for t in ind.terms:
                form = match_form(t)
                if not form:
                    raise ValueError(f"industry {name}: term {t!r} folds to nothing")
                if owner.setdefault(form, name) != name:
                    raise ValueError(f"industry term {t!r} belongs to both {owner[form]} and {name}")
        for ticker, ind in self.ticker_industry.items():
            if ind not in self.industries:
                raise ValueError(f"ticker {ticker} maps to unknown industry {ind!r}")
        for theme, kind in self.theme_kinds.items():
            if kind not in {"MACRO", "THEME", "MARKET"}:
                raise ValueError(f"theme {theme}: kind {kind!r} must be MACRO, THEME or MARKET")
        return self


class SourcesCfg(_Strict):
    authoritative_domains: list[str]
    copy_relations: list[str]


class GroupingCfg(_Strict):
    window_hours: float = Field(gt=0)
    min_shared_tokens: int = Field(ge=1)
    max_posting_length: int = Field(ge=1)
    min_cosine: float = Field(ge=0, le=1)
    min_shared_facts: int = Field(ge=0)
    unresolved_min_cosine: float = Field(ge=0, le=1)
    unresolved_min_shared_facts: int = Field(ge=0)


class EvidenceCfg(_Strict):
    strong_min_independent: int = Field(ge=1)
    strong_min_diversity: float = Field(ge=0, le=1)
    moderate_min_independent: int = Field(ge=1)
    conflict_caps_at: str = "WEAK"


class NoveltyCfg(_Strict):
    lookback_days: float = Field(gt=0)
    same_story_min_cosine: float = Field(ge=0, le=1)
    recurrence_gap_hours: float = Field(gt=0)
    min_new_facts: int = Field(ge=1)
    max_priors_shown: int = Field(ge=1)
    recurrence_cues: list[str]
    update_cues: list[str]


class VelocityCfg(_Strict):
    bucket_minutes: float = Field(gt=0)
    min_reports: int = Field(ge=2)
    min_span_hours: float = Field(gt=0)
    accel_min_reports: int = Field(ge=3)


class Axis(_Strict):
    label: str
    pos_label: str
    neg_label: str
    pos: list[str] = Field(min_length=1)
    neg: list[str] = Field(min_length=1)


class ClaimsCfg(_Strict):
    conflict_window_hours: float = Field(gt=0)
    min_conflict_tokens: int = Field(ge=1)
    max_subject_words: int = Field(ge=1)
    max_object_words: int = Field(ge=1)
    negators: list[str]
    hedges: list[str]
    retraction_cues: list[str]
    axes: dict[str, Axis]

    @model_validator(mode="after")
    def _cues_unambiguous(self) -> ClaimsCfg:
        owner: dict[str, str] = {}
        for aid, ax in self.axes.items():
            for pole, cues in (("pos", ax.pos), ("neg", ax.neg)):
                for c in cues:
                    form = match_form(c)
                    if not form:
                        raise ValueError(f"axis {aid}: cue {c!r} folds to nothing")
                    key = f"{aid}.{pole}"
                    if owner.setdefault(form, key) != key:
                        raise ValueError(f"claim cue {c!r} belongs to both {owner[form]} and {key}")
        return self


class LifecycleCfg(_Strict):
    confirmed_min_independent: int = Field(ge=1)
    resolution_min_independent: int = Field(ge=1)
    stale_after_hours: float = Field(gt=0)
    escalation_hold_hours: float = Field(gt=0)
    escalation_cues: list[str]
    deescalation_cues: list[str]
    resolution_cues: list[str]


class IntelligenceConfig(_Strict):
    version: str
    scope: ScopeVocab
    sources: SourcesCfg
    grouping: GroupingCfg
    evidence: EvidenceCfg
    novelty: NoveltyCfg
    velocity: VelocityCfg
    claims: ClaimsCfg
    lifecycle: LifecycleCfg


def load_intelligence_config(config_dir: Path) -> IntelligenceConfig:
    path = config_dir / "intelligence.yaml"
    try:
        return IntelligenceConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
