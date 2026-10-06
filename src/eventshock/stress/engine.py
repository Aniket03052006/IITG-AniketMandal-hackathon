"""Pure, deterministic revaluation formulas. No I/O, no randomness, no model calls.

Notation: V = baseline market value, s = scaled shock. Every position records the formula it used so
the UI can show the arithmetic (explainability, FR-15).

- EQUITY      dV = V * beta * s      (MARKET scope; ISSUER/SECTOR shocks are idiosyncratic: V * s)
- BOND        dP/P = -D * (d_rates + d_spread) / 10_000, floored at -100%
- LOAN        value = EAD - EL;  stressed EL = EAD * min(1, PD') * min(1, LGD')
              PD' = PD * (1 + (m - 1) * default_sensitivity),  LGD' = LGD + a
- DERIVATIVE  dV = delta * underlying_notional * s   (first-order delta-equivalent; gamma deferred)
- CASH        dV = 0   (its value is fixed by definition; no market shock reaches it, except the exchange rate when it is held in another currency)
- OTHER       dV = 0   (no revaluation is defined for it; reported as not stressed, never as safe)

Scenario-lab factors (exposure is data on the position, never a prior in the engine; a position that carries none is not moved):
- FX_PCT        dV = V * s   for a position whose ``currency`` is the shocked one (DERIVATIVE: delta * underlying * s; LOAN: V * s)
- COMMODITY_PCT dV = V * k * s   for an EQUITY with ``commodity_sensitivity`` k (DERIVATIVE: delta * underlying * k * s)

A BOND takes ``spread_sensitivity`` x the credit-spread shock (1 for corporate credit, 0 for government debt).
"""

from __future__ import annotations

from collections.abc import Iterable

from ..domain import (
    LAB_FACTORS,
    SCOPE_SPECIFICITY,
    AssetClass,
    Portfolio,
    PortfolioAsset,
    RiskFactor,
    ShockScope,
)
from ..domain.stress import AppliedShock, PositionResult, PositionShock

ENGINE_VERSION = "1.0.0"
BPS = 10_000.0


def scaled_shock_value(factor: RiskFactor, base: float, scale: float) -> float:
    """Severity scaling. PD multipliers scale their excess over 1; every other factor scales linearly."""
    if factor is RiskFactor.PD_MULTIPLIER:
        return 1.0 + (base - 1.0) * scale
    return base * scale


def select_shocks(
    asset: PortfolioAsset,
    shocks: Iterable[AppliedShock],
    signal_entity_id: str | None,
    signal_sector: str | None,
) -> dict[RiskFactor, AppliedShock]:
    """Per factor, pick the most specific applicable shock for this asset (ISSUER > SECTOR > MARKET)."""
    chosen: dict[RiskFactor, AppliedShock] = {}
    for shock in shocks:
        if not shock.applicable:
            continue
        if shock.scope is ShockScope.ISSUER and asset.entity_id != (shock.entity_id or signal_entity_id):
            continue
        if shock.factor is RiskFactor.FX_PCT and asset.currency != shock.currency:
            continue
        if shock.scope is ShockScope.SECTOR and asset.sector != (shock.sector or signal_sector):
            continue
        current = chosen.get(shock.factor)
        if current is None or SCOPE_SPECIFICITY[shock.scope] > SCOPE_SPECIFICITY[current.scope]:
            chosen[shock.factor] = shock
    return chosen


def _fx_effect(asset: PortfolioAsset, chosen: dict[RiskFactor, AppliedShock]) -> tuple[float, str] | None:
    """The exchange-rate effect on a position held in the shocked currency, or None when no FX shock reaches it."""
    shock = chosen.get(RiskFactor.FX_PCT)
    if shock is None:
        return None
    s = shock.scaled_value
    if asset.asset_type is AssetClass.DERIVATIVE:
        return (asset.delta or 0.0) * asset.notional * s, f"FX {asset.currency}: dV = delta x underlying x s = {asset.delta:+.2f} x {asset.notional:,.0f} x {s:+.4f}"
    return asset.market_value * s, f"FX {asset.currency}: dV = V x s = {asset.market_value:,.0f} x {s:+.4f}"


