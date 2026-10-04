from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...pipeline.engine import Outcome
from ...services.analyze import AnalysisInputError
from ..deps import Container, get_container
from ..schemas import AnalyzeRequest, AnalyzeResponse, Rejection
from .signals import summarise

router = APIRouter(tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest, c: Container = Depends(get_container)) -> AnalyzeResponse:
    """Analyse pasted text through the same engine as the live feed. Always 200 for a usable request: ``outcome`` says what happened
    (a text that cannot be scored is ``QUARANTINED`` with the reason, never given a guessed value)."""
    if c.analyzer is None:
        raise HTTPException(status_code=503, detail="analysis needs the replay profile (trained models); the demo profile has none")
    try:
        r = c.analyzer.analyze(req.text, source_type=req.source_type, published_at=req.published_at, source=req.source)
    except AnalysisInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    o = r.outcome
    assessment = c.assessments.detail(r.signal) if (c.assessments and r.signal) else None
    notes = list(r.notes)
    if assessment is not None:
        ex = assessment.extraction
        if ex.fallback_reason:
            notes.append(f"The language model could not be used ({ex.fallback_reason}); the deterministic rules read the text instead.")
        notes += ex.notes
    return AnalyzeResponse(
        outcome=o.outcome.value, signal_id=o.signal_id, signal=summarise(c, r.signal) if r.signal else None,
        rejection=Rejection(code=o.code or "UNKNOWN", detail=o.detail or "") if o.outcome is Outcome.QUARANTINED else None,
        headline=r.headline, analysed_chars=r.analysed_chars, truncated=r.truncated, notes=notes, assessment=assessment)
