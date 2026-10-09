import type { LedgerEntry, LedgerView, RebalanceCycleDetail, RebalanceDecisions, RebalancerBacktestView, RebalancerLabView, RebalancerOverview, RebalancerParams, RebalancerTimeline, StrategyInfo, TradeDecision } from "../../api/types";

/** Four stocks, three cycles: small enough to check by hand. NVDA is up, JPM is down, the others are at their benchmark. */
export const TICKERS = ["AAPL", "NVDA", "JPM", "XOM"];
const B = 0.25;
export const params = (over: Partial<RebalancerParams> = {}): RebalancerParams => ({ tilt: 2, half_life_hours: 36, max_turnover: 0.04, is_default: true, ...over });

const constituents = [
  { ticker: "AAPL", name: "Apple Inc.", sector: "Technology", benchmark_weight: B, lower: 0.125, upper: 0.375 },
  { ticker: "NVDA", name: "NVIDIA Corporation", sector: "Technology", benchmark_weight: B, lower: 0.125, upper: 0.375 },
  { ticker: "JPM", name: "JPMorgan Chase & Co.", sector: "Financials", benchmark_weight: B, lower: 0.125, upper: 0.375 },
  { ticker: "XOM", name: "Exxon Mobil Corporation", sector: "Energy", benchmark_weight: B, lower: 0.125, upper: 0.375 },
];

const W = [[0.25, 0.25, 0.25, 0.25], [0.25, 0.28, 0.22, 0.25], [0.24, 0.31, 0.2, 0.25]];
const S = [[0, 0, 0, 0], [0, 0.2, -0.2, 0], [0, 0.3, -0.3, 0.01]];

export const timeline = (over: Partial<RebalancerTimeline> = {}): RebalancerTimeline => ({
  version: "rebalancer-v1", strategy: "sentiment", params: params(), tickers: TICKERS, constituents,
  cycles: W.map((weights, i) => ({ index: i, at: `2026-09-1${8 + i}T06:00:00Z`, weights, scores: S[i]!, reports: [0, 4, 6].map((n, k) => (k === 0 ? 0 : n)).concat([0]).slice(0, 4), turnover: i === 0 ? 0 : 0.03, wanted_turnover: i === 0 ? 0 : 0.05, status: i === 0 ? "AT_TARGET" : "LIMITED_BY_TURNOVER", new_reports: i })),
  cumulative_turnover: 0.06, mean_turnover: 0.02, reports_used: 10, excluded_untrusted_clock: 3, excluded_other: 0, include_live: false,
  labels: ["A mock index: weights follow a transparent rule."], limitations: ["The frozen replay covers 14 days."], ...over,
});

export const detail = (index = 2, over: Partial<RebalanceCycleDetail> = {}): RebalanceCycleDetail => ({
  version: "rebalancer-v1", strategy: "sentiment", params: params(), index, at: `2026-09-1${8 + index}T06:00:00Z`, previous_at: "2026-09-19T06:00:00Z", status: "LIMITED_BY_TURNOVER", turnover: 0.03, wanted_turnover: 0.05, alpha: 0.6,
  names: TICKERS.map((t, j) => ({
    ticker: t, score: S[index]![j]!, evidence: 1, reports: j === 1 ? 6 : 0, sources: j === 1 ? 3 : 0, target_weight: W[index]![j]!, weight: W[index]![j]!, active: W[index]![j]! - B, change: W[index]![j]! - W[index - 1]![j]!,
    reason: t === "NVDA" ? "TILT_UP" : t === "JPM" ? "TILT_DOWN" : "NO_EVIDENCE", binding: [],
  })),
  drivers: { NVDA: [{ signal_id: "s1", headline: "Nvidia approves $150B buyback", source: "azernews.az", published_at: "2026-09-18T12:00:00Z", age_hours: 14, sentiment: 0.9, decayed_weight: 0.76, contribution: 0.3, url: "https://example.test/a", multiplier: 1 }], AAPL: [], JPM: [], XOM: [] },
  labels: ["l"], ...over,
});

