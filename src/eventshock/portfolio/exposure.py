"""What a portfolio is exposed to, from its holdings alone. Pure arithmetic; every figure carries the formula that produced it.

Exposure is not risk: a large position is only a risk once an event reaches it. This module never mentions an event, a scenario or a shock;
``chain.py`` and ``services/relevance.py`` do that, on top of these numbers.
"""

from __future__ import annotations

from collections import defaultdict

from ..domain import AssetClass, Portfolio, PortfolioAsset
from .crosstab import build_crosstab
from .models import ExposureRowV2, Metric, PortfolioExposureDetail, PositionWeight

TOP_N = 8
BPS = 10_000.0
SPLIT_LABEL = {"equity": "Equities", "bonds": "Bonds", "cash": "Cash", "other": "Loans, derivatives & other"}


def _name(a: PortfolioAsset) -> str:
    return a.name.split(" - ")[0]


def _rows(pf: Portfolio, key, label, where=None) -> list[ExposureRowV2]:  # noqa: ANN001
    """Groups of positions with their share of the WHOLE portfolio (``where`` leaves some positions out of the groups, not out of the total)."""
    value: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for a in pf.assets:
        if where is not None and not where(a):
            continue
        k = key(a)
        value[k] += a.market_value
        count[k] += 1
        labels.setdefault(k, label(a))
    total = pf.total_value
    rows = [ExposureRowV2(key=k, label=labels[k], market_value=v, share=v / total if total else 0.0, position_count=count[k]) for k, v in value.items()]
    return sorted(rows, key=lambda r: (-r.market_value, r.key))


def _bucket(a: PortfolioAsset) -> str:
    return {AssetClass.EQUITY: "equity", AssetClass.BOND: "bonds", AssetClass.CASH: "cash"}.get(a.asset_type, "other")


def compute_exposure(pf: Portfolio, *, kind: str = "USER") -> PortfolioExposureDetail:
    total = pf.total_value
    w = lambda a: a.market_value / total if total else 0.0  # noqa: E731
    by_class = _rows(pf, lambda a: a.asset_type.value, lambda a: a.asset_type.value)
    by_sector = _rows(pf, lambda a: a.sector, lambda a: a.sector)
    by_region = _rows(pf, lambda a: a.geography, lambda a: a.geography)
    # cash is not an issuer: it would otherwise top the issuer list and the single-issuer concentration
    by_issuer = _rows(pf, lambda a: a.entity_id, _name, where=lambda a: a.asset_type is not AssetClass.CASH)
    split = _rows(pf, _bucket, lambda a: SPLIT_LABEL[_bucket(a)])
    biggest = sorted(pf.assets, key=lambda a: (-a.market_value, a.asset_id))
    largest = [PositionWeight(asset_id=a.asset_id, name=_name(a), asset_class=a.asset_type, sector=a.sector, region=a.geography,
                              market_value=a.market_value, weight=w(a)) for a in biggest[:TOP_N]]
    not_stressed = [r for r in _rows(pf, lambda a: a.asset_id, _name) if any(a.asset_id == r.key and a.asset_type is AssetClass.OTHER for a in pf.assets)]

    metrics: list[Metric] = [Metric(key="total_value", label="Total value", value=total, unit="currency", formula="sum of position market values")]
    weights = sorted((w(a) for a in pf.assets), reverse=True)
    issuer_top = by_issuer[0].share if by_issuer else 0.0
    hhi = sum(x * x for x in weights)
    metrics += [
        Metric(key="top_position", label="Largest position", value=weights[0] if weights else 0.0, unit="fraction", formula="largest position value / total value"),
        Metric(key="top5_positions", label="Five largest positions", value=sum(weights[:5]), unit="fraction", formula="sum of the five largest position weights"),
        Metric(key="top_issuer", label="Largest single issuer", value=issuer_top, unit="fraction", formula="all positions in one issuer / total value (equity and bonds of the same issuer add)"),
        Metric(key="hhi", label="Concentration (HHI)", value=hhi, unit="ratio", formula="sum of squared position weights; 1 = one position, 1/N = N equal positions"),
        Metric(key="effective_n", label="Effective number of positions", value=1 / hhi if hhi else None, unit="count", formula="1 / HHI: how many equal positions the same concentration would equal"),
    ]
    eq = [a for a in pf.assets if a.asset_type is AssetClass.EQUITY]
    eq_value = sum(a.market_value for a in eq)
    if eq:
        metrics.append(Metric(key="equity_beta", label="Equity beta (value-weighted)", value=sum(a.market_value * a.beta for a in eq) / eq_value, unit="ratio",
                              formula="sum(value x beta) / equity value: how an equity-wide move scales into the equity holdings"))
        metrics.append(Metric(key="market_beta", label="Whole-portfolio market beta", value=sum(w(a) * a.beta for a in eq), unit="ratio",
                              formula="sum(weight x beta) over equities only (bonds, cash and unsupported instruments count as 0; derivatives are not included)"))
    bonds = [a for a in pf.assets if a.asset_type is AssetClass.BOND]
    bond_value = sum(a.market_value for a in bonds)
    if bonds and bond_value > 0:
        dur = sum(a.market_value * (a.duration or 0.0) for a in bonds) / bond_value
        dv01 = sum(a.market_value * (a.duration or 0.0) for a in bonds) / BPS
        metrics += [
            Metric(key="bond_duration", label="Bond duration (value-weighted)", value=dur, unit="years", formula="sum(value x duration) / bond value"),
            Metric(key="dv01", label="Rate sensitivity per +1 bp", value=-dv01, unit="currency", formula="-sum(value x duration) / 10,000: first-order change in value for a 1 bp parallel rise in yields (convexity ignored)"),
            Metric(key="rates_100bp", label="Value change for +100 bp", value=-dv01 * 100 / total if total else None, unit="fraction",
                   formula="100 x DV01 / total value; first order, so it overstates the loss for a large rise"),
        ]
    notes = [
        "Exposure is a description of the holdings, not a forecast: it becomes relevant only when an event reaches it.",
        "Region is the code each holding was entered with; EventShock models no currency moves.",
    ]
    if not_stressed:
        notes.append(f"{sum(r.share for r in not_stressed):.1%} of the value is in instruments EventShock cannot stress (held at its value, not treated as safe).")
    matrix = build_crosstab(((a.sector, a.sector, a.asset_type.value, a.asset_type.value, a.market_value, a.asset_id) for a in pf.assets),
                            unit="market_value", row_label="Sector", col_label="Asset class", total=total)
    return PortfolioExposureDetail(
        portfolio_id=pf.portfolio_id, name=pf.name, kind=kind, base_currency=pf.base_currency, total_value=total, position_count=len(pf.assets),  # type: ignore[arg-type]
        by_asset_class=by_class, by_sector=by_sector, by_region=by_region, by_issuer=by_issuer, split=split, largest_positions=largest,
        metrics=metrics, not_stressed=not_stressed, matrix=matrix, notes=notes)
