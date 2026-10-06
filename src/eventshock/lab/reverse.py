"""Reverse stress: "what would it take to lose X%?", answered by a bounded, deterministic search over a fixed basket of shocks. Every candidate is valued by the unchanged stress
engine (``StressService.quick_pnl``); the combination that is finally reported is re-run in full (``LabService.run``), so the loss shown is a complete engine run, not an estimate.

Method (BOUNDED_GRID_MINIMAX), also described in ``configs/decision.yaml``:
1. probe every basket axis alone at ``probe_fraction`` of its bound in its adverse direction; an axis that reaches nothing, or only gains, is dropped (and said so);
2. keep the ``max_axes`` most efficient axes (loss per unit of bound);
3. evaluate every grid point of ``(grid_levels + 1) ** axes`` levels, from 0 to 100% of each bound;
4. among the points whose loss reaches the target, take the one whose most extreme shock is the smallest share of its own bound (so the loss is spread across the basket rather than
   piled on one axis), then the smaller total share, then the basket order;
5. scale that combination by a common factor (bisection) until the engine's loss equals the target within tolerance.
If every kept axis at 100% of its bound still falls short, the target is NOT_ACHIEVABLE and the largest loss the bounds allow is returned with the axes that were already at their limit.
Nothing is random; the same book and target always give the same answer. The bounds are limits of the search, not predictions.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field

from ..decision.config import ReverseCfg
from ..domain import Portfolio, RiskFactor, ShockScope, ShockSpec
from .build import fmt
from .models import Assumption, AssumptionKind, ReverseStressRequest

METHOD = "BOUNDED_GRID_MINIMAX"
OBJECTIVE = "reach the target with the smallest largest share of any bound, then the smallest total share, then the basket order"
LIMITATIONS = [
    "The basket and its bounds are configured judgement: they limit what the search may try, not what can happen. A different basket gives a different combination.",
    "Many combinations reach the same loss; this reports the one that spreads the shocks across the basket most evenly. It is not the most likely and not the only one.",
    "The engine is first-order and every shock is instantaneous; a combination that reaches the loss here is not a forecast that it will.",
]


@dataclass(frozen=True)
class Axis:
    id: str
    label: str
    kind: AssumptionKind
    target: str | None
    sign: int            # +1 / -1: the direction of the shock; 0 = decided by the probe
    bound: float
    unit: str
    order: int


class Budget(Exception):
    pass


def _q(value: float, unit: str) -> float:
    """The value grid the engine is asked about: 0.01% for fractions, 0.1 bp for basis points. Searching on it keeps the reported combination exactly the one that was valued."""
    return round(value, 4) if unit == "fraction" else round(value, 1)


def _specs(axes: list[Axis], signs: dict[str, int], levels: dict[str, float]) -> list[ShockSpec]:
    out: list[ShockSpec] = []
    for a in axes:
        lv = levels.get(a.id, 0.0)
        if lv <= 0:
            continue
        v = _q(signs[a.id] * lv * a.bound, a.unit)
        if v == 0:
            continue
        if a.kind is AssumptionKind.EQUITY_MARKET:
            out.append(ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.MARKET, value=v))
        elif a.kind is AssumptionKind.CREDIT_SPREAD:
            out.append(ShockSpec(factor=RiskFactor.CREDIT_SPREAD_BPS, scope=ShockScope.MARKET, value=v))
        elif a.kind is AssumptionKind.RATES:
            out.append(ShockSpec(factor=RiskFactor.RATES_BPS, scope=ShockScope.MARKET, value=v))
        elif a.kind is AssumptionKind.COMMODITY:
            out.append(ShockSpec(factor=RiskFactor.COMMODITY_PCT, scope=ShockScope.MARKET, value=v))
        else:
            out.append(ShockSpec(factor=RiskFactor.EQUITY, scope=ShockScope.SECTOR, sector=a.target, value=v))
    return out


def build_axes(cfg: ReverseCfg, portfolio: Portfolio, only: list[str] | None) -> tuple[list[Axis], list[str]]:
    """The basket for this portfolio (one SECTOR axis per held sector) and, when the caller asked for specific axes, the ids that matched nothing."""
    axes: list[Axis] = []
    held = sorted({a.sector for a in portfolio.assets if a.sector not in ("Cash", "Other") and a.asset_type.value in ("EQUITY", "DERIVATIVE")})
    for b in cfg.basket:
        sign = 0 if b.sign == "auto" else int(b.sign)
        if b.kind == "SECTOR_EACH":
            for sec in held:
                axes.append(Axis(id=f"{b.id}:{sec}", label=f"{sec} equities", kind=AssumptionKind.SECTOR, target=sec, sign=sign, bound=b.bound, unit=b.unit, order=len(axes)))
        else:
            kind = AssumptionKind[b.kind]
            label = {"EQUITY_MARKET": "Equity market", "CREDIT_SPREAD": "Credit spreads", "RATES": "Interest rates", "COMMODITY": "Oil price"}[b.kind]
            axes.append(Axis(id=b.id, label=label, kind=kind, target=None, sign=sign, bound=b.bound, unit=b.unit, order=len(axes)))
    missing: list[str] = []
    if only:
        wanted = {w.strip().lower() for w in only}
        known = {a.id.lower(): a for a in axes}
        known.update({a.target.lower(): a for a in axes if a.target})
        missing = sorted(w for w in wanted if w not in known)
        keep = {known[w].id for w in wanted if w in known}
        axes = [a for a in axes if a.id in keep]
    return axes, missing


@dataclass
class Found:
    status: str                                   # ACHIEVABLE | NOT_ACHIEVABLE | NO_EXPOSURE
    signs: dict[str, int]
    efficiency: dict[str, float]                  # loss as a fraction of the book per 100% of an axis's bound (linear estimate from the probe)
    notes: dict[str, str]
    kept: list[Axis]
    levels: dict[str, float] = field(default_factory=dict)   # share of each kept axis's bound the answer uses
    max_loss: float | None = None                  # loss with every kept axis at 100% of its bound
    evaluations: int = 0


class ReverseSearch:
    def __init__(self, cfg: ReverseCfg, quick_pnl: Callable[[list[ShockSpec], Portfolio], tuple[float, float]], book: Portfolio) -> None:
        self.cfg, self._quick, self.book = cfg, quick_pnl, book
        self.evals = 0

    def _loss(self, specs: list[ShockSpec]) -> float:
        """Loss as a fraction of the book (negative = a loss) for these shocks, valued by the engine."""
        self.evals += 1
        if self.evals > self.cfg.max_evaluations:
            raise Budget("the search used its whole evaluation budget")
        pnl, base = self._quick(specs, self.book)
        return pnl / base if base else 0.0

    def search(self, axes: list[Axis], target_pct: float) -> Found:
        cfg = self.cfg
        target = target_pct / 100.0
        signs: dict[str, int] = {}
        eff: dict[str, float] = {}
        notes: dict[str, str] = {}
        # 1. probe each axis alone, in its adverse direction
        for a in axes:
            best: tuple[int, float] | None = None
            for sg in ([a.sign] if a.sign else [-1, 1]):
                loss = self._loss(_specs([a], {a.id: sg}, {a.id: cfg.probe_fraction}))
                if best is None or loss < best[1]:
                    best = (sg, loss)
            assert best is not None
            signs[a.id] = best[0]
            if best[1] >= -1e-12:
                eff[a.id] = 0.0
                notes[a.id] = "reaches nothing, or only gains, in its adverse direction: not used"
            else:
                eff[a.id] = best[1] / cfg.probe_fraction
        # 2. keep the axes that add the most loss on top of the ones already kept (a sector shock replaces the market shock inside its sector, so an axis can look efficient alone and add
        #    nothing beside another: marginal loss, not stand-alone loss, decides)
        pool = sorted((a for a in axes if eff[a.id] < 0), key=lambda a: (eff[a.id], a.order))
        kept: list[Axis] = []
        probe = {}
        while pool and len(kept) < cfg.max_axes:
            base_loss = self._loss(_specs(kept, signs, probe)) if kept else 0.0
            scored = []
            for a in pool:
                loss = self._loss(_specs([*kept, a], signs, {**probe, a.id: cfg.probe_fraction}))
                scored.append((loss - base_loss, eff[a.id], a.order, a))
            scored.sort(key=lambda t: (t[0], t[1], t[2]))
            gain, _, _, pick = scored[0]
            if gain >= -1e-12:
                break
            kept.append(pick)
            probe[pick.id] = cfg.probe_fraction
            pool.remove(pick)
        for a in pool:
            notes[a.id] = f"adds nothing, or little, on top of the axes kept (or fewer than {cfg.max_axes} axes were needed)"
        found = Found(status="NO_EXPOSURE", signs=signs, efficiency=eff, notes=notes, kept=kept)
        if not kept:
            found.evaluations = self.evals
            return found
        ids = [a.id for a in kept]
        found.max_loss = self._loss(_specs(kept, signs, {i: 1.0 for i in ids}))
        if found.max_loss > target:                                    # even every kept axis at its bound falls short
            found.status, found.levels, found.evaluations = "NOT_ACHIEVABLE", {i: 1.0 for i in ids}, self.evals
            return found
        # 3-4. grid over the kept axes; the point whose largest share of a bound is smallest once scaled to the target wins
        grid = [i / cfg.grid_levels for i in range(cfg.grid_levels + 1)]
        best_lv: tuple[float, ...] | None = None
        best_key: tuple | None = None
        for lv in itertools.product(grid, repeat=len(kept)):
            if not any(lv):
                continue
            loss = self._loss(_specs(kept, signs, dict(zip(ids, lv, strict=True))))
            if loss > target:
                continue                                              # does not reach the target
            lam = target / loss                                       # the scale at which this mix would just reach it (a linear estimate; step 5 corrects it)
            key = (round(lam * max(lv), 9), round(lam * sum(lv), 9), tuple(-x for x in lv))
            if best_key is None or key < best_key:
                best_key, best_lv = key, lv
        assert best_lv is not None                                    # the all-at-bound point reached the target, so at least one candidate did
        base = dict(zip(ids, best_lv, strict=True))
        # 5. scale the combination until the engine's loss equals the target
        lo, hi = 0.0, 1.0
        for _ in range(50):
            mid = (lo + hi) / 2
            loss = self._loss(_specs(kept, signs, {k: v * mid for k, v in base.items()}))
            if loss > target:
                lo = mid                                               # not enough loss yet
            else:
                hi = mid
                if abs(loss - target) * 100.0 <= cfg.tolerance_pp / 4:
                    break
        found.status, found.levels, found.evaluations = "ACHIEVABLE", {k: v * hi for k, v in base.items()}, self.evals
        return found


def describe(a: Axis, value: float) -> str:
    return f"{a.label} {fmt(value, a.unit)}"


def assumptions_for(axes: list[Axis], signs: dict[str, int], levels: dict[str, float]) -> list[Assumption]:
    out = []
    for a in axes:
        lv = levels.get(a.id, 0.0)
        v = _q(signs[a.id] * lv * a.bound, a.unit)
        if lv > 0 and v != 0:
            out.append(Assumption(kind=a.kind, value=v, target=a.target, rationale=f"found by reverse stress ({lv * 100:.0f}% of this axis's limit)"))
    return out


def reverse_id(pf: Portfolio, target_pct: float, req: ReverseStressRequest, cfg: ReverseCfg) -> str:
    raw = f"{pf.content_hash()}|{target_pct:.6f}|{sorted(req.factors or [])}|{req.exposure_priors}|{METHOD}|{cfg.grid_levels}|{cfg.max_axes}|{[(b.id, b.sign, b.bound) for b in cfg.basket]}"
    return "rev_" + hashlib.sha256(raw.encode()).hexdigest()[:12]
