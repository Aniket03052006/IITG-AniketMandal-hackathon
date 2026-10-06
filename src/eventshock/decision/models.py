"""Labelling vocabulary shared by every decision side-car.

Seven kinds of statement are kept apart wherever they appear: what a source reported, what EventShock assessed, what an external market is pricing, what a
user assumed for a scenario, what history shows, what happened afterwards, and what a product rule did. None is ever presented as another.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from ..domain.base import ContractModel

LABEL_ASSUMPTION = "SCENARIO ASSUMPTION"
LABEL_SIMULATION = "SCENARIO SIMULATION — NOT A PREDICTION"
LABEL_EXTERNAL_MARKET = "EXTERNAL MARKET OBSERVATION"
LABEL_HISTORICAL = "HISTORICAL OBSERVATION"


class ObservationKind(StrEnum):
    SOURCE_EVENT = "SOURCE_EVENT"                          # a report a source published
    EVENTSHOCK_ASSESSMENT = "EVENTSHOCK_ASSESSMENT"        # what EventShock derived (scores, tiers, states)
    EXTERNAL_MARKET_OBSERVATION = "EXTERNAL_MARKET_OBSERVATION"
    SCENARIO_ASSUMPTION = "SCENARIO_ASSUMPTION"
    HISTORICAL_OBSERVATION = "HISTORICAL_OBSERVATION"
    REALISED_OUTCOME = "REALISED_OUTCOME"
    PRODUCT_RULE = "PRODUCT_RULE"                          # a deterministic rule of the product (a threshold, a ranking order)


class ProvenanceRef(ContractModel):
    """Where one value came from: a kind, the component that produced it, and (when there is one) the record it came from."""

    kind: ObservationKind
    source: str = Field(description="the component or dataset, e.g. 'intelligence.lifecycle', 'monitor.diff', 'kalshi'")
    ref_id: str | None = Field(default=None, description="signal, report, run or market id the value was read from")
    as_of: datetime | None = None
