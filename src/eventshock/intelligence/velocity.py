"""Narrative velocity: how the count of independent sources grows over time. Evidence about spread, never a severity input."""

from __future__ import annotations

from .config import VelocityCfg
from .grouping import GReport
from .model import Availability, VelocityPoint, VelocityView


def build_velocity(reports: list[GReport], cfg: VelocityCfg, *, trusted: bool) -> VelocityView:
    empty = dict(series=[], window_start=None, window_end=None, window_hours=None, source_growth=None, velocity_per_hour=None,
                 acceleration=None, acceleration_reason=None)
    if not trusted:
        return VelocityView(availability=Availability.UNAVAILABLE, reason="The report timestamps were assigned by the replay, not published by the source, so the pace of coverage cannot be measured.", **empty)
    rs = sorted(reports, key=lambda r: (r.published_at, r.id))
    if not rs:
        return VelocityView(availability=Availability.UNAVAILABLE, reason="No report at or before the requested time.", **empty)

    series: list[VelocityPoint] = []
    ind = n = 0
    bucket = cfg.bucket_minutes * 60
    t0 = rs[0].published_at
    cur: int | None = None
    for r in rs:
        n += 1
        ind += 1 if r.independent else 0
        b = int((r.published_at - t0).total_seconds() // bucket)
        pt = VelocityPoint(at=r.published_at, independent_sources=ind, reports=n)
        if cur == b and series:
            series[-1] = pt  # one point per bucket: its last state
        else:
            series.append(pt)
            cur = b
    t1 = rs[-1].published_at
    span_h = (t1 - t0).total_seconds() / 3600
    base = dict(series=series, window_start=t0, window_end=t1, window_hours=round(span_h, 3))
    first_ind = 1 if rs[0].independent else 0  # the event starts with its first report; growth is counted from there
    growth = f"{first_ind} → {ind} independent source{'s' if ind != 1 else ''} over {span_h:.1f} h" if ind != first_ind or span_h else None
    if len(rs) < cfg.min_reports:
        return VelocityView(availability=Availability.ABSTAINED, reason=f"{len(rs)} report(s): fewer than {cfg.min_reports} are needed to state a pace.",
                            source_growth=growth, velocity_per_hour=None, acceleration=None, acceleration_reason="too few reports", **base)
    if span_h < cfg.min_span_hours:
        return VelocityView(availability=Availability.PARTIAL, reason=f"All reports fall within {cfg.min_span_hours:g} h, so a rate per hour would mean nothing.",
                            source_growth=growth, velocity_per_hour=None, acceleration=None, acceleration_reason="window too short", **base)
    velocity = round((ind - first_ind) / span_h, 4)
    accel: float | None = None
    why: str | None = None
    if len(rs) < cfg.accel_min_reports:
        why = f"{len(rs)} reports: acceleration needs at least {cfg.accel_min_reports}."
    elif span_h / 2 < cfg.min_span_hours:
        why = f"each half of the window must span at least {cfg.min_span_hours:g} h."
    else:
        mid = t0 + (t1 - t0) / 2
        first_half = [r for r in rs if r.published_at <= mid]
        ind_mid = sum(1 for r in first_half if r.independent)
        v1 = (ind_mid - first_ind) / (span_h / 2)
        v2 = (ind - ind_mid) / (span_h / 2)
        accel = round(v2 - v1, 4)
    return VelocityView(availability=Availability.AVAILABLE, reason=None, source_growth=growth, velocity_per_hour=velocity, acceleration=accel,
                        acceleration_reason=why, **base)
