"""Application container + dependency accessors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from ..config import (
    REPO_ROOT,
    AppConfig,
    ConfigError,
    Settings,
    Taxonomy,
    load_app_config,
    load_scenarios,
    load_taxonomy,
    resolve_fixtures_dir,
    resolve_replay_dir,
)
from ..ingestion.snapshot import Snapshot, load_snapshot
from ..pipeline.config import (
    load_enrichment_config,
    load_event_model_config,
    load_impact_model_config,
    load_pipeline_config,
    load_sentiment_model_config,
)
from ..pipeline.embeddings import ChainedEmbeddings, LiveEncoder, PinnedEmbeddings
from ..pipeline.enrich import ImpactModelEnricher, ModelEnricher
from ..pipeline.event_card import EventModelCard
from ..pipeline.event_context import EventCalendar
from ..pipeline.event_model import EventModel
from ..pipeline.evidence_card import EvidenceBundle
from ..pipeline.hybrid_event_model import HybridEventModel, load_event_model
from ..pipeline.impact_card import ImpactModelCard
from ..pipeline.impact_features_v2 import FEATURE_SCHEMA_V2
from ..pipeline.impact_model import ImpactModel
from ..pipeline.market_context import MarketContext
from ..pipeline.models import PipelineReport
from ..pipeline.run import run_snapshot
from ..pipeline.sentiment_card import SentimentModelCard
from ..pipeline.sentiment_model import SentimentModel
from ..ports import PortfolioRepository, SignalRepository
from ..services.evidence import build_evidence
from ..services.stress_service import StressService
from ..store import (
    InMemorySignalRepository,
    load_portfolio_files,
    load_portfolio_repository,
    load_signal_repository,
)
from ..stress.scenarios import ScenarioCatalog
from .schemas import ImpactStatus

HYBRID_ENCODER = "intfloat/multilingual-e5-large"


@dataclass
class Container:
    settings: Settings
    config: AppConfig
    taxonomy: Taxonomy
    scenario_set_version: str
    catalog: ScenarioCatalog
    signals: SignalRepository
    portfolio: PortfolioRepository
    stress: StressService
    profile: str = "demo"
    snapshot: Snapshot | None = None
    pipeline_report: PipelineReport | None = None
    sentiment_card: SentimentModelCard | None = None
    event_card: EventModelCard | None = None
    impact_card: ImpactModelCard | None = None
    impact_status: ImpactStatus | None = None
    evidence: EvidenceBundle | None = None
    impact_event_reference: str | None = None  # event model the impact stage reads when not the served one


def _load_impact(
    settings: Settings, snapshot: Snapshot
) -> tuple[ImpactModel | None, MarketContext | None, ImpactStatus]:
    """The impact model and the frozen market context, or the reason there are none.

    Missing artifact / context is a labelled degradation (the heuristic keeps serving) unless ``require`` is
    set; a modified or
    version-mismatched artifact, or a context that fails its hash, always raises ``ConfigError``.
    """
    cfg = load_impact_model_config(settings.config_dir)
    served = settings.impact_model_dir or Path(cfg.served_model_dir or cfg.model_dir)
    model_dir = served if served.is_absolute() else REPO_ROOT / served
    card_file = model_dir / "model_card.json"
    if settings.impact_model_dir is None and cfg.served_model_dir and not card_file.is_file():
        import logging

        logging.getLogger("eventshock").warning(
            "served impact artifact %s is missing: serving the v1 reference %s instead",
            model_dir, cfg.model_dir)
        model_dir = REPO_ROOT / cfg.model_dir
        card_file = model_dir / "model_card.json"
    ctx_path = snapshot.market_context_path()
    why: str | None = None
    if not (model_dir / "model_card.json").is_file():
        why = f"no impact model artifact at {model_dir} (run `make train-impact`)"
    elif ctx_path is None:
        why = "the replay snapshot has no market context (run `make market-context`)"
    if why:
        if cfg.require:
            raise ConfigError(f"impact model required (configs/impact_model.yaml require: true) but {why}")
        return None, None, ImpactStatus(mode="PLACEHOLDER", model_id=None, reason=why)
    # a model built on the v2 schema reads the committed event calendar; its card pins the calendar's hashes
    # and the loader refuses a modified one
    calendar = None
    if json.loads(card_file.read_text(encoding="utf-8")).get("feature_schema") == FEATURE_SCHEMA_V2:
        calendar = EventCalendar.load(REPO_ROOT / "data" / "events", settings.config_dir / "sec_items.yaml")
    model = ImpactModel.load(model_dir, cfg.min_link_confidence, calendar)
    assert ctx_path is not None
    context = MarketContext.load(ctx_path)
    served = model.served_scopes
    status = ImpactStatus(
        mode="MODEL" if served else "PLACEHOLDER", model_id=model.model_id,
        scopes={s: v.value for s, v in sorted(model.lifecycle.items())}, served_scopes=served,
        reason=None if served else "no scope reached a servable lifecycle: the heuristic keeps serving")
    return model, context, status


def _load_event(served: Path, reference: Path, snapshot: Snapshot) -> EventModel:
    """The served event model.

    A hybrid needs vectors: the pack's pinned ones, plus a live encoder if torch is installed.
    If the hybrid cannot be served at all (its artifact or its pinned vectors are missing) the
    TF-IDF reference model serves instead, and the model id on every signal and card says so.
    A *modified* artifact or vectors file always stops start-up.
    """
    if served == reference:
        return EventModel.load(reference)
    if not (served / "model_card.json").is_file():
        return _fallback(served, reference, "no artifact")
    pins = snapshot.embeddings_path()
    if pins is None or snapshot.manifest.embeddings is None:
        return _fallback(served, reference, "the snapshot pins no embeddings: run `make replay-embeddings`")
    pinned = PinnedEmbeddings(pins, sha256=snapshot.manifest.embeddings.sha256)
    live = LiveEncoder(HYBRID_ENCODER, dim=pinned.dim)  # torch is imported only for text that is not pinned
    return load_event_model(served, ChainedEmbeddings(pinned, live, pinned.dim))


def _fallback(served: Path, reference: Path, why: str) -> EventModel:
    import logging

    logging.getLogger("eventshock").warning(
        "served event model %s unavailable (%s): the TF-IDF reference serves", served.name, why)
    return EventModel.load(reference)


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    config = load_app_config(settings)
    taxonomy = load_taxonomy(settings)
    version, scenarios = load_scenarios(settings)
    catalog = ScenarioCatalog(scenarios, {c.id: c.default_scenario for c in taxonomy.categories})
    snapshot: Snapshot | None = None
    report: PipelineReport | None = None
    card: SentimentModelCard | None = None
    event_card: EventModelCard | None = None
    impact_card: ImpactModelCard | None = None
    impact_status: ImpactStatus | None = None
    impact_event_reference: str | None = None
    if config.data.profile == "replay":
        # Real sources: verify the frozen snapshot, run the pipeline, serve its output. Fails loudly on any
        # tampered file or invalid configuration; never touches the network.
        snapshot = load_snapshot(resolve_replay_dir(settings, config))
        # The sentiment stage is a trained model. A missing or modified artifact stops start-up (ConfigError):
        # there is deliberately no silent fall-back to the lexicon, which would mislabel what the numbers are.
        model_cfg = load_sentiment_model_config(settings.config_dir)
        model_dir = settings.sentiment_model_dir or Path(model_cfg.model_dir)
        model = SentimentModel.load(model_dir if model_dir.is_absolute() else REPO_ROOT / model_dir)
        # Same policy for the event stage: a trained model or no start-up.
        event_cfg = load_event_model_config(settings.config_dir)
        served = settings.event_model_dir or Path(event_cfg.served_model_dir or event_cfg.model_dir)
        served = served if served.is_absolute() else REPO_ROOT / served
        reference_dir = Path(event_cfg.model_dir)
        reference_dir = reference_dir if reference_dir.is_absolute() else REPO_ROOT / reference_dir
        event_model = _load_event(served, reference_dir, snapshot)
        legacy = EventModel.load(reference_dir) if isinstance(event_model, HybridEventModel) else None
        impact_event_reference = legacy.model_id if legacy is not None else None
        enrich_cfg = load_enrichment_config(settings.config_dir)
        impact_model, market_context, impact_status = _load_impact(settings, snapshot)
        enricher: ModelEnricher
        if impact_model is not None and market_context is not None and impact_model.served_scopes:
            enricher = ImpactModelEnricher(
                enrich_cfg, model, event_model, impact_model, market_context, impact_event_model=legacy)
        else:
            enricher = ModelEnricher(enrich_cfg, model, event_model)
        pipeline_cfg = load_pipeline_config(settings.config_dir)
        result = run_snapshot(snapshot, pipeline_cfg, enrich_cfg, enricher=enricher)
        impact_card = impact_model.card if impact_model is not None else None
        card = model.card
        event_card = event_model.card
        report = result.report
        signals = InMemorySignalRepository(result.signals, snapshot.manifest.replay_as_of)
        portfolio = load_portfolio_files(snapshot.portfolio_path(), snapshot.entities_path())
    else:
        fixtures = resolve_fixtures_dir(settings, config)
        signals = load_signal_repository(fixtures)
        portfolio = load_portfolio_repository(fixtures)
    replay = config.data.profile == "replay"
    evidence = build_evidence(REPO_ROOT, card, event_card, impact_card) if replay else None
    return Container(
        settings=settings,
        config=config,
        taxonomy=taxonomy,
        scenario_set_version=version,
        catalog=catalog,
        signals=signals,
        portfolio=portfolio,
        stress=StressService(signals, portfolio, catalog, config),
        profile=config.data.profile,
        snapshot=snapshot,
        pipeline_report=report,
        sentiment_card=card,
        event_card=event_card,
        impact_card=impact_card,
        impact_status=impact_status,
        evidence=evidence,
        impact_event_reference=impact_event_reference,
    )


def get_container(request: Request) -> Container:
    return request.app.state.container
