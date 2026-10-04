import type { RiskAssessment, SemanticReading } from "../api/types";

/** What each backend `Kind` is called. They stay separate everywhere: source text, an AI reading, a judgement prior, market state, a reference model, an assumption, a realised outcome. */
export const ASSESSMENT_KIND: Record<string, { label: string; says: string }> = {
  SOURCE: { label: "Source text", says: "Taken from the report itself." },
  EXTRACTION: { label: "Text reading", says: "A reading of the text, by a language model or by deterministic rules (the mode is stated)." },
  JUDGEMENT_PRIOR: { label: "Judgement prior", says: "A configured weight or prior: a documented judgement, not fitted to outcomes." },
  MARKET_STATE: { label: "Market state", says: "An observation of the market that was available when the report appeared." },
  MODEL_REFERENCE: { label: "Reference model", says: "A trained model's output, experimental, shown for comparison." },
  SCENARIO_ASSUMPTION: { label: "Scenario assumption", says: "A chosen shock run through a deterministic engine: a simulation, not a forecast." },
  REALISED: { label: "Realised outcome", says: "What the market did afterwards. Display only: never an input." },
};

export const ENTITY_KIND_LABEL: Record<string, string> = {
  COMPANY: "Company",
  INSTITUTION: "Institution",
  REGULATOR: "Regulator",
  GOVERNMENT: "Government",
  OTHER: "Other",
};

export const ASSET_LABEL: Record<string, string> = {
  EQUITY: "Equities",
  BOND: "Bonds",
  LOAN: "Loans",
  DERIVATIVE: "Derivatives",
  COMMODITY: "Commodities",
  FX: "Currencies",
};

export const SUPPORT_LABEL: Record<string, string> = {
  event_type: "event type",
  sentiment: "tone",
  entity: "entity",
  sector: "sector",
  region: "region",
  severity: "severity",
};

export const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;
export const pc = (p: number) => `${Math.round(p * 100)}%`;

/** "Rule-based demo mode" or "AI-assisted (model name)": the one phrase that says what read the text. */
export function modeLabel(a: Pick<RiskAssessment, "extraction">): string {
  const e = a.extraction;
  return e.mode === "LLM" ? `AI-assisted reading${e.model_id ? ` · ${e.model_id}` : ""}` : "Rule-based reading";
}

/** The sector a stress scenario would bind to, as the backend reads it: the first named. */
export const primarySector = (r: SemanticReading): string | null => r.sectors[0] ?? null;

/** Split `text` into plain and highlighted runs from non-overlapping-by-construction spans (overlaps are merged). */
export function segments(text: string, spans: { start: number; end: number; supports: string }[]): { text: string; hit: string[] }[] {
  const cuts = new Set<number>([0, text.length]);
  for (const s of spans) {
    if (s.start >= 0 && s.end <= text.length && s.end > s.start) {
      cuts.add(s.start);
      cuts.add(s.end);
    }
  }
  const pts = [...cuts].sort((a, b) => a - b);
  const out: { text: string; hit: string[] }[] = [];
  for (let i = 0; i + 1 < pts.length; i++) {
    const [a, b] = [pts[i]!, pts[i + 1]!];
    const hit = [...new Set(spans.filter((s) => s.start <= a && s.end >= b).map((s) => s.supports))];
    out.push({ text: text.slice(a, b), hit });
  }
  return out;
}

/** One sentence naming the factors that pushed the severity up, from the computed drivers (never free text). */
export function driversLede(sev: { drivers: { text: string; direction: string }[] }): string {
  const up = sev.drivers.filter((d) => d.direction === "UP").slice(0, 3).map((d) => d.text.replace(/ \(.*\)$/, ""));
  const down = sev.drivers.filter((d) => d.direction === "DOWN").slice(0, 2).map((d) => d.text.replace(/ \(.*\)$/, ""));
  // lower-case the first letter of an ordinary word, but leave an acronym ("M&A", "VIX") alone
  const lower = (t: string) => (/^[A-Z][a-z]/.test(t) ? t.charAt(0).toLowerCase() + t.slice(1) : t);
  const parts: string[] = [];
  if (up.length) parts.push(`Raised by ${up.map(lower).join("; ")}.`);
  if (down.length) parts.push(`Held down by ${down.map(lower).join("; ")}.`);
  return parts.join(" ") || "Every factor sits near the middle of its range.";
}
