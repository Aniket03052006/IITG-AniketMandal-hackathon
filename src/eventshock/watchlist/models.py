"""Contracts of the watchlist domain. A watch item names a subject from a closed vocabulary or from the entity master; free text never becomes a company."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from ..decision.models import ProvenanceRef
from ..domain.base import ContractModel
from ..monitor.models import ChangeType

VERSION = "watchlist-v1"


class WatchKind(StrEnum):
    COMPANY = "COMPANY"
    SECTOR = "SECTOR"
    INDUSTRY = "INDUSTRY"
    GEOGRAPHY = "GEOGRAPHY"
    EVENT_TYPE = "EVENT_TYPE"
    RISK_THEME = "RISK_THEME"
    PORTFOLIO_EXPOSURE = "PORTFOLIO_EXPOSURE"


class WatchItem(ContractModel):
    kind: WatchKind
    value: str = Field(min_length=1, max_length=64, description="COMPANY: an entity id or ticker in the entity master; SECTOR / INDUSTRY: a name from the vocabulary; GEOGRAPHY: a region code; "
                                                                  "EVENT_TYPE: an event category id; RISK_THEME: a theme id; PORTFOLIO_EXPOSURE: 'top:N' or a held entity id / ticker")
    label: str = Field(default="", max_length=120, description="a display name; filled in from the vocabulary when left empty")

    @field_validator("value")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class WatchlistInput(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    items: list[WatchItem] = Field(default_factory=list)


class Watchlist(WatchlistInput):
    id: str
    created_at: datetime
    updated_at: datetime


class VocabEntry(ContractModel):
    value: str
    label: str
    detail: str | None = None


class WatchVocabulary(ContractModel):
    """What each kind of item can name: the pickers of the UI and the validator of the API are the same object."""

    companies: list[VocabEntry]
    sectors: list[VocabEntry]
    industries: list[VocabEntry]
    geographies: list[VocabEntry]
    event_types: list[VocabEntry]
    risk_themes: list[VocabEntry]
    portfolio_exposure: list[VocabEntry]
    max_watchlists: int
    max_items: int


class WatchedEvent(ContractModel):
    event_id: str
    lead_signal_id: str
    headline: str
    match_reason: str = Field(description="why this event is on the list, in words: which scope level or which fact matched")
    first_seen: datetime | None
    last_seen: datetime | None
    is_new: bool = Field(description="first tracked within the requested window")
    severity: float | None
    lifecycle: str | None
    novelty: str | None
    velocity_per_hour: float | None
    evidence_tier: str
    conflict: str
    materiality: str | None
    exposure_share: float | None
    stress_pnl_pct: float | None = Field(description="modeled scenario P&L (a simulation, not a forecast); null when no scenario applies")
    recent_changes: list[ChangeType]
    clock_trusted: bool


class ItemRollup(ContractModel):
    max_severity: float | None
    lifecycle_counts: dict[str, int]
    evidence_counts: dict[str, int]
    conflicts_open: int
    max_materiality: str | None
    worst_stress_pnl_pct: float | None
    novelty_counts: dict[str, int]
    fastest_velocity_per_hour: float | None


class ItemActivity(ContractModel):
    item: WatchItem
    status: str = Field(description="MATCHED | NO_MATCH | DISABLED | UNAVAILABLE")
    reason: str | None = None
    matched_events: int
    new_events: int
    scanned: int
    truncated: bool
    events: list[WatchedEvent]
    rollup: ItemRollup | None


class WatchlistActivity(ContractModel):
    version: str = VERSION
    watchlist: Watchlist
    mode: str
    cycle: int | None
    window: int
    as_of: datetime | None
    portfolio_id: str | None
    status: str = Field(description="OK | DISABLED | UNAVAILABLE")
    reason: str | None = None
    items: list[ItemActivity]
    recent_changes: int
    provenance: list[ProvenanceRef]
    labels: list[str]
    limitations: list[str]


class WatchlistList(ContractModel):
    watchlists: list[Watchlist]
