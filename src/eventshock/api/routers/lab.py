from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...explain.models import Explanation
from ...lab.models import (
    Comparison,
    LabCompareRequest,
    LabOptions,
    LabPlan,
    LabResult,
    ReverseStressRequest,
    ReverseStressResult,
    ScenarioRequest,
)
from ...lab.service import LabInvalid
from ..deps import Container, get_container
from .portfolio import PID, book

router = APIRouter(tags=["scenario-lab"])


def _svc(c: Container):  # noqa: ANN202
    if c.lab is None:
        raise HTTPException(status_code=404, detail="the scenario lab is available in the replay profile only")
    return c.lab


def _pf(c: Container, portfolio_id: str | None):  # noqa: ANN202
    """None = the synthetic default book (the lab reads it itself), else the named saved portfolio."""
    return None if c.portfolios is None or c.portfolios.is_default(portfolio_id) else book(c, portfolio_id)


def _invalid(exc: LabInvalid) -> HTTPException:
    return HTTPException(status_code=422, detail=[{"loc": ["body", "assumptions", *( [i.index] if i.index is not None else [])], "msg": i.message, "type": f"lab.{i.field}"} for i in exc.issues])


@router.post("/scenarios", response_model=LabResult,
             description="Run a scenario through the unchanged stress engine. BASE = no shock; ASSESSED = EventShock's configured scenario for `signal_id`; CUSTOM = the assumptions you give, each a SCENARIO ASSUMPTION "
                         "(never a prediction). The id is deterministic: the same assumptions on the same portfolio give the same id and result. A shock only reaches positions that carry the exposure it acts on; "
                         "when none does the answer is NOT_APPLICABLE and says why, not a zero.")
def run_scenario(req: ScenarioRequest, c: Container = Depends(get_container)) -> LabResult:
    svc = _svc(c)
    try:
        return svc.run(req, _pf(c, req.portfolio_id))
    except LabInvalid as exc:
        raise _invalid(exc) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/scenarios/validate", response_model=LabPlan, description="What a request resolves to, and every problem with it, without running anything.")
def validate_scenario(req: ScenarioRequest, c: Container = Depends(get_container)) -> LabPlan:
    plan, _ = _svc(c).plan(req, _pf(c, req.portfolio_id))
    return plan


@router.post("/scenarios/compare", response_model=Comparison,
             description="Run two or three scenarios on one portfolio and compare them side by side: value before and after, loss, dominant driver, sectors, risk factors, holdings and the assumptions that differ.")
def compare_scenarios(req: LabCompareRequest, c: Container = Depends(get_container)) -> Comparison:
    svc = _svc(c)
    try:
        return svc.compare(req.scenarios, _pf(c, req.portfolio_id))
    except LabInvalid as exc:
        raise _invalid(exc) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/lab/options", response_model=LabOptions,
            description="What the scenario editor can offer, from the same vocabulary the validator enforces: kinds and their units and limits, sectors, issuers, currencies (and which the portfolio holds), risk factors, and the oil priors.")
def lab_options(portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> LabOptions:
    return _svc(c).options(_pf(c, portfolio_id))


@router.post("/reverse-stress", response_model=ReverseStressResult,
             description="What would it take to lose this much? A bounded, deterministic search (grid over a fixed basket of shocks, then a bisection) valued by the unchanged stress engine: the shocks that reach "
                         "`target_pct` of the portfolio, the dominant drivers, holdings, sectors and risk factors, the configured bounds, and the full engine run of the combination. Every shock is a SCENARIO "
                         "ASSUMPTION and the result is a hypothetical stress analysis, not a prediction of future losses. When the bounds cannot reach the target the answer says NOT_ACHIEVABLE and returns the "
                         "largest loss they allow.")
def reverse_stress(req: ReverseStressRequest, c: Container = Depends(get_container)) -> ReverseStressResult:
    svc = _svc(c)
    try:
        return svc.reverse(req, _pf(c, req.portfolio_id))
    except LabInvalid as exc:
        raise _invalid(exc) from exc


@router.post("/scenarios/explanation", response_model=Explanation,
             description="Why the scenario moves the portfolio as it does: each assumption (a SCENARIO ASSUMPTION you chose, or EventShock's configured one), what it reached, and the engine's own decomposition.")
def explain_scenario(req: ScenarioRequest, c: Container = Depends(get_container)) -> Explanation:
    if c.explain is None:
        raise HTTPException(status_code=404, detail="explanations are available in the replay profile only")
    try:
        return c.explain.lab(req, _pf(c, req.portfolio_id))
    except LabInvalid as exc:
        raise _invalid(exc) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reverse-stress/explanation", response_model=Explanation,
             description="Why these shocks reach the target: the method, each shock's share of its limit, the axes that were not used and why, the binding bounds, and the engine's decomposition.")
def explain_reverse(req: ReverseStressRequest, c: Container = Depends(get_container)) -> Explanation:
    if c.explain is None:
        raise HTTPException(status_code=404, detail="explanations are available in the replay profile only")
    try:
        return c.explain.reverse(req, _pf(c, req.portfolio_id))
    except LabInvalid as exc:
        raise _invalid(exc) from exc
