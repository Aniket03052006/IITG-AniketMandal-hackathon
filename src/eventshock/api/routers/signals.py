from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...domain import EventCategory, EventStatus, RiskSignal, SourceType
from ..deps import Container, get_container
from ..schemas import SignalPage, SignalSummary

router = APIRouter(prefix="/signals", tags=["signals"])


def _summary(s: RiskSignal) -> SignalSummary:
    return SignalSummary(
        id=s.id,
        headline=s.document.headline,
        source=s.document.source,
        source_type=s.document.source_type,
        published_at=s.document.published_at,
        entity_id=s.entity.entity_id,
        entity_name=s.entity.entity_name,
        ticker=s.entity.ticker,
        sector=s.entity.sector,
        category=s.event.category,
        event_status=s.event.status,
        sentiment_score=s.sentiment.score,
        impact_score=s.impact.score if s.impact else None,
        status=s.status,
        source_count=s.evidence.source_count,
        data_origin=s.data_origin.value,
    )


@router.get("", response_model=SignalPage)
def list_signals(
    category: EventCategory | None = None,
    source_type: SourceType | None = None,
    min_impact: int | None = Query(default=None, ge=1, le=10),
    q: str | None = Query(default=None, max_length=100),
    event_status: EventStatus | None = None,
    c: Container = Depends(get_container),
) -> SignalPage:
    items = c.signals.list(category=category, source_type=source_type, min_impact=min_impact, query=q,
                           event_status=event_status)
    return SignalPage(total=len(items), items=[_summary(s) for s in items])


@router.get("/{signal_id}", response_model=RiskSignal)
def get_signal(signal_id: str, c: Container = Depends(get_container)) -> RiskSignal:
    signal = c.signals.get(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
    return signal
