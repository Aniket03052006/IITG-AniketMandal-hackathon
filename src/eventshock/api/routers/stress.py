from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...domain import StressResult
from ...portfolio.chain import build_exposure_chain
from ...portfolio.models import ExposureChain
from ...services.stress_service import ScenarioNotFound, SignalNotFound
from ..deps import Container, get_container
from ..schemas import StressRequest
from .portfolio import book

router = APIRouter(tags=["stress"])


@router.post("/stress-test", response_model=StressResult)
def run_stress_test(req: StressRequest, c: Container = Depends(get_container)) -> StressResult:
    """Always 200 for a well-formed request; ``status`` says whether numbers were produced."""
    # a personal portfolio only when the request names one; without an id this is the synthetic book, exactly as before
    pf = None if c.portfolios is None or c.portfolios.is_default(req.portfolio_id) else book(c, req.portfolio_id)
    try:
        return c.stress.run(
            req.signal_id, req.scenario_id, force=req.force, impact_override=req.impact_override, portfolio=pf
        )
    except SignalNotFound as exc:
        raise HTTPException(status_code=404, detail=f"signal {req.signal_id!r} not found") from exc
    except ScenarioNotFound as exc:
        raise HTTPException(status_code=404, detail=f"scenario {req.scenario_id!r} not found") from exc


@router.get("/stress-runs", response_model=list[StressResult])
def list_stress_runs(signal_id: str = Query(description="runs made for this signal, newest first"),
                     portfolio_id: str | None = Query(default=None, description="only runs on this saved portfolio ('default' = the synthetic book)"),
                     c: Container = Depends(get_container)) -> list[StressResult]:
    if c.signals.get(signal_id) is None:
        raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
    only = None
    if portfolio_id is not None:
        only = c.portfolio.get().portfolio_id if c.portfolios is None or c.portfolios.is_default(portfolio_id) else portfolio_id
    return c.stress.runs_for(signal_id, only)


@router.get("/stress-runs/{run_id}", response_model=StressResult)
def get_stress_run(run_id: str, c: Container = Depends(get_container)) -> StressResult:
    run = c.stress.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    return run


@router.get("/stress-runs/{run_id}/exposure-chain", response_model=ExposureChain)
def get_exposure_chain(run_id: str, c: Container = Depends(get_container)) -> ExposureChain:
    """Why is the portfolio exposed? Event -> applied shock -> the holdings that take it -> modeled change, regrouped from this run's own results."""
    run = c.stress.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    if run.status.value != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"run {run_id!r} produced no numbers ({run.status.value}), so there is no exposure chain")
    signal = c.signals.get(run.signal_id)
    pf = book(c, run.audit.portfolio_id)
    if signal is None:
        raise HTTPException(status_code=404, detail=f"signal {run.signal_id!r} not found")
    if pf.content_hash() != run.audit.portfolio_hash:
        raise HTTPException(status_code=409, detail="the portfolio was edited after this run: run the scenario again")
    return build_exposure_chain(run, pf, signal)
