"""Scope resolution: what is this event about, when it may not name a company?

Company resolution (``entities.py``) is an enrichment, never a gate. After it, this module decides the *scope* of a signal
with an ordered, explainable rule table over a configured vocabulary (``configs/scope.yaml``):

1. a resolved company -> COMPANY (sector and country from the entity master);
2. the event model says "not a market event" -> UNRESOLVED (a subject is not guessed for chatter);
3. one sector with >= 2 distinct vocabulary terms, no other sector tied -> SECTOR (STRONG);
4. a macro/geopolitical event (event model, status CLASSIFIED) or any macro/market theme term -> MARKET;
5. one sector with exactly 1 distinct term, no tie -> SECTOR (WEAK);
6. otherwise UNRESOLVED, with the reason.

Pure and deterministic. It reads text and the event decision only; it never touches an impact feature, so the trained
stages keep exactly the inputs they were fitted on. Nothing here is a probability: ``strength`` is a rule tier whose
measured hit rate lives in ``docs/evidence/scope_eval.json``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError
from ..domain import (
    UNKNOWN_ENTITY,
    EntityMention,
    EventCategory,
    EventClassification,
    EventStatus,
    ScopeBasis,
    ScopeLevel,
    ScopeStrength,
    SignalScope,
)
from .config import _load
from .normalize import match_form


class SectorRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strong_min_terms: int = Field(default=2, ge=1)
    weak_allowed: bool = True


class ScopeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    sector: SectorRules = SectorRules()
    market_categories: list[EventCategory] = []
    sector_neutralisers: list[str] = []
    sectors: dict[str, list[str]]
    themes: dict[str, list[str]]
    regions: dict[str, list[str]]

    @model_validator(mode="after")
    def _terms_are_unambiguous(self) -> ScopeConfig:
        for dim, table in (("sectors", self.sectors), ("themes", self.themes), ("regions", self.regions)):
            owner: dict[str, str] = {}
            for key, terms in table.items():
                if not terms:
                    raise ValueError(f"{dim}.{key} has no terms")
                for t in terms:
                    form = match_form(t)
                    if not form:
                        raise ValueError(f"{dim}.{key}: term {t!r} folds to nothing")
                    if owner.setdefault(form, key) != key:
                        raise ValueError(f"{dim}: term {t!r} belongs to both {owner[form]} and {key}")
        return self


def load_scope_config(config_dir: Path) -> ScopeConfig:
    path = config_dir / "scope.yaml"
    try:
        return ScopeConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc


def _alternation(forms: list[str]) -> re.Pattern[str] | None:
    if not forms:
        return None
    alts = "|".join(re.escape(f) for f in sorted(set(forms), key=len, reverse=True))
    return re.compile(r"(?<![a-z0-9$])(?:" + alts + r")(?![a-z0-9])")


class _Dimension:
    """term -> key lookup plus one longest-first alternation, so overlapping terms ("oil" inside "oil prices") count once."""

    def __init__(self, table: dict[str, list[str]]) -> None:
        self.owner = {match_form(t): key for key, terms in table.items() for t in terms}
        self.pattern = _alternation(list(self.owner))

    def hits(self, folded: str) -> dict[str, list[str]]:
        """key -> distinct matched terms, each in the order first seen."""
        out: dict[str, list[str]] = defaultdict(list)
        if self.pattern is None:
            return out
        for m in self.pattern.finditer(folded):
            term = m.group(0)
            bucket = out[self.owner[term]]
            if term not in bucket:
                bucket.append(term)
        return out


class ScopeResolver:
    def __init__(self, cfg: ScopeConfig) -> None:
        self.cfg = cfg
        self.version = cfg.version
        self._sectors = _Dimension(cfg.sectors)
        self._themes = _Dimension(cfg.themes)
        self._regions = _Dimension(cfg.regions)
        self._neutral = _alternation([match_form(n) for n in cfg.sector_neutralisers])

    # ------------------------------------------------------------------------------------------------ vocabulary probes
    def sector_hits(self, text: str) -> dict[str, list[str]]:
        """sector -> distinct vocabulary terms in ``text`` (neutralised); used by the evaluation script as well."""
        folded = match_form(text)
        if self._neutral is not None:
            folded = self._neutral.sub(lambda m: " " * len(m.group(0)), folded)
        return dict(self._sectors.hits(folded))

    def region_hits(self, text: str) -> dict[str, list[str]]:
        """region code -> distinct vocabulary terms in ``text`` (read-only probe for the assessment layer)."""
        return dict(self._regions.hits(match_form(text)))

    def theme_hits(self, text: str) -> dict[str, list[str]]:
        """theme -> distinct vocabulary terms in ``text`` (read-only probe for the assessment layer)."""
        return dict(self._themes.hits(match_form(text)))

    def unique_sector(self, hits: dict[str, list[str]]) -> tuple[str, list[str]] | None:
        ranked = sorted(hits.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        if not ranked:
            return None
        if len(ranked) > 1 and len(ranked[1][1]) == len(ranked[0][1]):
            return None  # a tie between sectors is not a subject
        return ranked[0]

    # ------------------------------------------------------------------------------------------------------- the rule table
    def resolve(self, text: str, entity: EntityMention, event: EventClassification | None = None) -> SignalScope:
        v = self.version
        if entity.entity_id != UNKNOWN_ENTITY:
            return SignalScope(
                level=ScopeLevel.COMPANY, sector=entity.sector, regions=[entity.country] if entity.country else [],
                basis=ScopeBasis.ENTITY_RESOLVER, resolver_version=v,
                note=f"{entity.entity_name or entity.entity_id} was named in the text.")
        if event is not None and event.status is EventStatus.NO_EVENT:
            return SignalScope(
                level=ScopeLevel.UNRESOLVED, resolver_version=v,
                note="The event model judged this text not to be a market event, so no subject is assigned.")

        folded = match_form(text)
        sectors = self.sector_hits(text)
        themes = dict(self._themes.hits(folded))
        regions = dict(self._regions.hits(folded))
        theme_keys = sorted(themes)
        region_keys = sorted(regions)
        matched: dict[str, list[str]] = {}
        if themes:
            matched["theme"] = [t for k in theme_keys for t in themes[k]]
        if regions:
            matched["region"] = [t for k in region_keys for t in regions[k]]
        top = self.unique_sector(sectors)

        def scope(level: ScopeLevel, basis: ScopeBasis, note: str, *, sector: str | None = None,
                  strength: ScopeStrength | None = None, sector_terms: list[str] | None = None) -> SignalScope:
            m = dict(matched)
            if sector_terms:
                m = {"sector": sector_terms, **m}
            return SignalScope(level=level, sector=sector, regions=region_keys, themes=theme_keys, basis=basis,
                               strength=strength, matched_terms=m, note=note, resolver_version=v)

        if top and len(top[1]) >= self.cfg.sector.strong_min_terms:
            return scope(ScopeLevel.SECTOR, ScopeBasis.SECTOR_TERMS, strength=ScopeStrength.STRONG, sector=top[0],
                         sector_terms=top[1],
                         note=f"No company was named; {len(top[1])} {top[0]} terms ({', '.join(top[1])}) point to that sector.")
        macro_class = (event is not None and event.status is EventStatus.CLASSIFIED
                       and event.category in self.cfg.market_categories)
        if themes or macro_class:
            if themes:
                note = f"No company or sector was named; market-wide vocabulary ({', '.join(matched['theme'])})."
                basis = ScopeBasis.THEME_TERMS
            else:
                note = (f"No company or sector was named; the event model calls this {event.category.value.lower()} "  # type: ignore[union-attr]
                        "which concerns the market as a whole.")
                basis = ScopeBasis.EVENT_MODEL
            return scope(ScopeLevel.MARKET, basis, note)
        if top and self.cfg.sector.weak_allowed:
            return scope(ScopeLevel.SECTOR, ScopeBasis.SECTOR_TERMS, strength=ScopeStrength.WEAK, sector=top[0],
                         sector_terms=top[1],
                         note=f"No company was named; a single {top[0]} term ({top[1][0]}) is the only hint of a subject.")
        if sectors and top is None:
            reason = "several sectors are mentioned with equal weight, so none is chosen"
        elif event is not None and event.status is EventStatus.CLASSIFIED:
            reason = (f"the event type ({event.category.value.lower()}) usually concerns a specific issuer, "
                      "but no company, sector or market-wide theme could be identified")
        else:
            reason = "no company, sector or market-wide theme could be identified"
        return scope(ScopeLevel.UNRESOLVED, ScopeBasis.NONE, f"Kept as reported, not guessed about: {reason}.")
