from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...brief.builder import BriefError
from ...brief.models import Brief
from ...explain.builders import ExplanationError
from ...explain.models import Explanation, Subject
from ...markets.models import EventMarketView, MarketTimeline
from ...monitor.models import EventMemory
from ...retrieval.model import AnalogueSet
from ..deps import Container, get_container
from .portfolio import PID
from .propagation import _book

router = APIRouter(prefix="/events", tags=["events"])


def _monitor(c: Container):  # noqa: ANN202
    if c.monitor is None:
        raise HTTPException(status_code=404, detail="event memory is available in the replay profile only")
    return c.monitor


@router.get("/{event_id}/timeline", response_model=EventMemory,
            description="The event as an evolving narrative: every report classified as NEW_EVENT / CONTINUATION / UPDATE / ESCALATION / DE_ESCALATION / RESOLUTION by an explicit rule, the lifecycle "
                        "transitions with their verbatim cues, and the severity, evidence, conflict, portfolio-relevance and stress history by monitoring cycle. `event_id` is an event id (evt_...) "
                        "or the id of any signal in it. Reports with replay-assigned times are never ordered: those events answer UNAVAILABLE with the reason.")
def get_timeline(event_id: str, portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> EventMemory:
    svc = _monitor(c)
    try:
        return svc.memory(event_id, _book(c, portfolio_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{event_id}/explanation", response_model=Explanation,
            description="Why? as structured reasons: PRIORITY (why it is ranked where it is), VISIBILITY (why you are seeing it), CHANGE (why it was flagged as changed) or STRESS (why the modeled stress is what it is). "
                        "Each reason has a closed code, a value, the kind of statement it is (model output, product rule, scenario assumption, historical observation) and the output it was read from. "
                        "`cycle` picks the REPLAY moment (default: the last).")
def get_explanation(event_id: str, subject: Subject = Query(default=Subject.PRIORITY), cycle: int | None = Query(default=None, ge=0), change_id: str | None = Query(default=None),
                    portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> Explanation:
    if c.explain is None:
        raise HTTPException(status_code=404, detail="explanations are available in the replay profile only")
    if subject in (Subject.LAB, Subject.REVERSE):
        raise HTTPException(status_code=422, detail="LAB and REVERSE explanations are requested with POST /api/scenarios/explanation and /api/reverse-stress/explanation")
    try:
        return c.explain.event(event_id, subject, _book(c, portfolio_id), cycle=cycle, change_id=change_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExplanationError as exc:                      # a material output with no reason is a bug: never an empty explanation
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{event_id}/external-markets", response_model=EventMarketView,
            description="EXTERNAL MARKET OBSERVATION: what an independent prediction market (Kalshi) currently appears to price about this event's theme. The event reaches a market only through a curated theme and "
                        "explicit gates (class, resolved scope, evidence of the subject, place; market open, near, fresh), never by keyword overlap with a title. Match status MATCHED / LOW_CONFIDENCE_MATCH / "
                        "NO_MATCH / INSUFFICIENT_DATA; a descriptive interpretation (MARKET_REPRICED / ALIGNED / DIVERGENT / LOW_INFORMATION) that is not a verdict. Never an input to any EventShock number; "
                        "unavailable data says UNAVAILABLE and nothing is invented. `cycle` picks the REPLAY moment (default: the last).")
def get_external_markets(event_id: str, cycle: int | None = Query(default=None, ge=0), portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> EventMarketView:
    if c.markets is None:
        raise HTTPException(status_code=404, detail="external market data is available in the replay profile only")
    try:
        return c.markets.view(event_id, _book(c, portfolio_id), cycle=cycle)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{event_id}/market-timeline", response_model=MarketTimeline,
            description="The event's timeline with the matched market's probability path merged in. Each item says what kind of statement it is: SOURCE_EVENT, EVENTSHOCK_ASSESSMENT, EXTERNAL_MARKET_OBSERVATION or SCENARIO_ASSUMPTION; "
                        "they are never blurred.")
def get_market_timeline(event_id: str, cycle: int | None = Query(default=None, ge=0), portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> MarketTimeline:
    if c.markets is None:
        raise HTTPException(status_code=404, detail="external market data is available in the replay profile only")
    try:
        return c.markets.timeline(event_id, _book(c, portfolio_id), cycle=cycle)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{event_id}/analogues", response_model=AnalogueSet,
            description="HISTORICAL OBSERVATION: the events most like this one in the past and what the market did afterwards, from the Stage 8 analogue index (the same answer as /api/signals/{id}/analogues for the "
                        "event's anchor report). Retrieved with hindsight, never a prediction and never an input to severity. Live text is UNAVAILABLE without an encoder.")
def get_event_analogues(event_id: str, c: Container = Depends(get_container)) -> AnalogueSet:
    if c.monitor is None or c.analogues is None:
        raise HTTPException(status_code=404, detail="analogues are available in the replay profile only")
    try:
        ev = c.monitor.resolve_event(event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return c.analogues.for_signal(ev.anchor.signal)


@router.get("/{event_id}/brief", response_model=Brief,
            responses={200: {"content": {"text/markdown": {}}, "description": "JSON by default; `format=md` returns the same brief as Markdown"}},
            description="The executive risk brief for one event and one portfolio: sixteen sections in a fixed order (executive summary, what happened, current status, why it matters, evidence, conflicts, affected "
                        "entities and sectors, portfolio exposure, propagation, stress, top drivers, historical context, external market view, assumptions, uncertainty, what to monitor). Written from templates "
                        "over structured outputs; every statement lists the sources it was read from and what KIND of statement it is (a source report, an EventShock assessment, an external market observation, "
                        "a scenario assumption, a historical observation, a product rule). Where an input is absent the section says so in a fixed sentence. `cycle` picks the REPLAY moment (default: the last).")
def get_brief(event_id: str, format: Literal["json", "md"] = Query(default="json"), cycle: int | None = Query(default=None, ge=0), portfolio_id: str | None = PID,
              c: Container = Depends(get_container)):  # noqa: ANN201
    if c.brief is None:
        raise HTTPException(status_code=404, detail="the executive brief is available in the replay profile only")
    try:
        b = c.brief.build(event_id, _book(c, portfolio_id), cycle=cycle)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BriefError as exc:                              # a statement with no source is a bug: never a brief with an unsupported claim
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if format == "md":
        return PlainTextResponse(c.brief.markdown(b), media_type="text/markdown; charset=utf-8")
    return b
