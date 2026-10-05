import type {
  EventIntelligence,
  Meta,
  PipelineReport,
  PortfolioExposure,
  PortfolioSummary,
  RiskSignal,
  ScenarioList,
  SentimentModelCard,
  EventModelCard,
  ImpactModelCard,
  EvidenceBundle,
  SignalContext,
  RiskAssessment,
  EvidenceView,
  TimelineView,
  AnalyzeRequest,
  AnalyzeResponse,
  LiveStatus,
  PortfolioRelevance,
  ScopeInfo,
  AnalogueSet,
  OutcomeCheck,
  ScenarioHistoryCheck,
  SignalPage,
  StressRequest,
  StressResult,
  PortfolioInput,
  PortfolioListItem,
  PortfolioView,
  ResolvedPortfolio,
  ParseResult,
  PortfolioExposureDetail,
  ExposureChain,
  PortfolioComparison,
  CompareRequest,
} from "./types";
import { pfParam } from "../lib/portfolio";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
    });
  } catch {
    throw new ApiError(0, "Cannot reach the EventShock API. Is the backend running?");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error body: keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (...parts: string[]): string => {
  const q = parts.filter(Boolean).join("&");
  return q ? `?${q}` : "";
};

export interface SignalFilters {
  category?: string;
  source_type?: string;
  min_impact?: number;
  q?: string;
  event_status?: string;
  channel?: string;
  scope_level?: string;
  /** the hierarchical scope: COMPANY | INDUSTRY | SECTOR | GEOGRAPHY | MACRO | MARKET | THEME | UNRESOLVED */
  scope_type?: string;
  since_seq?: number;
  /** a saved personal portfolio, so each row's relevance reads it; omitted = the synthetic default */
  portfolio_id?: string | null;
}

export const api = {
  meta: () => request<Meta>("/meta"),
  signals: (f: SignalFilters = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
    const qs = p.toString();
    return request<SignalPage>(`/signals${qs ? `?${qs}` : ""}`);
  },
  signal: (id: string) => request<RiskSignal>(`/signals/${encodeURIComponent(id)}`),
  signalContext: (id: string) => request<SignalContext>(`/signals/${encodeURIComponent(id)}/context`),
  assessment: (id: string, refine = false) =>
    request<RiskAssessment>(`/signals/${encodeURIComponent(id)}/assessment${refine ? "?refine=true" : ""}`),
  signalEvidence: (id: string) => request<EvidenceView>(`/signals/${encodeURIComponent(id)}/evidence`),
  signalTimeline: (id: string) => request<TimelineView>(`/signals/${encodeURIComponent(id)}/timeline`),
  signalIntelligence: (id: string, asOf: string | null = null, pf: string | null = null) =>
    request<EventIntelligence>(`/signals/${encodeURIComponent(id)}/intelligence${qs(asOf ? `as_of=${encodeURIComponent(asOf)}` : "", pfParam(pf))}`),
  outcomeCheck: () => request<OutcomeCheck>("/evidence/outcome-check"),
  signalAnalogues: (id: string) => request<AnalogueSet>(`/signals/${encodeURIComponent(id)}/analogues`),
  scenarioHistoryCheck: (id: string, scale = 1) =>
    request<ScenarioHistoryCheck>(`/scenarios/${encodeURIComponent(id)}/history-check?severity_scale=${scale}`),
  signalRelevance: (id: string, pf: string | null = null) =>
    request<PortfolioRelevance>(`/signals/${encodeURIComponent(id)}/relevance${qs(pfParam(pf))}`),
  analyze: (body: AnalyzeRequest) => request<AnalyzeResponse>("/analyze", { method: "POST", body: JSON.stringify(body) }),
  liveStatus: () => request<LiveStatus>("/live/status"),
  liveRefresh: () => request<LiveStatus>("/live/refresh", { method: "POST" }),
  scopeInfo: () => request<ScopeInfo>("/scope"),
  scenarios: () => request<ScenarioList>("/scenarios"),
  pipelineReport: () => request<PipelineReport>("/pipeline/report"),
  sentimentModel: () => request<SentimentModelCard>("/models/sentiment"),
  eventModel: () => request<EventModelCard>("/models/event"),
  impactModel: () => request<ImpactModelCard>("/models/impact"),
  evidence: () => request<EvidenceBundle>("/evidence"),
  portfolioSummary: (pf: string | null = null) => request<PortfolioSummary>(`/portfolio/summary${qs(pfParam(pf))}`),
  portfolioExposure: (pf: string | null = null) => request<PortfolioExposure>(`/portfolio/exposure${qs(pfParam(pf))}`),
  portfolios: () => request<PortfolioListItem[]>("/portfolios"),
  portfolio: (id: string) => request<PortfolioView>(`/portfolios/${encodeURIComponent(id)}`),
  createPortfolio: (body: PortfolioInput) => request<PortfolioView>("/portfolios", { method: "POST", body: JSON.stringify(body) }),
  updatePortfolio: (id: string, body: PortfolioInput) =>
    request<PortfolioView>(`/portfolios/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) }),
  deletePortfolio: (id: string) => request<void>(`/portfolios/${encodeURIComponent(id)}`, { method: "DELETE" }),
  duplicatePortfolio: (id: string) => request<PortfolioView>(`/portfolios/${encodeURIComponent(id)}/duplicate`, { method: "POST" }),
  validatePortfolio: (body: PortfolioInput) => request<ResolvedPortfolio>("/portfolios/validate", { method: "POST", body: JSON.stringify(body) }),
  parsePortfolio: (body: { text: string; base_currency?: string; name?: string }) =>
    request<ParseResult>("/portfolios/parse", { method: "POST", body: JSON.stringify(body) }),
  portfolioExposureDetail: (id: string) => request<PortfolioExposureDetail>(`/portfolios/${encodeURIComponent(id)}/exposure`),
  exposureChain: (runId: string) => request<ExposureChain>(`/stress-runs/${encodeURIComponent(runId)}/exposure-chain`),
  comparePortfolios: (body: CompareRequest) => request<PortfolioComparison>("/portfolios/compare", { method: "POST", body: JSON.stringify(body) }),
  stressTest: (body: StressRequest) =>
    request<StressResult>("/stress-test", { method: "POST", body: JSON.stringify(body) }),
};
