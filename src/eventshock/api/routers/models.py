from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...pipeline.sentiment_card import SentimentModelCard
from ..deps import Container, get_container

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/sentiment", response_model=SentimentModelCard)
def sentiment_model(c: Container = Depends(get_container)) -> SentimentModelCard:
    """The sentiment model card: what it is, how it was chosen, how it scored and where it fails."""
    if c.sentiment_card is None:
        raise HTTPException(status_code=404, detail="no sentiment model: running the demo-fixture profile")
    return c.sentiment_card
