import type { AssumptionKind, LabAssumption, LabKindInfo } from "../api/types";

/** The word every user-set size carries. A hypothetical, never a prediction. */
export const ASSUMPTION_LABEL = "SCENARIO ASSUMPTION";
export const SIMULATION_LABEL = "SCENARIO SIMULATION — NOT A PREDICTION";

export type Draft = {
  id: string;
  type: "BASE" | "CUSTOM" | "ASSESSED";
  name: string;
  rows: Row[];
  exposurePriors: boolean;
  signalId: string | null;
};
export type Row = { key: string; kind: AssumptionKind; target: string; value: string; rationale: string };

let n = 0;
export const newId = (p: string) => `${p}${++n}`;
export const blankRow = (kind: AssumptionKind = "EQUITY_MARKET"): Row => ({ key: newId("r"), kind, target: "", value: "", rationale: "" });

/** The unit a person types in: fractions as percent (-10 means -10%), basis points as bp, a multiplier as x. */
export const displayUnit = (unit: string): string => (unit === "fraction" ? "%" : unit === "bp" ? "bp" : unit === "multiplier" ? "×" : "");

export function toValue(text: string, unit: string): number | null {
  const t = text.trim().replace("−", "-");
  if (t === "" || t === "-" || t === "+") return null;
  const v = Number(t);
  if (!Number.isFinite(v)) return null;
  return unit === "fraction" ? v / 100 : v;
}

export function fromValue(v: number, unit: string): string {
  const x = unit === "fraction" ? v * 100 : v;
  return String(Math.round(x * 1e6) / 1e6);
}

export function fmt(v: number, unit: string): string {
  const sign = v < 0 ? "−" : v > 0 ? "+" : "";
  if (unit === "bp") return `${sign}${Math.abs(v).toFixed(0)} bp`;
  if (unit === "multiplier") return `×${v.toFixed(2)}`;
  return `${sign}${Math.abs(v * 100).toFixed(1)}%`;
}

export const KIND_TARGET_PLACEHOLDER: Partial<Record<AssumptionKind, string>> = {
  SECTOR: "a sector",
  ISSUER: "an issuer",
  FX: "a currency",
  CREDIT_SPREAD: "all sectors (optional)",
  RISK_FACTOR: "a risk factor",
};

export function infoOf(kinds: LabKindInfo[] | undefined, kind: AssumptionKind): LabKindInfo | undefined {
  return kinds?.find((k) => k.kind === kind);
}

/** Builds the request body from a draft. Rows with no usable number are skipped (the server would refuse them), and the caller is told how many. */
export function toRequest(d: Draft, kinds: LabKindInfo[] | undefined, riskUnit: (target: string) => string): { body: import("../api/types").ScenarioRequest; skipped: number } {
  const assumptions: LabAssumption[] = [];
  let skipped = 0;
  for (const r of d.rows) {
    const unit = r.kind === "RISK_FACTOR" ? riskUnit(r.target) : (infoOf(kinds, r.kind)?.unit ?? "fraction");
    const v = toValue(r.value, unit);
    if (v == null) {
      skipped++;
      continue;
    }
    assumptions.push({ kind: r.kind, value: v, target: r.target.trim() || null, rationale: r.rationale.trim() });
  }
  return {
    body: { scenario_type: d.type, name: d.name.trim() || null, assumptions: d.type === "CUSTOM" ? assumptions : [], signal_id: d.signalId, exposure_priors: d.exposurePriors, force: false } as import("../api/types").ScenarioRequest,
    skipped,
  };
}
