"""Twitter-Financial-News topic labels -> EventShock event classes (configs/topic_mapping.yaml)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from ..config import ConfigError
from ..domain import EventCategory
from .config import _load

Tier = Literal["strong", "medium", "weak"]
TIER_RANK: dict[str, int] = {"weak": 0, "medium": 1, "strong": 2}


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    category: EventCategory | None
    tier: Tier | None = None  # how far the topic -> class mapping can be trusted; required whenever a class is given
    rationale: str = ""

    @model_validator(mode="after")
    def _tier_iff_mapped(self) -> Topic:
        if (self.category is None) != (self.tier is None):
            raise ValueError(f"topic {self.name!r}: tier is required exactly when category is set")
        return self


class TopicMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    dataset: str
    topics: dict[int, Topic]

    @model_validator(mode="after")
    def _contiguous(self) -> TopicMapping:
        if sorted(self.topics) != list(range(len(self.topics))):
            raise ValueError("topic ids must be 0..N-1 without gaps")
        return self

    def category(self, label: int) -> EventCategory | None:
        if label not in self.topics:
            raise KeyError(f"unknown topic label {label}")
        return self.topics[label].category

    def tier(self, label: int) -> Tier | None:
        if label not in self.topics:
            raise KeyError(f"unknown topic label {label}")
        return self.topics[label].tier

    def trainable(self, label: int, min_tier: Tier = "medium") -> EventCategory | None:
        """The class for a topic if its tier is at least ``min_tier``; None for unmapped or too-weak topics."""
        cat = self.category(label)
        t = self.tier(label)
        return cat if cat is not None and t is not None and TIER_RANK[t] >= TIER_RANK[min_tier] else None

    def distribution(self, labels: Iterable[int]) -> dict[str, int]:
        """Mapped class counts for a list of topic labels; unmapped topics are counted under ``UNMAPPED``."""
        c = Counter((self.category(x).value if self.category(x) else "UNMAPPED") for x in labels)
        return dict(sorted(c.items()))


def load_topic_mapping(config_dir: Path) -> TopicMapping:
    path = config_dir / "topic_mapping.yaml"
    try:
        return TopicMapping.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
