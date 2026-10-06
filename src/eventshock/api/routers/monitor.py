from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...monitor.digest import Digest
from ...monitor.models import ChangeSet, ChangeType, Mode, MonitorCycle, MonitorStatus
from ..deps import Container, get_container
from .portfolio import PID
from .propagation import _book

router = APIRouter(prefix="/monitor", tags=["monitor"])


def _svc(c: Container):  # noqa: ANN202
    if c.monitor is None:
        raise HTTPException(status_code=404, detail="the risk monitor is available in the replay profile only")
    return c.monitor


@router.get("/status", response_model=MonitorStatus,
            description="Whether the monitor can answer in each mode: REPLAY (a fixed clock over the frozen signals; always available offline) and LIVE (the live feed, or a capture "
                        "replayed as if live). A live feed that is off or degraded never affects REPLAY.")
def get_status(mode: Mode = Query(default=Mode.REPLAY), c: Container = Depends(get_container)) -> MonitorStatus:
    return _svc(c).status(mode)


@router.get("/cycles", response_model=list[MonitorCycle], description="The REPLAY clock: one monitoring cycle per fixed step from the first report to the replay clock. Cycle 0 is the baseline.")
def get_cycles(c: Container = Depends(get_container)) -> list[MonitorCycle]:
    return _svc(c).cycles()


@router.get("/changes", response_model=ChangeSet,
            description="What changed recently. REPLAY: the changes detected in cycle `cycle` (default: the last) and the `window - 1` cycles before it, identical on every run. LIVE: the "
                        "persisted change log since `since`. One event can produce several changes per cycle; an article that belongs to an existing event is never a new risk.")
def get_changes(mode: Mode = Query(default=Mode.REPLAY), cycle: int | None = Query(default=None, ge=0), window: int = Query(default=1, ge=1, le=60),
                types: list[ChangeType] | None = Query(default=None), since: str | None = Query(default=None, description="LIVE only: an ISO timestamp"),
                portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> ChangeSet:
    svc = _svc(c)
    pf = _book(c, portfolio_id)
    wanted = set(types) if types else None
    if mode is Mode.REPLAY:
        try:
            return svc.replay_changes(cycle=cycle, window=window, portfolio=pf, types=wanted)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    from datetime import datetime
    try:
        t = datetime.fromisoformat(since) if since else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="since must be an ISO timestamp") from exc
    return svc.live_changes(since=t, types=wanted, portfolio=pf)


@router.post("/refresh", response_model=MonitorStatus,
             description="LIVE: poll the live source once and diff (a no-op when the live feed is off). REPLAY needs no refresh.")
def post_refresh(c: Container = Depends(get_container)) -> MonitorStatus:
    svc = _svc(c)
    if c.live is not None and c.live.source is not None:
        c.live.refresh()  # its observer (the monitor) runs after the poll is applied
    return svc.status(Mode.LIVE)


@router.get("/digest", response_model=Digest,
            description="What should I care about right now? The executive digest: top new risks, escalations, the largest changes in portfolio exposure and in modeled stress, important evidence changes, major conflicts, "
                        "concentration changes and watchlist activity. Nothing is scored: every card shows the ordered key (materiality tier, severity, size of the change, recency, id) it was ranked by, and "
                        "drills down to the event, its evidence, scope, exposure, propagation, stress and attribution. REPLAY is a deterministic cycle of the replay clock; LIVE reads the live monitor.")
def get_digest(mode: Mode = Query(default=Mode.REPLAY), cycle: int | None = Query(default=None, ge=0), window: int = Query(default=4, ge=1, le=60), portfolio_id: str | None = PID,
               c: Container = Depends(get_container)) -> Digest:
    _svc(c)
    if c.digest is None:
        raise HTTPException(status_code=404, detail="the digest is available in the replay profile only")
    pf = _book(c, portfolio_id)
    try:
        return c.digest.digest(mode=mode, cycle=cycle, window=window, portfolio=pf, portfolio_name=(pf.name if pf is not None else c.portfolio.get().name))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
