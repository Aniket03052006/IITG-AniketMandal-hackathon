from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...domain import StressResult
from ...services.stress_service import ScenarioNotFound, SignalNotFound
from ..deps import Container, get_container
from ..schemas import StressRequest

router = APIRouter(tags=["stress"])


@router.post("/stress-test", response_model=StressResult)
def run_stress_test(req: StressRequest, c: Container = Depends(get_container)) -> StressResult:
    """Always 200 for a well-formed request; ``status`` says whether numbers were produced."""
    try:
        return c.stress.run(
            req.signal_id, req.scenario_id, force=req.force, impact_override=req.impact_override
        )
    except SignalNotFound as exc:
        raise HTTPException(status_code=404, detail=f"signal {req.signal_id!r} not found") from exc
    except ScenarioNotFound as exc:
        raise HTTPException(status_code=404, detail=f"scenario {req.scenario_id!r} not found") from exc


@router.get("/stress-runs", response_model=list[StressResult])
def list_stress_runs(signal_id: str = Query(description="runs made for this signal, newest first"),
                     c: Container = Depends(get_container)) -> list[StressResult]:
    if c.signals.get(signal_id) is None:
        raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
    return c.stress.runs_for(signal_id)


@router.get("/stress-runs/{run_id}", response_model=StressResult)
def get_stress_run(run_id: str, c: Container = Depends(get_container)) -> StressResult:
    run = c.stress.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    return run
