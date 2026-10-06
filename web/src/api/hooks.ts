import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useActivePortfolio } from "../lib/portfolio";
import { api, type SignalFilters } from "./client";
import type { AutoStressRequest, CompareRequest, ExplainSubject, FeedbackInput, MonitorMode, PortfolioInput, ReverseStressRequest, ScenarioRequest, StressRequest, WatchlistInput } from "./types";

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

/** Event intelligence: scope, event grouping, evidence, novelty, velocity, contradiction, lifecycle. Absent (404) where the engine is: callers hide the panel. */
export const useIntelligence = (id: string | undefined, enabled = true, asOf: string | null = null) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["signal-intelligence", id, asOf, pf], queryFn: () => api.signalIntelligence(id as string, asOf, pf), enabled: !!id && enabled, staleTime: 15_000, retry: false });
};

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
    for (const k of ["propagation", "materiality", "concentration", "overlaps", "signal-intelligence"]) qc.invalidateQueries({ queryKey: [k] });
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

// ---- Stage 11: event -> portfolio propagation (a derived side-car; absent where the replay engine is not running)
/** Mapping, relevance and the scenario an event would generate, for the ACTIVE portfolio. */
export const usePropagation = (id: string | undefined, enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["propagation", id, pf], queryFn: () => api.propagation(id as string, pf), enabled: !!id && enabled, staleTime: 15_000, retry: false });
};

export const useMateriality = (id: string | undefined, enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["materiality", id, pf], queryFn: () => api.materiality(id as string, pf), enabled: !!id && enabled, staleTime: 15_000, retry: false });
};

/** Generates the event's scenario for the active portfolio and runs it (the portfolio id is added here so no caller can forget it). */
export const usePortfolioStress = (signalId: string | undefined) => {
  const pf = useActivePortfolio();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Omit<AutoStressRequest, "portfolio_id"> = {}) => api.portfolioStress(signalId as string, pf ? { ...body, portfolio_id: pf } : body),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["propagation", signalId] });
      if (r.run) qc.setQueryData(["attribution", r.run.run_id], r.attribution ?? undefined);
    },
  });
};

export const useAttribution = (runId: string | undefined, enabled = true) =>
  useQuery({ queryKey: ["attribution", runId], queryFn: () => api.attribution(runId as string), enabled: !!runId && enabled, staleTime: Infinity, retry: false });

/** Concentration of the ACTIVE portfolio, or of the saved one named by `pfId` (null = the synthetic default). */
export const useConcentration = (enabled = true, pfId?: string | null) => {
  const active = useActivePortfolio();
  const pf = pfId === undefined ? active : pfId;
  return useQuery({ queryKey: ["concentration", pf], queryFn: () => api.concentration(pf), enabled, staleTime: 15_000, retry: false });
};

export const useOverlaps = (signalId: string | null = null, enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["overlaps", pf, signalId], queryFn: () => api.overlaps(pf, signalId), enabled, staleTime: 15_000, retry: false });
};

// ---- manual adjustment of the side-cars
export const useAdjustments = (enabled = true) => useQuery({ queryKey: ["adjustments"], queryFn: api.adjustments, enabled, staleTime: 5_000 });

/** Everything an adjustment can change is refetched: the derived side-cars read the new values on the next request. */
export const useAdjustmentMutations = () => {
  const qc = useQueryClient();
  const done = (state: unknown) => {
    qc.setQueryData(["adjustments"], state);
    for (const k of ["signal-intelligence", "signal-relevance", "signals", "propagation", "materiality", "attribution", "concentration", "overlaps", "pf-exposure-detail", "exposure-chain"]) {
      qc.invalidateQueries({ queryKey: [k] });
    }
  };
  return {
    validate: useMutation({ mutationFn: api.validateAdjustments }),
    save: useMutation({ mutationFn: api.putAdjustments, onSuccess: done }),
    reset: useMutation({ mutationFn: api.resetAdjustment, onSuccess: done }),
    resetAll: useMutation({ mutationFn: api.resetAdjustments, onSuccess: done }),
  };
};

/** The monitor: what changed. REPLAY is a deterministic clock over the frozen signals (always available); LIVE needs the live feed. Absent (404) in the demo profile. */
export const useMonitorStatus = (mode: MonitorMode, enabled = true) =>
  useQuery({ queryKey: ["monitor-status", mode], queryFn: () => api.monitorStatus(mode), enabled, staleTime: 10_000, retry: false });

export const useMonitorCycles = (enabled = true) =>
  useQuery({ queryKey: ["monitor-cycles"], queryFn: api.monitorCycles, enabled, staleTime: Infinity, retry: false });

export const useMonitorChanges = (mode: MonitorMode, cycle: number | null, window: number, enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({
    queryKey: ["monitor-changes", mode, cycle, window, pf],
    queryFn: () => api.monitorChanges({ mode, cycle, window, pf }),
    enabled,
    staleTime: mode === "LIVE" ? 5_000 : 60_000,
    retry: false,
    placeholderData: (prev) => prev,
  });
};

/** The event as an evolving narrative: reports classified as new / continuation / update / escalation / de-escalation / resolution, with its history by cycle. */
export const useEventTimeline = (id: string | undefined, enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["event-timeline", id, pf], queryFn: () => api.eventTimeline(id as string, pf), enabled: !!id && enabled, staleTime: 30_000, retry: false });
};

