from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ...services.live import LiveStatus, LiveUnavailable
from ..deps import Container, get_container

router = APIRouter(prefix="/live", tags=["live"])


class LiveStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    source: Literal["gdelt", "edgar", "both", "capture"] | None = None


@router.get("/status", response_model=LiveStatus)
def live_status(c: Container = Depends(get_container)) -> LiveStatus:
    """The live feed's health, honestly: OFF by default; DEGRADED / ERROR when the source fails (replay data keeps serving)."""
    if c.live is None:
        raise HTTPException(status_code=404, detail="the live feed exists only in the replay profile")
    return c.live.status()


@router.put("/state", response_model=LiveStatus)
def live_set_state(body: LiveStateRequest, c: Container = Depends(get_container)) -> LiveStatus:
    """The switch. ``enabled: true`` starts polling the chosen source (the first available when omitted); ``false`` stops it.

    Off keeps every signal already ingested and starts no further request. The feed is OFF at every start unless configured on, and a
    source that cannot start (for example a capture file that does not exist) is a 409 that says why and leaves the feed OFF.
    """
    if c.live is None:
        raise HTTPException(status_code=404, detail="the live feed exists only in the replay profile")
    try:
        return c.live.set_state(body.enabled, body.source)
    except LiveUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/refresh", response_model=LiveStatus)
def live_refresh(c: Container = Depends(get_container)) -> LiveStatus:
    """Poll the source once now. 409 when live is off. A failed poll is reported in the status, not as an HTTP error."""
    if c.live is None or c.live.source is None:
        raise HTTPException(status_code=409, detail="live is off: turn it on with the Live switch (or start with EVENTSHOCK_LIVE=1 / make run-live)")
    return c.live.refresh()
