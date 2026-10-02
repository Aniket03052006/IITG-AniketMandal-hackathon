"""Scenario catalog and event-category -> scenario mapping (FR-12)."""

from __future__ import annotations

from collections.abc import Iterable

from ..domain import EventCategory, Scenario


class ScenarioCatalog:
    """Immutable lookup of scenario templates plus the category -> default mapping."""

    def __init__(
        self,
        scenarios: Iterable[Scenario],
        default_by_category: dict[EventCategory, str],
        *,
        require_complete: bool = True,
    ) -> None:
        self._by_id: dict[str, Scenario] = {}
        for s in scenarios:
            if s.id in self._by_id:
                raise ValueError(f"duplicate scenario id: {s.id}")
            self._by_id[s.id] = s
        for cat, sid in default_by_category.items():
            if sid not in self._by_id:
                raise ValueError(f"taxonomy maps {cat} to unknown scenario {sid}")
            if self._by_id[sid].category != cat:
                raise ValueError(f"scenario {sid} is for {self._by_id[sid].category}, not {cat}")
        if require_complete:
            missing = set(EventCategory) - set(default_by_category)
            if missing:
                raise ValueError(f"no default scenario for: {sorted(missing)}")
        self._default = dict(default_by_category)

    def all(self) -> list[Scenario]:
        return list(self._by_id.values())

    def get(self, scenario_id: str) -> Scenario | None:
        return self._by_id.get(scenario_id)

    def default_for(self, category: EventCategory) -> Scenario | None:
        sid = self._default.get(category)
        return self._by_id[sid] if sid else None
