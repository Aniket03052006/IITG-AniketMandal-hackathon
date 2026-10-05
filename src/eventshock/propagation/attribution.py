"""Why did the portfolio move? A decomposition of a finished stress run that reconciles to its total.

Nothing is recomputed: every row is a regrouping of the engine's own per-position, per-factor changes (``PositionResult.by_factor``), plus any part of a
position's change the per-factor figures do not explain (``Other``; the engine's loan and bond floor arithmetic sums exactly, so it is normally zero).
Each table is checked against the run's total change and the builder raises if one does not reconcile: a decomposition that does not add up is a bug, not a result.
The stress formulas are untouched. This is a sensitivity decomposition under the scenario's assumptions, not causal attribution.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping

from ..domain import Portfolio, PortfolioAsset, RiskFactor, StressResult, StressStatus
from ..portfolio.chain import FACTOR_LABEL, money
from .models import AttributionRow, AttributionTable, ShockOrigin, StressAttribution

LABELS = [
    "A decomposition of the modeled change under the scenario's assumptions. Every table adds up to the run's total.",
    "Not causal attribution and not a forecast: the shock sizes are assumptions.",
]
OTHER = "OTHER"
SCOPE_LABEL = {"ISSUER": "Issuer-specific shocks", "SECTOR": "Sector shocks", "MARKET": "Market-wide shocks", OTHER: "Other (not explained by a shock)"}
TOLERANCE = 0.01  # currency units: far above float noise, far below anything a person would read as a difference


def _tolerance(total: float) -> float:
    return max(TOLERANCE, 1e-9 * abs(total))


class _Acc:
    def __init__(self) -> None:
        self.delta = 0.0
        self.label = ""
        self.positions: dict[str, float] = {}

    def add(self, label: str, delta: float, asset_id: str, baseline: float) -> None:
        self.label = label
        self.delta += delta
        self.positions[asset_id] = baseline


def _table(dimension: str, label: str, acc: Mapping[str, _Acc], total: float) -> AttributionTable:
    rows = [AttributionRow(key=k, label=a.label, delta=a.delta, share_of_total=(a.delta / total if total else None),
                           baseline_value=sum(a.positions.values()), position_count=len(a.positions))
            for k, a in acc.items() if abs(a.delta) > 0]
    rows.sort(key=lambda r: (r.delta, r.key))
    s = sum(r.delta for r in rows)
    resid = total - s
    if abs(resid) > _tolerance(total):
        raise ValueError(f"attribution by {dimension} does not reconcile: rows add to {s:,.4f} but the run's total change is {total:,.4f}")
    return AttributionTable(dimension=dimension, label=label, rows=rows, total=total, sum=s, residual=resid, reconciled=True)


def build_attribution(result: StressResult, portfolio: Portfolio, *, industry_of: Callable[[PortfolioAsset], str | None],
                      origins: list[ShockOrigin] | None = None, engine_factor_map: Mapping[RiskFactor, str] | None = None,
                      risk_factor_labels: Mapping[str, str] | None = None, entity_names: Mapping[str, str] | None = None) -> StressAttribution:
    if result.status is not StressStatus.COMPLETED or result.summary is None:
        raise ValueError("an attribution needs a completed stress run")
    assets = {a.asset_id: a for a in portfolio.assets}
    total = result.summary.pnl
    base = result.summary.baseline_value
    ccy = portfolio.base_currency
    rf_labels = dict(risk_factor_labels or {})
    origin_rf = {(o.factor, o.scope, o.sector): o for o in (origins or [])}
    engine_map = dict(engine_factor_map or {})

    drivers: dict[str, _Acc] = defaultdict(_Acc)
    by_issuer: dict[str, _Acc] = defaultdict(_Acc)
    by_sector: dict[str, _Acc] = defaultdict(_Acc)
    by_industry: dict[str, _Acc] = defaultdict(_Acc)
    by_class: dict[str, _Acc] = defaultdict(_Acc)
    by_market: dict[str, _Acc] = defaultdict(_Acc)
    by_rf: dict[str, _Acc] = defaultdict(_Acc)
    by_pos: dict[str, _Acc] = defaultdict(_Acc)

    for p in result.positions:
        a = assets.get(p.asset_id)
        parts: list[tuple[str, str, str, str, float]] = []  # (scope key, factor key, factor label, risk-factor key, amount)
        shock_of = {s.factor: s for s in p.shocks}
        for factor, amount in p.by_factor.items():
            sh = shock_of.get(factor)
            scope = sh.scope.value if sh else OTHER
            o = origin_rf.get((factor.value, scope, sh.sector if sh else None))
            if scope == "MARKET":
                rid = o.risk_factor if o and o.risk_factor else engine_map.get(factor)
                rkey, rlabel = (rid, rf_labels.get(rid or "", rid or "")) if rid else (OTHER, SCOPE_LABEL[OTHER])
            elif scope == "SECTOR" and o is not None and o.source == "PROPAGATED" and o.risk_factor:
                rkey, rlabel = o.risk_factor, rf_labels.get(o.risk_factor, o.risk_factor)
            elif scope == "SECTOR":
                rkey, rlabel = "SECTOR_SPECIFIC", "Sector-specific (the event's own sector, not a market risk factor)"
            elif scope == "ISSUER":
                rkey, rlabel = "ISSUER_SPECIFIC", "Issuer-specific (the named company, not a market risk factor)"
            else:
                rkey, rlabel = OTHER, SCOPE_LABEL[OTHER]
            parts.append((scope, factor.value, FACTOR_LABEL[factor], rkey + "\u0000" + rlabel, amount))
        residual = p.delta - sum(p.by_factor.values())
        if abs(residual) > 1e-9:
            parts.append((OTHER, OTHER, SCOPE_LABEL[OTHER], OTHER + "\u0000" + SCOPE_LABEL[OTHER], residual))
        issuer_name = (entity_names or {}).get(p.entity_id) or p.name.split(" - ")[0]
        ind = (industry_of(a) if a else None) or "Unclassified"
        for scope, fkey, flabel, rpair, amount in parts:
            drivers[scope].add(SCOPE_LABEL.get(scope, scope), amount, p.asset_id, p.baseline_value)
            by_market[fkey].add(flabel, amount, p.asset_id, p.baseline_value)
            rkey, rlabel = rpair.split("\u0000")
            by_rf[rkey].add(rlabel, amount, p.asset_id, p.baseline_value)
            by_issuer[p.entity_id].add(issuer_name, amount, p.asset_id, p.baseline_value)
            by_sector[p.sector].add(p.sector, amount, p.asset_id, p.baseline_value)
            by_industry[ind].add(ind, amount, p.asset_id, p.baseline_value)
            by_class[p.asset_class.value].add(p.asset_class.value.title(), amount, p.asset_id, p.baseline_value)
            by_pos[p.asset_id].add(p.name, amount, p.asset_id, p.baseline_value)

    d = _table("driver", "By kind of shock", drivers, total)
    tables = [
        _table("issuer", "By issuer", by_issuer, total),
        _table("sector", "By sector", by_sector, total),
        _table("industry", "By industry", by_industry, total),
        _table("market_factor", "By market factor (the engine's factors)", by_market, total),
        _table("risk_factor", "By risk factor", by_rf, total),
        _table("asset_class", "By asset class", by_class, total),
        _table("position", "By position", by_pos, total),
    ]
    pct = result.summary.pnl_pct
    parts_txt = ", ".join(f"{r.label.lower().replace(' shocks', '')} {money(r.delta, ccy, True)}" for r in d.rows[:4])
    headline = f"Total modeled change {money(total, ccy, True)} ({pct:+.2%} of the portfolio)" + (f": {parts_txt}." if parts_txt else ".")
    return StressAttribution(
        run_id=result.run_id, portfolio_id=portfolio.portfolio_id, total_pnl=total, baseline_value=base, pnl_pct=pct, headline=headline, drivers=d, tables=tables,
        tolerance=_tolerance(total), reconciled=True, labels=LABELS,
        note="Each table is the same total regrouped. Holdings the scenario does not move (cash, unsupported instruments, no shock reaching them) contribute zero and are omitted.")
