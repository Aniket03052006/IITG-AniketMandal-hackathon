import type { RiskSignal, SignalContext } from "../api/types";
import { sigma } from "./format";
import { relationNote, timestampNote } from "./provenance";

/**
 * "What did EventShock know at this moment?" as data.
 *   known    available at the time: the issuer's filings accepted before the report, and the report itself
 *   later    learned later: anything published or accepted at/after the report. Never read by the model.
 *   realised what the market did afterwards. Known only after the fact; never an input.
 * `visibleAt` is the ONLY way the UI reads the list: items after the cursor are not returned, so a later fact cannot be rendered in an
 * earlier state by accident (tested in timeline.test.ts).
 */
export type Lane = "known" | "later" | "realised";
export type MomentKind = "filing" | "report" | "assessment" | "coverage" | "outcome";

export interface Moment {
  id: string;
  at: string | null; // ISO instant; null only for the outcome (it follows every event)
  lane: Lane;
  kind: MomentKind;
  title: string;
  sub: string;
}

const KIND_ORDER: Record<MomentKind, number> = { filing: 0, report: 1, assessment: 2, coverage: 3, outcome: 4 };
const LANE_ORDER: Record<Lane, number> = { known: 0, later: 1, realised: 2 };

const hoursText = (h: number): string => {
  const a = Math.abs(h);
  if (a < 1) return `${Math.round(a * 60)} min`;
  if (a < 48) return `${a.toFixed(1).replace(/\.0$/, "")} h`;
  return `${(a / 24).toFixed(1).replace(/\.0$/, "")} days`;
};

export function buildMoments(s: RiskSignal, ctx: SignalContext | undefined): Moment[] {
  const out: Moment[] = [];
  const t0 = s.document.published_at;
  const t0ms = Date.parse(t0);

  for (const f of ctx?.filings ?? []) {
    const after = f.role === "AFTER_REPORT";
    const items = f.items.join(", ");
    const delta = after ? `${hoursText(f.hours_from_report)} after the report` : `${hoursText(f.hours_from_report)} before the report`;
    out.push({
      id: `filing-${f.accession}`,
      at: f.acceptance_utc,
      lane: after ? "later" : "known",
      kind: "filing",
      title: `${f.form} filed · item${f.items.length > 1 ? "s" : ""} ${items}`,
      sub: `${delta}. ${after ? (f.known_at_assessment ? "Not read by the model." : "Accepted after EventShock's replay clock; never read by the model.") : f.role === "FEEDS_MODEL" ? `Read by the model: ${f.role_note}.` : "On record, but no model feature reads it."}`,
    });
  }

  out.push({
    id: "report",
    at: t0,
    lane: "known",
    kind: "report",
    title: "First report published",
    sub: `${s.document.source} · ${timestampNote(s.provenance?.timestamp_origin ?? "SOURCE")}`,
  });
  out.push({
    id: "assessment",
    at: t0,
    lane: "known",
    kind: "assessment",
    title: "EventShock reads it and scores it",
    sub: "Event type, sentiment and impact are computed from this report and what was known before it, and nothing else.",
  });

  const reliable = s.provenance?.timestamp_origin !== "SYNTHETIC_REPLAY_CLOCK";
  if (reliable) {
    for (const c of s.evidence.corroborating) {
      const ms = Date.parse(c.published_at);
      if (!Number.isFinite(ms) || ms < t0ms) continue;
      out.push({
        id: `cov-${c.url ?? c.headline}`,
        at: c.published_at,
        lane: "later",
        kind: "coverage",
        title: `Another report · ${c.source}`,
        sub: `${relationNote(c.relation)}, ${hoursText((ms - t0ms) / 3_600_000)} after the first. It did not change the estimate: the model reads only the first report.`,
      });
    }
  }

  const o = ctx?.outcome;
  if (o) {
    const pred = s.impact?.predicted_severity;
    out.push({
      id: "outcome",
      at: null,
      lane: "realised",
      kind: "outcome",
      title: `Realised move ${sigma(o.abs_z)}${o.z < 0 ? " (down)" : " (up)"}`,
      sub: `${o.scope === "ISSUER" ? `${o.ticker ?? "The issuer"}'s abnormal move` : "The S&P 500's move"} over ${o.window_sessions} sessions from ${o.session}${pred != null ? `, against an estimate of ${sigma(pred)}` : ""}. Known only afterwards.`,
    });
  }

  return out.sort((a, b) => {
    const ta = a.at ? Date.parse(a.at) : Infinity;
    const tb = b.at ? Date.parse(b.at) : Infinity;
    return ta - tb || LANE_ORDER[a.lane] - LANE_ORDER[b.lane] || KIND_ORDER[a.kind] - KIND_ORDER[b.kind];
  });
}

/** Where the slider starts: the moment EventShock scored the report. */
export const assessmentIndex = (m: Moment[]): number => Math.max(0, m.findIndex((x) => x.kind === "assessment"));

/** Everything the cursor has reached, and nothing after it. */
export const visibleAt = (m: Moment[], cursor: number): Moment[] => m.slice(0, Math.max(0, Math.min(cursor, m.length - 1)) + 1);

export const hiddenCountAt = (m: Moment[], cursor: number): number => m.length - visibleAt(m, cursor).length;

export type Phase = "before" | "assessed" | "later" | "realised";

export function phaseAt(m: Moment[], cursor: number): Phase {
  const a = assessmentIndex(m);
  const cur = m[Math.max(0, Math.min(cursor, m.length - 1))];
  if (cur?.lane === "realised") return "realised";
  if (cursor < a) return "before";
  if (cursor === a) return "assessed";
  return "later";
}
