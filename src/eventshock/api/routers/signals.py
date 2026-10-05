from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from ...assessment.model import EvidenceView, RiskAssessment, TimelineView
from ...assessment.views import build_evidence, build_timeline
from ...domain import EventCategory, EventStatus, RiskSignal, SourceType
from ...intelligence.model import EventIntelligence
from ...retrieval.model import AnalogueSet
from ...services.relevance import PortfolioRelevance, RelevanceLevel
from ...services.signal_context import build_signal_context
from ...store import CHANNELS
from ..deps import Container, get_container
from ..schemas import SignalContext, SignalPage, SignalSummary
from .portfolio import PID, book

router = APIRouter(prefix="/signals", tags=["signals"])


def summarise(c: Container, s: RiskSignal, pf=None) -> SignalSummary:  # noqa: ANN001
    """The feed row for a signal: its own fields plus where it came from and how it reaches the book (``pf``: a personal portfolio, else the default)."""
    meta = c.signals.meta_of(s.id)
    level, share = c.relevance.headline(s, pf) if c.relevance else (RelevanceLevel.UNDETERMINED, None)
    sc = s.scope
    assert sc is not None
    a = c.assessments.assess(s) if c.assessments else None
    sev = a.severity if a else None
    isc = c.intelligence.scope_of(s) if c.intelligence else None
    return SignalSummary(
        severity_score=sev.score if sev else None, severity_low=sev.low if sev else None, severity_high=sev.high if sev else None,
        severity_basis=sev.basis if sev else None, severity_band=sev.band if sev else None, severity_band_label=sev.band_label if sev else None,
        severity_ai_effect=sev.ai_effect if sev else None, assessed_category=a.reading.event_type if a else None,
        assessed_sector=(a.reading.sectors[0] if a and a.reading.sectors else None), extraction_mode=a.extraction.mode.value if a else None,
        above_trigger=a.threshold.crosses if a and a.threshold else None,
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
        impact_origin=(None if s.impact is None or s.provenance is None else
                       "MODEL" if s.provenance.stage_origins.get("impact") == "MODEL" else "PLACEHOLDER"),
        impact_lifecycle=(s.provenance.impact.lifecycle.value if s.provenance and s.provenance.impact
                          else None),
        impact_score_low=s.impact.score_low if s.impact else None,
        impact_score_high=s.impact.score_high if s.impact else None,
        status=s.status,
        source_count=s.evidence.source_count,
        data_origin=s.data_origin.value,
        scope_level=sc.level.value,
        scope_sector=sc.sector,
        scope_strength=sc.strength.value if sc.strength else None,
        scope_themes=sc.themes,
        scope_regions=sc.regions,
        scope_type=isc.scope_type.value if isc else None,
        scope_value=isc.scope_value if isc else None,
        channel=c.signals.channel_of(s.id),
        first_seq=meta.first_seq if meta else None,
        updated_seq=meta.updated_seq if meta else None,
        relevance_level=level.value,
        relevance_share=share,
        relevance_band=c.relevance.band(share) if c.relevance else "UNDETERMINED",
    )


@router.get("", response_model=SignalPage)
def list_signals(
    category: EventCategory | None = None,
    source_type: SourceType | None = None,
    min_impact: int | None = Query(default=None, ge=1, le=10),
    q: str | None = Query(default=None, max_length=100),
    event_status: EventStatus | None = None,
    scope_level: str | None = Query(default=None, pattern="^(COMPANY|SECTOR|MARKET|UNRESOLVED)$"),
    scope_type: str | None = Query(default=None, pattern="^(COMPANY|INDUSTRY|SECTOR|GEOGRAPHY|MACRO|MARKET|THEME|UNRESOLVED)$",
                                   description="the hierarchical scope (needs event intelligence)"),
    channel: str | None = Query(default=None, pattern="^(REPLAY|LIVE|MANUAL)$"),
    since_seq: int | None = Query(default=None, ge=0, description="only live-overlay signals changed after this counter"),
    portfolio_id: str | None = PID,
    c: Container = Depends(get_container),
) -> SignalPage:
    assert channel is None or channel in CHANNELS
    seq = c.signals.seq  # read first: a change landing mid-listing is then picked up by the next poll
    # the headline score is the assessment's severity where there is one, so the filter reads the same number the feed shows
    # with an assessment layer the event class a row shows is the assessed one, so the category filter reads that too
    items = c.signals.list(category=None if c.assessments else category, source_type=source_type,
                           min_impact=None if c.assessments else min_impact, query=q, event_status=event_status, scope_level=scope_level,
                           channel=channel, since_seq=since_seq)
    pf = None if c.portfolios is None or c.portfolios.is_default(portfolio_id) else book(c, portfolio_id)  # relevance reads the chosen portfolio
    rows = [summarise(c, s, pf) for s in items]
    if scope_type is not None and c.intelligence:
        rows = [r for r in rows if r.scope_type == scope_type]
    if c.assessments and min_impact is not None:
        rows = [r for r in rows if (r.severity_score or 0) >= min_impact]
    if c.assessments and category is not None:
        rows = [r for r in rows if r.assessed_category == category.value]
    return SignalPage(total=len(rows), seq=seq, items=rows)


