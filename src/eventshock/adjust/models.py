"""Contracts of the adjustment API."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..domain.base import ContractModel


class Knob(ContractModel):
    path: str = Field(description="dotted path: <config>.<section>...; the first segment is intelligence, portfolio or propagation")
    group: str = Field(description="scenario | relevance | mapping | intelligence")
    label: str
    description: str = ""
    kind: str = Field(description="number | integer | boolean | choice | text | text_list")
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    choices: list[str] = Field(default_factory=list)
    default: Any = Field(description="the shipped value (frozen in configs/)")
    value: Any = Field(description="the value in effect")
    adjusted: bool


class AddedEdge(ContractModel):
    """A transmission edge the user added (it has no shipped default)."""

    path: str
    risk_factor: str
    edge_id: str
    value: dict[str, Any]


class AdjustmentState(ContractModel):
    version: str = Field(description="hash of the overrides in effect; 'default' when none")
    count: int
    updated_at: str | None
    knobs: list[Knob]
    added_edges: list[AddedEdge]
    risk_factors: list[str] = Field(description="the risk factors a transmission edge can be added to")
    note: str


class ValidationIssue(ContractModel):
    path: str | None
    message: str


class ValidationReport(ContractModel):
    ok: bool
    issues: list[ValidationIssue]


class AdjustmentNotice(ContractModel):
    """Attached to a side-car answer when any override is in effect (omitted otherwise, so default payloads are unchanged)."""

    count: int
    paths: list[str]
    note: str = "Some values behind this answer were adjusted by you. They are your assumptions, not validated."


class PutRequest(ContractModel):
    values: dict[str, Any]
