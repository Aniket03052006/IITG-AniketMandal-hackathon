from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...domain import EventCategory, Scenario
from ..deps import Container, get_container
from ..schemas import ScenarioList

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("", response_model=ScenarioList)
def list_scenarios(c: Container = Depends(get_container)) -> ScenarioList:
    defaults = {
        cat: sc.id for cat in EventCategory if (sc := c.catalog.default_for(cat)) is not None
    }
    return ScenarioList(
        version=c.scenario_set_version, default_by_category=defaults, scenarios=c.catalog.all()
    )


@router.get("/{scenario_id}", response_model=Scenario)
def get_scenario(scenario_id: str, c: Container = Depends(get_container)) -> Scenario:
    scenario = c.catalog.get(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"scenario {scenario_id!r} not found")
    return scenario
