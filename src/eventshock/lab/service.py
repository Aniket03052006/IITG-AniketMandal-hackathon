"""``LabService``: plan, run and compare scenarios on the existing stress engine. There is no second valuation engine here: every number is the engine's.

Identity. A scenario's id is a hash of the portfolio it runs on, its type and its canonical (sorted) engine shocks, so the same assumptions on the same book give the same id and the same
result, whatever order they were entered in. ``created_at`` is the (replay) clock and is not part of the id.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime

from ..decision.config import LabCfg, ReverseCfg
from ..decision.models import ObservationKind, ProvenanceRef
from ..domain import (
    Entity,
    EventCategory,
    Portfolio,
    RiskFactor,
    Scenario,
    ShockSpec,
    StressResult,
    StressStatus,
)
from ..domain.enums import FACTOR_UNITS
from ..propagation.models import StressAttribution
from ..propagation.service import PropagationService
from ..services.stress_service import StressService
from ..stress.engine import ENGINE_VERSION
from ..stress.history_check import ShockHistory
from .build import Plan, Vocab, fmt, resolve, resolved_shocks
from .exposure import apply_commodity_priors
from .models import (
    VERSION,
    AssumptionDiffRow,
    AssumptionKind,
    AssumptionResult,
    AxisBound,
    Comparison,
    ComparisonRow,
    KindInfo,
    LabIssue,
    LabOptions,
    LabPlan,
    LabResult,
    OptionEntry,
    PriorUse,
    RequiredShock,
    ResolvedShock,
    ReverseOptions,
    ReverseStressRequest,
    ReverseStressResult,
    ScenarioRequest,
    ScenarioType,
)
from .reverse import LIMITATIONS as REVERSE_LIMITATIONS
from .reverse import METHOD, OBJECTIVE, Axis, Budget, ReverseSearch, assumptions_for, build_axes, reverse_id

LABELS = [
    "Every size here is a SCENARIO ASSUMPTION: a hypothetical shock run through the deterministic stress engine. It is not a prediction, a forecast, a model output or an expected return.",
    "BASE is the portfolio as it is, ASSESSED is EventShock's configured scenario for an event, CUSTOM is what you chose: they are never mixed.",
    "Attribution regroups the engine's own result and adds up to its total; it is a sensitivity decomposition under the assumptions, not causal attribution.",
]
LIMITATIONS = [
    "A shock reaches only positions that carry the exposure it acts on: a currency shock reaches holdings in that currency, an oil shock reaches positions with an oil elasticity. Nothing is moved by a guess.",
    "The default synthetic book holds no foreign-currency positions and no measured oil elasticity; a personal portfolio can carry a currency, and the sector-prior oil estimate is a judgement prior you switch on.",
    "The engine is first-order: no convexity, no volatility regime, no second-round effects, and every shock is applied instantly.",
    "Only equity and rate shocks can be ranked against history; credit, default, oil and currency shocks are reported as not checkable.",
]
_MEMO = 256


class LabInvalid(ValueError):
    def __init__(self, issues: list[LabIssue]) -> None:
        super().__init__("; ".join(i.message for i in issues))
        self.issues = issues


class LabService:
    def __init__(self, cfg: LabCfg, *, reverse_cfg: ReverseCfg, stress: StressService, propagation: Callable[[], PropagationService | None], signals, book: Callable[[Portfolio | None], Portfolio],  # noqa: ANN001
                 entities: Callable[[], list[Entity]], sectors: Callable[[], list[str]], shock_history: Callable[[], ShockHistory | None],
                 clock: Callable[[], datetime] | None = None) -> None:
        self.cfg = cfg
        self.reverse_cfg = reverse_cfg
        self._stress = stress
        self._prop = propagation
        self._signals = signals
        self._book = book
        self._entities = entities
        self._sectors = sectors
        self._history = shock_history
        self._clock = clock or (lambda: signals.as_of or datetime.now(UTC))
        self._lock = threading.RLock()
        self._memo: OrderedDict[tuple, LabResult] = OrderedDict()

    # ------------------------------------------------------------------------------------------------------------------------------- vocabulary
    def _prop_svc(self) -> PropagationService:
        p = self._prop()
        if p is None:
            raise LookupError("the scenario lab needs the propagation layer (replay profile)")
        return p

    def _vocab(self, pf: Portfolio) -> Vocab:
        ents: dict[str, tuple[str, str]] = {}
        for e in self._entities():
            ents[e.entity_id.lower()] = (e.entity_id, e.name)
            if e.ticker:
                ents[e.ticker.lower()] = (e.entity_id, e.name)
        sectors = {s.lower(): s for s in self._sectors()}
        sectors.update({a.sector.lower(): a.sector for a in pf.assets if a.sector not in ("Cash", "Other")})
        return Vocab(base_currency=pf.base_currency, sectors=sectors, entities=ents, prop=self._prop_svc().cfg,
                     held_currencies={a.currency for a in pf.assets if a.currency})

    def bounds(self) -> dict[str, dict[str, float | str]]:
        out: dict[str, dict[str, float | str]] = {k: {"min": b.min, "max": b.max, "unit": b.unit} for k, b in self.cfg.bounds.items()}
        for k, r in self.cfg.risk_factors.items():
            out[f"RISK_FACTOR:{k}"] = {"min": r.min, "max": r.max, "unit": r.unit}
        return out

    def options(self, portfolio: Portfolio | None = None) -> LabOptions:
        pf = self._book(portfolio)
        v = self._vocab(pf)
        b = self.cfg.bounds
        kinds = [
            KindInfo(kind=AssumptionKind.EQUITY_MARKET, label="Equity market", unit=b["EQUITY_MARKET"].unit, min=b["EQUITY_MARKET"].min, max=b["EQUITY_MARKET"].max, needs_target=None,
                     reaches="every equity at its beta, and equity derivatives through their delta"),
            KindInfo(kind=AssumptionKind.RATES, label="Interest rates (parallel)", unit=b["RATES"].unit, min=b["RATES"].min, max=b["RATES"].max, needs_target=None, reaches="bonds, through their duration"),
            KindInfo(kind=AssumptionKind.CREDIT_SPREAD, label="Credit spreads", unit=b["CREDIT_SPREAD"].unit, min=b["CREDIT_SPREAD"].min, max=b["CREDIT_SPREAD"].max,
                     needs_target="an optional sector", reaches="corporate bonds, through spread duration"),
            KindInfo(kind=AssumptionKind.COMMODITY, label="Oil price", unit=b["COMMODITY"].unit, min=b["COMMODITY"].min, max=b["COMMODITY"].max, needs_target=None,
                     reaches="positions with an oil elasticity (measured, or a sector prior you switch on)"),
            KindInfo(kind=AssumptionKind.FX, label="Currency", unit=b["FX"].unit, min=b["FX"].min, max=b["FX"].max, needs_target="a currency code (not the base currency)",
                     reaches="positions held in that currency"),
            KindInfo(kind=AssumptionKind.SECTOR, label="Sector equities", unit=b["SECTOR"].unit, min=b["SECTOR"].min, max=b["SECTOR"].max, needs_target="a sector", reaches="that sector's equities, without a beta"),
            KindInfo(kind=AssumptionKind.ISSUER, label="Issuer equity", unit=b["ISSUER"].unit, min=b["ISSUER"].min, max=b["ISSUER"].max, needs_target="an issuer in the entity master",
                     reaches="that issuer's equity, without a beta"),
            KindInfo(kind=AssumptionKind.RISK_FACTOR, label="Risk factor", unit="per factor", min=None, max=None, needs_target="a risk factor id ('FX:EUR' for a currency)",
                     reaches="an engine factor, or (inflation, geopolitical) the sectors its transmission edges name"),
        ]
        common = ["EUR", "GBP", "JPY", "INR", "CNY", "CHF", "CAD", "AUD"]
        _, priors = apply_commodity_priors(pf, self.cfg.commodity_sector_priors)
        rc = self.reverse_cfg
        axes = build_axes(rc, pf, None)[0]
        return LabOptions(
            portfolio_id=pf.portfolio_id, base_currency=pf.base_currency, kinds=kinds, sectors=[OptionEntry(value=n, label=n) for n in sorted(set(v.sectors.values()))],
            issuers=sorted((OptionEntry(value=eid, label=name, detail=None) for eid, name in {x for x in v.entities.values()}), key=lambda o: (o.label, o.value)),
            currencies=[OptionEntry(value=c, label=c) for c in common if c != pf.base_currency], held_currencies=sorted(v.held_currencies),
            risk_factors=[OptionEntry(value=k, label=v.prop.risk_factors[k].label if k in v.prop.risk_factors else k, detail=f"{r.min:g} to {r.max:g} {r.unit}") for k, r in sorted(self.cfg.risk_factors.items())],
            oil_priors=priors, max_assumptions=self.cfg.max_assumptions, max_compared=self.cfg.max_compared,
            reverse=ReverseOptions(presets_pct=rc.presets_pct, min_target_pct=rc.min_target_pct, tolerance_pp=rc.tolerance_pp, method=METHOD,
                                   axes=[OptionEntry(value=a.id, label=a.label, detail=f"limit {a.bound:g} {a.unit}") for a in axes]))

    # --------------------------------------------------------------------------------------------------------------------------------- identity
    @staticmethod
    def scenario_id(kind: ScenarioType, pf: Portfolio, shocks: list[ShockSpec], extra: str = "") -> str:
        canon = sorted([s.factor.value, s.scope.value, s.sector or "", s.currency or "", s.entity_id or "", round(s.value, 8)] for s in shocks)
        raw = json.dumps({"type": kind.value, "portfolio": pf.content_hash(), "shocks": canon, "engine": ENGINE_VERSION, "extra": extra}, sort_keys=True)
        return "scn_lab_" + hashlib.sha256(raw.encode()).hexdigest()[:12]

    # ----------------------------------------------------------------------------------------------------------------------------------- plan
    def plan(self, req: ScenarioRequest, portfolio: Portfolio | None = None) -> tuple[LabPlan, list[Plan]]:
        pf = self._book(portfolio)
        if req.scenario_type is ScenarioType.ASSESSED:
            sid = None
            issues = [] if req.signal_id else [LabIssue(index=None, field="signal_id", message="an ASSESSED scenario names the signal whose scenario to run")]
            return LabPlan(ok=not issues, scenario_type=req.scenario_type, scenario_id=sid, issues=issues, assumptions=[], bounds=self.bounds()), []
        if req.scenario_type is ScenarioType.BASE:
            issues = [LabIssue(index=None, field="assumptions", message="a BASE scenario has no assumptions")] if req.assumptions else []
            return LabPlan(ok=not issues, scenario_type=req.scenario_type, scenario_id=self.scenario_id(ScenarioType.BASE, pf, []), issues=issues, assumptions=[],
                           bounds=self.bounds()), []
        if not req.assumptions:
            return LabPlan(ok=False, scenario_type=req.scenario_type, scenario_id=None, bounds=self.bounds(), assumptions=[],
                           issues=[LabIssue(index=None, field="assumptions", message="a CUSTOM scenario needs at least one assumption (or use BASE)")]), []
        plans, issues = resolve(req.assumptions, self.cfg, self._vocab(pf))
        shocks = [s for p in plans for s in p.shocks]
        sid = self.scenario_id(ScenarioType.CUSTOM, pf, shocks, extra="priors" if req.exposure_priors else "") if not issues else None
        res = [self._assumption_result(p, None, pf) for p in plans]
        return LabPlan(ok=not issues, scenario_type=req.scenario_type, scenario_id=sid, issues=issues, assumptions=res, bounds=self.bounds()), plans

    # ------------------------------------------------------------------------------------------------------------------------------------ run
    def run(self, req: ScenarioRequest, portfolio: Portfolio | None = None) -> LabResult:
        pf = self._book(portfolio)
        if req.scenario_type is ScenarioType.ASSESSED:
            return self._assessed(req, portfolio, pf)
        plan, plans = self.plan(req, portfolio)
        if not plan.ok:
            raise LabInvalid(plan.issues)
        shocks = [s for p in plans for s in p.shocks]
        priors: list[PriorUse] = []
        used = pf
        if req.exposure_priors and any(s.factor is RiskFactor.COMMODITY_PCT for s in shocks):
            used, priors = apply_commodity_priors(pf, self.cfg.commodity_sector_priors)
        key = (plan.scenario_id, used.content_hash(), req.name)
        with self._lock:
            hit = self._memo.get(key)
            if hit is not None:
                self._memo.move_to_end(key)
                return hit
        name = req.name or ("Base (no shock)" if req.scenario_type is ScenarioType.BASE else "Custom scenario")
        run = self._stress.run_custom(scenario_id=plan.scenario_id or "scn_lab_x", name=name, shocks=shocks, portfolio=used)
        out = self._finish(req.scenario_type, name, plan.scenario_id or "", pf, used, run, plans, priors, shocks)
        with self._lock:
            self._memo[key] = out
            while len(self._memo) > _MEMO:
                self._memo.popitem(last=False)
        return out

    def _finish(self, kind: ScenarioType, name: str, sid: str, pf: Portfolio, used: Portfolio, run: StressResult, plans: list[Plan], priors: list[PriorUse],
                shocks: list[ShockSpec]) -> LabResult:
        completed = run.status is StressStatus.COMPLETED and run.summary is not None
        attribution: StressAttribution | None = None
        if completed:
            attribution = self._prop_svc().attribution(run, used, extra_factor_map={RiskFactor.FX_PCT: "FX", RiskFactor.COMMODITY_PCT: "OIL_ENERGY"})
        results = [self._assumption_result(p, run, used) for p in plans]
        reason = run.reason
        if completed is False and reason is None:
            reason = "the scenario could not be applied"
        prov = [ProvenanceRef(kind=ObservationKind.SCENARIO_ASSUMPTION, source="scenario_lab.assumption", ref_id=f"{sid}#{r.index}", as_of=self._clock()) for r in results]
        prov += [ProvenanceRef(kind=ObservationKind.SCENARIO_ASSUMPTION, source="scenario_lab.exposure_prior", ref_id=p.sector, as_of=self._clock()) for p in priors]
        prov.append(ProvenanceRef(kind=ObservationKind.PRODUCT_RULE, source="stress.engine", ref_id=run.run_id, as_of=self._clock()))
        return LabResult(
            scenario_id=sid, scenario_type=kind, name=name, created_at=self._clock(), portfolio_id=pf.portfolio_id, portfolio_name=pf.name,
            status="COMPLETED" if completed else "NOT_APPLICABLE", reason=None if completed else reason, assumptions=results, result=run if completed else None,
            attribution=attribution, exposure_priors=priors, history_check=self._history_check(sid, shocks) if shocks else None, provenance=prov,
            labels=LABELS, limitations=LIMITATIONS)

    def _history_check(self, sid: str, shocks: list[ShockSpec]):  # noqa: ANN202
        h = self._history()
        if h is None:
            return None
        carrier = Scenario(id=sid, version=VERSION, name="scenario lab", category=EventCategory.MARKET_VALUATION, description="a user-built scenario", shocks=shocks)  # the category is only a carrier
        return h.check_scenario(carrier)

    # --------------------------------------------------------------------------------------------------------------------- per-assumption reach
    @staticmethod
    def _assumption_result(p: Plan, run: StressResult | None, pf: Portfolio) -> AssumptionResult:
        reached: set[str] = set()
        pnl = 0.0
        value = 0.0
        if run is not None:
            for pos in run.positions:
                took = False
                for ps in pos.shocks:
                    for s in p.shocks:
                        # a position "takes" a shock only if the engine actually revalued it by that factor (a chosen shock a bond has no sensitivity to is not a reach)
                        if (ps.factor, ps.scope, ps.sector, ps.currency, ps.entity_id) == (s.factor, s.scope, s.sector, s.currency, s.entity_id) and s.factor in pos.by_factor:
                            pnl += pos.by_factor[s.factor]
                            took = True
                if took and pos.asset_id not in reached:
                    reached.add(pos.asset_id)
                    value += pos.baseline_value
        total = pf.total_value or 1.0
        a = p.assumption
        note = None
        if run is not None and not reached:
            note = {AssumptionKind.FX: "no position is held in this currency, so nothing moves", AssumptionKind.COMMODITY: "no position has an oil elasticity: switch on the sector-prior estimate to include one",
                    AssumptionKind.ISSUER: "the portfolio holds no position in this issuer", AssumptionKind.SECTOR: "the portfolio holds nothing in this sector"}.get(a.kind, "no position carries the exposure this shock acts on")
        return AssumptionResult(
            index=p.index, origin="USER", kind=a.kind.value, description=p.description, value=a.value, unit=p.unit, target=a.target, target_label=p.target_label, rationale=a.rationale,
            shocks=resolved_shocks(p), reach="APPLIED" if reached else ("NOT_REACHED" if run is not None else "APPLIED"), positions_reached=len(reached), value_reached=value,
            share_reached=value / total, pnl=pnl if run is not None else None, note=note)

    # ----------------------------------------------------------------------------------------------------------------------------- assessed
    def _assessed(self, req: ScenarioRequest, portfolio: Portfolio | None, pf: Portfolio) -> LabResult:
        if not req.signal_id:
            raise LabInvalid([LabIssue(index=None, field="signal_id", message="an ASSESSED scenario names the signal whose scenario to run")])
        sig = self._signals.get(req.signal_id)
        if sig is None:
            raise LookupError(f"signal {req.signal_id!r} not found")
        prop = self._prop_svc()
        res = prop.portfolio_stress(sig, portfolio, force=req.force, store=False)
        gen = res.scenario
        name = req.name or (gen.scenario.name if gen.scenario else "Assessed scenario")
        base = dict(scenario_type=ScenarioType.ASSESSED, name=name, created_at=self._clock(), portfolio_id=pf.portfolio_id, portfolio_name=pf.name, labels=LABELS, limitations=LIMITATIONS)
        if res.run is None or res.run.summary is None:
            return LabResult(scenario_id=gen.scenario.id if gen.scenario else f"scn_assessed_{sig.id}", status="UNAVAILABLE", reason=res.note or gen.reason or "no defensible scenario for this event",
                             assumptions=[], result=None, attribution=None, provenance=[ProvenanceRef(kind=ObservationKind.EVENTSHOCK_ASSESSMENT, source="propagation.scenario", ref_id=sig.id,
                                                                                                   as_of=self._clock())], **base)
        run = res.run
        results = []
        for i, sh in enumerate(run.shocks):
            unit = {"%": "fraction", "bp": "bp", "x": "multiplier", "pp": "fraction"}[FACTOR_UNITS[sh.factor]]
            where = f"{sh.scope.value.lower()}{f' ({sh.sector})' if sh.sector else ''}"
            results.append(AssumptionResult(
                index=i, origin="ASSESSED", kind="ASSESSED_SHOCK", description=f"{sh.factor.value.replace('_', ' ').title()} {fmt(sh.scaled_value, unit)}, {where}", value=sh.scaled_value, unit=unit,
                target=sh.sector, target_label=sh.sector, rationale=sh.rationale,
                shocks=[ResolvedShock(factor=sh.factor.value, scope=sh.scope.value, sector=sh.sector, currency=sh.currency, entity_id=sh.entity_id, value=sh.scaled_value, unit=unit,
                                      basis="EventShock's configured scenario for this event (severity-scaled): an assumption, not yours")],
                reach="APPLIED" if sh.applicable else "NOT_REACHED", positions_reached=0, value_reached=0.0, share_reached=0.0, pnl=None,
                note=None if sh.applicable else sh.not_applicable_reason))
        prov = [ProvenanceRef(kind=ObservationKind.SCENARIO_ASSUMPTION, source="propagation.generated_scenario", ref_id=gen.scenario.id if gen.scenario else None, as_of=self._clock()),
                ProvenanceRef(kind=ObservationKind.EVENTSHOCK_ASSESSMENT, source="assessment.severity", ref_id=sig.id, as_of=self._clock()),
                ProvenanceRef(kind=ObservationKind.PRODUCT_RULE, source="stress.engine", ref_id=run.run_id, as_of=self._clock())]
        return LabResult(scenario_id=run.scenario.id if run.scenario else run.run_id, status="COMPLETED", reason=None, assumptions=results, result=run, attribution=res.attribution,
                         provenance=prov, history_check=gen.history_check, **base)

    # --------------------------------------------------------------------------------------------------------------------------- reverse stress
    def reverse(self, req: ReverseStressRequest, portfolio: Portfolio | None = None) -> ReverseStressResult:
        cfg = self.reverse_cfg
        pf = self._book(portfolio)
        if not cfg.min_target_pct <= req.target_pct < 0:
            raise LabInvalid([LabIssue(index=None, field="target_pct", message=f"the target must be a loss between {cfg.min_target_pct:g}% and 0%")])
        axes, missing = build_axes(cfg, pf, req.factors)
        if missing:
            raise LabInvalid([LabIssue(index=None, field="factors", message=f"unknown axis {m!r}: choose from {', '.join(a.id for a in build_axes(cfg, pf, None)[0])}") for m in missing])
        if not axes:
            raise LabInvalid([LabIssue(index=None, field="factors", message="no axis left to search")])
        used, priors = (apply_commodity_priors(pf, self.cfg.commodity_sector_priors) if req.exposure_priors else (pf, []))
        search = ReverseSearch(cfg, self._stress.quick_pnl, used)
        try:
            found = search.search(axes, req.target_pct)
        except Budget as exc:
            raise LabInvalid([LabIssue(index=None, field="target_pct", message=f"{exc}: nothing was returned rather than an unfinished answer")]) from exc
        rid = reverse_id(pf, req.target_pct, req, cfg)
        bounds = [AxisBound(axis=a.id, label=a.label, unit=a.unit, bound=a.bound, direction="ADVERSE_DOWN" if found.signs[a.id] < 0 else "ADVERSE_UP", efficiency=found.efficiency[a.id] * 100.0,
                            used=a in found.kept and found.levels.get(a.id, 0.0) > 0, note=found.notes.get(a.id)) for a in axes]
        base = dict(
            reverse_id=rid, portfolio_id=pf.portfolio_id, portfolio_name=pf.name, target_pct=req.target_pct, bounds=bounds, search_method=METHOD, evaluations=found.evaluations,
            exposure_priors=priors, search_config={"objective": OBJECTIVE, "grid_levels": cfg.grid_levels, "max_axes": cfg.max_axes, "probe_fraction": cfg.probe_fraction, "tolerance_pp": cfg.tolerance_pp,
                                                      "max_evaluations": cfg.max_evaluations, "basket": [a.id for a in axes], "axes_kept": [a.id for a in found.kept]},
            assumptions=["Every shock found is a SCENARIO ASSUMPTION: a hypothetical, chosen by the search within the configured bounds.",
                         "The basket and its bounds are configured judgement priors (configs/decision.yaml), not fitted.",
                         *(["Oil exposure for positions with no measured elasticity was estimated from sector priors (a judgement prior you switched on)."] if priors else [])],
            labels=["Hypothetical stress analysis under the stated bounds: not a prediction of future losses.", *[]], limitations=REVERSE_LIMITATIONS)
        if found.status == "NO_EXPOSURE":
            return ReverseStressResult(status="NO_EXPOSURE", achieved_pct=None, difference_pp=None, achieved_pnl=None, baseline_value=None, required_shocks=[], dominant_drivers=[],
                                       affected_holdings=[], affected_sectors=[], affected_risk_factors=[], binding_bounds=[], scenario=None, open_in_lab=None, **base)
        assum = assumptions_for(found.kept, found.signs, found.levels)
        lab_req = ScenarioRequest(scenario_type=ScenarioType.CUSTOM, name=f"Reverse stress {req.target_pct:g}%", assumptions=assum, exposure_priors=req.exposure_priors, portfolio_id=req.portfolio_id)
        run = self.run(lab_req, portfolio)
        s = run.result.summary if run.result and run.result.summary else None
        achieved = s.pnl_pct * 100.0 if s else None
        att = run.attribution

        def top(dim: str, n: int = 3) -> list[str]:
            t = next((t for t in att.tables if t.dimension == dim), None) if att else None
            return [r.label for r in (t.rows if t else [])[:n]]
        by_axis = {a.id: a for a in found.kept}
        req_shocks = []
        for a, asm in zip([x for x in found.kept if found.levels.get(x.id, 0) > 0 and _q_nonzero(x, found)], assum, strict=False):
            req_shocks.append(RequiredShock(axis=a.id, label=a.label, kind=asm.kind, target=a.target, value=asm.value, unit=a.unit, bound=a.bound, share_of_bound=abs(asm.value) / a.bound))
        binding = [a.id for a in by_axis.values() if found.levels.get(a.id, 0.0) >= 1.0 - 1e-9] if found.status == "NOT_ACHIEVABLE" else []
        driver_names = [r.label for r in (att.drivers.rows if att else [])[:3]] + top("market_factor", 2)
        return ReverseStressResult(
            status=found.status, achieved_pct=achieved, difference_pp=(achieved - req.target_pct) if achieved is not None else None, achieved_pnl=s.pnl if s else None,
            baseline_value=s.baseline_value if s else None, required_shocks=req_shocks, dominant_drivers=list(dict.fromkeys(driver_names)), affected_holdings=top("position", 5),
            affected_sectors=top("sector"), affected_risk_factors=top("risk_factor"), binding_bounds=binding, scenario=run,
            open_in_lab=lab_req.model_copy(update={"name": f"Reverse stress {req.target_pct:g}%"}), **base)

    # --------------------------------------------------------------------------------------------------------------------------------- compare
    def compare(self, reqs: list[ScenarioRequest], portfolio: Portfolio | None = None) -> Comparison:
        pf = self._book(portfolio)
        if not 2 <= len(reqs) <= self.cfg.max_compared:
            raise LabInvalid([LabIssue(index=None, field="scenarios", message=f"compare between 2 and {self.cfg.max_compared} scenarios")])
        results = [self.run(r, portfolio) for r in reqs]
        rows = [self._row(r) for r in results]
        done = [r for r in rows if r.pnl is not None]
        worst = min(done, key=lambda r: (r.pnl, r.scenario_id)).scenario_id if done else None
        return Comparison(portfolio_id=pf.portfolio_id, portfolio_name=pf.name, results=results, rows=rows, assumption_diff=self._diff(results), worst_scenario_id=worst)

    @staticmethod
    def _row(r: LabResult) -> ComparisonRow:
        s = r.result.summary if r.result and r.result.summary else None
        att = r.attribution

        def top(dim: str, n: int = 3) -> list[str]:
            if att is None:
                return []
            t = next((t for t in att.tables if t.dimension == dim), None)
            return [row.label for row in (t.rows if t else [])[:n]]
        driver = att.drivers.rows[0].label if att and att.drivers.rows else None
        return ComparisonRow(scenario_id=r.scenario_id, name=r.name, scenario_type=r.scenario_type, status=r.status, baseline_value=s.baseline_value if s else None,
                             stressed_value=s.stressed_value if s else None, pnl=s.pnl if s else None, pnl_pct=s.pnl_pct if s else None, dominant_driver=driver,
                             top_sectors=top("sector"), top_risk_factors=top("risk_factor"), top_holdings=top("position"), assumption_count=len(r.assumptions))

    @staticmethod
    def _diff(results: list[LabResult]) -> list[AssumptionDiffRow]:
        keys: dict[str, str] = {}
        table: dict[str, dict[int, str]] = {}
        for n, r in enumerate(results):
            for a in r.assumptions:
                key = f"{a.kind}|{a.target or ''}|{a.origin}"
                keys.setdefault(key, f"{a.kind.replace('_', ' ').title()}{f' · {a.target_label or a.target}' if (a.target_label or a.target) else ''}")
                table.setdefault(key, {})[n] = fmt(a.value, a.unit)
        out = []
        for key in sorted(keys):
            vals = [table[key].get(n) for n in range(len(results))]
            out.append(AssumptionDiffRow(key=key, label=keys[key], values=vals, differs=len(set(vals)) > 1))
        return out



def _q_nonzero(a: Axis, found) -> bool:  # noqa: ANN001
    """An axis whose scaled shock rounds to zero on the engine's value grid is not part of the answer."""
    from .reverse import _q
    return _q(found.signs[a.id] * found.levels.get(a.id, 0.0) * a.bound, a.unit) != 0