/** EXTERNAL MARKET OBSERVATION for an event (an event id or any signal in it). Never an input to a risk number; gate on `capabilities.external_markets`. */
export const useExternalMarkets = (id: string | undefined, enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["external-markets", id, pf], queryFn: () => api.eventExternalMarkets(id as string, pf), enabled: !!id && enabled, staleTime: 60_000, retry: false });
};

/** The executive risk brief of an event for the active portfolio. Fetched only while its drawer is open (`enabled`). */
export const useEventBrief = (id: string | undefined, enabled: boolean, cycle: number | null = null) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["brief", id, cycle, pf], queryFn: () => api.eventBrief(id as string, { pf, cycle }), enabled: !!id && enabled, staleTime: 30_000, retry: false });
};

export const useMarketTimeline = (id: string | undefined, enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["market-timeline", id, pf], queryFn: () => api.eventMarketTimeline(id as string, pf), enabled: !!id && enabled, staleTime: 60_000, retry: false });
};

/** Persistent watchlists (replay profile). Absent (404) elsewhere: callers gate on `capabilities.watchlists`. */
export const useWatchlists = (enabled = true) => useQuery({ queryKey: ["watchlists"], queryFn: api.watchlists, enabled, staleTime: 10_000, retry: false });

export const useWatchVocabulary = (enabled = true) => useQuery({ queryKey: ["watch-vocabulary"], queryFn: api.watchVocabulary, enabled, staleTime: Infinity, retry: false });

export const useWatchlistActivity = (id: string | undefined, mode: MonitorMode, cycle: number | null, window: number, enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["watchlist-activity", id, mode, cycle, window, pf], queryFn: () => api.watchlistActivity(id as string, { mode, cycle, window, pf }), enabled: !!id && enabled, staleTime: 30_000, retry: false });
};

export const useWatchlistMutations = () => {
  const qc = useQueryClient();
  const done = () => {
    qc.invalidateQueries({ queryKey: ["watchlists"] });
    qc.invalidateQueries({ queryKey: ["watchlist-activity"] });
  };
  return {
    create: useMutation({ mutationFn: (b: WatchlistInput) => api.createWatchlist(b), onSuccess: done }),
    update: useMutation({ mutationFn: (a: { id: string; body: WatchlistInput }) => api.updateWatchlist(a.id, a.body), onSuccess: done }),
    remove: useMutation({ mutationFn: (id: string) => api.deleteWatchlist(id), onSuccess: done }),
  };
};

/** The scenario lab: build, run and compare scenarios on the unchanged stress engine. Every size a person sets is a SCENARIO ASSUMPTION. */
export const useLabOptions = (enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["lab-options", pf], queryFn: () => api.labOptions(pf), enabled, staleTime: 60_000, retry: false });
};

export const useRunScenario = () => {
  const pf = useActivePortfolio();
  return useMutation({ mutationFn: (b: ScenarioRequest) => api.runScenario({ ...b, portfolio_id: pf }) });
};

export const useCompareScenarios = () => {
  const pf = useActivePortfolio();
  return useMutation({ mutationFn: (scenarios: ScenarioRequest[]) => api.compareScenarios({ scenarios, portfolio_id: pf }) });
};

/** Reverse stress: the hypothetical shocks that would reach a target loss, searched within configured bounds and valued by the unchanged engine. */
export const useReverseStress = () => {
  const pf = useActivePortfolio();
  return useMutation({ mutationFn: (b: Omit<ReverseStressRequest, "portfolio_id">) => api.reverseStress({ ...b, portfolio_id: pf } as ReverseStressRequest) });
};

/** "Why?" as structured reasons. Fetched only when a drawer is opened (`enabled`). */
export const useEventExplanation = (id: string | undefined, subject: ExplainSubject, enabled: boolean, cycle: number | null = null, changeId: string | null = null) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["explanation", id, subject, cycle, changeId, pf], queryFn: () => api.eventExplanation(id as string, subject, { cycle, changeId, pf }), enabled: !!id && enabled, staleTime: 30_000, retry: false });
};

export const useExplainScenario = () => {
  const pf = useActivePortfolio();
  return useMutation({ mutationFn: (b: ScenarioRequest) => api.explainScenario({ ...b, portfolio_id: pf }) });
};

export const useExplainReverse = () => {
  const pf = useActivePortfolio();
  return useMutation({ mutationFn: (b: Omit<ReverseStressRequest, "portfolio_id">) => api.explainReverse({ ...b, portfolio_id: pf } as ReverseStressRequest) });
};

/** The executive digest: what should I care about right now? Ordered by a documented key, never a score. */
export const useDigest = (mode: MonitorMode, cycle: number | null, window: number, enabled = true) => {
  const pf = useActivePortfolio();
  return useQuery({ queryKey: ["digest", mode, cycle, window, pf], queryFn: () => api.monitorDigest({ mode, cycle, window, pf }), enabled, staleTime: mode === "LIVE" ? 5_000 : 60_000, retry: false, placeholderData: (prev) => prev });
};

/** Analyst feedback: recorded and counted, never ground truth, never used to change a model. */
export const useFeedbackStats = (enabled = true) => useQuery({ queryKey: ["feedback-stats"], queryFn: api.feedbackStats, enabled, staleTime: 10_000, retry: false });

export const usePostFeedback = () => {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (b: FeedbackInput) => api.postFeedback(b), onSuccess: () => qc.invalidateQueries({ queryKey: ["feedback-stats"] }) });
};
