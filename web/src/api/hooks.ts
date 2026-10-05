import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useActivePortfolio } from "../lib/portfolio";
import { api, type SignalFilters } from "./client";
import type { CompareRequest, PortfolioInput, StressRequest } from "./types";

export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });

/** Relevance on each row reads the active portfolio (null = the synthetic default, so default requests are unchanged). */
export const useSignals = (filters: SignalFilters) => {
  const pf = useActivePortfolio();
  const f = pf ? { ...filters, portfolio_id: pf } : filters;
  return useQuery({ queryKey: ["signals", f], queryFn: () => api.signals(f), placeholderData: (prev) => prev });
};

export const useSignal = (id: string | undefined) =>
  useQuery({ queryKey: ["signal", id], queryFn: () => api.signal(id as string), enabled: !!id });

export const useSignalContext = (id: string | undefined) =>
  useQuery({ queryKey: ["signal-context", id], queryFn: () => api.signalContext(id as string), enabled: !!id, staleTime: Infinity });

/** The risk assessment (reading, severity, threshold). Absent (404) in the demo profile: callers fall back to the older impact view. */
export const useAssessment = (id: string | undefined, enabled = true) =>
  useQuery({ queryKey: ["assessment", id], queryFn: () => api.assessment(id as string), enabled: !!id && enabled, staleTime: Infinity, retry: false });

export const useSignalEvidence = (id: string | undefined, enabled = true) =>
  useQuery({ queryKey: ["signal-evidence", id], queryFn: () => api.signalEvidence(id as string), enabled: !!id && enabled, staleTime: Infinity, retry: false });

export const useSignalTimeline = (id: string | undefined, enabled = true) =>
  useQuery({ queryKey: ["signal-timeline", id], queryFn: () => api.signalTimeline(id as string), enabled: !!id && enabled, staleTime: Infinity, retry: false });

export const useOutcomeCheck = (enabled: boolean) =>
  useQuery({ queryKey: ["outcome-check"], queryFn: api.outcomeCheck, enabled, staleTime: Infinity, retry: false });

export const useSignalAnalogues = (id: string | undefined, enabled = true) =>
  useQuery({ queryKey: ["signal-analogues", id], queryFn: () => api.signalAnalogues(id as string), enabled: !!id && enabled, staleTime: Infinity, retry: false });

export const useScenarioHistoryCheck = (id: string | undefined, scale = 1, enabled = true) =>
  useQuery({ queryKey: ["scenario-history", id, scale], queryFn: () => api.scenarioHistoryCheck(id as string, scale), enabled: !!id && enabled, staleTime: Infinity, retry: false });

export const useSignalRelevance = (id: string | undefined) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["signal-relevance", id, pf], queryFn: () => api.signalRelevance(id as string, pf), enabled: !!id, staleTime: Infinity });
};

export const useAnalyze = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.analyze,
    onSuccess: () => {
      // a new signal changes the feed, the headline counts and the live counter
      qc.invalidateQueries({ queryKey: ["signals"] });
      qc.invalidateQueries({ queryKey: ["live-status"] });
    },
  });
};

/** Polls only when a live source is on (`enabled`); the feed refetches when `seq` moves, not on a timer of its own. */
export const useLiveStatus = (enabled: boolean, poll: boolean, everyMs = 10_000) =>
  useQuery({ queryKey: ["live-status"], queryFn: api.liveStatus, enabled, refetchInterval: poll ? everyMs : false, staleTime: 5_000 });

export const useLiveRefresh = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.liveRefresh,
    onSuccess: (st) => {
      qc.setQueryData(["live-status"], st);
      qc.invalidateQueries({ queryKey: ["signals"] });
    },
  });
};

export const useScopeInfo = (enabled: boolean) =>
  useQuery({ queryKey: ["scope-info"], queryFn: api.scopeInfo, staleTime: Infinity, enabled });

export const useScenarios = () => useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios, staleTime: Infinity });

export const usePortfolioSummary = () => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["pf-summary", pf], queryFn: () => api.portfolioSummary(pf) });
};

export const usePortfolioExposure = () => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["pf-exposure", pf], queryFn: () => api.portfolioExposure(pf) });
};

