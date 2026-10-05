from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...propagation.models import (
    AutoStressRequest,
    AutoStressResult,
    ConcentrationView,
    OverlapView,
    PortfolioFlow,
    PortfolioMateriality,
    StressAttribution,
)
from ..deps import Container, get_container
from .portfolio import PID, book

router = APIRouter(tags=["propagation"])


def _svc(c: Container):  # noqa: ANN202
    if c.propagation is None:
        raise HTTPException(status_code=404, detail="event-to-portfolio propagation is available in the replay profile only")
    return c.propagation


def _book(c: Container, portfolio_id: str | None):  # noqa: ANN202
    """None = the synthetic default book (the service reads it itself), else the named saved portfolio."""
    return None if c.portfolios is None or c.portfolios.is_default(portfolio_id) else book(c, portfolio_id)


def _signal(c: Container, signal_id: str):  # noqa: ANN202
    s = c.signals.get(signal_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
    return s


@router.get("/signals/{signal_id}/propagation", response_model=PortfolioFlow,
            description="Event -> scope -> risk factor -> portfolio exposure -> holdings (every edge says whether it is OBSERVED, a SCENARIO_ASSUMPTION or a USER_ASSUMPTION; "
                        "this is a mapping, not causal inference), the materiality of the event to this portfolio (LOW/MEDIUM/HIGH/CRITICAL by an explicit lookup, with its decomposition), "
                        "and the scenario it would generate (or SCENARIO UNAVAILABLE and why). Derived: nothing is stored on the signal and no stress is run by this call.")
def get_propagation(signal_id: str, portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> PortfolioFlow:
    svc = _svc(c)
    return svc.flow(_signal(c, signal_id), _book(c, portfolio_id))


@router.get("/signals/{signal_id}/materiality", response_model=PortfolioMateriality,
            description="Why is this event relevant to this portfolio? The lookup, the rules that fired and every input: reach, direct and indirect exposure, severity, concentration, mapping basis.")
def get_materiality(signal_id: str, portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> PortfolioMateriality:
    return _svc(c).materiality(_signal(c, signal_id), _book(c, portfolio_id))


@router.post("/signals/{signal_id}/portfolio-stress", response_model=AutoStressResult,
             description="Generate the event's scenario for this portfolio and run it through the unchanged stress engine, with the exposure chain and an attribution that reconciles to "
                         "the total. When no defensible scenario exists the answer says SCENARIO UNAVAILABLE and why. `force` runs a failed soft gate (severity, relevance, direction) as a what-if. "
                         "A SIMULATION, not a prediction.")
def post_portfolio_stress(signal_id: str, req: AutoStressRequest, c: Container = Depends(get_container)) -> AutoStressResult:
    svc = _svc(c)
    signal = _signal(c, signal_id)
    return svc.portfolio_stress(signal, _book(c, req.portfolio_id), force=req.force, impact_override=req.impact_override)


@router.get("/stress-runs/{run_id}/attribution", response_model=StressAttribution,
            description="Why did the portfolio move? The run's total change regrouped by kind of shock, issuer, sector, industry, market factor, risk factor, asset class and position. "
                        "Every table adds up to the total. Works for any completed run.")
def get_attribution(run_id: str, c: Container = Depends(get_container)) -> StressAttribution:
    svc = _svc(c)
    run = c.stress.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    if run.status.value != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"run {run_id!r} produced no numbers ({run.status.value}), so there is nothing to attribute")
    pf = book(c, run.audit.portfolio_id)
    if pf.content_hash() != run.audit.portfolio_hash:
        raise HTTPException(status_code=409, detail="the portfolio was edited after this run: run the scenario again")
    return svc.attribution(run, pf)


@router.get("/concentration", response_model=ConcentrationView,
            description="Concentration of the portfolio by issuer, sector, industry, geography, asset class and risk factor. Only meaningful concentration is flagged.")
def get_concentration(portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> ConcentrationView:
    return _svc(c).concentration(_book(c, portfolio_id))


@router.get("/concentration/overlaps", response_model=OverlapView,
            description="Current events that bear on the same risk factor and the same holdings (concentrated risk). Needs several independent events; one story counts once. "
                        "With `signal_id`, only the clusters that event belongs to.")
def get_overlaps(portfolio_id: str | None = PID, signal_id: str | None = Query(default=None), c: Container = Depends(get_container)) -> OverlapView:
    svc = _svc(c)
    view = svc.overlaps(_book(c, portfolio_id))
    if signal_id is None:
        return view
    signal = _signal(c, signal_id)
    ev = c.intelligence.index().event_of(signal.id) if c.intelligence is not None else None
    mine = [k for k in view.clusters if ev is not None and any(e.event_id == ev.id for e in k.events)]
    return view.model_copy(update={"clusters": mine, "reason": None if mine else "this event is not part of a cluster of overlapping events"})
