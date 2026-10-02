from __future__ import annotations

from fastapi import APIRouter, Depends

from ... import __version__
from ...domain import DataOrigin
from ...stress.engine import ENGINE_VERSION
from ..deps import Container, get_container
from ..schemas import Meta, ReplayInfo, TaxonomyItem

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _notices(c: Container) -> list[str]:
    if c.pipeline_report is None:
        first = "Signals are hand-authored demo fixtures (fixture-v0), not model output."
    else:
        first = (
            "Documents are real (GDELT news metadata, Twitter Financial News posts) replayed from a frozen "
            "snapshot. Sentiment, event type and impact are PLACEHOLDER rules, not trained models."
        )
    return [
        first,
        "The portfolio is synthetic" + (" (positions on real issuers)." if c.pipeline_report else "."),
        "Scenario magnitudes are illustrative assumptions, not forecasts.",
        "Stress results are computed by a deterministic engine from those inputs.",
    ]


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
        data_origin=(DataOrigin.DEMO_FIXTURE if r is None else DataOrigin.REAL_SOURCE_PLACEHOLDER_NLP).value,
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
    )
