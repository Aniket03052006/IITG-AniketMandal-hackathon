"""A two-way table of a portfolio's value or of a stress run's modeled change. Pure arithmetic over figures that already exist.

The cells must add up to the total they claim to break down (within a cent, far above float noise): a table that does not reconcile raises, the
same rule as the stress attribution. Zero cells are left out. Rows and columns are ordered by their totals so the biggest sit top-left.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Literal

from .models import AxisItem, CrossCell, CrossTab

TOLERANCE = 0.01


def build_crosstab(entries: Iterable[tuple[str, str, str, str, float, str]], *, unit: Literal["market_value", "pnl"], row_label: str, col_label: str,
                   total: float, largest_first: bool = True) -> CrossTab:
    """``entries``: (row key, row label, column key, column label, value, asset id). ``largest_first`` sorts by size; otherwise by most negative first."""
    cell: dict[tuple[str, str], float] = defaultdict(float)
    assets: dict[tuple[str, str], set[str]] = defaultdict(set)
    rlabel: dict[str, str] = {}
    clabel: dict[str, str] = {}
    for rk, rl, ck, cl, value, asset_id in entries:
        cell[(rk, ck)] += value
        assets[(rk, ck)].add(asset_id)
        rlabel.setdefault(rk, rl)
        clabel.setdefault(ck, cl)
    cell = {k: v for k, v in cell.items() if v != 0.0}
    rt: dict[str, float] = defaultdict(float)
    ct: dict[str, float] = defaultdict(float)
    for (rk, ck), v in cell.items():
        rt[rk] += v
        ct[ck] += v
    order = (lambda t: (-t[1], t[0])) if largest_first else (lambda t: (t[1], t[0]))
    rows = [AxisItem(key=k, label=rlabel[k], total=v) for k, v in sorted(rt.items(), key=order)]
    cols = [AxisItem(key=k, label=clabel[k], total=v) for k, v in sorted(ct.items(), key=order)]
    cells = [CrossCell(row=rk, col=ck, value=v, position_count=len(assets[(rk, ck)])) for (rk, ck), v in sorted(cell.items())]
    s = sum(c.value for c in cells)
    resid = total - s
    tol = max(TOLERANCE, 1e-9 * abs(total))
    if abs(resid) > tol:
        raise ValueError(f"{row_label} by {col_label} does not reconcile: cells add to {s:,.4f} but the total is {total:,.4f}")
    return CrossTab(unit=unit, row_label=row_label, col_label=col_label, rows=rows, cols=cols, cells=cells, total=total, sum=s, residual=resid, reconciled=True)
