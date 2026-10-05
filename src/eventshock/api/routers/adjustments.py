from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...adjust.models import AdjustmentState, PutRequest, ValidationReport
from ...config import ConfigError
from ..deps import Container, get_container

router = APIRouter(prefix="/adjustments", tags=["adjustments"])


def _svc(c: Container):  # noqa: ANN202
    if c.adjust is None:
        raise HTTPException(status_code=404, detail="adjustments are not available")
    return c.adjust


@router.get("", response_model=AdjustmentState,
            description="Every setting of the side-cars that can be adjusted by hand: its shipped default, its value now, its bounds. Adjusted values are the user's own assumptions.")
def get_adjustments(c: Container = Depends(get_container)) -> AdjustmentState:
    return _svc(c).state()


@router.post("/validate", response_model=ValidationReport, description="Check a change without saving it: bounds and the cross-field rules of the real configuration.")
def validate_adjustments(req: PutRequest, c: Container = Depends(get_container)) -> ValidationReport:
    return _svc(c).validate(req.values)


@router.put("", response_model=AdjustmentState,
            description="Save adjustments (dotted path -> value) and rebuild the side-cars on them. 422 with the issues per path when a value is not allowed; nothing is saved then.")
def put_adjustments(req: PutRequest, c: Container = Depends(get_container)) -> AdjustmentState:
    svc = _svc(c)
    try:
        report = svc.put(req.values)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail={"issues": [{"path": None, "message": str(exc)}]}) from exc
    if not report.ok:
        raise HTTPException(status_code=422, detail={"issues": [i.model_dump() for i in report.issues]})
    return svc.state()


@router.delete("", response_model=AdjustmentState, description="Reset one adjusted value to its default (`path`), or every value when no path is given.")
def reset_adjustments(path: str | None = Query(default=None), c: Container = Depends(get_container)) -> AdjustmentState:
    svc = _svc(c)
    try:
        svc.reset(path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"{path!r} is not adjusted") from exc
    return svc.state()


@router.post("/reset", response_model=AdjustmentState, description="Reset every adjusted value to its shipped default.")
def reset_all(c: Container = Depends(get_container)) -> AdjustmentState:
    svc = _svc(c)
    svc.reset(None)
    return svc.state()
