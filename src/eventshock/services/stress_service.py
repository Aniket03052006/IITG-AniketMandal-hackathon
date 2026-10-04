"""signal + scenario + portfolio -> StressResult. Owns the trigger rule and run identity."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..config import AppConfig
from ..domain import (
    EventCategory,
    RiskSignal,
    Scenario,
    ScopeLevel,
    ShockScope,
    SignalStatus,
    StressStatus,
)
from ..domain.stress import (
    AppliedShock,
    ScenarioRef,
    SeverityScaling,
    StressAudit,
    StressResult,
    StressSummary,
)
from ..ports import PortfolioRepository, SignalRepository
from ..stress.attribution import build_contributions, find_uncovered
from ..stress.engine import ENGINE_VERSION, scaled_shock_value, stress_portfolio
from ..stress.scenarios import ScenarioCatalog


@dataclass(frozen=True)
class SeverityView:
    """What the risk assessment hands the stress engine: a trigger score, the event class to map a scenario from, and a sector to bind sector
    shocks to when the signal's own scope has none. The engine applies them mechanically; nothing here is computed by a model at run time."""

    score: int
    category: EventCategory
    sector: str | None
    basis: str
    version: str
    extraction_mode: str


SeverityProvider = Callable[[RiskSignal], "SeverityView | None"]


MAX_RUNS_KEPT = 500


class SignalNotFound(LookupError):
    pass


class ScenarioNotFound(LookupError):
    pass


