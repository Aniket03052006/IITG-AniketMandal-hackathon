import type { RiskSignal, SignalScope, SignalSummary } from "../api/types";

export type ScopeLevel = SignalScope["level"];
export type Channel = SignalSummary["channel"];

export const SCOPE_LABEL: Record<ScopeLevel, string> = {
  COMPANY: "Company",
  SECTOR: "Sector",
  MARKET: "Market-wide",
  UNRESOLVED: "Unresolved",
};

export const SCOPE_BLURB: Record<ScopeLevel, string> = {
  COMPANY: "A company was named in the text.",
  SECTOR: "No company was named, but the text is about one sector.",
  MARKET: "No company or sector: a macro, geopolitical or market-wide event.",
  UNRESOLVED: "Nothing could be established. The event is kept, not guessed about.",
};

export const CHANNEL_LABEL: Record<string, string> = { REPLAY: "Replay", LIVE: "Live", MANUAL: "Pasted" };

export const THEME_LABEL = (t: string) => t.replace(/_/g, " ");

export const REGION_LABEL: Record<string, string> = {
  US: "United States", GB: "United Kingdom", EU: "Europe", CN: "China", JP: "Japan", IN: "India", MIDEAST: "Middle East", RU_UA: "Russia / Ukraine",
};

export interface Subject {
  level: string;
  sector?: string | null;
  themes?: string[];
  entityName?: string | null;
  ticker?: string | null;
}

/** One line saying what a signal is about, whatever its scope. */
export function subjectLine(p: Subject): string {
  if (p.level === "COMPANY") return `${p.entityName ?? "Company"}${p.ticker ? ` (${p.ticker})` : ""}`;
  if (p.level === "SECTOR") return `${p.sector} sector`;
  if (p.level === "MARKET") return p.themes?.length ? `Market-wide · ${p.themes.map(THEME_LABEL).join(", ")}` : "Market-wide";
  return "No subject identified";
}

export const subjectOf = (s: RiskSignal): Subject => ({
  level: s.scope.level, sector: s.scope.sector, themes: s.scope.themes, entityName: s.entity.entity_name, ticker: s.entity.ticker,
});

export const subjectOfSummary = (s: SignalSummary): Subject => ({
  level: s.scope_level, sector: s.scope_sector, themes: s.scope_themes, entityName: s.entity_name, ticker: s.ticker,
});

export const RELEVANCE_LABEL: Record<string, string> = {
  DIRECT: "Held directly",
  SECTOR: "Sector exposure",
  MARKET_WIDE: "Whole book",
  NONE: "Not held",
  UNDETERMINED: "Relevance unknown",
};

export function relevanceShort(level: string, share: number | null | undefined): string {
  const l = RELEVANCE_LABEL[level] ?? level;
  return share != null && (level === "DIRECT" || level === "SECTOR") ? `${l} · ${(share * 100).toFixed(1)}%` : l;
}
