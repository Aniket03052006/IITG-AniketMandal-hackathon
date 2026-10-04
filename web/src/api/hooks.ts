import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SignalFilters } from "./client";

export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });

export const useSignals = (filters: SignalFilters) =>
  useQuery({ queryKey: ["signals", filters], queryFn: () => api.signals(filters), placeholderData: (prev) => prev });

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

export const useSignalRelevance = (id: string | undefined) =>
  useQuery({ queryKey: ["signal-relevance", id], queryFn: () => api.signalRelevance(id as string), enabled: !!id, staleTime: Infinity });

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

export const usePortfolioSummary = () => useQuery({ queryKey: ["pf-summary"], queryFn: api.portfolioSummary });

export const usePortfolioExposure = () => useQuery({ queryKey: ["pf-exposure"], queryFn: api.portfolioExposure });

export const useStressTest = () => useMutation({ mutationFn: api.stressTest });

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
