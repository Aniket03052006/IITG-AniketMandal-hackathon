"""Validated configuration of the decision side-cars (configs/decision.yaml). Every number is a judgement prior, not a fit."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError
from ..config_overrides import apply_overrides
from ..pipeline.config import _load

MATERIALITY_LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE", "UNDETERMINED")
DIGEST_SECTIONS = ("NEW_RISKS", "ESCALATIONS", "EXPOSURE_CHANGES", "STRESS_CHANGES", "EVIDENCE_CHANGES", "CONFLICTS", "CONCENTRATION", "WATCHLISTS")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MonitorCfg(_Strict):
    replay_step_hours: float = Field(gt=0)
    replay_max_cycles: int = Field(ge=2)
    escalation_delta: float = Field(gt=0)
    stress_change_pp: float = Field(gt=0)
    exposure_change_pp: float = Field(gt=0)
    track_min_severity: float = Field(ge=1, le=10)
    track_min_materiality: str
    max_tracked_events: int = Field(ge=1)
    max_changes_returned: int = Field(ge=1)
    store_max_changes: int = Field(ge=10)

    @model_validator(mode="after")
    def _level(self) -> MonitorCfg:
        if self.track_min_materiality not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            raise ValueError("track_min_materiality must be LOW, MEDIUM, HIGH or CRITICAL")
        return self


class MemoryCfg(_Strict):
    escalation_rules: list[str]
    de_escalation_rules: list[str]
    resolution_rules: list[str]
    update_min_new_facts: int = Field(ge=1)

    @model_validator(mode="after")
    def _disjoint(self) -> MemoryCfg:
        seen: dict[str, str] = {}
        for name in ("escalation_rules", "de_escalation_rules", "resolution_rules"):
            for rule in getattr(self, name):
                if seen.setdefault(rule, name) != name:
                    raise ValueError(f"lifecycle rule {rule!r} is listed under both {seen[rule]} and {name}")
        return self


class WatchlistCfg(_Strict):
    max_watchlists: int = Field(ge=1, le=200)
    max_items: int = Field(ge=1, le=500)
    max_events_per_item: int = Field(ge=1, le=100)
    max_scan_events: int = Field(ge=10, le=5000)
    top_holdings_max: int = Field(ge=1, le=50)
    name_max_chars: int = Field(ge=10, le=200)


class Bound(_Strict):
    min: float
    max: float
    unit: str

    @model_validator(mode="after")
    def _ordered(self) -> Bound:
        if self.min >= self.max:
            raise ValueError("a bound needs min < max")
        return self


class RiskFactorBound(Bound):
    kind: str

    @model_validator(mode="after")
    def _kind(self) -> RiskFactorBound:
        if self.kind not in ("RATES", "EQUITY_MARKET", "CREDIT_SPREAD", "COMMODITY", "FX", "PD_MULTIPLIER", "PROXY"):
            raise ValueError(f"unknown risk-factor kind {self.kind!r}")
        return self


LAB_KINDS = ("EQUITY_MARKET", "RATES", "CREDIT_SPREAD", "COMMODITY", "FX", "SECTOR", "ISSUER")


class LabCfg(_Strict):
    max_assumptions: int = Field(ge=1, le=50)
    max_compared: int = Field(ge=2, le=5)
    bounds: dict[str, Bound]
    risk_factors: dict[str, RiskFactorBound]
    commodity_sector_priors: dict[str, float]

    @model_validator(mode="after")
    def _complete(self) -> LabCfg:
        if set(self.bounds) != set(LAB_KINDS):
            raise ValueError(f"lab.bounds must list exactly {list(LAB_KINDS)}")
        for sector, k in self.commodity_sector_priors.items():
            if not -5 <= k <= 5:
                raise ValueError(f"commodity prior for {sector} must be within [-5, 5]")
        return self


REVERSE_KINDS = ("EQUITY_MARKET", "CREDIT_SPREAD", "RATES", "COMMODITY", "SECTOR_EACH")


class BasketAxis(_Strict):
    id: str
    kind: str
    sign: int | str
    bound: float = Field(gt=0)
    unit: str

    @model_validator(mode="after")
    def _ok(self) -> BasketAxis:
        if self.kind not in REVERSE_KINDS:
            raise ValueError(f"basket kind {self.kind!r} must be one of {list(REVERSE_KINDS)}")
        if self.sign not in (-1, 1, "auto"):
            raise ValueError("basket sign must be -1, 1 or auto")
        return self


class ReverseCfg(_Strict):
    presets_pct: list[float]
    min_target_pct: float = Field(lt=0, ge=-100)
    tolerance_pp: float = Field(gt=0, le=1)
    grid_levels: int = Field(ge=2, le=12)
    max_axes: int = Field(ge=1, le=4)
    probe_fraction: float = Field(gt=0, le=1)
    max_evaluations: int = Field(ge=50, le=5000)
    basket: list[BasketAxis] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> ReverseCfg:
        if any(not (self.min_target_pct <= p < 0) for p in self.presets_pct):
            raise ValueError("every preset must be a loss between min_target_pct and 0")
        if len({a.id for a in self.basket}) != len(self.basket):
            raise ValueError("basket ids must be unique")
        if (self.grid_levels + 1) ** self.max_axes + 2 * len(self.basket) + 60 > self.max_evaluations:
            raise ValueError("max_evaluations is too small for the grid: raise it or lower grid_levels / max_axes")
        return self


class FeedbackCfg(_Strict):
    max_comment_chars: int = Field(ge=0, le=5000)
    max_records: int = Field(ge=10)
    max_list: int = Field(ge=1, le=2000)


class DigestCfg(_Strict):
    per_section: int = Field(ge=1, le=50)
    materiality_order: list[str]
    sections: list[str]

    @model_validator(mode="after")
    def _known(self) -> DigestCfg:
        if sorted(self.materiality_order) != sorted(MATERIALITY_LEVELS):
            raise ValueError(f"materiality_order must list exactly {list(MATERIALITY_LEVELS)}")
        bad = [s for s in self.sections if s not in DIGEST_SECTIONS]
        if bad or len(set(self.sections)) != len(self.sections):
            raise ValueError(f"digest sections must be unique and drawn from {list(DIGEST_SECTIONS)}; got {self.sections}")
        return self


class DecisionConfig(_Strict):
    version: str
    monitor: MonitorCfg
    memory: MemoryCfg
    watchlist: WatchlistCfg
    lab: LabCfg
    reverse: ReverseCfg
    feedback: FeedbackCfg
    digest: DigestCfg


def load_decision_config(config_dir: Path, overrides: Mapping[str, Any] | None = None) -> DecisionConfig:
    path = config_dir / "decision.yaml"
    try:
        return DecisionConfig.model_validate(apply_overrides(_load(path), overrides))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
