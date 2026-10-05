from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...domain import EventCategory, Scenario
from ...stress.history_check import ScenarioHistoryCheck
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


@router.get("/{scenario_id}/history-check", response_model=ScenarioHistoryCheck,
            description="Where each shock of the scenario falls in the empirical distribution of 1-, 5- and 21-session moves since 2014 (read-only; a historical frequency, not a probability). "
                        "`severity_scale` scales the shocks as a stress run would (1.0 = the scenario's reference impact).")
def history_check(scenario_id: str, severity_scale: float = Query(default=1.0, ge=0.1, le=3.0), c: Container = Depends(get_container)) -> ScenarioHistoryCheck:
    scenario = c.catalog.get(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"scenario {scenario_id!r} not found")
    if c.shock_history is None:
        raise HTTPException(status_code=404, detail="no shock history is installed: `make shock-history`")
    return c.shock_history.check_scenario(scenario, severity_scale=severity_scale)
