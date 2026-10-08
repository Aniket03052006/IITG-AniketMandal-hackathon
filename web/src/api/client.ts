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
  ReviewDecision,
  ReviewDecisionInput,
  ReviewQueue,
  LiveSourceKind,
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
  PortfolioFlow,
  PortfolioMateriality,
  AutoStressRequest,
  AutoStressResult,
  StressAttribution,
  ConcentrationView,
  OverlapView,
  AdjustmentState,
  ValidationReport,
  ChangeSet,
  Brief,
  EventMarketView,
  EventMemory,
  MarketTimeline,
  MonitorCycle,
  MonitorMode,
  MonitorStatus,
  Watchlist,
  WatchlistActivity,
  WatchlistInput,
  WatchVocabulary,
  LabComparison,
  LabOptions,
  LabPlan,
  LabResult,
  ScenarioRequest,
  ReverseStressRequest,
  ReverseStressResult,
  Explanation,
  ExplainSubject,
  Digest,
  Feedback,
  FeedbackInput,
  FeedbackStats,
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
      else if (Array.isArray(body?.detail?.issues)) detail = body.detail.issues.map((i: { path: string | null; message: string }) => (i.path ? `${i.path}: ` : "") + i.message).join("; ");
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
  liveSetState: (body: { enabled: boolean; source?: LiveSourceKind | null }) =>
    request<LiveStatus>("/live/state", { method: "PUT", body: JSON.stringify(body) }),
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
  propagation: (id: string, pf: string | null = null) => request<PortfolioFlow>(`/signals/${encodeURIComponent(id)}/propagation${qs(pfParam(pf))}`),
  materiality: (id: string, pf: string | null = null) => request<PortfolioMateriality>(`/signals/${encodeURIComponent(id)}/materiality${qs(pfParam(pf))}`),
  portfolioStress: (id: string, body: AutoStressRequest) =>
    request<AutoStressResult>(`/signals/${encodeURIComponent(id)}/portfolio-stress`, { method: "POST", body: JSON.stringify(body) }),
  attribution: (runId: string) => request<StressAttribution>(`/stress-runs/${encodeURIComponent(runId)}/attribution`),
  concentration: (pf: string | null = null) => request<ConcentrationView>(`/concentration${qs(pfParam(pf))}`),
  overlaps: (pf: string | null = null, signalId: string | null = null) =>
    request<OverlapView>(`/concentration/overlaps${qs(pfParam(pf), signalId ? `signal_id=${encodeURIComponent(signalId)}` : "")}`),
  adjustments: () => request<AdjustmentState>("/adjustments"),
  validateAdjustments: (values: Record<string, unknown>) =>
    request<ValidationReport>("/adjustments/validate", { method: "POST", body: JSON.stringify({ values }) }),
  putAdjustments: (values: Record<string, unknown>) => request<AdjustmentState>("/adjustments", { method: "PUT", body: JSON.stringify({ values }) }),
  resetAdjustment: (path: string) => request<AdjustmentState>(`/adjustments?path=${encodeURIComponent(path)}`, { method: "DELETE" }),
  resetAdjustments: () => request<AdjustmentState>("/adjustments/reset", { method: "POST" }),
  monitorStatus: (mode: MonitorMode) => request<MonitorStatus>(`/monitor/status${qs(`mode=${mode}`)}`),
  monitorCycles: () => request<MonitorCycle[]>("/monitor/cycles"),
  monitorChanges: (q: { mode: MonitorMode; cycle?: number | null; window?: number; pf?: string | null }) =>
    request<ChangeSet>(`/monitor/changes${qs(`mode=${q.mode}`, q.cycle != null ? `cycle=${q.cycle}` : "", q.window ? `window=${q.window}` : "", pfParam(q.pf ?? null))}`),
  eventExternalMarkets: (id: string, pf: string | null = null) => request<EventMarketView>(`/events/${encodeURIComponent(id)}/external-markets${qs(pfParam(pf))}`),
  eventMarketTimeline: (id: string, pf: string | null = null) => request<MarketTimeline>(`/events/${encodeURIComponent(id)}/market-timeline${qs(pfParam(pf))}`),
  eventBrief: (id: string, q: { pf?: string | null; cycle?: number | null } = {}) =>
    request<Brief>(`/events/${encodeURIComponent(id)}/brief${qs(q.cycle != null ? `cycle=${q.cycle}` : "", pfParam(q.pf ?? null))}`),
  eventBriefMarkdown: async (id: string, q: { pf?: string | null; cycle?: number | null } = {}): Promise<string> => {
    const res = await fetch(`${BASE}/events/${encodeURIComponent(id)}/brief${qs("format=md", q.cycle != null ? `cycle=${q.cycle}` : "", pfParam(q.pf ?? null))}`, { headers: { Accept: "text/markdown" } });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.text();
  },
  eventTimeline: (id: string, pf: string | null = null) => request<EventMemory>(`/events/${encodeURIComponent(id)}/timeline${qs(pfParam(pf))}`),
  watchlists: () => request<{ watchlists: Watchlist[] }>("/watchlists"),
  watchVocabulary: () => request<WatchVocabulary>("/watchlists/vocabulary"),
  createWatchlist: (body: WatchlistInput) => request<Watchlist>("/watchlists", { method: "POST", body: JSON.stringify(body) }),
  updateWatchlist: (id: string, body: WatchlistInput) => request<Watchlist>(`/watchlists/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteWatchlist: (id: string) => request<void>(`/watchlists/${encodeURIComponent(id)}`, { method: "DELETE" }),
  watchlistActivity: (id: string, q: { mode: MonitorMode; cycle?: number | null; window?: number; pf?: string | null }) =>
    request<WatchlistActivity>(`/watchlists/${encodeURIComponent(id)}/activity${qs(`mode=${q.mode}`, q.cycle != null ? `cycle=${q.cycle}` : "", q.window ? `window=${q.window}` : "", pfParam(q.pf ?? null))}`),
  labOptions: (pf: string | null = null) => request<LabOptions>(`/lab/options${qs(pfParam(pf))}`),
  runScenario: (body: ScenarioRequest) => request<LabResult>("/scenarios", { method: "POST", body: JSON.stringify(body) }),
  validateScenario: (body: ScenarioRequest) => request<LabPlan>("/scenarios/validate", { method: "POST", body: JSON.stringify(body) }),
  compareScenarios: (body: { scenarios: ScenarioRequest[]; portfolio_id?: string | null }) =>
    request<LabComparison>("/scenarios/compare", { method: "POST", body: JSON.stringify(body) }),
  reverseStress: (body: ReverseStressRequest) => request<ReverseStressResult>("/reverse-stress", { method: "POST", body: JSON.stringify(body) }),
  eventExplanation: (id: string, subject: ExplainSubject, q: { cycle?: number | null; changeId?: string | null; pf?: string | null } = {}) =>
    request<Explanation>(`/events/${encodeURIComponent(id)}/explanation${qs(`subject=${subject}`, q.cycle != null ? `cycle=${q.cycle}` : "", q.changeId ? `change_id=${encodeURIComponent(q.changeId)}` : "", pfParam(q.pf ?? null))}`),
  explainScenario: (body: ScenarioRequest) => request<Explanation>("/scenarios/explanation", { method: "POST", body: JSON.stringify(body) }),
  explainReverse: (body: ReverseStressRequest) => request<Explanation>("/reverse-stress/explanation", { method: "POST", body: JSON.stringify(body) }),
  monitorDigest: (q: { mode: MonitorMode; cycle?: number | null; window?: number; pf?: string | null }) =>
    request<Digest>(`/monitor/digest${qs(`mode=${q.mode}`, q.cycle != null ? `cycle=${q.cycle}` : "", q.window ? `window=${q.window}` : "", pfParam(q.pf ?? null))}`),
  reviewQueue: (q: { mode: MonitorMode; status: string; pf?: string | null }) =>
    request<ReviewQueue>(`/review/queue${qs(`mode=${q.mode}`, `status=${q.status}`, pfParam(q.pf ?? null))}`),
  reviewDecide: (body: ReviewDecisionInput) =>
    request<ReviewDecision>("/review/decisions", { method: "POST", body: JSON.stringify(body) }),
  postFeedback: (body: FeedbackInput) => request<Feedback>("/feedback", { method: "POST", body: JSON.stringify(body) }),
  feedbackStats: () => request<FeedbackStats>("/feedback/statistics"),
  stressTest: (body: StressRequest) =>
    request<StressResult>("/stress-test", { method: "POST", body: JSON.stringify(body) }),
};
