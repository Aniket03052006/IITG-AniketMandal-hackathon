"""signal + scenario + portfolio -> StressResult. Owns the trigger rule and run identity."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from ..config import AppConfig
from ..domain import (
    EventCategory,
    RiskSignal,
    Scenario,
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
    ) -> None:
        self._signals = signals
        self._portfolio = portfolio
        self._catalog = catalog
        self._cfg = config
        # Replay mode pins time to the fixture clock so results are reproducible byte for byte.
        self._clock = clock or (lambda: signals.as_of)
        self._runs: dict[str, StressResult] = {}

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
            scenario = self._catalog.default_for(signal.event.category)

        result = self._evaluate(signal, scenario, force, impact_override)
        self._runs[result.run_id] = result
        return result

    def get_run(self, run_id: str) -> StressResult | None:
        return self._runs.get(run_id)

    def default_scenario(self, category: EventCategory) -> Scenario | None:
        return self._catalog.default_for(category)

    # ----------------------------------------------------------------- internals

    def _evaluate(
        self, signal: RiskSignal, scenario: Scenario | None, force: bool, override: float | None
    ) -> StressResult:
        threshold = self._cfg.stress.trigger_threshold
        portfolio = self._portfolio.get()
        pf_hash = portfolio.content_hash()

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
                calculated_at=self._clock(),
            )

        def early(status: StressStatus, reason: str, impact: float | None = None) -> StressResult:
            return StressResult(
                run_id=self._run_id(signal.id, scenario, impact, force, pf_hash, status),
                status=status,
                reason=reason,
                signal_id=signal.id,
                scenario=self._ref(scenario),
                audit=audit(impact, scenario.version if scenario else None),
            )

        if signal.status is SignalStatus.PARTIAL or signal.impact is None:
            return early(
                StressStatus.UNAVAILABLE,
                "This signal has no impact score (partial signal). EventShock does not invent one, "
                "so no stress test can be mapped.",
            )
        if scenario is None:
            return early(
                StressStatus.NO_SCENARIO,
                f"No scenario template is mapped to {signal.event.category.value}.",
                signal.impact.score,
            )

        impact = float(override) if override is not None else float(signal.impact.score)
        if override is not None and not force:
            return early(
                StressStatus.NOT_TRIGGERED,
                "impact_override is a what-if input and requires force=true.",
                impact,
            )
        if impact < threshold and not force:
            return early(
                StressStatus.NOT_TRIGGERED,
                f"Impact {impact:g} is below the trigger threshold {threshold:g}. "
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

        entity_known = not signal.entity.is_unknown
        entity_id = signal.entity.entity_id if entity_known else None
        sector = signal.entity.sector if entity_known else None
        applied = [
            AppliedShock(
                factor=s.factor,
                scope=s.scope,
                base_value=s.value,
                scaled_value=scaled_shock_value(s.factor, s.value, scale),
                applicable=(s.scope.value == "MARKET") or entity_known,
                rationale=s.rationale,
            )
            for s in scenario.shocks
        ]

        positions = stress_portfolio(portfolio, applied, entity_id, sector)
        baseline = sum(p.baseline_value for p in positions)
        pnl = sum(p.delta for p in positions)
        return StressResult(
            run_id=self._run_id(signal.id, scenario, impact, force, pf_hash, StressStatus.COMPLETED),
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
    ) -> str:
        payload = json.dumps(
            {
                "signal": signal_id,
                "scenario": [scenario.id, scenario.version] if scenario else None,
                "impact": None if impact is None else round(impact, 6),
                "force": force,
                "portfolio": pf_hash,
                "status": status.value,
            },
            sort_keys=True,
        )
        return "run_" + hashlib.sha256(payload.encode()).hexdigest()[:12]
