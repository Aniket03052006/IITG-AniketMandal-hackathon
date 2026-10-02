export type Band = "low" | "mod" | "high" | "crit";

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
  low: { band: "low", label: "Low", text: "text-sev-low", bg: "bg-sev-low", dim: "bg-sev-low-dim", border: "border-sev-low" },
  mod: { band: "mod", label: "Moderate", text: "text-sev-mod", bg: "bg-sev-mod", dim: "bg-sev-mod-dim", border: "border-sev-mod" },
  high: { band: "high", label: "High", text: "text-sev-high", bg: "bg-sev-high", dim: "bg-sev-high-dim", border: "border-sev-high" },
  crit: { band: "crit", label: "Critical", text: "text-sev-crit", bg: "bg-sev-crit", dim: "bg-sev-crit-dim", border: "border-sev-crit" },
};

/** Presentation bands for the 1-10 impact scale. These are display groupings, not model facts. */
export function severityBand(score: number): BandInfo {
  if (score >= 9) return BANDS.crit;
  if (score >= 7) return BANDS.high;
  if (score >= 4) return BANDS.mod;
  return BANDS.low;
}

export function sentimentLabel(score: number): "Negative" | "Neutral" | "Positive" {
  if (score <= -0.15) return "Negative";
  if (score >= 0.15) return "Positive";
  return "Neutral";
}
