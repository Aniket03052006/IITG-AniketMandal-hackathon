"""Evaluation splits that mimic "an event arriving now".

Impact: strictly time ordered, with an embargo so a train row's target window cannot overlap the next period.
A train row is dropped if its session is within ``embargo_sessions`` of the start of the validation period; a
validation row likewise before the test period. The ``live`` period (news-only, publisher/first-seen clocks) is a
separate, locked test. Rows between periods are ``gap`` (none exist in the current data: nothing covers 2023-2025).
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter

from .config import ImpactSplitConfig

IMPACT_SPLITS = ("train", "val", "test", "live")


def impact_split(s0: int, dates: list[str], cfg: ImpactSplitConfig) -> str:
    """Split name for the session index ``s0`` ("embargo" / "gap" mark rows that must not be used)."""
    d = dates[s0]
    iso = {k: getattr(cfg, k).isoformat() for k in ("train_end", "val_start", "val_end", "test_start", "test_end", "live_start")}
    if d >= iso["live_start"]:
        return "live"
    if iso["test_start"] <= d <= iso["test_end"]:
        return "test"
    if iso["val_start"] <= d <= iso["val_end"]:
        if s0 >= bisect_left(dates, iso["test_start"]) - cfg.embargo_sessions:
            return "embargo"
        return "val"
    if d <= iso["train_end"]:
        if s0 >= bisect_left(dates, iso["val_start"]) - cfg.embargo_sessions:
            return "embargo"
        return "train"
    return "gap"


def assign_impact_splits(rows: list[dict], dates: list[str], cfg: ImpactSplitConfig) -> Counter[str]:
    """Stamp ``split`` on every row (in place) and return the counts."""
    for r in rows:
        r["split"] = impact_split(r["s0"], dates, cfg)
    return Counter(r["split"] for r in rows)
