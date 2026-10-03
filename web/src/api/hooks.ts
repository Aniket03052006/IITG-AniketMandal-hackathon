import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type SignalFilters } from "./client";

export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });

export const useSignals = (filters: SignalFilters) =>
  useQuery({ queryKey: ["signals", filters], queryFn: () => api.signals(filters), placeholderData: (prev) => prev });

export const useSignal = (id: string | undefined) =>
  useQuery({ queryKey: ["signal", id], queryFn: () => api.signal(id as string), enabled: !!id });

export const useSignalContext = (id: string | undefined) =>
  useQuery({ queryKey: ["signal-context", id], queryFn: () => api.signalContext(id as string), enabled: !!id, staleTime: Infinity });

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
