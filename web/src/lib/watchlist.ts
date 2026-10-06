import type { WatchKind } from "../api/types";

export const KIND_LABEL: Record<WatchKind, string> = {
  COMPANY: "Company",
  SECTOR: "Sector",
  INDUSTRY: "Industry",
  GEOGRAPHY: "Geography",
  EVENT_TYPE: "Event type",
  RISK_THEME: "Risk theme",
  PORTFOLIO_EXPOSURE: "Portfolio exposure",
};

export const KIND_BLURB: Record<WatchKind, string> = {
  COMPANY: "Events whose company was resolved to this entity. A text that only mentions a name never matches.",
  SECTOR: "Events whose resolved scope includes this sector.",
  INDUSTRY: "Events whose resolved scope includes this industry.",
  GEOGRAPHY: "Events whose resolved scope points to this region.",
  EVENT_TYPE: "Events assessed as this kind of event.",
  RISK_THEME: "Events about this macro or risk theme.",
  PORTFOLIO_EXPOSURE: "Events that reach the holdings you name (the top N by value, or one holding).",
};

export const KINDS = Object.keys(KIND_LABEL) as WatchKind[];
