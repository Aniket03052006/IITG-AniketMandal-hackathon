import type { ImpactAssessment, RiskSignal } from "../api/types";
import { pct, sigma } from "./format";
import { featureInfo } from "./featureLabels";
import { severityBand } from "./severity";

/** One plain sentence about the impact, built only from fields the API returned. */
export function impactSentence(s: RiskSignal): string {
  const i = s.impact;
  if (!i) return "";
  const band = severityBand(i.score).label;
  if (s.data_origin === "DEMO_FIXTURE") return `${band}: a hand-authored fixture value, not a measurement.`;
  if (i.score_low != null && i.score_high != null && i.comparable_events != null) {
    return `${band} relative to comparable historical events: those scored alike realised anywhere from ${i.score_low} to ${i.score_high} out of 10.`;
  }
  return `${band} by a fixed placeholder rule. It has no uncertainty range and has not been tested against market outcomes.`;
}

export interface DriverLine {
  feature: string;
  label: string;
  contribution: number;
}

/** The additive attributions with plain names, largest first; baseline and the lump of small ones excluded. */
export function driverLines(i: ImpactAssessment, categoryLabel?: (id: string) => string): DriverLine[] {
  return i.drivers
    .filter((d) => d.feature !== "baseline" && !/^\d+ other features$/.test(d.feature))
    .map((d) => ({ feature: d.feature, label: featureInfo(d.feature, categoryLabel).label, contribution: d.contribution }))
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
}

/** "Mostly because X and Y; held back by Z." Attribution of the model, not a cause in the market. */
export function driversSentence(lines: DriverLine[]): string {
  const up = lines.filter((l) => l.contribution > 0.02).slice(0, 2);
  const down = lines.filter((l) => l.contribution < -0.02).slice(0, 1);
  if (!up.length && !down.length) return "No single input moves the estimate much: it sits close to the model's typical output.";
  const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);
  const parts: string[] = [];
  if (up.length) parts.push(`Pushed up mainly by ${up.map((u) => lower(u.label)).join(" and ")}`);
  if (down.length) parts.push(`held back by ${lower(down[0]!.label)}`);
  return `${parts.join("; ")}.`;
}

export const comparableLine = (i: ImpactAssessment, base?: number): string | null =>
  i.comparable_events != null && i.p_extreme != null
    ? `${pct(i.p_extreme, 1)} of the ${i.comparable_events.toLocaleString("en-US")} comparable events realised a move of 3σ or more${base != null ? `, against ${pct(base, 1)} of all events` : ""}.`
    : null;

export const predictedLine = (i: ImpactAssessment): string | null => (i.predicted_severity != null ? `${sigma(i.predicted_severity)} expected move` : null);
