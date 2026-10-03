from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...pipeline.event_card import EventModelCard
from ...pipeline.impact_card import ImpactModelCard
from ...pipeline.sentiment_card import SentimentModelCard
from ..deps import Container, get_container

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/sentiment", response_model=SentimentModelCard)
def sentiment_model(c: Container = Depends(get_container)) -> SentimentModelCard:
    """The sentiment model card: what it is, how it was chosen, how it scored and where it fails."""
    if c.sentiment_card is None:
        raise HTTPException(status_code=404, detail="no sentiment model: running the demo-fixture profile")
    return c.sentiment_card


@router.get("/event", response_model=EventModelCard)
def event_model(c: Container = Depends(get_container)) -> EventModelCard:
    """The event model card: training data, abstention, per-class reliability, scores and failure modes."""
    if c.event_card is None:
        raise HTTPException(status_code=404, detail="no event model: running the demo-fixture profile")
    return c.event_card


@router.get("/impact", response_model=ImpactModelCard)
def impact_model(c: Container = Depends(get_container)) -> ImpactModelCard:
    """The impact model card: per-scope lifecycle, baselines vs model, calibration, acceptance, limits."""
    if c.impact_card is None:
        raise HTTPException(
            status_code=404, detail="no impact model: the demo profile, or no artifact (heuristic impact)")
    return c.impact_card