class StressService:
    def __init__(
        self,
        signals: SignalRepository,
        portfolio: PortfolioRepository,
        catalog: ScenarioCatalog,
        config: AppConfig,
        clock: Callable[[], datetime] | None = None,
        severity_provider: SeverityProvider | None = None,
    ) -> None:
        self._severity = severity_provider
        self._signals = signals
        self._portfolio = portfolio
        self._catalog = catalog
        self._cfg = config
        # Replay mode pins time to the fixture clock so results are reproducible byte for byte.
        self._clock = clock or (lambda: signals.as_of)
        self._runs: dict[str, StressResult] = {}  # bounded (oldest dropped): a run id is a hash, so any run can be recomputed identically

    # ------------------------------------------------------------------ public

    def run(
        self,
        signal_id: str,
        scenario_id: str | None = None,
        *,
        force: bool = False,
        impact_override: float | None = None,
    ) -> StressResult:
        signal = self._signals.get(signal_id)
        if signal is None:
            raise SignalNotFound(signal_id)

        scenario: Scenario | None
        if scenario_id is not None:
            scenario = self._catalog.get(scenario_id)
            if scenario is None:
                raise ScenarioNotFound(scenario_id)
        else:
            view = self._severity(signal) if self._severity else None
            scenario = self._catalog.default_for(view.category if view else signal.event.category)

        result = self._evaluate(signal, scenario, force, impact_override)
        self._runs.pop(result.run_id, None)
        self._runs[result.run_id] = result
        while len(self._runs) > MAX_RUNS_KEPT:
            self._runs.pop(next(iter(self._runs)))
        return result

    def get_run(self, run_id: str) -> StressResult | None:
        return self._runs.get(run_id)

    def runs_for(self, signal_id: str) -> list[StressResult]:
        """Runs already made for a signal, newest first."""
        return [r for r in reversed(self._runs.values()) if r.signal_id == signal_id]

    def default_scenario(self, category: EventCategory) -> Scenario | None:
        return self._catalog.default_for(category)

    # ----------------------------------------------------------------- internals

    def _evaluate(
        self, signal: RiskSignal, scenario: Scenario | None, force: bool, override: float | None
    ) -> StressResult:
        threshold = self._cfg.stress.trigger_threshold
        portfolio = self._portfolio.get()
        pf_hash = portfolio.content_hash()
        view = self._severity(signal) if self._severity else None

        scope0 = signal.scope
        # A sector read from the text by the assessment binds sector shocks only where the vocabulary scope found none (never over a resolved company).
        assessed_sector = (view.sector if view and view.sector and not (scope0 is not None and scope0.has_sector) else None)

        def audit(impact: float | None, version: str | None) -> StressAudit:
            return StressAudit(
                mode=self._cfg.mode,
                data_origin=signal.data_origin,
                engine_version=ENGINE_VERSION,
                scenario_version=version,
                portfolio_id=portfolio.portfolio_id,
                portfolio_hash=pf_hash,
                threshold=threshold,
                forced=force,
                impact_overridden=override is not None,
                impact_origin="ASSESSMENT" if view else _impact_origin(signal),
                impact_lifecycle=None if view else _impact_lifecycle(signal),
                scope_level=signal.scope.level.value if signal.scope else None,
                scope_note=_scope_note(signal, assessed_sector),
                severity_basis=view.basis if view else None,
                severity_version=view.version if view else None,
                assessed_sector=assessed_sector,
                extraction_mode=view.extraction_mode if view else None,
                calculated_at=max(self._clock(), signal.created_at),
            )

        def early(status: StressStatus, reason: str, impact: float | None = None) -> StressResult:
            return StressResult(
                run_id=self._run_id(signal.id, scenario, impact, force, pf_hash, status, view.basis if view else None),
                status=status,
                reason=reason,
                signal_id=signal.id,
                scenario=self._ref(scenario),
                audit=audit(impact, scenario.version if scenario else None),
            )

        if view is None and (signal.status is SignalStatus.PARTIAL or signal.impact is None):
            return early(
                StressStatus.UNAVAILABLE,
                "This signal has no impact score (partial signal). EventShock does not invent one, "
                "so no stress test can be mapped.",
            )
        if scenario is None:
            return early(
                StressStatus.NO_SCENARIO,
                f"No scenario template is mapped to {(view.category if view else signal.event.category).value}.",
                float(view.score) if view else signal.impact.score,  # type: ignore[union-attr]
            )

        base_impact = float(view.score) if view else float(signal.impact.score)  # type: ignore[union-attr]
        impact = float(override) if override is not None else base_impact
        if override is not None and not force:
            return early(
                StressStatus.NOT_TRIGGERED,
                "impact_override is a what-if input and requires force=true.",
                impact,
            )
        if impact < threshold and not force:
            return early(
                StressStatus.NOT_TRIGGERED,
                f"{'Severity' if view else 'Impact'} {impact:g} is below the trigger threshold {threshold:g}. "
                "Run as a what-if to stress it anyway.",
                impact,
            )

        # ---- severity scaling (explicit and shown to the user)
        cfg = self._cfg.stress
        raw_ratio = impact / scenario.reference_impact
        scale = min(max(raw_ratio, cfg.severity_scale_min), cfg.severity_scale_max)
        severity = SeverityScaling(
            impact_used=impact,
            reference_impact=scenario.reference_impact,
            min_scale=cfg.severity_scale_min,
            max_scale=cfg.severity_scale_max,
            raw_ratio=raw_ratio,
            scale=scale,
            formula=(
                f"scale = clamp(impact / reference, {cfg.severity_scale_min:g}, {cfg.severity_scale_max:g})"
                f" = clamp({impact:g} / {scenario.reference_impact:g}) = {scale:.4f}"
            ),
        )

        scope = signal.scope
        assert scope is not None  # RiskSignal always carries one (derived from the entity when a producer set none)
        entity_known = scope.level is ScopeLevel.COMPANY and not signal.entity.is_unknown
        entity_id = signal.entity.entity_id if entity_known else None
        sector = scope.sector if scope.has_sector else assessed_sector
        level = ScopeLevel.SECTOR if assessed_sector else scope.level
        applied = []
        for s in scenario.shocks:
            ok, why = _binds(s.scope, level, entity_known, sector)
            applied.append(AppliedShock(
                factor=s.factor, scope=s.scope, base_value=s.value,
                scaled_value=scaled_shock_value(s.factor, s.value, scale),
                applicable=ok, not_applicable_reason=why, rationale=s.rationale))
        if not any(a.applicable for a in applied):
            return StressResult(
                run_id=self._run_id(signal.id, scenario, impact, force, pf_hash, StressStatus.NOT_APPLICABLE, view.basis if view else None),
                status=StressStatus.NOT_APPLICABLE,
                reason=(f"No shock in '{scenario.name}' reaches what this event is about "
                        f"({_scope_words(level, sector)}); the scenario is written for an identified "
                        "company or sector, so no loss is computed rather than reporting a zero."),
                signal_id=signal.id, scenario=self._ref(scenario), severity=severity, shocks=applied,
                audit=audit(impact, scenario.version))

        positions = stress_portfolio(portfolio, applied, entity_id, sector)
        baseline = sum(p.baseline_value for p in positions)
        pnl = sum(p.delta for p in positions)
        return StressResult(
            run_id=self._run_id(signal.id, scenario, impact, force, pf_hash, StressStatus.COMPLETED, view.basis if view else None),
            status=StressStatus.COMPLETED,
            reason=None,
            signal_id=signal.id,
            scenario=self._ref(scenario),
            severity=severity,
            shocks=applied,
            summary=StressSummary(
                baseline_value=baseline,
                stressed_value=baseline + pnl,
                pnl=pnl,
                pnl_pct=pnl / baseline if baseline else 0.0,
            ),
            positions=sorted(positions, key=lambda p: (p.delta, p.asset_id)),
            contributions=build_contributions(positions, cfg.top_n_positions),
            uncovered=find_uncovered(positions, baseline),
            audit=audit(impact, scenario.version),
        )

    @staticmethod
    def _ref(scenario: Scenario | None) -> ScenarioRef | None:
        if scenario is None:
            return None
        return ScenarioRef(
            id=scenario.id, version=scenario.version, name=scenario.name,
            category=scenario.category.value, illustrative=scenario.illustrative,
        )

    @staticmethod
    def _run_id(
        signal_id: str,
        scenario: Scenario | None,
        impact: float | None,
        force: bool,
        pf_hash: str,
        status: StressStatus,
        basis: str | None = None,
    ) -> str:
        body = {
            "signal": signal_id,
            "scenario": [scenario.id, scenario.version] if scenario else None,
            "impact": None if impact is None else round(impact, 6),
            "force": force,
            "portfolio": pf_hash,
            "status": status.value,
        }
        if basis:  # only a run driven by the assessment carries it: every other run id is unchanged
            body["basis"] = basis
        payload = json.dumps(body, sort_keys=True)
        return "run_" + hashlib.sha256(payload.encode()).hexdigest()[:12]


