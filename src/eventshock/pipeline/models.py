"""Report contracts for the ingestion pipeline (served by ``GET /api/pipeline/report``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ..domain import SourceType
from ..domain.base import ContractModel


class QuarantinedRecord(ContractModel):
    source: str
    record_ref: str
    code: str
    detail: str
    preview: str


class SourceReport(ContractModel):
    name: str
    source_type: SourceType
    license: str
    attribution: str
    origin_url: str
    notes: str
    records: int
    quarantined: int
    accepted: int
    exact_duplicates_folded: int
    signals: int


class FetchQuery(ContractModel):
    """Final outcome of one download request, collapsed over its attempts (failures are never hidden)."""

    query: str
    status: str = Field(description="ok | error (latest attempt)")
    attempts: int
    returned: int
    added: int
    last_error: str


class PipelineCounts(ContractModel):
    records_read: int
    quarantined: int
    accepted: int
    exact_duplicates_folded: int
    reports_in_signals: int = Field(description="distinct reports represented by signals (canonical + corroborating)")
    signals: int
    entity_resolved: int
    entity_unknown: int
    multi_entity: int
    rejected_ambiguous_mentions: int = Field(description="ambiguous-name candidates refused by entity resolution")
    syndicated: int
    near_duplicates: int
    same_event: int


class PipelineReport(ContractModel):
    snapshot_id: str
    description: str
    replay_as_of: datetime
    window_start: datetime
    window_end: datetime
    pipeline_version: str
    entity_resolver_version: str
    enrichment_version: str
    output_digest: str = Field(description="sha256 of the canonical JSON of all signals; equal digest = identical replay")
    counts: PipelineCounts
    sources: list[SourceReport]
    quarantine_by_code: dict[str, int]
    quarantine_sample: list[QuarantinedRecord]
    stage_origins: dict[str, str] = Field(description="what is real vs placeholder in this run")
    fetch_log: list[FetchQuery] = Field(default_factory=list, description="how the snapshot was downloaded")
    superseded_requests: int = Field(
        default=0, description="distinct requests from an abandoned earlier download plan, left out of fetch_log")
