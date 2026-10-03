"""Impact feature schema v2: the v1 schema plus the structured-calendar block (and, optionally, a representation block).

v1 (``impact_features``) is untouched, so the served ``impact-v1`` artifact and its market-context pack keep loading. This module only
*extends* the names: the nested rungs of the Stage 4 ladder are

    R2   market state + timing                          (v1's R2)
    R2s  R2 + structured calendar                       (new: availability classes a and b, see ``event_context``)
    R3   R2 + the frozen text-model outputs             (v1's R3)
    R3s  R3 + structured calendar
    R3h  R3s + the hybrid/affect block                  (only if the representation rule adopted one; otherwise a diagnostic)

Every name is registered ``AT_EVENT_TIME`` in ``modeling.leakage.FEATURE_REGISTRY``; the study refuses to run otherwise.
"""

from __future__ import annotations

from .event_context import ISSUER_CALENDAR, MARKET_CALENDAR
from .impact_features import DOC, ISSUER, MARKET, SCOPES, STATE, TEXT

FEATURE_SCHEMA_V2 = "impact-features-v2"
RUNGS_V2 = ("R2", "R2s", "R3", "R3s", "R3h")
CALENDAR = {ISSUER: list(ISSUER_CALENDAR), MARKET: list(MARKET_CALENDAR)}
# the representation block: names are filled by the bake-off's winner (empty means "no block was adopted")
AFFECT: list[str] = []


def feature_names_v2(scope: str, rung: str, affect: list[str] | None = None) -> list[str]:
    base = [*STATE[scope], *DOC[scope]]
    if rung == "R2":
        return base
    if rung == "R2s":
        return [*base, *CALENDAR[scope]]
    if rung == "R3":
        return [*base, *TEXT]
    if rung == "R3s":
        return [*base, *CALENDAR[scope], *TEXT]
    if rung == "R3h":
        return [*base, *CALENDAR[scope], *TEXT, *(AFFECT if affect is None else affect)]
    raise ValueError(f"unknown rung {rung!r}")


# Track F (filing events): the report IS the filing, so its own item codes are published at event time (class b)
FILING_ITEMS = ["item_earnings", "item_deal", "item_distress", "item_financing", "item_leadership", "item_other"]
FILING_RUNGS = ("F0", "F1", "F2")


def filing_feature_names(rung: str) -> list[str]:
    """F0 market state + timing; F1 + the calendar block; F2 + the filing's own item codes."""
    from .impact_features import TIMING

    base = [*STATE[ISSUER], "dow", "local_hour", *TIMING]
    if rung == "F0":
        return base
    if rung == "F1":
        return [*base, *CALENDAR[ISSUER]]
    if rung == "F2":
        return [*base, *CALENDAR[ISSUER], *FILING_ITEMS]
    raise ValueError(f"unknown filing rung {rung!r}")


ALL_FEATURES_V2 = sorted({n for sc in SCOPES for n in feature_names_v2(sc, "R3h")} | set(FILING_ITEMS))


def feature_group_v2(name: str) -> str:
    """Family label (extends ``impact_features.feature_group`` for the calendar block)."""
    from .impact_features import feature_group

    if name.startswith("earn_"):
        return "earnings calendar (known in advance)"
    if name.startswith("f8k_"):
        return "recent SEC filings (published before the report)"
    if name.startswith("fomc_"):
        return "scheduled FOMC decision (known in advance)"
    if name.startswith("item_"):
        return "the filing's own item codes (published with it)"
    return feature_group(name)