def _scope_words(level: ScopeLevel, sector: str | None) -> str:
    return {ScopeLevel.COMPANY: "one named company", ScopeLevel.SECTOR: f"the {sector} sector, no single company",
            ScopeLevel.MARKET: "the market as a whole, no single company or sector",
            ScopeLevel.UNRESOLVED: "no company, sector or market theme could be identified"}[level]


def _binds(shock_scope: ShockScope, level: ScopeLevel, entity_known: bool, sector: str | None) -> tuple[bool, str | None]:
    """Does a shock of this scope reach the event? MARKET always; SECTOR needs a sector (named or implied); ISSUER needs a company."""
    if shock_scope is ShockScope.MARKET:
        return True, None
    if shock_scope is ShockScope.SECTOR:
        return (True, None) if sector else (False, f"No sector was identified ({_scope_words(level, sector)}).")
    return (True, None) if entity_known else (False, f"No single company was identified ({_scope_words(level, sector)}).")


def _scope_note(signal: RiskSignal, assessed_sector: str | None = None) -> str | None:
    s = signal.scope
    if s is None:
        return None
    if assessed_sector:
        return (f"Sector ({assessed_sector}) was read from the text by the risk assessment, not found by the vocabulary scope; "
                "sector and market-wide shocks apply, issuer shocks do not (no single company).")
    return {ScopeLevel.COMPANY: "Issuer, sector and market-wide shocks apply.",
            ScopeLevel.SECTOR: f"Sector ({s.sector}) and market-wide shocks apply; issuer shocks do not (no single company).",
            ScopeLevel.MARKET: "Only market-wide shocks apply (no single company or sector).",
            ScopeLevel.UNRESOLVED: "No subject was identified: only market-wide shocks can apply, and the impact is a "
                                   "market-state estimate."}[s.level]


def _impact_origin(signal: RiskSignal) -> str | None:
    if signal.impact is None:
        return None
    if signal.provenance is None:
        return None  # demo fixtures: no per-stage record
    return "MODEL" if signal.provenance.stage_origins.get("impact") == "MODEL" else "PLACEHOLDER"


def _impact_lifecycle(signal: RiskSignal) -> str | None:
    audit = signal.provenance.impact if signal.provenance else None
    return audit.lifecycle.value if audit else None