export const STRATEGIES: StrategyInfo[] = [
  { id: "sentiment", label: "Sentiment tilt (baseline)", description: "The shipped rule.", score: "sentiment", sector_cap: false, vol_limit: false, liquidity_floor: false, available: true, reason: null, experimental: false },
  { id: "sentiment_risk", label: "Sentiment tilt + risk limits", description: "The baseline plus a sector cap, a volatility limit and a liquidity floor.", score: "sentiment", sector_cap: true, vol_limit: true, liquidity_floor: true, available: true, reason: null, experimental: true },
  { id: "sentiment_impact", label: "Sentiment x impact (experimental)", description: "A report counts in proportion to its impact score.", score: "sentiment_impact", sector_cap: false, vol_limit: false, liquidity_floor: false, available: true, reason: null, experimental: true },
];

export const overview = (over: Partial<RebalancerOverview> = {}): RebalancerOverview => ({
  version: "rebalancer-v1", available: true, params: params(), tilt_max: 6, max_turnover_limit: 0.25, half_life_hours_default: 36, benchmark: "Equal weight", constituents, cycle_count: 3, step_hours: 6,
  first_cycle: "2026-09-18T06:00:00Z", last_cycle: "2026-09-20T06:00:00Z",
  strategies: STRATEGIES,
  bounds: { lower: 0.125, upper: 0.375, benchmark: 0.25, max_active_ratio: 0.5, floor: 0.01, cap: 0.12, min_trade: 0.002, cost_bps: 5 },
  curve: Array.from({ length: 21 }, (_, i) => { const s = -1 + i / 10; const t = Math.exp(2 * s) / (Math.exp(2 * s) + 3); return { score: s, target: t, bounded: Math.min(0.375, Math.max(0.125, t)) }; }),
  labels: ["l"], limitations: ["x"], ...over,
});

export const backtest = (status: "AVAILABLE" | "STALE" | "UNAVAILABLE" = "AVAILABLE", percentile = 0.82): RebalancerBacktestView =>
  status === "UNAVAILABLE" ? { status, reason: "no backtest has been built: `make rebalancer-backtest`", backtest: null } : {
    status, reason: status === "STALE" ? "the weights now served differ" : null,
    backtest: {
      version: "rebalancer-backtest-v1", params: params(), cost_bps: 5, tickers: TICKERS, dates: ["2026-09-18", "2026-09-21", "2026-09-22"], rebalanced: [0.001, -0.002, 0.003], benchmark: [0.001, -0.003, 0.002],
      cumulative_rebalanced: [0.001, -0.001, 0.002], cumulative_benchmark: [0.001, -0.002, 0], turnover: [0.01, 0.02, 0.02],
      summary: { rebalanced_return: 0.002, benchmark_return: 0, active_return: 0.002, daily_active_mean: 0.0007, daily_active_std: 0.001, mean_daily_turnover: 0.017, total_cost: 0.0003 },
      rank_ic: { mean: 0.1, daily: [0.1, 0.2, 0], days: 3 },
      placebo: { runs: 200, seed: 1, active_return_p05: -0.003, active_return_p50: 0, active_return_p95: 0.003, mean_ic_p05: -0.2, mean_ic_p50: 0, mean_ic_p95: 0.2, active_return_percentile: percentile, ic_percentile: 0.7 },
      inputs: {}, timeline_sha256: "x", caveats: ["About ten trading sessions."],
    },
  };

const decision = (over: Partial<TradeDecision> & Pick<TradeDecision, "ticker" | "side" | "before" | "after">): TradeDecision => ({
  name: `${over.ticker} Corp`, sector: "Technology", target: over.after, trade: over.after - over.before, lower: 0.125, upper: 0.375, est_cost: Math.abs(over.after - over.before) * 5e-4, notional_usd: Math.abs(over.after - over.before) * 1e9,
  participation: 0.002, liquidity_flag: false, score: 0, evidence: 1, reports: 0, sources: 0, evidence_quality: "NONE", newest_age_hours: null, mean_age_hours: null, stale: false, conflicting: false, positive_share: 0, negative_share: 0,
  reason: "NO_EVIDENCE", binding: [], drivers: [], explanation: `${over.ticker} explanation.`, ...over,
});

