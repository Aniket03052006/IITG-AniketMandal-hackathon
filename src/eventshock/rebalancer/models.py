"""Contracts of the tactical index rebalancer (Module A). Everything here is *derived* from signals and is never stored on a ``RiskSignal``.

The vocabulary, kept apart on purpose: a **score** is how positively the engine's reports read about a company (a shrunk, decayed, source-capped mean of the
sentiment score, in (-1, 1)); a **target weight** is what the tilt rule asks for; the **weight** is what the turnover limit lets the index hold; **active** is the
weight minus the equal-weight benchmark. None of these is a forecast of a return.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from ..domain.base import ContractModel

VERSION = "rebalancer-v1"

LABELS = [
    "A mock index: weights follow a transparent rule (sentiment tilt, bounded, turnover-limited). It is not an alpha signal, a forecast or investment advice.",
    "Sentiment is the engine's own score (a TF-IDF / logistic model); tone, source reliability, severity and impact are not inputs, and none of it is validated against returns.",
    "Every parameter is a judgement prior written before any result was looked at (configs/rebalancer.yaml); the what-if controls change them for one request only.",
]
LIMITATIONS = [
    "The frozen replay covers 14 days, about ten trading sessions: far too few to say whether the rule earns anything. The backtest is an illustration of the mechanics.",
    "The benchmark is equal weight (the repo holds no market-cap data). Weights shown are target weights at each cycle; drift between cycles is not modelled.",
    "A company has only a handful of reports per day, so one report can move a score. Shrinkage, the one-source-one-vote cap and the turnover limit exist to damp that, not to remove it.",
    "Social posts carry a replay-assigned time, not a real one, so they are never placed on the timeline (they are counted).",
]


class WeightReason(StrEnum):
    """Why a stock holds the weight it holds at a cycle (first matching rule wins; this is the order the rules are tried in)."""

    AT_UPPER_BOUND = "AT_UPPER_BOUND"                   # its weight sits at the most the bounds allow (the tilt asked for at least that much)
    AT_LOWER_BOUND = "AT_LOWER_BOUND"                   # its weight sits at the least the bounds allow
    LIMITED_BY_TURNOVER = "LIMITED_BY_TURNOVER"         # the move toward the target was shortened to respect the turnover cap, so it is not there yet
    HELD_BELOW_MIN_TRADE = "HELD_BELOW_MIN_TRADE"       # the whole rebalance was too small to trade, so it is not at the target
    NO_EVIDENCE = "NO_EVIDENCE"                         # no report about it inside the evidence window
    NO_CLEAR_SENTIMENT = "NO_CLEAR_SENTIMENT"           # reports exist, but they net to roughly zero (or its weight is at the benchmark)
    TILT_UP = "TILT_UP"                                 # weight above its benchmark, following positive sentiment
    TILT_DOWN = "TILT_DOWN"                             # weight below its benchmark, following negative sentiment


class ConstraintCode(StrEnum):
    """Which rule held a weight back, in the order the rules are applied (tilt -> bounds -> sector cap -> volatility limit -> liquidity floor -> turnover cap -> minimum trade)."""

    UPPER_BOUND = "UPPER_BOUND"             # the per-stock upper bound cut the tilt's ask
    LOWER_BOUND = "LOWER_BOUND"             # the per-stock lower bound lifted the tilt's ask
    SECTOR_CAP = "SECTOR_CAP"               # its sector was held at its cap
    VOL_LIMIT = "VOL_LIMIT"                 # the volatility-aware upper bound cut it
    LIQUIDITY_FLOOR = "LIQUIDITY_FLOOR"     # thin trading kept it from being overweight
    TURNOVER_CAP = "TURNOVER_CAP"           # the move to the target was shortened to respect the turnover cap
    MIN_TRADE = "MIN_TRADE"                 # the whole rebalance was too small to trade


class ConstraintEffect(ContractModel):
    """One rule that bound a stock at a cycle, and how far it moved the weight. The effect of adding that rule to the ones before it (an order-defined attribution of a joint projection)."""

    code: ConstraintCode
    effect: float = Field(description="signed change in this stock's weight caused by adding this rule, as a fraction of the index (negative = it cut the weight)")


class StrategyInfo(ContractModel):
    id: str
    label: str
    description: str
    score: str
    sector_cap: bool
    vol_limit: bool
    liquidity_floor: bool
    available: bool
    reason: str | None = Field(default=None, description="why it cannot be served when available is false")
    experimental: bool


class RebalancerParams(ContractModel):
    """The three knobs a caller may turn for one request; everything else is the shipped configuration."""

    tilt: float = Field(ge=0, description="tilt strength k in p_i = b_i exp(k S_i) / sum_j b_j exp(k S_j)")
    half_life_hours: float = Field(gt=0, description="a report's weight halves every this many hours")
    max_turnover: float = Field(gt=0, le=1, description="most of the index traded in one cycle (one-way: 1/2 sum |new - old|)")
    is_default: bool = Field(description="false when the caller overrode the shipped configuration (a what-if, not the index of record)")


class IndexConstituent(ContractModel):
    ticker: str
    name: str
    sector: str
    benchmark_weight: float
    lower: float = Field(description="the lowest weight the bounds allow")
    upper: float = Field(description="the highest weight the bounds allow")


class ScoreDriver(ContractModel):
    """One report behind a company's score. The contributions of every report add up exactly to the score."""

    signal_id: str
    headline: str
    source: str
    published_at: datetime
    age_hours: float
    sentiment: float = Field(ge=-1, le=1)
    decayed_weight: float = Field(ge=0, description="0.5 ** (age / half-life)")
    contribution: float = Field(description="this report's share of the score (signed); the contributions sum to the score")
    url: str | None = None
    multiplier: float = Field(default=1.0, description="the impact multiplier applied to this report's tone (1.0 unless the impact strategy is on)")


