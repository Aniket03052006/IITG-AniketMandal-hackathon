"""What a signal is *about*: a company, a sector, the market, or nothing that could be established.

Company resolution is one way to find a subject, not a gate. A signal whose company could not be resolved still
carries whatever its text supports (a sector, a macro theme, a region) and says how it knew; when nothing is
supported it says ``UNRESOLVED`` and why. Nothing here is a probability: ``strength`` is a rule tier, not a calibrated
confidence (its measured hit rate is in ``docs/evidence/scope_eval.json``).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import ContractModel
from .documents import EntityMention
from .enums import UNKNOWN_ENTITY


class ScopeLevel(StrEnum):
    COMPANY = "COMPANY"  # one resolved issuer (its sector and country follow from the entity master)
    SECTOR = "SECTOR"  # no issuer, but the text is about one sector of the portfolio's universe
    MARKET = "MARKET"  # no issuer or sector: a macro / geopolitical / market-wide event
    UNRESOLVED = "UNRESOLVED"  # nothing could be established; the event is kept, not guessed about


class ScopeBasis(StrEnum):
    ENTITY_RESOLVER = "ENTITY_RESOLVER"  # a company was named (dictionary entity resolution)
    SECTOR_TERMS = "SECTOR_TERMS"  # sector vocabulary in the text
    THEME_TERMS = "THEME_TERMS"  # macro / market vocabulary in the text
    EVENT_MODEL = "EVENT_MODEL"  # the trained event model called it macroeconomic or geopolitical
    NONE = "NONE"


class ScopeStrength(StrEnum):
    STRONG = "STRONG"  # two or more distinct sector terms, no competing sector
    WEAK = "WEAK"  # a single distinct sector term


class SignalScope(ContractModel):
    level: ScopeLevel
    sector: str | None = Field(default=None, description="set for COMPANY and SECTOR scope")
    regions: list[str] = Field(default_factory=list, description="portfolio geography codes the text points to")
    themes: list[str] = Field(default_factory=list, description="macro / market themes the text names")
    basis: ScopeBasis = ScopeBasis.NONE
    strength: ScopeStrength | None = Field(
        default=None, description="rule tier for a SECTOR scope; not a probability")
    matched_terms: dict[str, list[str]] = Field(
        default_factory=dict, description="dimension (sector | theme | region) -> the terms that matched")
    note: str = Field(default="", description="why the scope is what it is, in plain words (always set when UNRESOLVED)")
    resolver_version: str = "entity-only"

    @property
    def has_sector(self) -> bool:
        return self.sector is not None and self.level in (ScopeLevel.COMPANY, ScopeLevel.SECTOR)


def scope_from_entity(entity: EntityMention) -> SignalScope:
    """The scope implied by entity resolution alone: COMPANY for a resolved entity, UNRESOLVED otherwise.

    Used for fixtures and for any caller that has no scope resolver; it never claims more than the entity says.
    """
    if entity.entity_id == UNKNOWN_ENTITY:
        return SignalScope(level=ScopeLevel.UNRESOLVED, note="No company was resolved and no scope resolver ran.")
    return SignalScope(
        level=ScopeLevel.COMPANY, sector=entity.sector, regions=[entity.country] if entity.country else [],
        basis=ScopeBasis.ENTITY_RESOLVER, note=f"{entity.entity_name or entity.entity_id} was named in the text.")
