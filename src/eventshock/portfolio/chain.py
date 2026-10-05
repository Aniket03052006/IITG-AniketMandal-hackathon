"""Why is my portfolio exposed? The event -> shock -> your exposure -> modeled change chain, read off a finished stress run.

Nothing here is computed afresh and nothing is generated: every step is a regrouping of the engine's own ``PositionResult`` rows (which shocks a
position took, and its per-factor change), plus the holdings' own beta and duration. The sentences are fixed templates filled with those numbers.
The outcome is a *modeled* scenario change, not a forecast; the scenario's shock sizes remain illustrative assumptions.
"""

from __future__ import annotations

from collections import defaultdict

from ..domain import (
    Portfolio,
    PortfolioAsset,
    RiskFactor,
    RiskSignal,
    ScopeLevel,
    StressResult,
    StressStatus,
)
from .models import ChainStep, ExposureChain, ExposureRowV2, SkippedShock

FACTOR_LABEL = {
    RiskFactor.EQUITY: "equity price shock", RiskFactor.RATES_BPS: "interest-rate shock", RiskFactor.CREDIT_SPREAD_BPS: "credit-spread shock",
    RiskFactor.PD_MULTIPLIER: "default-probability shock", RiskFactor.LGD_ADD: "loss-given-default shock",
}
SCOPE_LABEL = {"MARKET": "market-wide", "SECTOR": "sector", "ISSUER": "issuer"}
UNIT = {RiskFactor.EQUITY: "fraction", RiskFactor.RATES_BPS: "bp", RiskFactor.CREDIT_SPREAD_BPS: "bp", RiskFactor.PD_MULTIPLIER: "x", RiskFactor.LGD_ADD: "fraction"}
SYMBOL = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£", "JPY": "¥"}


def money(x: float, ccy: str, signed: bool = False) -> str:
    sym = SYMBOL.get(ccy, ccy + " ")
    sign = "-" if x < 0 else ("+" if signed and x > 0 else "")
    return f"{sign}{sym}{abs(x):,.0f}"


def shock_text(f: RiskFactor, v: float) -> str:
    if f in (RiskFactor.RATES_BPS, RiskFactor.CREDIT_SPREAD_BPS):
        return f"{v:+.0f} bp"
    if f is RiskFactor.PD_MULTIPLIER:
        return f"x{v:.2f}"
    return f"{100 * v:+.1f}%" if f is RiskFactor.EQUITY else f"{100 * v:+.1f} pp"


def _sensitivity(f: RiskFactor, scope: str, assets: list[PortfolioAsset]) -> str:
    value = sum(a.market_value for a in assets)
    if not assets or value <= 0:
        return "n/a"
    if f is RiskFactor.EQUITY:
        if scope == "MARKET":
            beta = sum(a.market_value * a.beta for a in assets) / value
            return f"value-weighted beta {beta:.2f}: a market move reaches these holdings at {beta:.2f} times"
        return "full pass-through (a sector or issuer shock is applied without a beta)"
    if f in (RiskFactor.RATES_BPS, RiskFactor.CREDIT_SPREAD_BPS):
        dur = sum(a.market_value * (a.duration or 0.0) for a in assets) / value
        if f is RiskFactor.CREDIT_SPREAD_BPS:
            sens = sum(a.market_value * a.spread_sensitivity for a in assets) / value
            return f"value-weighted duration {dur:.1f} years, credit-spread sensitivity {sens:.2f}"
        return f"value-weighted duration {dur:.1f} years: price change = -duration x yield change"
    return "expected-loss model (probability and loss given default)"


def _event_line(signal: RiskSignal) -> str:
    sc = signal.scope
    name = signal.entity.entity_name or signal.entity.entity_id
    if sc is None or sc.level is ScopeLevel.UNRESOLVED:
        return "Subject not identified: only market-wide shocks can apply"
    if sc.level is ScopeLevel.COMPANY:
        return f"Company event: {name}"
    if sc.level is ScopeLevel.SECTOR:
        return f"Sector event: {sc.sector}"
    themes = ", ".join(t.replace("_", " ") for t in sc.themes)
    return f"Market-wide event{f' ({themes})' if themes else ''}"


