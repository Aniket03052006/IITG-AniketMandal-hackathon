"""``configs/retrieval.yaml``: how the product serves analogues. The design (point-in-time rule, story collapse, reliability bar) is the pre-registered
one in ``configs/evidence_v3.yaml``; this file holds only the operational choices, and the similarity floor comes from the pre-registered floor rule
(``docs/evidence/analogue_floor.json``), which a test checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..config import ConfigError


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    enabled: bool = True
    index_dir: str = "data/replay/analogues"
    similarity_floor: float | Literal["rule"] = Field(default="rule", description="'rule': the value the pre-registered floor rule chose (docs/evidence/analogue_floor.json)")
    aggregate_over: int = Field(default=20, ge=5, le=100, description="distinct stories behind the summary statistics (display shows k)")

    @field_validator("similarity_floor")
    @classmethod
    def _floor_range(cls, v: float | str) -> float | str:
        if v != "rule" and not 0.0 < float(v) < 1.0:
            raise ValueError("similarity_floor must be 'rule' or a cosine similarity strictly between 0 and 1")
        return v


def load_retrieval_config(config_dir: Path) -> RetrievalConfig:
    path = config_dir / "retrieval.yaml"
    if not path.is_file():
        raise ConfigError(f"missing {path}")
    try:
        return RetrievalConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (ValidationError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def resolve_floor(cfg: RetrievalConfig, repo_root: Path) -> tuple[float | None, str | None]:
    """(floor, None) or (None, why not). ``rule`` reads the committed floor evidence; a missing file or a NOT_VIABLE rule is a reason, not a guess."""
    if cfg.similarity_floor != "rule":
        return float(cfg.similarity_floor), None
    path = repo_root / "docs" / "evidence" / "analogue_floor.json"
    if not path.is_file():
        return None, "the pre-registered similarity-floor rule has not been run: `make analogue-floor`"
    chosen = json.loads(path.read_text(encoding="utf-8")).get("chosen")
    if chosen is None:
        return None, "the pre-registered similarity-floor rule found no viable floor: analogue retrieval is not served"
    return float(chosen), None
