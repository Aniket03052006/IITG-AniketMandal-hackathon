"""Application container + dependency accessors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import Request

from ..assessment.config import load_hybrid_config, load_semantics_config
from ..assessment.extractor import SemanticExtractor
from ..assessment.hybrid import HybridScorer
from ..assessment.rules import RuleExtractor
from ..assessment.service import AssessmentService
from ..assessment.vocab import Vocab
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
from ..ingestion.live import CaptureSource, GdeltLiveSource, LiveSource
from ..ingestion.snapshot import Snapshot, load_snapshot
from ..llm.cache import ExtractionCache
from ..llm.client import CLIENTS, LLMClient
from ..llm.config import load_llm_config
from ..pipeline.config import (
    load_enrichment_config,
    load_event_model_config,
    load_impact_model_config,
    load_pipeline_config,
    load_sentiment_model_config,
)
from ..pipeline.embeddings import ChainedEmbeddings, LiveEncoder, PinnedEmbeddings
from ..pipeline.engine import RiskEngine
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
from ..pipeline.run import load_entities, run_snapshot
from ..pipeline.scope import ScopeConfig, ScopeResolver, load_scope_config
from ..pipeline.sentiment_card import SentimentModelCard
from ..pipeline.sentiment_model import SentimentModel
from ..ports import PortfolioRepository
from ..services.analyze import Analyzer
from ..services.evidence import build_evidence
from ..services.live import Journal, LiveConfig, LiveService, load_live_config
from ..services.relevance import RelevanceService
from ..services.signal_context import Outcomes
from ..services.stress_service import StressService
from ..store import (
    CombinedSignalRepository,
    InMemorySignalRepository,
    LiveSignalStore,
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
    signals: CombinedSignalRepository
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
    # SEC filings + FOMC dates the impact model reads (read-only, for the per-signal context)
    calendar: EventCalendar | None = None
    # realised moves after the replay reports (derived, committed; never a model input)
    outcomes: Outcomes | None = None
    as_of: datetime | None = None  # the replay clock
    relevance: RelevanceService | None = None
    # the incremental engine (replay profile only): pasted text and the live feed enter through it
    engine: RiskEngine | None = None
    analyzer: Analyzer | None = None
    live: LiveService | None = None
    live_store: LiveSignalStore | None = None
    live_config: LiveConfig | None = None
    scope_config: ScopeConfig | None = None
    # reads the text (LLM or rules), scores severity from explicit weights, feeds the stress engine's trigger (replay profile only)
    assessments: AssessmentService | None = None


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


def _live_source(settings: Settings, cfg: LiveConfig) -> LiveSource | None:
    """The configured live source, or None when live is off (the default). Capture mode reads a local file and needs no network."""
    enabled = settings.live if settings.live is not None else cfg.enabled
    if not enabled:
        return None
    if (settings.live_source or cfg.source.kind) == "capture":
        cap = cfg.source.capture if settings.capture_path is None else cfg.source.capture.model_copy(update={"path": settings.capture_path})
        return CaptureSource(cap, base=REPO_ROOT)
    return GdeltLiveSource(cfg.source.gdelt)


def _build_engine(pipeline_cfg, live_cfg: LiveConfig, enrich_cfg, scope_resolver, enricher, sentiment, event_model, legacy,
                  impact_model, market_context, store: LiveSignalStore, entities, snapshot_id: str):  # noqa: ANN001, ANN202
    """The incremental engine over the same models the replay run used (loaded once, shared).

    New text has no pinned vector, so a hybrid event model can only score it when an encoder is installed. Without one the engine
    starts on the reference TF-IDF model (impact is trained on that model's outputs anyway) and says so in its status.
    """
    import importlib.util

    cfg = pipeline_cfg.model_copy(update={"dedup": pipeline_cfg.dedup.model_copy(
        update={"unknown_same_event": live_cfg.dedup.unknown_same_event})})
    hybrid = isinstance(event_model, HybridEventModel)
    fallback = None
    if hybrid and legacy is not None:
        if impact_model is not None and market_context is not None and impact_model.served_scopes:
            fallback = ImpactModelEnricher(enrich_cfg, sentiment, legacy, impact_model, market_context)
        else:
            fallback = ModelEnricher(enrich_cfg, sentiment, legacy)
    engine = RiskEngine(
        entities=entities, pipeline_cfg=cfg, enrich_cfg=enrich_cfg, scope_resolver=scope_resolver, enricher=enricher,
        fallback_enricher=fallback, store=store, event_model_id=event_model.model_id,
        fallback_event_model_id=legacy.model_id if legacy is not None else None,
        start_on_fallback=hybrid and importlib.util.find_spec("torch") is None, snapshot_id=f"{snapshot_id}+live")
    return engine, (legacy.model_id if legacy is not None else None)


def _build_assessments(settings: Settings, taxonomy: Taxonomy, scope_config: ScopeConfig, scope_resolver: ScopeResolver,
                       signals: CombinedSignalRepository, config: AppConfig) -> AssessmentService:
    """The risk-assessment layer: closed vocabulary, the language model if (and only if) it is switched on and has a key, the rule extractor
    otherwise, and the hybrid scorer. A missing key is a labelled degradation (rule mode), never a start-up failure."""
    sem = load_semantics_config(settings.config_dir)
    hybrid = load_hybrid_config(settings.config_dir)
    llm_cfg = load_llm_config(settings.config_dir)
    llm_cfg = llm_cfg.for_provider(settings.llm_provider or llm_cfg.provider, settings.llm_model)
    enabled = settings.llm if settings.llm is not None else llm_cfg.enabled
    llm_cfg = llm_cfg.model_copy(update={"enabled": enabled})
    vocab = Vocab.build(sem, scope_config, {c.id.value: c.label for c in taxonomy.categories})
    rules = RuleExtractor(vocab, scope_resolver, max_quotes=llm_cfg.grounding.max_quotes, max_entities=llm_cfg.grounding.max_entities)
    client: LLMClient | None = None
    why: str | None = None
    if enabled:
        key = settings.llm_key(llm_cfg.provider)
        if not key:
            why = f"the language model is switched on (EVENTSHOCK_LLM) but {llm_cfg.key_env} is not set"
        else:
            client = CLIENTS[llm_cfg.provider](key, llm_cfg)
    cache = ExtractionCache(llm_cfg.cache_path(settings.llm_cache_path), llm_cfg.cache.max_entries)
    extractor = SemanticExtractor(vocab, rules, llm_cfg, client=client, cache=cache, unavailable_reason=why)
    return AssessmentService(extractor, HybridScorer(hybrid), signals, stress=config.stress)


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
    calendar: EventCalendar | None = None
    outcomes: Outcomes | None = None
    as_of: datetime | None = None
    engine = live_cfg = live_store = market_context = pipeline_cfg = scope_config = assessments = None
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
        scope_config = load_scope_config(settings.config_dir)
        scope_resolver = ScopeResolver(scope_config)
        result = run_snapshot(snapshot, pipeline_cfg, enrich_cfg, enricher=enricher, scope_resolver=scope_resolver)
        impact_card = impact_model.card if impact_model is not None else None
        calendar = impact_model.calendar if impact_model is not None else None
        outcomes_path = REPO_ROOT / "data" / "outcomes" / "replay_outcomes.json"
        outcomes = Outcomes.load(outcomes_path) if outcomes_path.is_file() else None
        as_of = snapshot.manifest.replay_as_of
        card = model.card
        event_card = event_model.card
        report = result.report
        base = InMemorySignalRepository(result.signals, snapshot.manifest.replay_as_of)
        portfolio = load_portfolio_files(snapshot.portfolio_path(), snapshot.entities_path())
        live_cfg = load_live_config(settings.config_dir)
        live_source = _live_source(settings, live_cfg)
        retention = max(live_cfg.retention_hours, 24.0 * 365) if isinstance(live_source, CaptureSource) else live_cfg.retention_hours
        live_store = LiveSignalStore(retention, live_cfg.max_signals)
        signals = CombinedSignalRepository(base, live_store)
        engine, fallback_id = _build_engine(
            pipeline_cfg, live_cfg, enrich_cfg, scope_resolver, enricher, model, event_model, legacy, impact_model, market_context,
            live_store, load_entities(snapshot.entities_path()), snapshot.manifest.snapshot_id)
    else:
        fixtures = resolve_fixtures_dir(settings, config)
        signals = CombinedSignalRepository(load_signal_repository(fixtures), LiveSignalStore())
        portfolio = load_portfolio_repository(fixtures)
    replay = config.data.profile == "replay"
    evidence = build_evidence(REPO_ROOT, card, event_card, impact_card) if replay else None
    catalog_relevance = RelevanceService(portfolio, catalog)
    analyzer = live = None
    if replay:
        journal = Journal(settings.journal_path or REPO_ROOT / live_cfg.journal)
        analyzer = Analyzer(engine, signals, pipeline_cfg.validation, journal=journal)
        market_through = market_context.last_session if market_context is not None else None
        live = LiveService(
            cfg=live_cfg, engine=engine, store=live_store, source=live_source, journal=journal,
            event_model_note=lambda: (engine.status.event_model, engine.status.event_fallback_reason),
            market_through=market_through)
        live.warm_start()
        assert scope_config is not None
        assessments = _build_assessments(settings, taxonomy, scope_config, scope_resolver, signals, config)
    return Container(
        settings=settings,
        config=config,
        taxonomy=taxonomy,
        scenario_set_version=version,
        catalog=catalog,
        signals=signals,
        portfolio=portfolio,
        stress=StressService(signals, portfolio, catalog, config,
                             severity_provider=assessments.severity_view if assessments else None),
        profile=config.data.profile,
        snapshot=snapshot,
        pipeline_report=report,
        sentiment_card=card,
        event_card=event_card,
        impact_card=impact_card,
        impact_status=impact_status,
        evidence=evidence,
        impact_event_reference=impact_event_reference,
        calendar=calendar,
        outcomes=outcomes,
        as_of=as_of,
        relevance=catalog_relevance,
        engine=engine if replay else None,
        analyzer=analyzer,
        live=live,
        live_store=live_store if replay else None,
        live_config=live_cfg if replay else None,
        scope_config=scope_config,
        assessments=assessments,
    )


def get_container(request: Request) -> Container:
    return request.app.state.container
