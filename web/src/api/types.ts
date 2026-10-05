import type { components } from "./schema";

type S = components["schemas"];

export type RiskSignal = S["RiskSignal"];
export type RiskAssessment = S["RiskAssessment"];
export type SemanticReading = S["SemanticReading"];
export type SeverityAssessment = S["SeverityAssessment"];
export type RubricField = S["RubricField"];
export type ScoreStep = S["ScoreStep"];
export type MarketUse = S["MarketUse"];
export type Reliability = S["Reliability"];
export type ProvenanceLine = S["ProvenanceLine"];
export type Origin = S["Origin"];
export type IndicatorHit = S["IndicatorHit"];
export type ThresholdState = S["ThresholdState"];
export type EvidenceView = S["EvidenceView"];
export type TimelineView = S["TimelineView"];
export type TimelineItem = S["TimelineItem"];
export type LLMInfo = S["LLMInfo"];
export type AssessedEntity = S["AssessedEntity"];
export type EvidenceSpan = S["EvidenceSpan"];
export type SignalSummary = S["SignalSummary"];
export type SignalPage = S["SignalPage"];
export type SignalContext = S["SignalContext"];
export type ContextInput = S["ContextInput"];
export type FilingMoment = S["FilingMoment"];
export type RealisedOutcome = S["RealisedOutcome"];
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
export type ImpactModelCard = S["ImpactModelCard"];
export type ImpactAudit = S["ImpactAudit"];
export type ImpactStatus = S["ImpactStatus"];
export type ImpactLifecycle = S["ImpactLifecycle"];
export type ImpactScope = S["ImpactScope"];
export type ImpactAssessment = S["ImpactAssessment"];
export type ImpactScopeCard = S["ScopeCard"];
export type ImpactSetResult = S["SetResult"];
export type ImpactModelScore = S["ModelScore"];
export type ImpactEstimate = S["Estimate"];
export type ImpactCalibrationBin = S["CalibrationBin"];
export type Scenario = S["Scenario"];
export type AnalyzeRequest = S["AnalyzeRequest"];
export type AnalyzeResponse = S["AnalyzeResponse"];
export type LiveStatus = S["LiveStatus"];
export type PortfolioRelevance = S["PortfolioRelevance"];
export type ExposureSlice = S["ExposureSlice"];
export type SignalScope = S["SignalScope"];
export type ScopeInfo = S["ScopeInfo"];
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

export type EvidenceBundle = S["EvidenceBundle"];
export type StageStatus = S["StageStatus"];
export type EvidenceFeature = S["FeatureRow"];
export type EvidenceIncrement = S["Increment"];
export type EvidenceProtocolRun = S["ProtocolRun"];
export type EvidenceContrast = S["ContrastRow"];
export type EvidenceCandidate = S["CandidateRow"];