/** A proposal over the four-stock index: NVDA is bought on good news (held back by the turnover cap), JPM is sold, the others do not trade. */
export const decisions = (over: Partial<RebalanceDecisions> = {}): RebalanceDecisions => ({
  version: "rebalancer-v1", strategy: "sentiment", params: params(), index: 2, cycles: 3, at: "2026-09-20T06:00:00Z", previous_at: "2026-09-19T06:00:00Z", status: "LIMITED_BY_TURNOVER", turnover: 0.03, wanted_turnover: 0.05,
  buys: 1, sells: 2, holds: 1, est_cost: 0.0000375, est_cost_usd: 37500, proposal_sha256: "a".repeat(64), tickers: TICKERS, latest_decision: null, labels: ["A mock index."],
  decisions: [
    decision({ ticker: "NVDA", side: "BUY", before: 0.28, after: 0.31, target: 0.34, score: 0.3, evidence: 1.2, reports: 6, sources: 3, evidence_quality: "OK", newest_age_hours: 14, mean_age_hours: 20, reason: "LIMITED_BY_TURNOVER",
      binding: [{ code: "TURNOVER_CAP", effect: -0.03 }], explanation: "Buy NVDA +3.00 pp (28.00% to 31.00%). Its sentiment score is +0.30.",
      drivers: [{ signal_id: "s1", headline: "Nvidia approves $150B buyback", source: "azernews.az", published_at: "2026-09-19T16:00:00Z", age_hours: 14, sentiment: 0.9, decayed_weight: 0.76, contribution: 0.3, url: "https://example.test/a", multiplier: 1 }] }),
    decision({ ticker: "JPM", side: "SELL", before: 0.22, after: 0.2, target: 0.2, score: -0.3, evidence: 0.5, reports: 2, sources: 2, evidence_quality: "THIN", newest_age_hours: 60, mean_age_hours: 60, stale: true, conflicting: true, positive_share: 0.4, negative_share: 0.6,
      reason: "TILT_DOWN", explanation: "Sell JPM -2.00 pp (22.00% to 20.00%).",
      drivers: [{ signal_id: "s2", headline: "JPMorgan faces new probe", source: "wire", published_at: "2026-09-17T18:00:00Z", age_hours: 60, sentiment: -0.6, decayed_weight: 0.3, contribution: -0.2, url: null, multiplier: 1 }] }),
    decision({ ticker: "AAPL", side: "SELL", before: 0.25, after: 0.24, target: 0.24, reason: "NO_EVIDENCE", explanation: "Sell AAPL -1.00 pp (25.00% to 24.00%)." }),
    decision({ ticker: "XOM", side: "HOLD", before: 0.25, after: 0.25, reason: "NO_EVIDENCE", explanation: "No trade in XOM: it stays at 25.00%." }),
  ],
  ...over,
});

const lStrategy = (id: string, label: string, kind: string, ret: number, over: Partial<LabStrategyT> = {}): LabStrategyT => ({
  id, label, description: label, kind, experimental: id === "sentiment_risk" || id === "sentiment_impact", daily_net: [0.001, -0.002, 0.003], cumulative: [0.001, -0.001, ret], drawdown: [0, -0.002, -0.001], turnover: [0.01, 0.02, 0.02],
  metrics: { cumulative_return: ret, benchmark_return: 0, active_return: ret, annualised_vol: 0.12, max_drawdown: -0.002, hit_rate: kind === "TILT" ? 0.6 : null, mean_daily_turnover: 0.017, total_cost: 0.0003, rank_ic: kind === "TILT" ? 0.1 : null },
  windows: [{ label: "full window", start: "2026-09-18", end: "2026-09-22", sessions: 3, strategy_return: ret, benchmark_return: 0, active_return: ret },
    { label: "first half", start: "2026-09-18", end: "2026-09-18", sessions: 1, strategy_return: 0.001, benchmark_return: 0, active_return: 0.001 },
    { label: "second half", start: "2026-09-21", end: "2026-09-22", sessions: 2, strategy_return: ret, benchmark_return: 0, active_return: ret }],
  windows_positive: 1, windows_total: 2, placebo: kind === "TILT" ? { runs: 200, active_return_p05: -0.003, active_return_p50: 0, active_return_p95: 0.003, active_return_percentile: 0.82, ic_percentile: 0.7 } : null,
  verdict: kind === "TILT" ? "WITHIN_PLACEBO_RANGE" : null, timeline_sha256: kind === "TILT" ? "x" : null, ...over,
});
type LabStrategyT = NonNullable<RebalancerLabView["lab"]>["strategies"][number];

