import type { ConstraintCode, IndexConstituent, TradeDecision, WeightReason } from "../api/types";

/** Sectors the entity master uses, in the order the stacked chart lays them out (so each sector is one contiguous band). */
export const SECTOR_ORDER = ["Technology", "Financials", "Energy", "Healthcare", "Industrials", "Consumer"] as const;

const SECTOR_VAR: Record<string, string> = {
  Technology: "--color-sector-technology",
  Financials: "--color-sector-financials",
  Energy: "--color-sector-energy",
  Healthcare: "--color-sector-healthcare",
  Industrials: "--color-sector-industrials",
  Consumer: "--color-sector-consumer",
};

export const sectorVar = (sector: string): string => SECTOR_VAR[sector] ?? "--color-muted";

export interface SeriesSpec {
  ticker: string;
  name: string;
  sector: string;
  /** index into the timeline's `tickers` / `weights` arrays */
  index: number;
  benchmark: number;
  /** the fill: the sector hue, lightened step by step inside its sector so neighbours in a stack can be told apart */
  fill: string;
  /** the line colour: the sector hue, un-lightened */
  stroke: string;
}

/** Series in stacking order (sector, then ticker) with the colour of each. Colour is never the only signal: the ticker is printed beside every band. */
export function orderSeries(constituents: IndexConstituent[], tickers: string[]): SeriesSpec[] {
  const rank = (s: string) => {
    const i = (SECTOR_ORDER as readonly string[]).indexOf(s);
    return i < 0 ? SECTOR_ORDER.length : i;
  };
  const rows = constituents
    .map((c) => ({ c, index: tickers.indexOf(c.ticker) }))
    .filter((r) => r.index >= 0)
    .sort((a, b) => rank(a.c.sector) - rank(b.c.sector) || a.c.ticker.localeCompare(b.c.ticker));
  const inSector = new Map<string, number>();
  rows.forEach((r) => inSector.set(r.c.sector, (inSector.get(r.c.sector) ?? 0) + 1));
  const seen = new Map<string, number>();
  return rows.map(({ c, index }) => {
    const k = seen.get(c.sector) ?? 0;
    seen.set(c.sector, k + 1);
    const n = inSector.get(c.sector) ?? 1;
    const strength = n === 1 ? 100 : Math.round(100 - (k * 38) / (n - 1)); // 100 % → 62 % of the hue inside a sector
    const v = sectorVar(c.sector);
    return {
      ticker: c.ticker,
      name: c.name,
      sector: c.sector,
      index,
      benchmark: c.benchmark_weight,
      fill: `color-mix(in oklab, var(${v}) ${strength}%, var(--color-paper-2))`,
      stroke: `var(${v})`,
    };
  });
}

export interface Layer {
  spec: SeriesSpec;
  /** cumulative bottom and top of the band at every cycle (fractions of the index, 0..1) */
  bottom: number[];
  top: number[];
}

/** Stack the weights bottom-up in series order. Every column sums to the same total as the weights, which the chart asserts. */
export function stackLayers(weights: number[][], series: SeriesSpec[]): Layer[] {
  const base = weights.map(() => 0);
  return series.map((spec) => {
    const bottom = [...base];
    const top = weights.map((w, i) => {
      base[i] = base[i]! + (w[spec.index] ?? 0);
      return base[i]!;
    });
    return { spec, bottom, top };
  });
}

/** Push labels apart so none overlaps (minimum gap), keeping their order and staying inside [lo, hi]. */
export function spreadLabels(ys: number[], gap: number, lo: number, hi: number): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y || a.i - b.i);
  const out = order.map((o) => Math.min(Math.max(o.y, lo), hi));
  for (let k = 1; k < out.length; k++) if (out[k]! < out[k - 1]! + gap) out[k] = out[k - 1]! + gap;
  const over = (out[out.length - 1] ?? 0) - hi;
  if (over > 0) {
    out[out.length - 1] = hi;
    for (let k = out.length - 2; k >= 0; k--) if (out[k]! > out[k + 1]! - gap) out[k] = out[k + 1]! - gap;
  }
  const result = new Array<number>(ys.length).fill(0);
  order.forEach((o, k) => (result[o.i] = out[k]!));
  return result;
}

