from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...services.live import LiveStatus
from ..deps import Container, get_container

router = APIRouter(prefix="/live", tags=["live"])


@router.get("/status", response_model=LiveStatus)
def live_status(c: Container = Depends(get_container)) -> LiveStatus:
    """The live feed's health, honestly: OFF by default; DEGRADED / ERROR when the source fails (replay data keeps serving)."""
    if c.live is None:
        raise HTTPException(status_code=404, detail="the live feed exists only in the replay profile")
    return c.live.status()


@router.post("/refresh", response_model=LiveStatus)
def live_refresh(c: Container = Depends(get_container)) -> LiveStatus:
    """Poll the source once now. 409 when live is off. A failed poll is reported in the status, not as an HTTP error."""
    if c.live is None or c.live.source is None:
        raise HTTPException(status_code=409, detail="live is off: start with EVENTSHOCK_LIVE=1 (make run-live)")
    return c.live.refresh()
