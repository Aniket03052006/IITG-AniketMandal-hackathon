import type {
  Meta,
  PipelineReport,
  PortfolioExposure,
  PortfolioSummary,
  RiskSignal,
  ScenarioList,
  SignalPage,
  StressRequest,
  StressResult,
} from "./types";

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
  return (await res.json()) as T;
}

export interface SignalFilters {
  category?: string;
  source_type?: string;
  min_impact?: number;
  q?: string;
}

export const api = {
  meta: () => request<Meta>("/meta"),
  signals: (f: SignalFilters = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== "") p.set(k, String(v));
    const qs = p.toString();
    return request<SignalPage>(`/signals${qs ? `?${qs}` : ""}`);
  },
  signal: (id: string) => request<RiskSignal>(`/signals/${encodeURIComponent(id)}`),
  scenarios: () => request<ScenarioList>("/scenarios"),
  pipelineReport: () => request<PipelineReport>("/pipeline/report"),
  portfolioSummary: () => request<PortfolioSummary>("/portfolio/summary"),
  portfolioExposure: () => request<PortfolioExposure>("/portfolio/exposure"),
  stressTest: (body: StressRequest) =>
    request<StressResult>("/stress-test", { method: "POST", body: JSON.stringify(body) }),
};
