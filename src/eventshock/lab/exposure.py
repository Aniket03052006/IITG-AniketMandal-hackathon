"""Optional estimate of oil exposure from the sector: a judgement prior, applied to a COPY of the portfolio and always reported beside the result that used it.

An equity or derivative that already carries a measured elasticity keeps it. The default synthetic book has none, so without this switch an oil shock reaches nothing and says so
(NOT_APPLICABLE), rather than inventing an exposure."""

from __future__ import annotations

from ..domain import AssetClass, Portfolio
from .models import PriorUse


def apply_commodity_priors(portfolio: Portfolio, priors: dict[str, float]) -> tuple[Portfolio, list[PriorUse]]:
    assets = []
    used: dict[str, list[float]] = {}
    for a in portfolio.assets:
        k = priors.get(a.sector)
        if a.commodity_sensitivity is None and k is not None and a.asset_type in (AssetClass.EQUITY, AssetClass.DERIVATIVE):
            assets.append(a.model_copy(update={"commodity_sensitivity": k}))
            used.setdefault(a.sector, []).append(a.market_value)
        else:
            assets.append(a)
    if not used:
        return portfolio, []
    uses = [PriorUse(sector=s, sensitivity=priors[s], positions=len(v), value=sum(v)) for s, v in sorted(used.items())]
    return portfolio.model_copy(update={"assets": assets}), uses