@router.get("/{signal_id}", response_model=RiskSignal)
def get_signal(signal_id: str, c: Container = Depends(get_container)) -> RiskSignal:
    signal = c.signals.get(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
    return signal


@router.get("/{signal_id}/relevance", response_model=PortfolioRelevance)
def get_signal_relevance(signal_id: str, portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> PortfolioRelevance:
    """What the event means for the book: which holdings it reaches, by issuer / sector / region / whole book, and how many of the
    default scenario's shocks bind to this kind of event. Exposure is the book's own; nothing here is a forecast."""
    signal = c.signals.get(signal_id)
    if signal is None or c.relevance is None:
        raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
    pf = None if c.portfolios is None or c.portfolios.is_default(portfolio_id) else book(c, portfolio_id)
    return c.relevance.assess(signal, portfolio=pf)


@router.get("/{signal_id}/context", response_model=SignalContext)
def get_signal_context(signal_id: str, c: Container = Depends(get_container)) -> SignalContext:
    """What the impact model saw (grouped, with availability classes), the issuer's filings placed around
    the report, and, separately and labelled, what the market did afterwards.

    Read-only: nothing here feeds scoring.
    """
    signal = c.signals.get(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
    return build_signal_context(signal, c.calendar, c.outcomes, c.as_of or signal.created_at)


def _need_signal(c: Container, signal_id: str) -> RiskSignal:
    signal = c.signals.get(signal_id)
    if signal is None or c.assessments is None:
        raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
    return signal


@router.get("/{signal_id}/assessment", response_model=RiskAssessment)
def get_signal_assessment(signal_id: str, refine: bool = Query(default=False, description="read the text with the language model, if one is configured"),
                          c: Container = Depends(get_container)) -> RiskAssessment:
    """The risk assessment: what the report means (event, tone, entities, sectors, regions, asset classes, severity indicators, evidence quotes),
    how serious it is and why (explicit factors and weights), whether it crosses the stress trigger, and what the trained reference model says.

    Derived from the signal and never stored on it. ``extraction.mode`` says whether a language model or the deterministic rules read the text."""
    signal = _need_signal(c, signal_id)
    assert c.assessments is not None
    return c.assessments.detail(signal, refine=refine)


@router.get("/{signal_id}/evidence", response_model=EvidenceView)
def get_signal_evidence(signal_id: str, c: Container = Depends(get_container)) -> EvidenceView:
    """Evidence for this assessment in three separate groups: source evidence (verbatim quotes, the reports), model inference (the reading and the
    score's factors) and scenario assumptions (the configured shocks). They are never blended."""
    signal = _need_signal(c, signal_id)
    assert c.assessments is not None
    a = c.assessments.assess(signal)
    return build_evidence(signal, a, c.catalog, c.config.stress.severity_scale_min, c.config.stress.severity_scale_max)


@router.get("/{signal_id}/timeline", response_model=TimelineView)
def get_signal_timeline(signal_id: str, c: Container = Depends(get_container)) -> TimelineView:
    """What was known when. Items dated after the report are shown for audit and flagged as never used by the score."""
    signal = _need_signal(c, signal_id)
    assert c.assessments is not None
    as_of = c.as_of or signal.created_at
    ctx = build_signal_context(signal, c.calendar, c.outcomes, as_of)
    return build_timeline(signal, c.assessments.assess(signal), ctx, as_of)


@router.get("/{signal_id}/intelligence", response_model=EventIntelligence,
            description="Event intelligence: the hierarchical scope (company to market, or UNRESOLVED), the event this report belongs to with every report kept, evidence "
                        "(independent sources, strength tier, model confidence: kept apart), novelty class, narrative velocity, structured contradiction, lifecycle with its "
                        "timeline, affected entities/sectors/risk factors, portfolio relevance and stress. Every section can abstain with a reason. Derived: nothing is stored on "
                        "the signal and nothing here feeds the severity score. `as_of` replays the view as it stood at that time (only reports published by then are read).")
def get_signal_intelligence(signal_id: str, as_of: datetime | None = Query(default=None, description="an instant with a time zone; omitted = the event's last report (replay) or now (live, pasted)"),
                            portfolio_id: str | None = PID, c: Container = Depends(get_container)) -> EventIntelligence:
    signal = c.signals.get(signal_id)
    if signal is None or c.intelligence is None:
        raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
    pf = None if c.portfolios is None or c.portfolios.is_default(portfolio_id) else book(c, portfolio_id)
    try:
        return c.intelligence.for_signal(signal, as_of=as_of, portfolio=pf)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{signal_id}/analogues", response_model=AnalogueSet,
            description="Past reports that resemble this one and what the market did after them: RETRIEVED evidence, labelled hindsight, never a score input. "
                        "status NO_RELIABLE_ANALOGUE means the bar was not met and nothing is padded; UNAVAILABLE means the index or encoder is missing.")
def get_analogues(signal_id: str, c: Container = Depends(get_container)) -> AnalogueSet:
    signal = _need_signal(c, signal_id)
    if c.analogues is None:
        raise HTTPException(status_code=404, detail="analogues are available in the replay profile only")
    return c.analogues.for_signal(signal)