def _commodity_effect(asset: PortfolioAsset, chosen: dict[RiskFactor, AppliedShock]) -> tuple[float, str] | None:
    shock = chosen.get(RiskFactor.COMMODITY_PCT)
    k = asset.commodity_sensitivity
    if shock is None or k is None or asset.asset_type not in (AssetClass.EQUITY, AssetClass.DERIVATIVE):
        return None
    s = shock.scaled_value
    if asset.asset_type is AssetClass.DERIVATIVE:
        return (asset.delta or 0.0) * asset.notional * k * s, f"oil: dV = delta x underlying x k x s = {asset.delta:+.2f} x {asset.notional:,.0f} x {k:.2f} x {s:+.4f}"
    return asset.market_value * k * s, f"oil: dV = V x k x s = {asset.market_value:,.0f} x {k:.2f} x {s:+.4f}"


def _with_lab_factors(base, asset: PortfolioAsset, chosen: dict[RiskFactor, AppliedShock]):  # noqa: ANN001, ANN202
    """Add the FX and oil effects to a position's revaluation. Both are empty for every catalog scenario, so existing results are unchanged."""
    delta, by_factor, formula = base
    notes = [formula]
    for factor, fn in ((RiskFactor.FX_PCT, _fx_effect), (RiskFactor.COMMODITY_PCT, _commodity_effect)):
        got = fn(asset, chosen)
        if got is not None:
            amount, note = got
            by_factor = {**by_factor, factor: amount}
            delta += amount
            notes.append(note)
    return delta, by_factor, "; ".join(n for n in notes if n)


def _equity_effect(asset: PortfolioAsset, shock: AppliedShock | None) -> tuple[float, str]:
    if shock is None:
        return 0.0, "no equity shock applies"
    s = shock.scaled_value
    if shock.scope is ShockScope.MARKET:
        return asset.market_value * asset.beta * s, (
            f"dV = V x beta x s = {asset.market_value:,.0f} x {asset.beta:.2f} x {s:+.4f}"
        )
    return asset.market_value * s, f"dV = V x s = {asset.market_value:,.0f} x {s:+.4f}"


def _revalue_equity(asset: PortfolioAsset, chosen: dict[RiskFactor, AppliedShock]):
    delta, formula = _equity_effect(asset, chosen.get(RiskFactor.EQUITY))
    return delta, {RiskFactor.EQUITY: delta}, formula


def _revalue_derivative(asset: PortfolioAsset, chosen: dict[RiskFactor, AppliedShock]):
    shock = chosen.get(RiskFactor.EQUITY)
    if shock is None:
        return 0.0, {}, "no equity shock applies to the underlying"
    s = shock.scaled_value
    if shock.scope is ShockScope.MARKET:
        s *= asset.beta
    delta = (asset.delta or 0.0) * asset.notional * s
    formula = (
        f"dV = delta x underlying x s = {asset.delta:+.2f} x {asset.notional:,.0f} x {s:+.4f}"
    )
    return delta, {RiskFactor.EQUITY: delta}, formula


def _revalue_bond(asset: PortfolioAsset, chosen: dict[RiskFactor, AppliedShock]):
    duration = asset.duration or 0.0
    d_rates = chosen[RiskFactor.RATES_BPS].scaled_value if RiskFactor.RATES_BPS in chosen else 0.0
    d_spread = (
        chosen[RiskFactor.CREDIT_SPREAD_BPS].scaled_value * asset.spread_sensitivity
        if RiskFactor.CREDIT_SPREAD_BPS in chosen
        else 0.0
    )
    pct_rates = -duration * d_rates / BPS
    pct_spread = -duration * d_spread / BPS
    pct = pct_rates + pct_spread
    floor_factor = 1.0
    if pct < -1.0:  # a bond cannot lose more than its value
        floor_factor = -1.0 / pct
    by_factor: dict[RiskFactor, float] = {}
    if d_rates:
        by_factor[RiskFactor.RATES_BPS] = asset.market_value * pct_rates * floor_factor
    if d_spread:
        by_factor[RiskFactor.CREDIT_SPREAD_BPS] = asset.market_value * pct_spread * floor_factor
    delta = sum(by_factor.values())
    formula = (
        f"dP/P = -D x (d_rates + d_spread) = -{duration:.2f} x ({d_rates:.1f} + {d_spread:.1f}) bp"
        f" = {max(pct, -1.0):+.4%}"
    )
    return delta, by_factor, formula


