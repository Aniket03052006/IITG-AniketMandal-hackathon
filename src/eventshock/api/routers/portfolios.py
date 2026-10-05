"""Optional personal portfolios. The synthetic wholesale book (id ``default``) is always there, read-only, and what every request without a
``portfolio_id`` uses; nothing here is required to use EventShock."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...portfolio.compare import compare_runs
from ...portfolio.exposure import compute_exposure
from ...portfolio.models import (
    CompareRequest,
    ParseRequest,
    ParseResult,
    PortfolioComparison,
    PortfolioExposureDetail,
    PortfolioInput,
    PortfolioListItem,
    PortfolioView,
    ResolvedPortfolio,
)
from ...portfolio.service import PortfolioInvalid, PortfolioService
from ...portfolio.store import PortfolioLimit, PortfolioNotFound
from ...services.stress_service import ScenarioNotFound, SignalNotFound
from ..deps import Container, get_container

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


def service(c: Container) -> PortfolioService:
    if c.portfolios is None:
        raise HTTPException(status_code=404, detail="personal portfolios are not available")
    return c.portfolios


def _issues_detail(exc: PortfolioInvalid) -> list[dict]:
    """FastAPI's own validation-error shape, so the client's existing error reader shows each message."""
    return [{"loc": ["body", *(["holdings", i.holding] if i.holding is not None else []), *([i.field] if i.field else [])], "msg": i.message, "type": f"portfolio.{i.code.lower()}"}
            for i in exc.issues if i.level.value == "ERROR"]


@router.get("", response_model=list[PortfolioListItem])
def list_portfolios(c: Container = Depends(get_container)) -> list[PortfolioListItem]:
    return service(c).list()


@router.post("", response_model=PortfolioView, status_code=201)
def create_portfolio(body: PortfolioInput, c: Container = Depends(get_container)) -> PortfolioView:
    try:
        return service(c).create(body)
    except PortfolioInvalid as exc:
        raise HTTPException(status_code=422, detail=_issues_detail(exc)) from exc
    except PortfolioLimit as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/parse", response_model=ParseResult)
def parse_quick(body: ParseRequest, c: Container = Depends(get_container)) -> ParseResult:
    """Quick entry: ``AAPL 20%`` lines (or ``AAPL 100 @ 190``) into a draft, resolved so every issue shows. Saves nothing."""
    return service(c).parse(body)


@router.post("/validate", response_model=ResolvedPortfolio)
def validate_portfolio(body: PortfolioInput, c: Container = Depends(get_container)) -> ResolvedPortfolio:
    """Resolve a draft without saving it: weights, sources of every filled-in field, and every issue (200 even when it has errors)."""
    return service(c).validate(body)


@router.post("/compare", response_model=PortfolioComparison)
def compare(body: CompareRequest, c: Container = Depends(get_container)) -> PortfolioComparison:
    """The same event and scenario on two portfolios. Each side is an ordinary deterministic stress run; this only lines them up."""
    svc = service(c)
    try:
        pa, pb = (svc.get_portfolio(i) for i in body.portfolio_ids)
        ia, ib = (svc.view(i).list_item for i in body.portfolio_ids)
        ra = c.stress.run(body.signal_id, body.scenario_id, force=body.force, impact_override=body.impact_override, portfolio=pa)
        rb = c.stress.run(body.signal_id, body.scenario_id, force=body.force, impact_override=body.impact_override, portfolio=pb)
    except PortfolioNotFound as exc:
        raise HTTPException(status_code=404, detail=f"portfolio {exc.args[0]!r} not found") from exc
    except PortfolioInvalid as exc:
        raise HTTPException(status_code=422, detail=_issues_detail(exc)) from exc
    except SignalNotFound as exc:
        raise HTTPException(status_code=404, detail=f"signal {body.signal_id!r} not found") from exc
    except ScenarioNotFound as exc:
        raise HTTPException(status_code=404, detail=f"scenario {body.scenario_id!r} not found") from exc
    return compare_runs(body.signal_id, ra.scenario.id if ra.scenario else body.scenario_id, ia, ib, ra, rb)


@router.get("/{portfolio_id}", response_model=PortfolioView)
def get_portfolio(portfolio_id: str, c: Container = Depends(get_container)) -> PortfolioView:
    try:
        return service(c).view(portfolio_id)
    except PortfolioNotFound as exc:
        raise HTTPException(status_code=404, detail=f"portfolio {portfolio_id!r} not found") from exc


@router.put("/{portfolio_id}", response_model=PortfolioView)
def update_portfolio(portfolio_id: str, body: PortfolioInput, c: Container = Depends(get_container)) -> PortfolioView:
    try:
        return service(c).update(portfolio_id, body)
    except PortfolioNotFound as exc:
        raise HTTPException(status_code=404 if portfolio_id != "default" else 405, detail=str(exc.args[0]) if portfolio_id == "default" else f"portfolio {portfolio_id!r} not found") from exc
    except PortfolioInvalid as exc:
        raise HTTPException(status_code=422, detail=_issues_detail(exc)) from exc


@router.delete("/{portfolio_id}", status_code=204)
def delete_portfolio(portfolio_id: str, c: Container = Depends(get_container)) -> None:
    try:
        service(c).delete(portfolio_id)
    except PortfolioNotFound as exc:
        raise HTTPException(status_code=404 if portfolio_id != "default" else 405, detail=str(exc.args[0]) if portfolio_id == "default" else f"portfolio {portfolio_id!r} not found") from exc


@router.post("/{portfolio_id}/duplicate", response_model=PortfolioView, status_code=201)
def duplicate_portfolio(portfolio_id: str, c: Container = Depends(get_container)) -> PortfolioView:
    try:
        return service(c).duplicate(portfolio_id)
    except PortfolioNotFound as exc:
        raise HTTPException(status_code=404 if portfolio_id != "default" else 405, detail=str(exc.args[0]) if portfolio_id == "default" else f"portfolio {portfolio_id!r} not found") from exc
    except PortfolioInvalid as exc:
        raise HTTPException(status_code=422, detail=_issues_detail(exc)) from exc
    except PortfolioLimit as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{portfolio_id}/exposure", response_model=PortfolioExposureDetail)
def portfolio_exposure(portfolio_id: str, c: Container = Depends(get_container)) -> PortfolioExposureDetail:
    """What the portfolio is exposed to (asset class, sector, region, issuer, concentration, beta, duration), with the formula of each metric."""
    svc = service(c)
    try:
        pf = svc.get_portfolio(portfolio_id)
    except PortfolioNotFound as exc:
        raise HTTPException(status_code=404, detail=f"portfolio {portfolio_id!r} not found") from exc
    except PortfolioInvalid as exc:
        raise HTTPException(status_code=422, detail=_issues_detail(exc)) from exc
    return compute_exposure(pf, kind=svc.label(portfolio_id)[1])
