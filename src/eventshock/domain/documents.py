"""Source documents and entity resolution contracts (PRD §10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from .base import ContractModel
from .enums import UNKNOWN_ENTITY, SourceType


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class RawDocument(ContractModel):
    """Common shape every source adapter normalises into (FR-01, FR-02)."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1, description="Human-readable source name")
    source_type: SourceType
    published_at: datetime
    ingested_at: datetime
    author: str | None = None
    headline: str
    body: str = ""
    url: str | None = None
    language: str = "en"
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    aware_check = field_validator("published_at", "ingested_at")(_require_aware)

    @model_validator(mode="after")
    def _text_and_order(self) -> RawDocument:
        if not (self.headline.strip() or self.body.strip()):
            raise ValueError("document needs a non-empty headline or body")
        if self.ingested_at < self.published_at:
            raise ValueError("ingested_at cannot precede published_at")
        return self


class Entity(ContractModel):
    """Canonical company record (entity master)."""

    entity_id: str = Field(min_length=1)
    name: str
    ticker: str | None = None
    sector: str
    country: str
    aliases: list[str] = Field(default_factory=list)


class EntityMention(ContractModel):
    """Result of entity resolution for one document. ``UNKNOWN_ENTITY`` is a first-class state."""

    entity_id: str = UNKNOWN_ENTITY
    entity_name: str | None = None
    ticker: str | None = None
    sector: str | None = None
    country: str | None = None
    link_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def is_unknown(self) -> bool:
        return self.entity_id == UNKNOWN_ENTITY