/** A closed SVG path for the area between two polylines. */
export function areaPath(x: number[], top: number[], bottom: number[], y: (v: number) => number): string {
  if (x.length === 0) return "";
  const up = x.map((px, i) => `${i === 0 ? "M" : "L"}${px.toFixed(1)} ${y(top[i]!).toFixed(1)}`).join(" ");
  const down = [...x].reverse().map((px, i) => `L${px.toFixed(1)} ${y(bottom[x.length - 1 - i]!).toFixed(1)}`).join(" ");
  return `${up} ${down} Z`;
}

export function linePath(x: number[], v: number[], y: (v: number) => number): string {
  return x.map((px, i) => `${i === 0 ? "M" : "L"}${px.toFixed(1)} ${y(v[i]!).toFixed(1)}`).join(" ");
}

export const REASON_LABEL: Record<WeightReason, string> = {
  AT_UPPER_BOUND: "At the upper bound",
  AT_LOWER_BOUND: "At the lower bound",
  LIMITED_BY_TURNOVER: "Limited by turnover",
  HELD_BELOW_MIN_TRADE: "Held (too small to trade)",
  NO_EVIDENCE: "No reports",
  NO_CLEAR_SENTIMENT: "No clear sentiment",
  TILT_UP: "Tilted up",
  TILT_DOWN: "Tilted down",
};

export const REASON_HELP: Record<WeightReason, string> = {
  AT_UPPER_BOUND: "The sentiment asked for at least this much weight; the bound stops it here.",
  AT_LOWER_BOUND: "The sentiment asked for at most this much weight; the bound stops it here.",
  LIMITED_BY_TURNOVER: "The move toward the target was shortened so no more than the turnover cap is traded in one cycle.",
  HELD_BELOW_MIN_TRADE: "The whole rebalance was smaller than the minimum trade, so nothing was traded.",
  NO_EVIDENCE: "No report about this company falls inside the evidence window.",
  NO_CLEAR_SENTIMENT: "Reports exist but net to roughly zero, or the weight sits at its benchmark.",
  TILT_UP: "Weight above the benchmark, following positive sentiment.",
  TILT_DOWN: "Weight below the benchmark, following negative sentiment.",
};

/** Percentage points, signed, e.g. "+1.25 pp". */
export const pp = (fraction: number, digits = 2): string => {
  const v = fraction * 100;
  const s = Math.abs(v) < 0.5 * 10 ** -digits ? (0).toFixed(digits) : v.toFixed(digits);
  return `${v > 0 && s !== (0).toFixed(digits) ? "+" : ""}${s} pp`;
};

export const share = (fraction: number, digits = 2): string => `${(fraction * 100).toFixed(digits)}%`;

export interface Trade {
  ticker: string;
  side: "BUY" | "SELL";
  /** weight change as a fraction of the index */
  change: number;
}

/** The trades a cycle made, largest first. A change below `eps` is rounding, not a trade. */
export function tradesOf(names: { ticker: string; change: number }[], eps = 5e-5): Trade[] {
  return names
    .filter((n) => Math.abs(n.change) > eps)
    .map((n) => ({ ticker: n.ticker, side: n.change > 0 ? ("BUY" as const) : ("SELL" as const), change: n.change }))
    .sort((a, b) => Math.abs(b.change) - Math.abs(a.change) || a.ticker.localeCompare(b.ticker));
}

/** Map a pointer x inside the plot to the nearest cycle index (clamped). */
export function nearestIndex(px: number, left: number, right: number, xs: number[]): number {
  if (xs.length === 0) return 0;
  const target = Math.min(Math.max(px, left), right);
  let best = 0;
  for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i]! - target) < Math.abs(xs[best]! - target)) best = i;
  return best;
}

/** Evenly spaced ticks across [min, max]: for the time axis (day starts) the chart picks its own. */
export function axisTicks(min: number, max: number, count: number): number[] {
  if (count < 2 || max <= min) return [min];
  return Array.from({ length: count }, (_, i) => min + ((max - min) * i) / (count - 1));
}

/* ---- constraints, trade decisions, the approval preview ---- */

export const CONSTRAINT_LABEL: Record<ConstraintCode, string> = {
  UPPER_BOUND: "Upper bound",
  LOWER_BOUND: "Lower bound",
  SECTOR_CAP: "Sector cap",
  VOL_LIMIT: "Volatility limit",
  LIQUIDITY_FLOOR: "Liquidity floor",
  TURNOVER_CAP: "Turnover cap",
  MIN_TRADE: "Minimum trade",
};

