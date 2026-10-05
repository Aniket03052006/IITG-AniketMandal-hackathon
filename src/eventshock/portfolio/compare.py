"""Two portfolios, one event: where do the modeled changes differ? A regrouping of two finished stress runs; nothing is recomputed."""

from __future__ import annotations

from ..domain import StressResult
from ..domain.stress import Contribution
from .models import DiffRow, PortfolioComparison, PortfolioListItem

FACTOR_NAME = {"EQUITY": "equity price", "RATES_BPS": "interest-rate", "CREDIT_SPREAD_BPS": "credit-spread", "PD_MULTIPLIER": "default-probability", "LGD_ADD": "loss-given-default"}


def _rows(a: list[Contribution], base_a: float, b: list[Contribution], base_b: float, label=lambda k, x: x) -> list[DiffRow]:  # noqa: ANN001
    da = {c.key: c for c in a}
    db = {c.key: c for c in b}
    out = []
    for k in sorted(set(da) | set(db)):
        ca, cb = da.get(k), db.get(k)
        va, vb = (ca.delta if ca else 0.0), (cb.delta if cb else 0.0)
        pa, pb = (va / base_a if base_a else 0.0), (vb / base_b if base_b else 0.0)
        out.append(DiffRow(key=k, label=label(k, (ca or cb).label), a_pct=pa, b_pct=pb, gap_pct=pa - pb, a_value=va, b_value=vb))
    return sorted(out, key=lambda r: (-abs(r.gap_pct), r.key))


def compare_runs(signal_id: str, scenario_id: str | None, ia: PortfolioListItem, ib: PortfolioListItem, ra: StressResult, rb: StressResult) -> PortfolioComparison:
    note = "Modeled scenario changes under illustrative shock sizes, as a percent of each portfolio's own value. Not forecasts."
    ok = ra.summary is not None and rb.summary is not None and ra.contributions is not None and rb.contributions is not None
    if not ok:
        reasons = [f"{n}: {r.reason or r.status.value}" for n, r in ((ia.name, ra), (ib.name, rb)) if r.summary is None]
        return PortfolioComparison(
            signal_id=signal_id, scenario_id=scenario_id, a=ia, b=ib, run_a=ra.run_id, run_b=rb.run_id, status_a=ra.status.value, status_b=rb.status.value,
            pnl_pct_a=ra.summary.pnl_pct if ra.summary else None, pnl_pct_b=rb.summary.pnl_pct if rb.summary else None,
            pnl_a=ra.summary.pnl if ra.summary else None, pnl_b=rb.summary.pnl if rb.summary else None, by_sector=[], by_factor=[], by_asset_class=[],
            difference="No comparison: " + "; ".join(reasons), note=note)
    assert ra.summary and rb.summary and ra.contributions and rb.contributions
    sa, sb = ra.summary, rb.summary
    by_sector = _rows(ra.contributions.by_sector, sa.baseline_value, rb.contributions.by_sector, sb.baseline_value)
    by_factor = _rows(ra.contributions.by_factor, sa.baseline_value, rb.contributions.by_factor, sb.baseline_value, lambda k, _l: FACTOR_NAME.get(k, k))
    by_class = _rows(ra.contributions.by_asset_class, sa.baseline_value, rb.contributions.by_asset_class, sb.baseline_value)
    gap = sa.pnl_pct - sb.pnl_pct
    if abs(gap) < 1e-9:
        diff = f"Both portfolios show the same modeled change ({sa.pnl_pct:+.2%})."
    else:
        worse, better = (ia, ib) if gap < 0 else (ib, ia)
        lead = by_factor[0] if by_factor else None
        sec = by_sector[0] if by_sector else None
        parts = [f"{worse.name} shows the larger modeled loss ({min(sa.pnl_pct, sb.pnl_pct):+.2%} against {max(sa.pnl_pct, sb.pnl_pct):+.2%} for {better.name})."]
        if lead and abs(lead.gap_pct) > 1e-9:
            parts.append(f"The largest gap by risk factor is the {lead.label} shock ({lead.a_pct:+.2%} against {lead.b_pct:+.2%}).")
        if sec and abs(sec.gap_pct) > 1e-9:
            parts.append(f"By sector it is {sec.label} ({sec.a_pct:+.2%} against {sec.b_pct:+.2%}).")
        diff = " ".join(parts)
    return PortfolioComparison(
        signal_id=signal_id, scenario_id=scenario_id, a=ia, b=ib, run_a=ra.run_id, run_b=rb.run_id, status_a=ra.status.value, status_b=rb.status.value,
        pnl_pct_a=sa.pnl_pct, pnl_pct_b=sb.pnl_pct, pnl_a=sa.pnl, pnl_b=sb.pnl, by_sector=by_sector, by_factor=by_factor, by_asset_class=by_class,
        difference=diff, note=note)