def _revalue_loan(asset: PortfolioAsset, chosen: dict[RiskFactor, AppliedShock]):
    ead, pd, lgd = asset.notional, asset.pd or 0.0, asset.lgd or 0.0
    mult = chosen[RiskFactor.PD_MULTIPLIER].scaled_value if RiskFactor.PD_MULTIPLIER in chosen else 1.0
    lgd_add = chosen[RiskFactor.LGD_ADD].scaled_value if RiskFactor.LGD_ADD in chosen else 0.0
    pd_s = min(1.0, pd * (1.0 + (mult - 1.0) * asset.default_sensitivity))
    lgd_s = min(1.0, max(0.0, lgd + lgd_add))
    # Sequential attribution that sums exactly to the total EL change.
    d_pd = -ead * (pd_s - pd) * lgd
    d_lgd = -ead * pd_s * (lgd_s - lgd)
    by_factor: dict[RiskFactor, float] = {}
    if RiskFactor.PD_MULTIPLIER in chosen:
        by_factor[RiskFactor.PD_MULTIPLIER] = d_pd
    if RiskFactor.LGD_ADD in chosen:
        by_factor[RiskFactor.LGD_ADD] = d_lgd
    delta = d_pd + d_lgd
    formula = (
        f"EL: {ead:,.0f} x {pd:.2%} x {lgd:.0%} -> {ead:,.0f} x {pd_s:.2%} x {lgd_s:.0%}"
        f" (PD' = PD x (1 + (m-1) x sens), m = {mult:.2f}, sens = {asset.default_sensitivity:.2f})"
    )
    return delta, by_factor, formula


def _revalue_fixed(note: str):
    def revalue(asset: PortfolioAsset, chosen: dict[RiskFactor, AppliedShock]):  # noqa: ARG001
        return 0.0, {}, note
    return revalue


_REVALUE = {
    AssetClass.EQUITY: _revalue_equity,
    AssetClass.BOND: _revalue_bond,
    AssetClass.LOAN: _revalue_loan,
    AssetClass.DERIVATIVE: _revalue_derivative,
    AssetClass.CASH: _revalue_fixed("cash: dV = 0 (no shock moves it)"),
    AssetClass.OTHER: _revalue_fixed("not stressed: EventShock has no revaluation rule for this instrument"),
}


def revalue_asset(
    asset: PortfolioAsset,
    shocks: Iterable[AppliedShock],
    signal_entity_id: str | None,
    signal_sector: str | None,
) -> PositionResult:
    # cash and unsupported instruments take no market shock at all (so they never read as "covered"); cash held in another currency still takes the exchange-rate shock
    unshocked = asset.asset_type in (AssetClass.CASH, AssetClass.OTHER)
    chosen = select_shocks(asset, shocks, signal_entity_id, signal_sector)
    if unshocked:
        chosen = {RiskFactor.FX_PCT: chosen[RiskFactor.FX_PCT]} if asset.asset_type is AssetClass.CASH and RiskFactor.FX_PCT in chosen else {}
    delta, by_factor, formula = _with_lab_factors(_REVALUE[asset.asset_type](asset, chosen), asset, chosen)
    baseline = asset.market_value
    # Derivative MTM can be zero/negative; percentage change is only meaningful against |V|.
    pct = delta / abs(baseline) if baseline else 0.0
    return PositionResult(
        asset_id=asset.asset_id,
        name=asset.name,
        asset_class=asset.asset_type,
        entity_id=asset.entity_id,
        sector=asset.sector,
        baseline_value=baseline,
        stressed_value=baseline + delta,
        delta=delta,
        delta_pct=pct,
        shocks=[PositionShock(factor=f, scope=s.scope, value=s.scaled_value, sector=s.sector, currency=s.currency, entity_id=s.entity_id)
                for f, s in chosen.items() if f not in LAB_FACTORS or f in by_factor],
        by_factor=by_factor,
        formula=formula,
    )


def stress_portfolio(
    portfolio: Portfolio,
    shocks: list[AppliedShock],
    signal_entity_id: str | None,
    signal_sector: str | None,
) -> list[PositionResult]:
    return [revalue_asset(a, shocks, signal_entity_id, signal_sector) for a in portfolio.assets]
