"""The closed vocabulary in one object, plus the derivations both extractors share (labels, the primary issuer, the one-line summary)."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import UNKNOWN_ENTITY, EventCategory
from ..pipeline.scope import ScopeConfig
from .config import SemanticsConfig
from .model import PrimaryIssuer, SemanticReading
from .reference import Reference

NO_EVENT = "NO_EVENT"
OTHER = "other"


@dataclass(frozen=True)
class Vocab:
    cfg: SemanticsConfig
    sectors: tuple[str, ...]  # the six sectors of the portfolio's universe (scope.yaml)
    regions: tuple[str, ...]  # portfolio geography codes (scope.yaml)
    event_labels: dict[str, str]  # EventCategory id -> display label (event_taxonomy.yaml)

    @classmethod
    def build(cls, cfg: SemanticsConfig, scope: ScopeConfig, event_labels: dict[str, str]) -> Vocab:
        return cls(cfg, tuple(scope.sectors), tuple(scope.regions), event_labels)

    # ------------------------------------------------------------------------------------------------------------------ events
    def event_label(self, event_type: str) -> str:
        return "Not a market event" if event_type == NO_EVENT else self.event_labels.get(event_type, event_type)

    def subtype_label(self, event_type: str, subtype: str) -> str:
        if event_type == NO_EVENT or subtype == OTHER:
            return "Unspecified" if event_type != NO_EVENT else "None"
        st = self.cfg.subtype(EventCategory(event_type), subtype)
        return st.label if st else subtype

    def valid_subtype(self, event_type: str, subtype: str) -> str:
        if event_type == NO_EVENT:
            return OTHER
        return subtype if subtype in self.cfg.subtype_ids(EventCategory(event_type)) else OTHER

    # ---------------------------------------------------------------------------------------------------------------- sentiment
    def sentiment_label(self, score: float) -> str:
        c = self.cfg.sentiment_label
        return "negative" if score <= c.negative_below else "positive" if score >= c.positive_above else "neutral"

    def sentiment_intensity(self, score: float) -> str:
        i = self.cfg.sentiment_label.intensity
        a = abs(score)
        return "high" if a >= i["high_from"] else "medium" if a >= i["medium_from"] else "low"


def primary_issuer(ref: Reference) -> PrimaryIssuer:
    """The signal's issuer comes ONLY from the entity master (the deterministic resolver). A name in the text that is not in the master, however
    plausible, is an entity mention with ``resolved=False`` and never an issuer: EventShock holds no data for it and will not invent any."""
    e = ref.entity
    if e is None or e.entity_id == UNKNOWN_ENTITY:
        return PrimaryIssuer(
            entity_id=UNKNOWN_ENTITY, resolved=False,
            note="No company in the entity master was identified; exposure is assessed at sector / market level where the text supports it.")
    return PrimaryIssuer(entity_id=e.entity_id, name=e.entity_name, ticker=e.ticker, resolved=True,
                         note=f"Matched the entity master (link confidence {e.link_confidence:.2f}).")


def build_summary(r: SemanticReading) -> str:
    """One deterministic sentence from the reading: nothing is generated, so nothing can be invented."""
    if r.event_type == NO_EVENT:
        return "This text does not describe a market event."
    subject = r.primary_issuer.name or next((e.name for e in r.entities if e.role == "subject"), None)
    where = (f" affecting {', '.join(r.sectors)}" if r.sectors else "") + (f" in {', '.join(r.regions)}" if r.regions else "")
    who = f"{subject}: " if subject else ""
    sub = f" ({r.event_subtype_label.lower()})" if r.event_subtype != OTHER else ""
    tone = {"negative": "adverse tone", "positive": "favourable tone", "neutral": "neutral tone"}[r.sentiment_label]
    return f"{who}{r.event_label.lower()} event{sub}{where}; {tone}."

