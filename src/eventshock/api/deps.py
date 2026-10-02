"""Application container + dependency accessors."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ..config import (
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
from ..pipeline.config import load_enrichment_config, load_pipeline_config
from ..pipeline.models import PipelineReport
from ..pipeline.run import run_snapshot
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


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    config = load_app_config(settings)
    taxonomy = load_taxonomy(settings)
    version, scenarios = load_scenarios(settings)
    catalog = ScenarioCatalog(scenarios, {c.id: c.default_scenario for c in taxonomy.categories})
    snapshot: Snapshot | None = None
    report: PipelineReport | None = None
    if config.data.profile == "replay":
        # Real sources: verify the frozen snapshot, run the pipeline, serve its output. Fails loudly on any
        # tampered file or invalid configuration; never touches the network.
        snapshot = load_snapshot(resolve_replay_dir(settings, config))
        result = run_snapshot(snapshot, load_pipeline_config(settings.config_dir),
                              load_enrichment_config(settings.config_dir))
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
    )


def get_container(request: Request) -> Container:
    return request.app.state.container
