"""A cycle read as a rebalance proposal: for every stock the weight before, the target and the weight after, the trade, the reports behind it and the rule that held it back.

Everything here is read off the cycle the service already computed; nothing is re-derived and nothing is scored. The sentence on each card is a template whose clauses are each backed
by a field of the same record (no model writes it), the same stance as the executive brief.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from .models import (
    LABELS,
    VERSION,
    ConstraintCode,
    EvidenceQuality,
    RebalanceDecisions,
    RebalancerParams,
    ScoreDriver,
    TradeDecision,
    TradeSide,
    WeightReason,
)

RULE_TEXT = {
    ConstraintCode.UPPER_BOUND: "the per-stock upper bound",
    ConstraintCode.LOWER_BOUND: "the per-stock lower bound",
    ConstraintCode.SECTOR_CAP: "the sector cap",
    ConstraintCode.VOL_LIMIT: "the volatility-aware limit",
    ConstraintCode.LIQUIDITY_FLOOR: "the liquidity floor",
    ConstraintCode.TURNOVER_CAP: "the turnover cap",
    ConstraintCode.MIN_TRADE: "the minimum trade size",
}


def proposal_digest(strategy: str, params: RebalancerParams, include_live: bool, index: int, at: datetime, tickers: list[str], before: list[float], target: list[float],
                    after: list[float]) -> str:
    payload = {"strategy": strategy, "p": [params.tilt, params.half_life_hours, params.max_turnover], "live": include_live, "i": index, "at": at.astimezone(UTC).isoformat(),
               "t": tickers, "b": [round(x, 12) for x in before], "g": [round(x, 12) for x in target], "a": [round(x, 12) for x in after]}
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _pp(x: float) -> str:
    return f"{x * 100:+.2f} pp"


def _age(h: float) -> str:
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.1f} days"


def explain(d: TradeDecision, half_life_hours: float) -> str:
    """One deterministic paragraph for a card. Nothing is said that the record does not hold."""
    parts = []
    if d.side is TradeSide.HOLD:
        parts.append(f"No trade in {d.ticker}: it stays at {_pct(d.after)}.")
    else:
        verb = "Buy" if d.side is TradeSide.BUY else "Sell"
        parts.append(f"{verb} {d.ticker} {_pp(d.trade)} ({_pct(d.before)} to {_pct(d.after)}).")
    if d.reports == 0:
        parts.append("No report about it is inside the evidence window, so sentiment does not move it.")
    else:
        lean = "positive" if d.score > 0.02 else "negative" if d.score < -0.02 else "about neutral"
        parts.append(f"Its sentiment score is {d.score:+.2f} ({lean}), from {d.reports} report{'s' if d.reports != 1 else ''} across {d.sources} source{'s' if d.sources != 1 else ''}; "
                     f"the newest is {_age(d.newest_age_hours or 0.0)} old and a report's weight halves every {half_life_hours:g} h.")
    if abs(d.target - d.after) > 5e-4:
        parts.append(f"The rule asked for {_pct(d.target)}; {_pct(d.after)} was reached.")
    held = [b for b in d.binding if b.code not in (ConstraintCode.TURNOVER_CAP, ConstraintCode.MIN_TRADE)]
    if held:
        parts.append("It was held by " + ", ".join(RULE_TEXT[b.code] + f" ({_pp(b.effect)})" for b in held) + ".")
    for b in d.binding:
        if b.code is ConstraintCode.TURNOVER_CAP:
            parts.append(f"The turnover cap shortened the move by {_pp(abs(b.effect))}.")
        elif b.code is ConstraintCode.MIN_TRADE:
            parts.append("The whole rebalance was below the minimum trade size, so nothing was traded.")
    flags = []
    if d.evidence_quality is EvidenceQuality.THIN:
        flags.append("the evidence is thin")
    if d.stale:
        flags.append("the newest report is stale")
    if d.conflicting:
        flags.append(f"the reports disagree ({d.positive_share * 100:.0f}% positive, {d.negative_share * 100:.0f}% negative)")
    if d.liquidity_flag:
        flags.append("the trade is large against its average daily volume")
    if flags:
        parts.append("Caution: " + "; ".join(flags) + ".")
    return " ".join(parts)


def build(svc, index: int, params: RebalancerParams, include_live: bool, strategy: str | None) -> RebalanceDecisions:  # noqa: ANN001
    """The proposal for one cycle. Raises ``LookupError`` for a cycle that does not exist and ``ValueError`` for an unknown strategy."""
    sid = svc.resolve_strategy(strategy)
    cycles = svc.run_cycles(params, include_live, sid)
    if not 0 <= index < len(cycles):
        raise LookupError(f"cycle {index} does not exist (0..{len(cycles) - 1})" if cycles else "there are no cycles: no company report is available")
    cfg = svc.cfg
    c = cycles[index]
    before_v = cycles[index - 1].weights if index else svc.bench
    detail = svc.cycle(index, params, include_live, sid)
    by_name = {n.ticker: n for n in detail.names}
    cons = {x.ticker: x for x in svc.constituents(sid)}
    eps = cfg.display.active_epsilon
    aum = cfg.risk.liquidity.mock_aum_usd
    out: list[TradeDecision] = []
    for j, t in enumerate(svc.tickers):
        n, sc = by_name[t], c.scores[j]
        trade = c.weights[j] - before_v[j]
        side = TradeSide.HOLD if abs(trade) <= eps else TradeSide.BUY if trade > 0 else TradeSide.SELL
        notional = abs(trade) * aum
        adv = svc.adv_usd(t)
        participation = notional / adv if adv else None
        pos = sum(k.contribution for k in sc.contributions if k.contribution > 0)
        neg = -sum(k.contribution for k in sc.contributions if k.contribution < 0)
        mass = pos + neg
        pshare, nshare = (pos / mass, neg / mass) if mass > 0 else (0.0, 0.0)
        quality = EvidenceQuality.NONE if sc.reports == 0 else EvidenceQuality.THIN if sc.evidence < cfg.explain.thin_evidence_below else EvidenceQuality.OK
        newest = min((k.age_hours for k in sc.contributions), default=None)
        wsum = sum(k.decayed_weight for k in sc.contributions)
        mean_age = sum(k.decayed_weight * k.age_hours for k in sc.contributions) / wsum if wsum > 0 else None
        drivers = [ScoreDriver(signal_id=k.report.signal_id, headline=k.report.headline, source=k.report.source, published_at=k.report.published_at, age_hours=k.age_hours,
                               sentiment=k.report.sentiment, decayed_weight=k.decayed_weight, contribution=k.contribution, url=k.report.url, multiplier=k.multiplier)
                   for k in sc.contributions[:cfg.display.top_drivers_per_name]]
        d = TradeDecision(
            ticker=t, name=cons[t].name, sector=cons[t].sector, side=side, before=before_v[j], target=c.target[j], after=c.weights[j], trade=trade, lower=cons[t].lower,
            upper=cons[t].upper, est_cost=abs(trade) * cfg.turnover.cost_bps / 1e4, notional_usd=notional, participation=participation,
            liquidity_flag=participation is not None and participation > cfg.risk.liquidity.max_participation, score=sc.value, evidence=sc.evidence, reports=sc.reports,
            sources=sc.sources, evidence_quality=quality, newest_age_hours=newest, mean_age_hours=mean_age,
            stale=newest is not None and newest > cfg.explain.stale_after_half_lives * params.half_life_hours,
            conflicting=mass > 0 and min(pshare, nshare) >= cfg.explain.conflict_min_share, positive_share=pshare, negative_share=nshare, reason=n.reason if isinstance(n.reason, WeightReason) else WeightReason(n.reason),
            binding=n.binding, drivers=drivers, explanation="")
        out.append(d.model_copy(update={"explanation": explain(d, params.half_life_hours)}))
    out.sort(key=lambda d: (-abs(d.trade), d.ticker))
    order = {t: i for i, t in enumerate(svc.tickers)}
    by_order = sorted(out, key=lambda d: order[d.ticker])
    digest = proposal_digest(sid, params, include_live, index, c.at, svc.tickers, [d.before for d in by_order], [d.target for d in by_order], [d.after for d in by_order])
    cost = sum(d.est_cost for d in out)
    return RebalanceDecisions(
        version=VERSION, strategy=sid, params=params, index=index, cycles=len(cycles), at=c.at, previous_at=cycles[index - 1].at if index else None, status=c.step_status,
        turnover=c.traded, wanted_turnover=c.wanted, buys=sum(1 for d in out if d.side is TradeSide.BUY), sells=sum(1 for d in out if d.side is TradeSide.SELL),
        holds=sum(1 for d in out if d.side is TradeSide.HOLD), est_cost=cost, est_cost_usd=cost * aum, proposal_sha256=digest, tickers=svc.tickers, decisions=out, labels=LABELS)
