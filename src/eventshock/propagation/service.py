"""``PropagationService``: event -> scope -> portfolio materiality -> exposure propagation -> scenario -> stress -> attribution, for one signal and one portfolio.

It reuses the Stage 10 scope (``IntelligenceService.scope_of``), the Stage 7 assessment (severity, event class, direction), the Stage 9 portfolio, and the unchanged
stress engine (``StressService.run_scenario``). Nothing is stored on a signal; every answer is derived and deterministic for a given signal, portfolio and configuration.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from ..adjust.models import AdjustmentNotice
from ..domain import (
    EventCategory,
    Portfolio,
    RiskFactor,
    RiskSignal,
    ScopeLevel,
    StressResult,
    StressStatus,
)
from ..domain.enums import UNKNOWN_ENTITY
from ..intelligence.model import EventScope
from ..intelligence.service import IntelligenceService
from ..portfolio.chain import build_exposure_chain
from ..ports import PortfolioRepository
from ..services.stress_service import StressService
from ..store import CombinedSignalRepository
from .attribution import build_attribution
from .concentration import ConcentrationAnalyzer, OverlapItem
from .config import PropagationConfig
from .mapping import PropagationMapper
from .materiality import MaterialityAssessor
from .models import (
    AutoStressResult,
    ConcentrationView,
    GeneratedScenario,
    OverlapView,
    PortfolioFlow,
    PortfolioMateriality,
    PropagationGraph,
    ShockOrigin,
    StressAttribution,
)
from .scenario_gen import ScenarioGenerator

NO_EVENT = "NO_EVENT"
_MEMO = 256


class _Ctx:
    __slots__ = ("scope", "category", "severity", "direction", "event_sector", "issuer_known")

    def __init__(self, scope: EventScope, category: EventCategory | None, severity: float | None, direction: str | None,
                 event_sector: str | None, issuer_known: bool) -> None:
        self.scope, self.category, self.severity, self.direction, self.event_sector, self.issuer_known = scope, category, severity, direction, event_sector, issuer_known


class PropagationService:
    def __init__(self, cfg: PropagationConfig, *, signals: CombinedSignalRepository, intelligence: IntelligenceService, assessments: Any,  # AssessmentService | None
                 stress: StressService, portfolio: PortfolioRepository, mapper: PropagationMapper, assessor: MaterialityAssessor, generator: ScenarioGenerator,
                 concentration: ConcentrationAnalyzer, notice: Callable[[], AdjustmentNotice | None] | None = None, adjust_version: Callable[[], str] | None = None) -> None:
        self.cfg = cfg
        self._signals = signals
        self._intel = intelligence
        self._assess = assessments
        self._stress = stress
        self._portfolio = portfolio
        self._mapper = mapper
        self._assessor = assessor
        self._gen = generator
        self._conc = concentration
        self._notice = notice or (lambda: None)
        self._adjust_version = adjust_version or (lambda: "default")
        self._lock = threading.RLock()
        self._memo: OrderedDict[tuple, Any] = OrderedDict()
        self._origins: OrderedDict[tuple[str, str], list[ShockOrigin]] = OrderedDict()
        self._hashes: OrderedDict[int, tuple[Portfolio, str]] = OrderedDict()  # id(portfolio) -> (portfolio, content hash): hashing 100 holdings per lookup was the cost

    # ------------------------------------------------------------------------------------------------------------------ helpers
    def _book(self, portfolio: Portfolio | None) -> Portfolio:
        return portfolio if portfolio is not None else self._portfolio.get()

    def _cached(self, key: tuple, build: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._memo:
                self._memo.move_to_end(key)
                return self._memo[key]
        value = build()
        with self._lock:
            self._memo[key] = value
            while len(self._memo) > _MEMO:
                self._memo.popitem(last=False)
        return value

    def _ctx(self, signal: RiskSignal) -> _Ctx:
        scope = self._intel.scope_of(signal)
        a = self._assess.assess(signal) if self._assess is not None else None
        category: EventCategory | None
        severity = direction = None
        sector = signal.scope.sector if signal.scope is not None and signal.scope.has_sector else None
        if a is not None:
            category = None if a.reading.event_type == NO_EVENT else EventCategory(a.reading.event_type)
            if a.severity is not None:
                severity = float(a.severity.score)
                direction = next((f.final for f in a.severity.rubric if f.id == "direction"), None)
            if sector is None and a.reading.sectors:
                sector = a.reading.sectors[0]
        else:
            category = None if signal.event.status.value == NO_EVENT else signal.event.category
        issuer_known = signal.scope is not None and signal.scope.level is ScopeLevel.COMPANY and signal.entity.entity_id != UNKNOWN_ENTITY
        return _Ctx(scope, category, severity, direction, sector, issuer_known)

    def _pf_hash(self, pf: Portfolio) -> str:
        """``pf.content_hash()``, computed once per portfolio object (the object is held so its id cannot be reused; portfolios are never mutated in place)."""
        with self._lock:
            hit = self._hashes.get(id(pf))
            if hit is not None and hit[0] is pf:
                return hit[1]
        h = pf.content_hash()
        with self._lock:
            self._hashes[id(pf)] = (pf, h)
            while len(self._hashes) > 32:
                self._hashes.popitem(last=False)
        return h

    def _key(self, kind: str, signal: RiskSignal, pf: Portfolio, *extra: object) -> tuple:
        return (kind, signal.id, signal.created_at, signal.document.id, self._pf_hash(pf), self._signals.seq, self._adjust_version(), *extra)

    # ---------------------------------------------------------------------------------------------------------------------- graph
    def graph(self, signal: RiskSignal, portfolio: Portfolio | None = None) -> PropagationGraph:
        pf = self._book(portfolio)

        def build() -> PropagationGraph:
            c = self._ctx(signal)
            return self._mapper.map(signal, pf, c.scope, c.category, self._notice())
        return self._cached(self._key("graph", signal, pf), build)

    def materiality(self, signal: RiskSignal, portfolio: Portfolio | None = None) -> PortfolioMateriality:
        pf = self._book(portfolio)

        def build() -> PortfolioMateriality:
            return self._assessor.assess(self.graph(signal, pf), self._ctx(signal).severity, self._notice())
        return self._cached(self._key("materiality", signal, pf), build)

    def scenario(self, signal: RiskSignal, portfolio: Portfolio | None = None) -> GeneratedScenario:
        pf = self._book(portfolio)

        def build() -> GeneratedScenario:
            c = self._ctx(signal)
            gen = self._gen.generate(
                signal_id=signal.id, portfolio=pf, graph=self.graph(signal, pf), materiality=self.materiality(signal, pf), category=c.category, severity=c.severity,
                direction=c.direction, event_sector=c.event_sector, issuer_known=c.issuer_known, mapper=self._mapper, adjustments=self._notice())
            if gen.scenario is not None:
                with self._lock:
                    self._origins[(gen.scenario.id, gen.scenario.version)] = gen.origins
                    while len(self._origins) > 200:
                        self._origins.popitem(last=False)
            return gen
        return self._cached(self._key("scenario", signal, pf), build)

    # ----------------------------------------------------------------------------------------------------------------------- flow
    def flow(self, signal: RiskSignal, portfolio: Portfolio | None = None) -> PortfolioFlow:
        pf = self._book(portfolio)
        gen = self.scenario(signal, pf)
        run_id = None
        if gen.scenario is not None:
            for r in self._stress.runs_for(signal.id, pf.portfolio_id):
                if r.scenario and r.scenario.id == gen.scenario.id and r.scenario.version == gen.scenario.version:
                    run_id = r.run_id
                    break
        return PortfolioFlow(signal_id=signal.id, portfolio_id=pf.portfolio_id, portfolio_name=pf.name, graph=self.graph(signal, pf),
                             materiality=self.materiality(signal, pf), scenario=gen, existing_run_id=run_id, adjustments=self._notice())

    # ------------------------------------------------------------------------------------------------------------------- stress
    def portfolio_stress(self, signal: RiskSignal, portfolio: Portfolio | None = None, *, force: bool = False,
                         impact_override: float | None = None, store: bool = True) -> AutoStressResult:
        pf = self._book(portfolio)
        mat = self.materiality(signal, pf)
        gen = self.scenario(signal, pf)
        base = dict(signal_id=signal.id, portfolio_id=pf.portfolio_id, materiality=mat, scenario=gen, adjustments=self._notice())
        if gen.scenario is None:
            return AutoStressResult(run=None, chain=None, attribution=None, note=gen.reason, **base)
        if gen.availability.value != "AVAILABLE" and not (force and gen.can_force):
            return AutoStressResult(run=None, chain=None, attribution=None, note=gen.reason, **base)
        sev = self._ctx(signal).severity
        below_trigger = (sev if impact_override is None else impact_override) is not None and \
            (sev if impact_override is None else impact_override) < self._stress.trigger_threshold
        run = self._stress.run_scenario(signal.id, gen.scenario, force=force or impact_override is not None or below_trigger, impact_override=impact_override, portfolio=pf, store=store)
        chain = attribution = None
        note = None
        if run.status is StressStatus.COMPLETED:
            chain = build_exposure_chain(run, pf, signal)
            attribution = self.attribution(run, pf)
        else:
            note = run.reason
        return AutoStressResult(run=run, chain=chain, attribution=attribution, note=note, **base)

    def attribution(self, run: StressResult, portfolio: Portfolio, *, extra_factor_map: Mapping[RiskFactor, str] | None = None) -> StressAttribution:
        """``extra_factor_map`` names the risk factors of engine factors a user-built scenario adds (FX, oil); every catalog and generated run passes none."""
        origins = None
        if run.scenario is not None:
            with self._lock:
                origins = self._origins.get((run.scenario.id, run.scenario.version))
        return build_attribution(
            run, portfolio, industry_of=self._mapper.industry_of, origins=origins, engine_factor_map={**self.cfg.engine_factor_map, **(extra_factor_map or {})},
            risk_factor_labels={k: v.label for k, v in self.cfg.risk_factors.items()}, entity_names=self._names())

    def _names(self) -> dict[str, str]:
        return {e.entity_id: e.name for e in self._portfolio.entities()}

    # ------------------------------------------------------------------------------------------------------------ concentration
    def concentration(self, portfolio: Portfolio | None = None) -> ConcentrationView:
        pf = self._book(portfolio)
        return self._cached(("conc", self._pf_hash(pf), self._adjust_version()), lambda: self._conc.view(pf, self._notice()))

    def overlaps_of(self, items: list[OverlapItem], portfolio: Portfolio | None = None) -> OverlapView:
        """Overlaps among a given set of events (each already mapped to the portfolio): the same analyzer, over events a caller chose (the monitor's states at a moment)."""
        return self._conc.overlaps(self._book(portfolio), items, considered=len(items), adjustments=self._notice())

    def overlaps(self, portfolio: Portfolio | None = None) -> OverlapView:
        pf = self._book(portfolio)
        c = self.cfg.concentration

        def build() -> OverlapView:
            sigs = self._signals.list()
            if not sigs:
                return self._conc.overlaps(pf, [], adjustments=self._notice())
            ref = max(sigs[0].document.published_at, self._signals.as_of)
            cutoff = ref - timedelta(days=c.window_days)
            idx = self._intel.index()
            items: list[OverlapItem] = []
            considered = 0
            for s in sigs:  # newest first
                if s.document.published_at < cutoff:
                    break
                if considered >= c.max_signals:
                    break
                ev = idx.event_of(s.id)
                if ev is None:
                    continue
                considered += 1
                mat = self.materiality(s, pf)
                if mat.level not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                    continue
                sev = self._ctx(s).severity
                items.append(OverlapItem(signal_id=s.id, event_id=ev.id, headline=s.document.headline, published_at=s.document.published_at,
                                         materiality=mat.level, severity=sev, graph=self.graph(s, pf)))
            return self._conc.overlaps(pf, items, considered=considered, adjustments=self._notice())
        return self._cached(("overlaps", self._pf_hash(pf), self._signals.seq, self._adjust_version()), build)

