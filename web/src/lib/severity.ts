export type Band = "negligible" | "low" | "mod" | "high" | "crit";

export interface BandInfo {
  band: Band;
  label: string;
  /** Static class names so Tailwind can see them. */
  text: string;
  bg: string;
  dim: string;
  border: string;
}

const BANDS: Record<Band, BandInfo> = {
  negligible: { band: "negligible", label: "Negligible", text: "text-sev-low", bg: "bg-sev-low", dim: "bg-sev-low-dim", border: "border-sev-low" },
  low: { band: "low", label: "Low", text: "text-sev-low", bg: "bg-sev-low", dim: "bg-sev-low-dim", border: "border-sev-low" },
  mod: { band: "mod", label: "Moderate", text: "text-sev-mod", bg: "bg-sev-mod", dim: "bg-sev-mod-dim", border: "border-sev-mod" },
  high: { band: "high", label: "High", text: "text-sev-high", bg: "bg-sev-high", dim: "bg-sev-high-dim", border: "border-sev-high" },
  crit: { band: "crit", label: "Extreme", text: "text-sev-crit", bg: "bg-sev-crit", dim: "bg-sev-crit-dim", border: "border-sev-crit" },
};

/** The five semantic bands of the 1-10 scale: 1-2 negligible, 3-4 low, 5-6 moderate, 7-8 high, 9-10 extreme. They are semantic ranges, not quotas. */
export const SCALE_BANDS: { id: Band; label: string; range: [number, number]; says: string }[] = [
  { id: "negligible", label: "Negligible", range: [1, 2], says: "routine; no market consequence" },
  { id: "low", label: "Low", range: [3, 4], says: "minor, contained, or a small favourable move" },
  { id: "mod", label: "Moderate", range: [5, 6], says: "material to one issuer or one narrow segment" },
  { id: "high", label: "High", range: [7, 8], says: "sector- or market-wide consequence, or a serious credit or geopolitical event" },
  { id: "crit", label: "Extreme", range: [9, 10], says: "threatens the stability of the financial system or global markets" },
];

export function severityBand(score: number): BandInfo {
  if (score >= 9) return BANDS.crit;
  if (score >= 7) return BANDS.high;
  if (score >= 5) return BANDS.mod;
  if (score >= 3) return BANDS.low;
  return BANDS.negligible;
}

export function sentimentLabel(score: number): "Negative" | "Neutral" | "Positive" {
  if (score <= -0.15) return "Negative";
  if (score >= 0.15) return "Positive";
  return "Neutral";
}
