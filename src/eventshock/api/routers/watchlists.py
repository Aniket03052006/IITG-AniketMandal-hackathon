from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...monitor.models import Mode
from ...watchlist.models import Watchlist, WatchlistActivity, WatchlistInput, WatchlistList, WatchVocabulary
from ...watchlist.service import WatchlistInvalid
from ...watchlist.store import WatchlistLimit, WatchlistNotFound
from ..deps import Container, get_container
from .portfolio import PID
from .propagation import _book

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


def _svc(c: Container):  # noqa: ANN202
    if c.watchlists is None:
        raise HTTPException(status_code=404, detail="watchlists are available in the replay profile only")
    return c.watchlists


def _invalid(exc: WatchlistInvalid) -> HTTPException:
    return HTTPException(status_code=422, detail=[{"loc": ["body", "items"], "msg": m, "type": "watchlist.invalid"} for m in exc.issues])


@router.get("", response_model=WatchlistList, description="Every saved watchlist, oldest first.")
def list_watchlists(c: Container = Depends(get_container)) -> WatchlistList:
    return WatchlistList(watchlists=_svc(c).list())


@router.get("/vocabulary", response_model=WatchVocabulary,
            description="What each kind of item can name: companies (the entity master), sectors, industries, region codes, event categories, risk themes, and 'top:N' holdings. A value outside it is refused: free text never becomes a company.")
def get_vocabulary(c: Container = Depends(get_container)) -> WatchVocabulary:
    return _svc(c).vocabulary()


@router.post("", response_model=Watchlist, status_code=201)
def create_watchlist(body: WatchlistInput, c: Container = Depends(get_container)) -> Watchlist:
    try:
        return _svc(c).create(body)
    except WatchlistInvalid as exc:
        raise _invalid(exc) from exc
    except WatchlistLimit as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{watchlist_id}", response_model=Watchlist)
def get_watchlist(watchlist_id: str, c: Container = Depends(get_container)) -> Watchlist:
    try:
        return _svc(c).get(watchlist_id)
    except WatchlistNotFound as exc:
        raise HTTPException(status_code=404, detail=f"watchlist {watchlist_id!r} not found") from exc


@router.put("/{watchlist_id}", response_model=Watchlist, description="Replace a watchlist's name, switch and items (create, edit, enable/disable are all this call).")
def update_watchlist(watchlist_id: str, body: WatchlistInput, c: Container = Depends(get_container)) -> Watchlist:
    try:
        return _svc(c).update(watchlist_id, body)
    except WatchlistNotFound as exc:
        raise HTTPException(status_code=404, detail=f"watchlist {watchlist_id!r} not found") from exc
    except WatchlistInvalid as exc:
        raise _invalid(exc) from exc


@router.delete("/{watchlist_id}", status_code=204)
def delete_watchlist(watchlist_id: str, c: Container = Depends(get_container)) -> None:
    try:
        _svc(c).delete(watchlist_id)
    except WatchlistNotFound as exc:
        raise HTTPException(status_code=404, detail=f"watchlist {watchlist_id!r} not found") from exc


@router.get("/{watchlist_id}/activity", response_model=WatchlistActivity,
            description="What each watched item shows now: matching events with severity, lifecycle, novelty, velocity, evidence quality, conflicts, portfolio relevance, modeled stress and recent changes. "
                        "REPLAY is a deterministic cycle of the replay clock (default: the last); LIVE reads the live monitor. A disabled list matches nothing.")
def get_activity(watchlist_id: str, mode: Mode = Query(default=Mode.REPLAY), cycle: int | None = Query(default=None, ge=0), window: int = Query(default=1, ge=1, le=60),
                 portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> WatchlistActivity:
    svc = _svc(c)
    try:
        w = svc.get(watchlist_id)
    except WatchlistNotFound as exc:
        raise HTTPException(status_code=404, detail=f"watchlist {watchlist_id!r} not found") from exc
    return svc.activity(w, mode=mode, cycle=cycle, window=window, portfolio=_book(c, portfolio_id))
