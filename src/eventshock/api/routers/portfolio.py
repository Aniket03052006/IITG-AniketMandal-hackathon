from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from fastapi import APIRouter, Depends

from ...domain import Portfolio, PortfolioAsset
from ..deps import Container, get_container
from ..schemas import ExposureRow, PortfolioExposure, PortfolioSummary

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


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
def summary(c: Container = Depends(get_container)) -> PortfolioSummary:
    pf = c.portfolio.get()
    return PortfolioSummary(
        portfolio_id=pf.portfolio_id, name=pf.name, description=pf.description, as_of=pf.as_of,
        base_currency=pf.base_currency, total_value=pf.total_value, asset_count=len(pf.assets),
        entity_count=len({a.entity_id for a in pf.assets}),
    )


@router.get("/exposure", response_model=PortfolioExposure)
def exposure(c: Container = Depends(get_container)) -> PortfolioExposure:
    pf = c.portfolio.get()
    names = {e.entity_id: e.name for e in c.portfolio.entities()}
    return PortfolioExposure(
        by_asset_class=_rows(pf, lambda a: a.asset_type.value, lambda a: a.asset_type.value),
        by_sector=_rows(pf, lambda a: a.sector, lambda a: a.sector),
        by_entity=_rows(pf, lambda a: a.entity_id, lambda a: names.get(a.entity_id, a.entity_id)),
        by_geography=_rows(pf, lambda a: a.geography, lambda a: a.geography),
    )


@router.get("/assets", response_model=list[PortfolioAsset])
def assets(c: Container = Depends(get_container)) -> list[PortfolioAsset]:
    return c.portfolio.get().assets
