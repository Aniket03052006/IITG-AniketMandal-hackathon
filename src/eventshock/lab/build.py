"""Assumptions -> engine shocks. A pure, validating translation: every size is checked against the configured bounds and every target against a vocabulary, so what reaches the
engine is something the engine can apply. Nothing here computes a loss.

A risk-factor shock either maps to the engine shock of that factor (rates, equity market, credit spread, oil, currency, default probability) or, for a proxy factor (inflation,
geopolitical), is spread over the sectors its transmission edges name: sector shock = size x edge weight, each edge a SCENARIO ASSUMPTION written down in the propagation config.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..decision.config import LabCfg
from ..domain import RiskFactor, ShockScope, ShockSpec
from ..propagation.config import PropagationConfig
from .models import Assumption, AssumptionKind, LabIssue, ResolvedShock

CCY = re.compile(r"^[A-Z]{3}$")
UNIT_TEXT = {"fraction": "", "bp": " bp", "multiplier": "x"}


@dataclass
class Plan:
    """One assumption, resolved."""

    index: int
    assumption: Assumption
    unit: str
    description: str
    target_label: str | None
    shocks: list[ShockSpec]
    bases: list[str]


@dataclass
class Vocab:
    base_currency: str
    sectors: dict[str, str]                 # lower-case -> name
    entities: dict[str, tuple[str, str]]    # lower-case entity id / ticker -> (entity id, display name)
    prop: PropagationConfig
    held_currencies: set[str] = field(default_factory=set)


def fmt(value: float, unit: str) -> str:
    if unit == "bp":
        return f"{'+' if value > 0 else '−' if value < 0 else ''}{abs(value):g} bp"
    if unit == "multiplier":
        return f"×{value:g}"
    return f"{'+' if value > 0 else '−' if value < 0 else ''}{abs(value) * 100:.1f}%"


def _bound(cfg: LabCfg, a: Assumption) -> tuple[float, float, str, str] | None:
    """(min, max, unit, kind) that governs this assumption."""
    if a.kind is AssumptionKind.RISK_FACTOR:
        rid = (a.target or "").split(":")[0]
        rf = cfg.risk_factors.get(rid)
        return None if rf is None else (rf.min, rf.max, rf.unit, rf.kind)
    b = cfg.bounds[a.kind.value]
    return b.min, b.max, b.unit, a.kind.value


def _spec(factor: RiskFactor, scope: ShockScope, value: float, rationale: str, **kw) -> ShockSpec:  # noqa: ANN003
    return ShockSpec(factor=factor, scope=scope, value=value, rationale=rationale, **kw)


def resolve(assumptions: list[Assumption], cfg: LabCfg, v: Vocab) -> tuple[list[Plan], list[LabIssue]]:
    issues: list[LabIssue] = []
    plans: list[Plan] = []
    if len(assumptions) > cfg.max_assumptions:
        issues.append(LabIssue(index=None, field="assumptions", message=f"a scenario holds at most {cfg.max_assumptions} assumptions"))
        assumptions = assumptions[: cfg.max_assumptions]
    for i, a in enumerate(assumptions):
        def bad(msg: str, field_: str = "value", i: int = i) -> None:
            issues.append(LabIssue(index=i, field=field_, message=msg))

        if not math.isfinite(a.value):
            bad("the size must be a finite number")
            continue
        b = _bound(cfg, a)
        if b is None:
            bad(f"unknown risk factor {a.target!r}: choose one of {', '.join(sorted(cfg.risk_factors))}", "target")
            continue
        lo, hi, unit, kind = b
        if not lo <= a.value <= hi:
            bad(f"{fmt(a.value, unit)} is outside the limits of this lab for {a.kind.value.replace('_', ' ').lower()}: {fmt(lo, unit)} to {fmt(hi, unit)}")
            continue
        text = a.kind.value.replace("_", " ").title()
        try:
            plan = _plan(i, a, kind, unit, text, cfg, v)
        except ValueError as exc:
            bad(str(exc), "target" if "target" in str(exc).lower() or "unknown" in str(exc).lower() else "value")
            continue
        plans.append(plan)
    # two assumptions must not set the same engine shock: one value per (factor, scope, sector, currency, issuer)
    seen: dict[tuple, int] = {}
    for p in plans:
        for s in p.shocks:
            key = (s.factor, s.scope, s.sector, s.currency, s.entity_id)
            if key in seen and seen[key] != p.index:
                issues.append(LabIssue(index=p.index, field="kind", message=f"assumption {seen[key] + 1} already sets {s.factor.value.replace('_', ' ').lower()}"
                                                                                   f"{f' for {s.sector or s.currency or s.entity_id}' if (s.sector or s.currency or s.entity_id) else ''}: one value per shock"))
            seen.setdefault(key, p.index)
    return plans, issues


def _plan(i: int, a: Assumption, kind: str, unit: str, text: str, cfg: LabCfg, v: Vocab) -> Plan:  # noqa: C901
    t = (a.target or "").strip()
    why = a.rationale or "chosen by the user"
    if a.kind is AssumptionKind.RISK_FACTOR:
        return _risk_factor(i, a, kind, unit, cfg, v)
    if a.kind is AssumptionKind.EQUITY_MARKET:
        return Plan(i, a, unit, f"Equity market {fmt(a.value, unit)}", None, [_spec(RiskFactor.EQUITY, ShockScope.MARKET, a.value, why)], ["a market-wide equity move reaches each equity at its beta"])
    if a.kind is AssumptionKind.RATES:
        return Plan(i, a, unit, f"Interest rates {fmt(a.value, unit)} (parallel)", None, [_spec(RiskFactor.RATES_BPS, ShockScope.MARKET, a.value, why)], ["reaches bonds through their duration"])
    if a.kind is AssumptionKind.CREDIT_SPREAD:
        if t:
            sector = v.sectors.get(t.lower())
            if sector is None:
                raise ValueError(f"unknown sector {t!r} (target): choose one of {', '.join(sorted(v.sectors.values()))}")
            return Plan(i, a, unit, f"Credit spread {fmt(a.value, unit)} in {sector}", sector, [_spec(RiskFactor.CREDIT_SPREAD_BPS, ShockScope.SECTOR, a.value, why, sector=sector)],
                        ["reaches the corporate bonds of that sector through spread duration"])
        return Plan(i, a, unit, f"Credit spreads {fmt(a.value, unit)}", None, [_spec(RiskFactor.CREDIT_SPREAD_BPS, ShockScope.MARKET, a.value, why)], ["reaches corporate bonds through spread duration"])
    if a.kind is AssumptionKind.COMMODITY:
        return Plan(i, a, unit, f"Oil price {fmt(a.value, unit)}", None, [_spec(RiskFactor.COMMODITY_PCT, ShockScope.MARKET, a.value, why)],
                    ["reaches only positions with an oil elasticity (a measured one, or a sector prior you switched on)"])
    if a.kind is AssumptionKind.FX:
        ccy = t.upper()
        if not CCY.match(ccy):
            raise ValueError("target: name the currency that moves, as a three-letter code such as EUR")
        if ccy == v.base_currency:
            raise ValueError(f"target: {ccy} is the portfolio's base currency; a shock to it moves nothing against itself")
        return Plan(i, a, unit, f"{ccy} {fmt(a.value, unit)} against {v.base_currency}", ccy, [_spec(RiskFactor.FX_PCT, ShockScope.MARKET, a.value, why, currency=ccy)],
                    [f"reaches positions held in {ccy} one for one"])
    if a.kind is AssumptionKind.SECTOR:
        sector = v.sectors.get(t.lower())
        if sector is None:
            raise ValueError(f"unknown sector {t!r} (target): choose one of {', '.join(sorted(v.sectors.values()))}")
        return Plan(i, a, unit, f"{sector} equities {fmt(a.value, unit)}", sector, [_spec(RiskFactor.EQUITY, ShockScope.SECTOR, a.value, why, sector=sector)],
                    ["an idiosyncratic sector move: applied without a beta"])
    if a.kind is AssumptionKind.ISSUER:
        ent = v.entities.get(t.lower())
        if ent is None:
            raise ValueError(f"unknown issuer {t!r} (target): name an issuer in the entity master by id or ticker; free text is never turned into a company")
        return Plan(i, a, unit, f"{ent[1]} equity {fmt(a.value, unit)}", ent[1], [_spec(RiskFactor.EQUITY, ShockScope.ISSUER, a.value, why, entity_id=ent[0])],
                    ["an idiosyncratic issuer move: applied without a beta"])
    raise ValueError(f"unsupported assumption kind {a.kind}")


def _risk_factor(i: int, a: Assumption, kind: str, unit: str, cfg: LabCfg, v: Vocab) -> Plan:
    rid, _, arg = (a.target or "").partition(":")
    rf = v.prop.risk_factors.get(rid)
    label = rf.label if rf else rid
    why = a.rationale or f"a shock to {label.lower()}, chosen by the user"
    if kind == "PROXY":
        edges = [(eid, e) for eid, e in (rf.transmission.items() if rf else []) if e.enabled and e.shock and e.kind == "SECTOR" and e.weight != 0]
        if not edges:
            raise ValueError(f"target: {label} has no sector transmission edge, so a shock to it reaches nothing")
        shocks, bases = [], []
        for eid, e in edges:
            val = max(-1.0, min(1.0, round(a.value * e.weight, 6)))
            shocks.append(_spec(RiskFactor.EQUITY, ShockScope.SECTOR, val, f"{why}; transmission edge {eid} (weight {e.weight:+.2f}): {e.rationale}", sector=e.key))
            bases.append(f"{e.key}: size × edge weight {e.weight:+.2f} = {fmt(val, unit)} (edge {eid}, an assumption)")
        return Plan(i, a, unit, f"{label} {fmt(a.value, unit)} (spread over {', '.join(e.key for _, e in edges)})", label, shocks, bases)
    if kind == "FX":
        ccy = arg.upper()
        if not CCY.match(ccy):
            raise ValueError("target: an FX risk factor names its currency, e.g. FX:EUR")
        if ccy == v.base_currency:
            raise ValueError(f"target: {ccy} is the portfolio's base currency")
        return Plan(i, a, unit, f"{ccy} {fmt(a.value, unit)} against {v.base_currency}", ccy, [_spec(RiskFactor.FX_PCT, ShockScope.MARKET, a.value, why, currency=ccy)],
                    [f"risk factor {label}: reaches positions held in {ccy}"])
    engine = {"RATES": RiskFactor.RATES_BPS, "EQUITY_MARKET": RiskFactor.EQUITY, "CREDIT_SPREAD": RiskFactor.CREDIT_SPREAD_BPS, "COMMODITY": RiskFactor.COMMODITY_PCT,
              "PD_MULTIPLIER": RiskFactor.PD_MULTIPLIER}[kind]
    return Plan(i, a, unit, f"{label} {fmt(a.value, unit)}", label, [_spec(engine, ShockScope.MARKET, a.value, why)], [f"risk factor {label}: its engine shock"])


def resolved_shocks(plan: Plan) -> list[ResolvedShock]:
    return [ResolvedShock(factor=s.factor.value, scope=s.scope.value, sector=s.sector, currency=s.currency, entity_id=s.entity_id, value=s.value, unit=plan.unit,
                          basis=(plan.bases[i] if i < len(plan.bases) else plan.bases[-1]) if plan.bases else "the user's choice") for i, s in enumerate(plan.shocks)]