class RebalanceName(ContractModel):
    ticker: str
    score: float = Field(ge=-1, le=1)
    evidence: float = Field(ge=0, description="effective evidence behind the score after decay and the one-source-one-vote cap")
    reports: int = Field(ge=0)
    sources: int = Field(ge=0)
    target_weight: float
    weight: float
    active: float = Field(description="weight minus benchmark weight")
    change: float = Field(description="weight minus the previous cycle's weight")
    reason: WeightReason
    binding: list[ConstraintEffect] = Field(default_factory=list, description="every rule that bound this stock at this cycle, in the order the rules apply")


class RebalanceCycle(ContractModel):
    """One cycle on the timeline, in the order of ``RebalancerTimeline.tickers`` (compact: this is what the chart draws)."""

    index: int
    at: datetime
    weights: list[float]
    scores: list[float]
    reports: list[int]
    turnover: float
    wanted_turnover: float
    status: str = Field(description="TRADED | LIMITED_BY_TURNOVER | HELD_BELOW_MIN_TRADE | AT_TARGET")
    new_reports: int = Field(ge=0, description="company reports that entered the evidence window since the previous cycle")


class RebalancerTimeline(ContractModel):
    version: str
    strategy: str = "sentiment"
    params: RebalancerParams
    tickers: list[str]
    constituents: list[IndexConstituent]
    cycles: list[RebalanceCycle]
    cumulative_turnover: float
    mean_turnover: float
    reports_used: int
    excluded_untrusted_clock: int = Field(description="company reports left off the timeline because their time was assigned by the replay")
    excluded_other: int = Field(description="reports about these companies that fail another rule (a sentiment that is a placeholder rule, or a company link below the confidence floor)")
    include_live: bool
    labels: list[str]
    limitations: list[str]


class RebalanceCycleDetail(ContractModel):
    version: str
    strategy: str = "sentiment"
    params: RebalancerParams
    index: int
    at: datetime
    previous_at: datetime | None
    status: str
    turnover: float
    wanted_turnover: float
    alpha: float = Field(description="the fraction of the way to the target that was traded (1 = all of it)")
    names: list[RebalanceName]
    drivers: dict[str, list[ScoreDriver]] = Field(description="per ticker, the reports behind its score, largest absolute contribution first")
    labels: list[str]


class RebalancerOverview(ContractModel):
    version: str
    available: bool
    params: RebalancerParams
    tilt_max: float
    max_turnover_limit: float
    half_life_hours_default: float
    benchmark: str
    constituents: list[IndexConstituent]
    cycle_count: int
    step_hours: float
    first_cycle: datetime | None
    last_cycle: datetime | None
    bounds: dict[str, float]
    strategies: list[StrategyInfo] = Field(default_factory=list)
    curve: list[dict[str, float]] = Field(description="the rule drawn: for a stock alone at score S and every other at 0, its target weight before bounds")
    labels: list[str]
    limitations: list[str]


class BacktestStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


# ------------------------------------------------------------------------------------------------------------------------------ trade decisions
class TradeSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class EvidenceQuality(StrEnum):
    NONE = "NONE"    # no report inside the evidence window
    THIN = "THIN"    # less than one source's worth of evidence after decay and the one-source-one-vote cap
    OK = "OK"


