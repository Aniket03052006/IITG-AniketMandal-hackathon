import { describe, expect, it } from "vitest";
import type { RiskSignal, SignalContext } from "../api/types";
import { assessmentIndex, buildMoments, hiddenCountAt, phaseAt, visibleAt } from "./timeline";

const signal = {
  id: "sig_x",
  document: { source: "example.com", published_at: "2026-09-30T03:00:00Z" },
  provenance: { timestamp_origin: "SOURCE" },
  impact: { predicted_severity: 1.66 },
  evidence: {
    corroborating: [
      { source: "other.com", source_type: "NEWS", published_at: "2026-09-30T09:30:00Z", headline: "Same story", relation: "SAME_EVENT", url: "https://o/1" },
      { source: "old.com", source_type: "NEWS", published_at: "2026-09-29T00:00:00Z", headline: "Earlier than canonical?", relation: "SAME_EVENT", url: "https://o/0" },
    ],
  },
} as unknown as RiskSignal;

const ctx = {
  filings: [
    { accession: "A1", form: "8-K", items: ["5.02", "7.01"], acceptance_utc: "2026-09-17T00:21:00Z", hours_from_report: -314.6, role: "FEEDS_MODEL", role_note: "the most recent 8-K", known_at_assessment: true },
    { accession: "A2", form: "8-K", items: ["2.02", "2.05"], acceptance_utc: "2026-10-02T00:15:00Z", hours_from_report: 45.25, role: "AFTER_REPORT", role_note: "x", known_at_assessment: false },
  ],
  outcome: { scope: "ISSUER", ticker: "NKE", session: "2026-09-30", window_sessions: 2, abs_z: 0.41, z: -0.41, score: 1, note: "" },
} as unknown as SignalContext;

describe("timeline moments", () => {
  const m = buildMoments(signal, ctx);

  it("orders by time, then lane, with the realised outcome last", () => {
    expect(m.map((x) => x.kind)).toEqual(["filing", "report", "assessment", "coverage", "filing", "outcome"]);
    expect(m[m.length - 1]!.lane).toBe("realised");
  });

  it("puts only things before the report in the 'known' lane, and everything after it in 'later'", () => {
    const t0 = Date.parse(signal.document.published_at);
    for (const x of m) {
      if (x.lane === "known" && x.at) expect(Date.parse(x.at)).toBeLessThanOrEqual(t0);
      if (x.lane === "later" && x.at) expect(Date.parse(x.at)).toBeGreaterThanOrEqual(t0);
    }
  });

  it("drops a corroborating report that predates the canonical one rather than inventing an order", () => {
    expect(m.some((x) => x.title.includes("old.com"))).toBe(false);
  });

  it("starts at the assessment and never returns a later fact in an earlier state (future invariance)", () => {
    const a = assessmentIndex(m);
    const atAssessment = visibleAt(m, a);
    expect(atAssessment.every((x) => x.lane === "known")).toBe(true);
    expect(atAssessment.some((x) => x.lane === "later" || x.lane === "realised")).toBe(false);
    expect(hiddenCountAt(m, a)).toBe(m.length - a - 1);
    // before the report: not even the report or the scores
    const before = visibleAt(m, 0);
    expect(before.map((x) => x.kind)).toEqual(["filing"]);
    expect(phaseAt(m, 0)).toBe("before");
    expect(phaseAt(m, a)).toBe("assessed");
    expect(phaseAt(m, a + 1)).toBe("later");
    expect(phaseAt(m, m.length - 1)).toBe("realised");
  });

  it("says the later report did not change the estimate, and marks a filing after the replay clock", () => {
    expect(m.find((x) => x.kind === "coverage")!.sub).toMatch(/did not change the estimate/);
    expect(m.filter((x) => x.kind === "filing")[1]!.sub).toMatch(/after EventShock's replay clock/);
  });

  it("with no context there is just the report and the assessment", () => {
    const only = buildMoments({ ...signal, evidence: { corroborating: [] } } as unknown as RiskSignal, undefined);
    expect(only.map((x) => x.kind)).toEqual(["report", "assessment"]);
  });

  it("shows no timeline of coverage when the time is a replay-assigned clock", () => {
    const syn = { ...signal, provenance: { timestamp_origin: "SYNTHETIC_REPLAY_CLOCK" } } as unknown as RiskSignal;
    expect(buildMoments(syn, undefined).some((x) => x.kind === "coverage")).toBe(false);
  });
});