const cell = (hl: number, to: number, tilt: number, ratio: number, active: number, pct: number) => ({ half_life_hours: hl, max_turnover: to, tilt, max_active_ratio: ratio, active_return: active, rank_ic: 0.1, placebo_percentile: pct, mean_daily_turnover: 0.05 });

export const lab = (status: "AVAILABLE" | "STALE" | "UNAVAILABLE" = "AVAILABLE"): RebalancerLabView =>
  status === "UNAVAILABLE" ? { status, reason: "the lab has not been built (make rebalancer-lab)", lab: null } : {
    status, reason: status === "STALE" ? "the weights of strategy 'sentiment' differ from the ones the lab was built from" : null,
    lab: {
      version: "rebalancer-lab-v1", params: params(), cost_bps: 5, tickers: TICKERS, dates: ["2026-09-18", "2026-09-21", "2026-09-22"],
      strategies: [lStrategy("sentiment", "Sentiment tilt (baseline)", "TILT", 0.002), lStrategy("sentiment_risk", "Sentiment tilt + risk limits", "TILT", 0.0015), lStrategy("sentiment_impact", "Sentiment x impact (experimental)", "TILT", 0.001),
        lStrategy("equal_weight", "Equal weight (benchmark)", "REFERENCE", 0, { metrics: { cumulative_return: 0, benchmark_return: 0, active_return: 0, annualised_vol: 0.12, max_drawdown: -0.003, hit_rate: null, mean_daily_turnover: 0.005, total_cost: 0.0001, rank_ic: null } }),
        lStrategy("buy_and_hold", "Buy and hold", "REFERENCE", -0.0005)],
      grid: { half_life_by_turnover: [cell(36, 0.04, 2, 0.5, 0.002, 0.82), cell(36, 0.08, 2, 0.5, 0.0021, 0.84), cell(12, 0.04, 2, 0.5, 0.0027, 0.96), cell(12, 0.08, 2, 0.5, 0.0023, 0.9)],
        tilt_by_position_limit: [cell(36, 0.04, 2, 0.5, 0.002, 0.82), cell(36, 0.04, 2, 0.25, 0.001, 0.7), cell(36, 0.04, 4, 0.5, 0.0018, 0.75), cell(36, 0.04, 4, 0.25, 0.0001, 0.5)],
        cells_total: 8, cells_positive: 8, cells_outside_placebo_range: 1, expected_outside_by_chance: 0.8, active_min: 0.0001, active_max: 0.0027, placebo_runs: 100 },
      cost_sensitivity: [0, 5, 10, 25].map((b) => ({ cost_bps: b, strategy_return: 0.002 - b * 1e-5, benchmark_return: 0, active_return: 0.002 - b * 1e-5 })),
      impact_reports: 277, reports_used: 577, inputs: {}, caveats: ["About ten trading sessions."],
    },
  };

export const ledgerEntry = (over: Partial<LedgerEntry> = {}): LedgerEntry => ({
  id: "lg_1", seq: 1, recorded_at: "2026-10-09T10:00:00Z", action: "APPROVE", strategy: "sentiment", cycle_index: 2, cycle_at: "2026-09-20T06:00:00Z", params: params(), include_live: false, tickers: TICKERS,
  before: [0.25, 0.28, 0.22, 0.25], proposed: [0.24, 0.31, 0.2, 0.25], approved: [0.24, 0.31, 0.2, 0.25], accepted_tickers: ["AAPL", "JPM", "NVDA"], rejected_tickers: [], turnover: 0.03, est_cost: 0.0000375,
  tracking_difference: 0, proposal_sha256: "a".repeat(64), analyst: "Aniket", note: "looks fine", prev_hash: "0".repeat(64), entry_hash: "b".repeat(64), stale: false, ...over,
});

export const ledger = (entries: LedgerEntry[] = [ledgerEntry()], chain_ok = true): LedgerView => ({
  version: "rebalancer-v1", chain_ok, broken_at: chain_ok ? null : 1, entries, total: entries.length, approvals: entries.filter((e) => e.action === "APPROVE").length,
  rejections: entries.filter((e) => e.action === "REJECT").length, paper_book: entries.length ? { entry_id: entries[0]!.id, cycle_at: entries[0]!.cycle_at, strategy: "sentiment", tickers: TICKERS, weights: entries[0]!.approved } : null,
  labels: ["A simulated ledger."],
});
