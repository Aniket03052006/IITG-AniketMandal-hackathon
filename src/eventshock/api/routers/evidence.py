from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...pipeline.evidence_card import EvidenceBundle
from ...services.outcome_check import OutcomeCheck
from ..deps import Container, get_container

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("", response_model=EvidenceBundle)
def evidence(c: Container = Depends(get_container)) -> EvidenceBundle:
    """How far the numbers can be trusted.

    Stage status, data foundation, feature availability, the incremental-value study and the
    representation comparison. Read-only: built once at start-up from the loaded model cards and
    the committed evidence files. A section whose evidence file does not exist says so and names
    the command that produces it; nothing is computed or invented per request.
    """
    if c.evidence is None:
        raise HTTPException(status_code=404, detail="no evidence bundle: running the demo-fixture profile")
    return c.evidence


@router.get("/outcome-check", response_model=OutcomeCheck)
def outcome_check(c: Container = Depends(get_container)) -> OutcomeCheck:
    """Stage 8: whether the severity scale ranks realised moves (it does not, out of sample), what the market does around ordinary news, and what retrieval earned. Built from committed evidence files."""
    if c.outcome_check is None:
        raise HTTPException(status_code=404, detail="no outcome check: running the demo-fixture profile")
    return c.outcome_check
