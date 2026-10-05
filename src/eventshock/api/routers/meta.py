from __future__ import annotations

from fastapi import APIRouter, Depends

from ... import __version__
from ...domain import DataOrigin
from ...stress.engine import ENGINE_VERSION
from ..deps import Container, get_container
from ..schemas import Capabilities, LLMInfo, Meta, ReplayInfo, TaxonomyItem

router = APIRouter(tags=["meta"])


def llm_info(c: Container) -> LLMInfo | None:
    if c.assessments is None:
        return None
    st = c.assessments.extractor.status()
    return LLMInfo(
        mode=str(st["mode"]), enabled=bool(st["enabled"]), model=st["model"] if isinstance(st["model"], str) else None,
        reason=st["reason"] if isinstance(st["reason"], str) else None, llm_calls=int(st["llm_calls"]),  # type: ignore[call-overload]
        cache_hits=int(st["cache_hits"]), fallbacks=int(st["fallbacks"]),  # type: ignore[call-overload]
        last_fallback_reason=st["last_fallback_reason"] if isinstance(st["last_fallback_reason"], str) else None,
        sends_text_off_machine=st["mode"] == "LLM")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _impact_clause(c: Container) -> str:
    st = c.impact_status
    if st is None or st.mode != "MODEL":
        return "impact is a PLACEHOLDER rule, not a trained model"
    life = ", ".join(f"{s.lower()} {v.lower()}" for s, v in st.scopes.items())
    words = {"PRODUCTION": "validated", "CALIBRATED": "experimental", "TRAINED": "experimental"}
    kinds = sorted({words.get(v, "placeholder") for s, v in st.scopes.items() if s in st.served_scopes})
    ref = (f"; its event-type inputs come from {c.impact_event_reference}, the model it was trained on"
           if c.impact_event_reference else "")
    return (f"impact is a trained model ({st.model_id}; {life}{ref}), labelled {' / '.join(kinds)} per "
            "signal, with the PLACEHOLDER rule for any signal the model cannot score")


def _notices(c: Container) -> list[str]:
    if c.pipeline_report is None:
        first = "Signals are hand-authored demo fixtures (fixture-v0), not model output."
    elif c.sentiment_card is not None and c.event_card is not None:
        first = (
            "Documents are real (GDELT news metadata, Twitter Financial News posts) replayed from a frozen "
            f"snapshot. Sentiment ({c.sentiment_card.id}) and event type ({c.event_card.id}, which can say "
            f"\"not an event\" or \"uncertain\") are trained models; {_impact_clause(c)}."
        )
    elif c.sentiment_card is not None:
        first = (
            "Documents are real (GDELT news metadata, Twitter Financial News posts) replayed from a frozen "
            f"snapshot. Sentiment is a trained model ({c.sentiment_card.id}); event type and impact are "
            "PLACEHOLDER rules, not trained models."
        )
    else:
        first = (
            "Documents are real (GDELT news metadata, Twitter Financial News posts) replayed from a frozen "
            "snapshot. Sentiment, event type and impact are PLACEHOLDER rules, not trained models."
        )
    return [
        first,
        "The default portfolio is synthetic" + (" (positions on real issuers)." if c.pipeline_report else ".")
        + " You can optionally stress a personal portfolio instead; the synthetic one is always one click away.",
        "Scenario magnitudes are illustrative assumptions, not forecasts.",
        "Stress results are computed by a deterministic engine from those inputs.",
    ]


def _origin(c: Container) -> DataOrigin:
    if c.pipeline_report is None:
        return DataOrigin.DEMO_FIXTURE
    if c.sentiment_card is not None:
        return DataOrigin.REAL_SOURCE_MIXED_NLP
    return DataOrigin.REAL_SOURCE_PLACEHOLDER_NLP


@router.get("/meta", response_model=Meta)
def meta(c: Container = Depends(get_container)) -> Meta:
    r = c.pipeline_report
    replay = None if r is None else ReplayInfo(
        snapshot_id=r.snapshot_id, description=r.description, window_start=r.window_start,
        window_end=r.window_end, output_digest=r.output_digest, pipeline_version=r.pipeline_version,
        stage_origins=r.stage_origins, sources=[s.name for s in r.sources])
    return Meta(
        app="EventShock",
        version=__version__,
        mode=c.config.mode,
        profile=c.profile,
        data_origin=_origin(c).value,
        replay=replay,
        as_of=c.signals.as_of,
        trigger_threshold=c.config.stress.trigger_threshold,
        base_currency=c.config.base_currency,
        signal_count=len(c.signals.list()),
        asset_count=len(c.portfolio.get().assets),
        scenario_set_version=c.scenario_set_version,
        engine_version=ENGINE_VERSION,
        taxonomy=[TaxonomyItem(**t.model_dump()) for t in c.taxonomy.categories],
        notices=_notices(c),
        impact=c.impact_status,
        capabilities=Capabilities(analyze=c.analyzer is not None, live_enabled=bool(c.live and c.live.source),
                                  assessment=c.assessments is not None, llm=llm_info(c),
                                  analogues=bool(c.analogues and c.analogues.available), history_check=c.shock_history is not None, intelligence=c.intelligence is not None,
                                  propagation=c.propagation is not None, adjustments=c.adjust is not None),
    )