export const CONSTRAINT_HELP: Record<ConstraintCode, string> = {
  UPPER_BOUND: "The per-stock upper bound cut the weight the sentiment asked for.",
  LOWER_BOUND: "The per-stock lower bound lifted the weight the sentiment asked for.",
  SECTOR_CAP: "Its sector was held at its cap (its share of the benchmark plus a margin), so every member of the sector was cut.",
  VOL_LIMIT: "A volatile stock may be overweight less than a calm one, so its upper bound is lower.",
  LIQUIDITY_FLOOR: "Thinly traded stocks may not be overweight: its upper bound is its benchmark weight.",
  TURNOVER_CAP: "The move toward the target was shortened so no more than the turnover cap is traded in one cycle.",
  MIN_TRADE: "The whole rebalance was smaller than the minimum trade, so nothing was traded.",
};

/** Which constraint codes count as "the rule held it back" (as opposed to the pacing of the trade). */
export const isRiskRule = (c: ConstraintCode): boolean => c !== "TURNOVER_CAP" && c !== "MIN_TRADE";

/** Percent of the index with a sign and the word the sign stands for, so a trade never reads as a bare colour. */
export const tradeText = (d: Pick<TradeDecision, "side" | "trade">): string => (d.side === "HOLD" ? "No trade" : `${d.side === "BUY" ? "Buy" : "Sell"} ${(Math.abs(d.trade) * 100).toFixed(2)} pp`);

export const ageText = (h: number | null | undefined): string => {
  if (h == null) return "none";
  if (h < 1) return "under an hour";
  if (h < 48) return `${Math.round(h)} h`;
  return `${(h / 24).toFixed(1)} days`;
};

export const VERDICT_TEXT: Record<string, string> = {
  WITHIN_PLACEBO_RANGE: "Within what shuffled scores give",
  ABOVE_PLACEBO_RANGE: "Above the shuffled range",
  BELOW_PLACEBO_RANGE: "Below the shuffled range",
};

export interface Preview {
  /** weights after accepting the chosen trades, in the proposal's ticker order */
  weights: number[];
  /** set when the selection cannot be funded (only buys or only sells accepted) */
  problem: string | null;
  accepted: string[];
  rejected: string[];
}

/**
 * The allocation that results from accepting a subset of a proposal's trades. Mirrors the server (rebalancer/ledger.py::approved_allocation): accepted trades are carried out
 * in full unless buys and sells no longer balance, in which case the larger side is scaled down so what is bought equals what is sold. The server recomputes and checks it.
 */
export function previewApproval(decisions: TradeDecision[], tickers: string[], accepted: ReadonlySet<string> | null): Preview {
  const by = new Map(decisions.map((d) => [d.ticker, d]));
  const traded = decisions.filter((d) => d.side !== "HOLD").map((d) => d.ticker);
  if (accepted === null) return { weights: tickers.map((t) => by.get(t)!.after), problem: null, accepted: traded, rejected: [] };
  const take = traded.filter((t) => accepted.has(t));
  const buys = take.reduce((a, t) => a + Math.max(by.get(t)!.trade, 0), 0);
  const sells = take.reduce((a, t) => a + Math.max(-by.get(t)!.trade, 0), 0);
  const rejected = traded.filter((t) => !accepted.has(t));
  if ((buys > 0) !== (sells > 0)) {
    return { weights: tickers.map((t) => by.get(t)!.before), problem: "A buy is paid for by a sell: accept at least one of each, or neither.", accepted: take, rejected };
  }
  const sb = buys <= sells ? 1 : sells / buys;
  const ss = sells <= buys ? 1 : buys / sells;
  const weights = tickers.map((t) => {
    const d = by.get(t)!;
    const f = !take.includes(t) ? 0 : d.trade > 0 ? sb : ss;
    return d.before + f * d.trade;
  });
  return { weights, problem: null, accepted: take, rejected };
}

/** One-way turnover between two weight vectors. */
export const turnoverBetween = (a: number[], b: number[]): number => 0.5 * a.reduce((s, x, i) => s + Math.abs(x - b[i]!), 0);
