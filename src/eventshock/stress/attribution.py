"""Aggregate position results into contribution tables (FR-13, FR-15)."""

from __future__ import annotations

from collections import defaultdict

from ..domain import RiskFactor
from ..domain.stress import Contribution, Contributions, PositionResult, UncoveredExposure


def _share(delta: float, total: float) -> float | None:
    return None if abs(total) < 1e-9 else delta / total


def _group(positions: list[PositionResult], key_fn, label_fn, total: float) -> list[Contribution]:
    base: dict[str, float] = defaultdict(float)
    delta: dict[str, float] = defaultdict(float)
    labels: dict[str, str] = {}
    for p in positions:
        k = key_fn(p)
        base[k] += p.baseline_value
        delta[k] += p.delta
        labels[k] = label_fn(p)
    rows = [
        Contribution(key=k, label=labels[k], baseline_value=base[k], delta=delta[k],
                     share_of_loss=_share(delta[k], total))
        for k in base
    ]
    # Largest loss first; ties broken by key for determinism.
    return sorted(rows, key=lambda c: (c.delta, c.key))


def build_contributions(positions: list[PositionResult], top_n: int) -> Contributions:
    total = sum(p.delta for p in positions)
    by_factor: dict[RiskFactor, float] = defaultdict(float)
    for p in positions:
        for f, v in p.by_factor.items():
            by_factor[f] += v
    factor_rows = [
        Contribution(key=f.value, label=f.value, baseline_value=0.0, delta=v,
                     share_of_loss=_share(v, total))
        for f, v in by_factor.items()
    ]
    return Contributions(
        by_asset_class=_group(positions, lambda p: p.asset_class.value, lambda p: p.asset_class.value, total),
        by_sector=_group(positions, lambda p: p.sector, lambda p: p.sector, total),
        by_entity=_group(positions, lambda p: p.entity_id, lambda p: p.entity_id, total),
        by_factor=sorted(factor_rows, key=lambda c: (c.delta, c.key)),
        top_positions=sorted(
            (
                Contribution(key=p.asset_id, label=p.name, baseline_value=p.baseline_value,
                             delta=p.delta, share_of_loss=_share(p.delta, total))
                for p in positions
            ),
            key=lambda c: (c.delta, c.key),
        )[:top_n],
    )


def find_uncovered(positions: list[PositionResult], portfolio_value: float) -> UncoveredExposure:
    """Positions that received no shock at all — surfaced rather than silently treated as safe."""
    ids = [p.asset_id for p in positions if not p.shocks]
    value = sum(p.baseline_value for p in positions if not p.shocks)
    return UncoveredExposure(
        asset_count=len(ids),
        market_value=value,
        share_of_portfolio=value / portfolio_value if portfolio_value else 0.0,
        asset_ids=ids,
    )
