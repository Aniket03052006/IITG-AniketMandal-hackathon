"""Which events a watch item matches. Matching reads the scope the intelligence layer already resolved and the facts on the signals; it never guesses.

* COMPANY matches only an event with a signal whose company was resolved by the entity resolver to that entity: an event with no resolved company never matches, however its
  text reads. A name in the text that the entity master does not hold is a mention, not a company.
* SECTOR / INDUSTRY / GEOGRAPHY match a node of the event's resolved scope path (or a secondary region); an UNRESOLVED or AMBIGUOUS-sector event has no such node.
* EVENT_TYPE matches the assessed event class (the trained class when no assessment ran); NO_EVENT never matches.
* RISK_THEME matches a theme or macro node of the scope, or a theme the text's vocabulary named.
* PORTFOLIO_EXPOSURE matches an event whose propagation reaches one of the named holdings (observed reach, direct or indirect).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import UNKNOWN_ENTITY, EventStatus, RiskSignal
from ..intelligence.grouping import Event
from ..intelligence.model import EventScope, ScopeType

NO_EVENT = "NO_EVENT"


@dataclass(frozen=True)
class Match:
    reason: str


def _nodes(scope: EventScope, *types: ScopeType) -> list[str]:
    return [n.value for n in [*scope.scope_path, *scope.secondary] if n.type in types]


def match_company(event: Event, entity_id: str, name: str) -> Match | None:
    for n in event.nodes:
        if n.signal.entity.entity_id == entity_id and entity_id != UNKNOWN_ENTITY:
            return Match(f"{name} was resolved as the company by the entity resolver (link confidence {n.signal.entity.link_confidence:.2f})")
    return None


def match_scope_level(scope: EventScope, kind: ScopeType, value: str, label: str) -> Match | None:
    if scope.scope_type is ScopeType.UNRESOLVED:
        return None
    for n in [*scope.scope_path, *scope.secondary]:
        if n.type is kind and n.value == value:
            return Match(f"{label} is in the event's scope path ({n.basis.lower().replace('_', ' ')})")
    return None


def match_event_type(signal: RiskSignal, assessed_type: str | None, value: str, label: str) -> Match | None:
    if assessed_type is not None:
        return Match(f"the assessed event class is {label}") if assessed_type == value and assessed_type != NO_EVENT else None
    ev = signal.event
    return Match(f"the trained event model classifies it as {label}") if ev.status is EventStatus.CLASSIFIED and ev.category.value == value else None


def match_theme(event: Event, scope: EventScope, theme: str, label: str) -> Match | None:
    if scope.scope_type is ScopeType.UNRESOLVED:
        return None
    for v in _nodes(scope, ScopeType.THEME, ScopeType.MACRO):
        if v.replace(" ", "_") == theme:
            return Match(f"{label} is a theme of the event's scope")
    if scope.scope_type is ScopeType.MARKET and (scope.scope_value or "").replace(" ", "_").lower() == theme:
        return Match(f"{label} is the event's market-wide subject")
    for n in event.nodes:
        if n.signal.scope is not None and theme in n.signal.scope.themes:
            return Match(f"the text uses {label} vocabulary")
    return None
