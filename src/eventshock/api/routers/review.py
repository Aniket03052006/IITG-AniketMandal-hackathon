from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from ...monitor.models import Mode
from ...review.models import ReviewDecision, ReviewDecisionInput, ReviewDecisionList, ReviewQueue
from ...review.service import ReviewInvalid
from ...review.store import ReviewLimit
from ..deps import Container, get_container
from .portfolio import PID
from .propagation import _book

router = APIRouter(prefix="/review", tags=["review"])


def _svc(c: Container):  # noqa: ANN202
    if c.review is None:
        raise HTTPException(status_code=404, detail="the analyst review queue is available in the replay profile only")
    return c.review


@router.get("/queue", response_model=ReviewQueue,
            description="The events a person should look at, each with the named rule(s) that put it there (sources disagree, high severity with an unresolved subject or one source, material to the book, "
                        "a large modeled loss, escalating, or changed since it was reviewed). Ordered by a key shown on every item, not scored. `status` filters OPEN (default), REVIEWED, DISMISSED or ALL. "
                        "REPLAY reads the fixed replay clock; LIVE reads the live monitor. A triage list derived from existing signals: never ground truth, and it changes nothing that is served.")
def get_queue(mode: Mode = Query(default=Mode.REPLAY), status: str = Query(default="OPEN"), limit: int | None = Query(default=None, ge=1, le=500), portfolio_id: str | None = PID,
              c: Container = Depends(get_container)) -> ReviewQueue:
    svc = _svc(c)
    try:
        return svc.queue(mode=mode, status=status, portfolio=_book(c, portfolio_id), limit=limit)
    except ReviewInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/decisions", response_model=ReviewDecision, status_code=201,
             description="Record what an analyst decided about an event: REVIEWED, DISMISSED, or OPEN (reopen), with an optional note. Append-only; the latest decision is the current one. "
                         "A decision is a note, never ground truth: it does not change a model, a score, a threshold or any served output.")
def post_decision(body: ReviewDecisionInput, x_analyst_id: str | None = Header(default=None), c: Container = Depends(get_container)) -> ReviewDecision:
    svc = _svc(c)
    try:
        return svc.decide(body, header_analyst=x_analyst_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ReviewLimit as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/decisions", response_model=ReviewDecisionList, description="Recorded decisions, newest first; `event_id` (an event id or a signal id) narrows it to one event's history.")
def list_decisions(event_id: str | None = Query(default=None), limit: int | None = Query(default=None, ge=1, le=2000), c: Container = Depends(get_container)) -> ReviewDecisionList:
    return _svc(c).history(event_id, limit)