/** Stresses the ACTIVE portfolio (the synthetic default when none is chosen): the id is added here so no caller can forget it. */
export const useStressTest = () => {
  const pf = useActivePortfolio();
  return useMutation({ mutationFn: (body: StressRequest) => api.stressTest(pf ? { ...body, portfolio_id: pf } : body) });
};

// ---- personal portfolios (optional)
export const usePortfolios = () => useQuery({ queryKey: ["portfolios"], queryFn: api.portfolios, staleTime: 10_000 });

export const usePortfolio = (id: string | undefined) =>
  useQuery({ queryKey: ["portfolio", id], queryFn: () => api.portfolio(id as string), enabled: !!id });

export const usePortfolioExposureDetail = (id: string | null | undefined) =>
  useQuery({ queryKey: ["pf-exposure-detail", id ?? "default"], queryFn: () => api.portfolioExposureDetail(id ?? "default") });

export const useExposureChain = (runId: string | undefined) =>
  useQuery({ queryKey: ["exposure-chain", runId], queryFn: () => api.exposureChain(runId as string), enabled: !!runId, staleTime: Infinity, retry: false });

export const useComparePortfolios = () => useMutation({ mutationFn: (b: CompareRequest) => api.comparePortfolios(b) });

export const useValidatePortfolio = () => useMutation({ mutationFn: (b: PortfolioInput) => api.validatePortfolio(b) });

export const useParsePortfolio = () => useMutation({ mutationFn: api.parsePortfolio });

/** Create / update / delete / duplicate refresh the list and everything keyed by the portfolio. */
export const usePortfolioMutations = () => {
  const qc = useQueryClient();
  const done = () => {
    qc.invalidateQueries({ queryKey: ["portfolios"] });
    qc.invalidateQueries({ queryKey: ["portfolio"] });
    qc.invalidateQueries({ queryKey: ["pf-summary"] });
    qc.invalidateQueries({ queryKey: ["pf-exposure"] });
    qc.invalidateQueries({ queryKey: ["pf-exposure-detail"] });
    qc.invalidateQueries({ queryKey: ["signal-relevance"] });
    qc.invalidateQueries({ queryKey: ["signals"] });
  };
  return {
    create: useMutation({ mutationFn: api.createPortfolio, onSuccess: done }),
    update: useMutation({ mutationFn: (a: { id: string; body: PortfolioInput }) => api.updatePortfolio(a.id, a.body), onSuccess: done }),
    remove: useMutation({ mutationFn: api.deletePortfolio, onSuccess: done }),
    duplicate: useMutation({ mutationFn: api.duplicatePortfolio, onSuccess: done }),
  };
};

export const usePipelineReport = (enabled: boolean) =>
  useQuery({ queryKey: ["pipeline-report"], queryFn: api.pipelineReport, staleTime: Infinity, enabled });

export const useEventModel = (enabled: boolean) =>
  useQuery({ queryKey: ["event-model"], queryFn: api.eventModel, staleTime: Infinity, enabled });

export const useSentimentModel = (enabled: boolean) =>
  useQuery({ queryKey: ["sentiment-model"], queryFn: api.sentimentModel, staleTime: Infinity, enabled });

export const useImpactModel = (enabled: boolean) =>
  useQuery({ queryKey: ["impact-model"], queryFn: api.impactModel, staleTime: Infinity, enabled });

export const useEvidence = (enabled: boolean) =>
  useQuery({ queryKey: ["evidence"], queryFn: api.evidence, staleTime: Infinity, enabled });

/** The active portfolio as a list item (null = the default). If the chosen id no longer exists (deleted elsewhere) it falls back to the default. */
export const useActivePortfolioItem = () => {
  const id = useActivePortfolio();
  const list = usePortfolios();
  const item = id ? list.data?.find((p) => p.id === id) : list.data?.find((p) => p.kind === "DEFAULT");
  const stale = !!id && !!list.data && !item;
  return { id: stale ? null : id, item: stale ? list.data?.find((p) => p.kind === "DEFAULT") : item, stale, loading: list.isLoading };
};