class TradeDecision(ContractModel):
    """One stock at one cycle as a decision: where it was, where the rule wanted it, where it ended up, and what the reports and rules were behind that."""

    ticker: str
    name: str
    sector: str
    side: TradeSide
    before: float = Field(description="the weight held going into this cycle")
    target: float = Field(description="what the rule asked for after tilt and every constraint")
    after: float = Field(description="the weight held after the turnover step")
    trade: float = Field(description="after minus before, as a fraction of the index (positive = buy)")
    lower: float
    upper: float = Field(description="the highest weight this strategy's constraints allow this stock")
    est_cost: float = Field(ge=0, description="|trade| x the one-way cost, as a fraction of the index (illustrative cost model)")
    notional_usd: float = Field(ge=0, description="|trade| of an imagined index of mock_aum_usd; display only")
    participation: float | None = Field(default=None, description="notional as a share of the stock's average daily dollar volume (None when no volume data is built)")
    liquidity_flag: bool = Field(description="participation above the configured maximum")
    score: float = Field(ge=-1, le=1)
    evidence: float = Field(ge=0)
    reports: int = Field(ge=0)
    sources: int = Field(ge=0)
    evidence_quality: EvidenceQuality
    newest_age_hours: float | None = Field(description="age of the newest report inside the window")
    mean_age_hours: float | None = Field(description="decayed-weight mean age of the reports inside the window")
    stale: bool = Field(description="the newest report is older than the configured number of half-lives")
    conflicting: bool = Field(description="both a positive and a negative side hold at least the configured share of the absolute contribution")
    positive_share: float = Field(ge=0, le=1)
    negative_share: float = Field(ge=0, le=1)
    reason: WeightReason
    binding: list[ConstraintEffect]
    drivers: list[ScoreDriver]
    explanation: str = Field(description="a template-written sentence; every clause is backed by a field of this record, no model wrote it")


class LedgerAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class LedgerEntry(ContractModel):
    """One simulated decision on a proposed rebalance. A note, never an order: nothing is sent anywhere and the served index does not change."""

    id: str
    seq: int
    recorded_at: datetime
    action: LedgerAction
    strategy: str
    cycle_index: int
    cycle_at: datetime
    params: RebalancerParams
    include_live: bool
    tickers: list[str]
    before: list[float]
    proposed: list[float]
    approved: list[float] = Field(description="the allocation the analyst accepted: the proposal for a full approval, the previous weights for a rejection")
    accepted_tickers: list[str]
    rejected_tickers: list[str]
    turnover: float = Field(description="one-way turnover of before -> approved")
    est_cost: float
    tracking_difference: float = Field(description="one-way distance between the approved and the proposed allocation (0 = approved as proposed)")
    proposal_sha256: str
    analyst: str
    note: str
    prev_hash: str
    entry_hash: str
    stale: bool = Field(default=False, description="set on read: the proposal for this cycle and strategy is no longer the one that was decided")


class RebalanceDecisions(ContractModel):
    version: str
    strategy: str
    params: RebalancerParams
    index: int
    cycles: int
    at: datetime
    previous_at: datetime | None
    status: str
    turnover: float
    wanted_turnover: float
    buys: int
    sells: int
    holds: int
    est_cost: float
    est_cost_usd: float
    proposal_sha256: str = Field(description="digest of the proposal (strategy, parameters, cycle and the three weight vectors); a decision on it is void if this changes")
    tickers: list[str]
    decisions: list[TradeDecision]
    latest_decision: LedgerEntry | None = None
    labels: list[str]


class DecisionRequest(ContractModel):
    """A simulated decision on one proposal. ``proposal_sha256`` must be the digest of the proposal the analyst was looking at: a proposal that has changed since is refused, not decided."""

    strategy: str = "sentiment"
    cycle_index: int = Field(ge=0)
    tilt: float | None = Field(default=None, ge=0)
    half_life_hours: float | None = Field(default=None, gt=0)
    max_turnover: float | None = Field(default=None, gt=0, le=1)
    include_live: bool = False
    action: LedgerAction
    accepted_tickers: list[str] | None = Field(default=None, description="APPROVE only: the trades accepted; omitted = every trade of the proposal")
    note: str = Field(default="", max_length=2000)
    analyst: str = Field(min_length=1, max_length=80)
    proposal_sha256: str = Field(min_length=64, max_length=64)


class PaperBook(ContractModel):
    """The simulated allocation after the latest approval: what an analyst who followed the ledger would hold. A record, not a position at any broker."""

    entry_id: str
    cycle_at: datetime
    strategy: str
    tickers: list[str]
    weights: list[float]


class LedgerView(ContractModel):
    version: str
    chain_ok: bool = Field(description="false when a line of the ledger was edited or removed after it was written")
    broken_at: int | None = Field(default=None, description="the sequence number of the first entry whose hash does not follow from the one before")
    entries: list[LedgerEntry] = Field(description="newest first")
    total: int
    approvals: int
    rejections: int
    paper_book: PaperBook | None
    labels: list[str]
