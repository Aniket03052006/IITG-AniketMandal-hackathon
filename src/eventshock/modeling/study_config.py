"""Validated loader for ``configs/evidence_v2.yaml``: the Stage 4 pre-registration (protocols, adoption rules, added acceptance checks)."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError
from .config import ImpactSplitConfig


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Protocol(_Strict):
    embargo_sessions: int = Field(ge=0)
    train_end: date
    val: tuple[date, date]
    test: tuple[date, date]
    live_start: date

    def split_config(self) -> ImpactSplitConfig:
        return ImpactSplitConfig(embargo_sessions=self.embargo_sessions, train_end=self.train_end, val_start=self.val[0], val_end=self.val[1],
                                 test_start=self.test[0], test_end=self.test[1], live_start=self.live_start)


class Battery(_Strict):
    vol_buckets: int = Field(ge=2)
    min_episodes_per_cell: int = Field(ge=2)
    control: dict[str, Any]
    permutation_repeats: int = Field(ge=10)
    permutation_within: list[str]
    min_year_episodes: int = Field(ge=10)


class AcceptanceAdded(_Strict):
    c9_regime_neutral_spearman_ci_lower_above: float
    c10_block_increment_mae_ci_upper_below: float
    c11_positive_year_share_at_least: float = Field(gt=0, le=1)


class ImpactStudy(_Strict):
    rungs: list[str]
    adoption: str
    fit: dict[str, Any]
    folds: dict[str, Any]
    chain: list[str]
    side_branch: list[str]
    battery: Battery
    acceptance_added: AcceptanceAdded
    bootstrap_resamples: int = Field(ge=100)
    bootstrap_seed: int


class StudyConfig(_Strict):
    version: str
    seed: int
    data: dict[str, Any]
    protocols: dict[str, Any]
    structured_features: dict[str, Any]
    representation: dict[str, Any]
    impact: ImpactStudy
    gold_v2: dict[str, Any]

    @model_validator(mode="after")
    def _valid(self) -> StudyConfig:
        if not {"P1_legacy", "P2_extended"} <= set(self.protocols):
            raise ValueError("protocols must define P1_legacy and P2_extended")
        return self

    def protocol(self, name: str) -> Protocol:
        return Protocol.model_validate(self.protocols[name])

    @property
    def tolerance(self) -> float:
        return float(self.protocols["p1_regression_tolerance_spearman"])


def load_study_config(config_dir: Path) -> tuple[StudyConfig, str]:
    """The config and the sha256 of its file (stamped into every artifact so the pre-registration is verifiable)."""
    path = config_dir / "evidence_v2.yaml"
    try:
        raw = path.read_bytes()
        cfg = StudyConfig.model_validate(yaml.safe_load(raw))
        # validate the protocol blocks now, not when first used
        for name in ("P1_legacy", "P2_extended"):
            cfg.protocol(name).split_config()
    except (OSError, ValueError) as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
    return cfg, hashlib.sha256(raw).hexdigest()
