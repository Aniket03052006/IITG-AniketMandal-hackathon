"""Application container + dependency accessors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from ..config import (
    REPO_ROOT,
    AppConfig,
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
    load_pipeline_config,
    load_sentiment_model_config,
)
from ..pipeline.enrich import ModelEnricher
from ..pipeline.event_card import EventModelCard
from ..pipeline.event_model import EventModel
from ..pipeline.models import PipelineReport
from ..pipeline.run import run_snapshot
from ..pipeline.sentiment_card import SentimentModelCard
from ..pipeline.sentiment_model import SentimentModel
from ..ports import PortfolioRepository, SignalRepository
from ..services.stress_service import StressService
from ..store import (
    InMemorySignalRepository,
    load_portfolio_files,
    load_portfolio_repository,
    load_signal_repository,
)
from ..stress.scenarios import ScenarioCatalog


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
        event_dir = settings.event_model_dir or Path(event_cfg.model_dir)
        event_model = EventModel.load(event_dir if event_dir.is_absolute() else REPO_ROOT / event_dir)
        enrich_cfg = load_enrichment_config(settings.config_dir)
        result = run_snapshot(snapshot, load_pipeline_config(settings.config_dir), enrich_cfg,
                              enricher=ModelEnricher(enrich_cfg, model, event_model))
        card = model.card
        event_card = event_model.card
        report = result.report
        signals = InMemorySignalRepository(result.signals, snapshot.manifest.replay_as_of)
        portfolio = load_portfolio_files(snapshot.portfolio_path(), snapshot.entities_path())
    else:
        fixtures = resolve_fixtures_dir(settings, config)
        signals = load_signal_repository(fixtures)
        portfolio = load_portfolio_repository(fixtures)
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
    )


def get_container(request: Request) -> Container:
    return request.app.state.container
