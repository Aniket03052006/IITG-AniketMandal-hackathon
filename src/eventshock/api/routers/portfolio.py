from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from ...domain import Portfolio, PortfolioAsset
from ..deps import Container, get_container
from ..schemas import ExposureRow, PortfolioExposure, PortfolioSummary

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
PID = Query(default=None, description="a saved personal portfolio; absent or 'default' = the synthetic wholesale book")


def book(c: Container, portfolio_id: str | None) -> Portfolio:
    """The portfolio a request names (the synthetic default when it names none). Unknown or unusable ids are 404 / 422."""
    if c.portfolios is None or c.portfolios.is_default(portfolio_id):
        return c.portfolio.get()
    from ...portfolio.service import PortfolioInvalid
    from ...portfolio.store import PortfolioNotFound

    try:
        return c.portfolios.get_portfolio(portfolio_id)
    except PortfolioNotFound as exc:
        raise HTTPException(status_code=404, detail=f"portfolio {portfolio_id!r} not found") from exc
    except PortfolioInvalid as exc:
        raise HTTPException(status_code=422, detail=f"portfolio {portfolio_id!r} no longer resolves: {exc}") from exc


def _rows(
    pf: Portfolio, key: Callable[[PortfolioAsset], str], label: Callable[[PortfolioAsset], str]
) -> list[ExposureRow]:
    value: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for a in pf.assets:
        k = key(a)
        value[k] += a.market_value
        count[k] += 1
        labels[k] = label(a)
    total = pf.total_value
    rows = [
        ExposureRow(key=k, label=labels[k], market_value=v, share=v / total, asset_count=count[k])
        for k, v in value.items()
    ]
    return sorted(rows, key=lambda r: (-r.market_value, r.key))


@router.get("/summary", response_model=PortfolioSummary)
def summary(portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> PortfolioSummary:
    pf = book(c, portfolio_id)
    user = c.portfolios is not None and not c.portfolios.is_default(portfolio_id)
    preset = user and c.portfolios.is_preset(portfolio_id)
    return PortfolioSummary(
        portfolio_id=pf.portfolio_id, name=pf.name, description=pf.description, as_of=pf.as_of,
        base_currency=pf.base_currency, total_value=pf.total_value, asset_count=len(pf.assets),
        entity_count=len({a.entity_id for a in pf.assets}), synthetic=not user or preset, kind="PRESET" if preset else "USER" if user else "DEFAULT",
    )


@router.get("/exposure", response_model=PortfolioExposure)
def exposure(portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> PortfolioExposure:
    pf = book(c, portfolio_id)
    names = {e.entity_id: e.name for e in c.portfolio.entities()}
    return PortfolioExposure(
        by_asset_class=_rows(pf, lambda a: a.asset_type.value, lambda a: a.asset_type.value),
        by_sector=_rows(pf, lambda a: a.sector, lambda a: a.sector),
        by_entity=_rows(pf, lambda a: a.entity_id, lambda a: names.get(a.entity_id, a.name.split(" - ")[0])),
        by_geography=_rows(pf, lambda a: a.geography, lambda a: a.geography),
    )


@router.get("/assets", response_model=list[PortfolioAsset])
def assets(portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> list[PortfolioAsset]:
    return book(c, portfolio_id).assets
