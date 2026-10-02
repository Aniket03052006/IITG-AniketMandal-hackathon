from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...pipeline.models import PipelineReport
from ..deps import Container, get_container

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/report", response_model=PipelineReport)
def report(c: Container = Depends(get_container)) -> PipelineReport:
    """What the ingestion pipeline did to the replay snapshot: counts, quarantine, sources, digest."""
    if c.pipeline_report is None:
        raise HTTPException(status_code=404, detail="no pipeline report: running the demo-fixture profile")
    return c.pipeline_report
