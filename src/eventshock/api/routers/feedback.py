from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from ...feedback.models import Feedback, FeedbackInput, FeedbackList, FeedbackStats
from ...feedback.service import FeedbackInvalid
from ...feedback.store import FeedbackLimit
from ..deps import Container, get_container
from .portfolio import PID

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _svc(c: Container):  # noqa: ANN202
    if c.feedback is None:
        raise HTTPException(status_code=404, detail="analyst feedback is available in the replay profile only")
    return c.feedback


@router.post("", response_model=Feedback, status_code=201,
             description="Record what an analyst says about an event: RELEVANCE (relevant / partially relevant / irrelevant), SCOPE (correct / incorrect) or EVENT (correct / incorrect), with an optional comment. "
                         "ANALYST FEEDBACK: stored and counted, never ground truth, never used to change a model, a score, a threshold or any served output.")
def post_feedback(body: FeedbackInput, x_analyst_id: str | None = Header(default=None), portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> Feedback:
    svc = _svc(c)
    try:
        return svc.submit(body, header_analyst=x_analyst_id, portfolio_id=portfolio_id if portfolio_id and portfolio_id != "default" else None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FeedbackInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FeedbackLimit as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/statistics", response_model=FeedbackStats,
            description="Counts of analyst feedback: volume, relevance agreement, scope agreement, event agreement, and the event/type pairs that need review or where analysts disagree. Analyst feedback, not ground truth.")
def get_statistics(c: Container = Depends(get_container)) -> FeedbackStats:
    return _svc(c).statistics()


@router.get("", response_model=FeedbackList, description="Recorded feedback, newest first; `event_id` (an event id or a signal id) narrows it to one event.")
def list_feedback(event_id: str | None = Query(default=None), limit: int | None = Query(default=None, ge=1, le=2000), c: Container = Depends(get_container)) -> FeedbackList:
    return _svc(c).list(event_id, limit)
