import type { components } from "./schema";

type S = components["schemas"];

export type RiskSignal = S["RiskSignal"];
export type SignalSummary = S["SignalSummary"];
export type SignalPage = S["SignalPage"];
export type Meta = S["Meta"];
export type PipelineReport = S["PipelineReport"];
export type SignalProvenance = S["SignalProvenance"];
export type SentimentAudit = S["SentimentAudit"];
export type SentimentModelCard = S["SentimentModelCard"];
export type EvalSet = S["EvalSet"];
export type EventAudit = S["EventAudit"];
export type EventStatus = S["EventStatus"];
export type EventModelCard = S["EventModelCard"];
export type EventEvalSet = S["EventEvalSet"];
export type ClassReliability = S["ClassReliability"];
export type Scenario = S["Scenario"];
export type ScenarioList = S["ScenarioList"];
export type ShockSpec = S["ShockSpec"];
export type PortfolioSummary = S["PortfolioSummary"];
export type PortfolioExposure = S["PortfolioExposure"];
export type ExposureRow = S["ExposureRow"];
export type StressRequest = S["StressRequest"];
export type StressResult = S["StressResult"];
export type StressStatus = S["StressStatus"];
export type PositionResult = S["PositionResult"];
export type Contribution = S["Contribution"];
export type AppliedShock = S["AppliedShock"];
export type EventCategory = S["EventCategory"];
export type SourceType = S["SourceType"];
export type RiskFactor = S["RiskFactor"];
export type ShockScope = S["ShockScope"];
export type AssetClass = S["AssetClass"];

export const EVENT_CATEGORIES: EventCategory[] = [
  "GEOPOLITICAL",
  "MACROECONOMIC",
  "CREDIT_FUNDING",
  "MA_CORPORATE_ACTION",
  "REGULATORY_LEGAL",
  "PRODUCT_OPERATIONS",
  "EARNINGS_FINANCIAL_PERFORMANCE",
  "MARKET_VALUATION",
];