def build_exposure_chain(result: StressResult, portfolio: Portfolio, signal: RiskSignal) -> ExposureChain:
    if result.status is not StressStatus.COMPLETED or result.summary is None:
        raise ValueError("an exposure chain needs a completed stress run")
    ccy = portfolio.base_currency
    assets = {a.asset_id: a for a in portfolio.assets}
    base = result.summary.baseline_value
    # (factor, scope) -> positions that took that shock and responded to it
    groups: dict[tuple[RiskFactor, str], list] = defaultdict(list)
    for p in result.positions:
        for s in p.shocks:
            if s.factor in p.by_factor:
                groups[(s.factor, s.scope.value)].append(p)
    steps: list[ChainStep] = []
    skipped: list[SkippedShock] = []
    for sh in result.shocks:
        if not sh.applicable:
            skipped.append(SkippedShock(factor_label=FACTOR_LABEL[sh.factor], scope_label=SCOPE_LABEL[sh.scope.value], reason=sh.not_applicable_reason or "does not reach this event"))
            continue
        pos = groups.get((sh.factor, sh.scope.value), [])
        if not pos:
            continue
        exposed = sum(p.baseline_value for p in pos)
        impact = sum(p.by_factor[sh.factor] for p in pos)
        sens = _sensitivity(sh.factor, sh.scope.value, [assets[p.asset_id] for p in pos if p.asset_id in assets])
        n = len(pos)
        sentence = (f"{n} position{'s' if n != 1 else ''} ({exposed / base:.1%} of the portfolio, {money(exposed, ccy)}) take the {SCOPE_LABEL[sh.scope.value]} "
                    f"{FACTOR_LABEL[sh.factor]} of {shock_text(sh.factor, sh.scaled_value)}; {sens}. Modeled change: {money(impact, ccy, True)} ({impact / base:+.2%} of the portfolio).")
        steps.append(ChainStep(factor=sh.factor.value, factor_label=FACTOR_LABEL[sh.factor], scope=sh.scope.value, scope_label=SCOPE_LABEL[sh.scope.value],
                               applied_shock=sh.scaled_value, unit=UNIT[sh.factor], exposed_value=exposed, exposed_share=exposed / base if base else 0.0,
                               position_count=n, sensitivity=sens, impact=impact, impact_pct=impact / base if base else 0.0, sentence=sentence))
    steps.sort(key=lambda s: (s.impact, s.factor, s.scope))
    unmoved = [p for p in result.positions if p.delta == 0]
    not_reached = None
    if unmoved:
        v = sum(p.baseline_value for p in unmoved)
        not_reached = ExposureRowV2(key="unmoved", label="Holdings this scenario does not move (cash, unsupported instruments, or no shock reaches them)",
                                    market_value=v, share=v / base if base else 0.0, position_count=len(unmoved))

    sc = signal.scope
    held_note = ""
    if sc is not None and sc.level is ScopeLevel.COMPANY and not signal.entity.is_unknown:
        mine = [p for p in result.positions if p.entity_id == signal.entity.entity_id]
        name = signal.entity.entity_name or signal.entity.entity_id
        if mine:
            v, d = sum(p.baseline_value for p in mine), sum(p.delta for p in mine)
            held_note = (f"You hold {name}: {v / base:.1%} of the portfolio in {len(mine)} position{'s' if len(mine) != 1 else ''}; "
                         f"modeled change on those holdings {money(d, ccy, True)}. ")
        else:
            held_note = f"You do not hold {name}: only sector and market-wide shocks reach your portfolio. "
    elif sc is not None and sc.level is ScopeLevel.SECTOR:
        mine = [p for p in result.positions if p.sector == sc.sector]
        if mine:
            v, d = sum(p.baseline_value for p in mine), sum(p.delta for p in mine)
            held_note = f"{sc.sector} is {v / base:.1%} of your portfolio ({len(mine)} positions); modeled change on them {money(d, ccy, True)}. "
        else:
            held_note = f"You hold nothing in {sc.sector}: only market-wide shocks reach your portfolio. "
    pnl, pct = result.summary.pnl, result.summary.pnl_pct
    if not steps:
        summary = held_note + "None of your holdings responds to the shocks that apply, so the modeled change is zero."
    else:
        top = steps[0]
        summary = (held_note + f"The largest modeled effect is the {top.scope_label} {top.factor_label} ({shock_text(RiskFactor(top.factor), top.applied_shock)}) on "
                   f"{top.exposed_share:.1%} of your portfolio: {money(top.impact, ccy, True)}. Total modeled change {money(pnl, ccy, True)} ({pct:+.2%}).")
    return ExposureChain(
        run_id=result.run_id, portfolio_id=portfolio.portfolio_id, portfolio_name=portfolio.name, event_line=_event_line(signal),
        scope_level=sc.level.value if sc else "UNRESOLVED", steps=steps, skipped=skipped, not_reached=not_reached, total_impact=pnl, total_impact_pct=pct,
        summary=summary,
        note="A modeled scenario change under illustrative shock sizes, not a forecast. The severity that triggered the scenario is a transparent, uncalibrated score.")
