import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RiskAssessment, EvidenceView, TimelineView } from "../api/types";
import { AssessmentTimeline } from "../components/assessment/AssessmentTimeline";
import { EvidenceGroups } from "../components/assessment/EvidenceGroups";
import { ModeChip } from "../components/assessment/ModeChip";
import { SeverityBreakdown } from "../components/assessment/SeverityBreakdown";
import { ThresholdNotice } from "../components/assessment/ThresholdNotice";
import { UnderstandingCard } from "../components/assessment/UnderstandingCard";
import { severityLede, segments } from "../lib/assessment";
import { ScoreBuildUp } from "../components/assessment/ScoreBuildUp";
import { RubricTable } from "../components/assessment/RubricTable";
import { ProvenanceStrip } from "../components/assessment/ProvenanceStrip";
import { ScaleBar } from "../components/assessment/ScaleBar";
import { MarketNote } from "../components/assessment/MarketNote";
import { AnalyzePage } from "./AnalyzePage";

const AS_OF = "2026-10-01T12:00:00Z";
const TEXT = "Quantum Dynamics announces a major restructuring following weaker-than-expected demand.";

const assessment = (over: Partial<RiskAssessment> = {}): RiskAssessment =>
  ({
    signal_id: "sig_q",
    headline: TEXT,
    source: "manual paste",
    source_type: "NEWS",
    published_at: AS_OF,
    ingested_at: AS_OF,
    analysed_at: AS_OF,
    timestamp_origin: "ANALYSIS_TIME",
    summary: "restructuring event (restructuring / divestiture); adverse tone.",
    extraction: { mode: "RULES", model_id: "semantics-v1", vocabulary_version: "semantics-v1", prompt_version: null, cached: false, fallback_reason: null, notes: ["Dropped entity 'Acme': it does not appear in the text."], basis: "Event class from cue phrases." },
    reading: {
      text: TEXT, event_type: "MA_CORPORATE_ACTION", event_label: "M&A / Corporate Action", event_subtype: "restructuring_divestiture", event_subtype_label: "Restructuring / divestiture",
      event_confidence: null, sentiment: -0.5, sentiment_label: "negative", sentiment_intensity: "medium", sentiment_confidence: null,
      entities: [{ name: "Quantum Dynamics", kind: "COMPANY", role: "subject", resolved: false, entity_id: null, ticker: null, sector: null }],
      primary_issuer: { entity_id: "UNKNOWN_ENTITY", name: null, ticker: null, resolved: false, note: "No company in the entity master was identified; exposure is assessed at sector / market level where the text supports it." },
      sectors: [], regions: [], asset_classes: ["EQUITY", "BOND"],
      severity_indicators: [
        { id: "restructuring", label: "Restructuring / job cuts", level: 2, polarity: "adverse", basis: "QUOTED", quote: "restructuring", reason: null },
        { id: "inflation_persistence", label: "Persistent inflation", level: 2, polarity: "adverse", basis: "INFERRED", quote: null, reason: "price pressure suggests inflation is not fading" },
      ],
      ai_rubric: null,
      uncertainty: null,
      evidence: [{ quote: "a major restructuring", start: 27, end: 48, supports: "event_type" }],
      rationale: null,
    },
    agreement: { reference_event_type: "MA_CORPORATE_ACTION", reference_event_status: "UNCERTAIN", reference_event_confidence: null, event_type_agrees: null, reference_sentiment: -0.5, sentiment_direction_agrees: true, note: "The assessment and the trained models agree (or the trained models made no firm call)." },
    severity: {
      score: 5, points: 5.2, band: "moderate", band_label: "Moderate", band_says: "material to one issuer or one narrow segment", low: 4, high: 6,
      range_basis: "Assumption sensitivity, not a statistical interval: the lowest and highest score when each judgement parameter is changed in turn.",
      basis: "SCORECARD", version: "severity-v2",
      rubric: [
        { id: "magnitude", label: "Event intensity", baseline: "1", baseline_label: "Minor", baseline_basis: ["strongest indicator: restructuring (typical level 2)"], ai: "2", ai_label: "Significant",
          ai_reason: "a restructuring is a clear consequence for the firm", ai_quote: "a major restructuring", final: "2", final_label: "Significant", final_says: "a clear, material consequence for those affected",
          origin: "HYBRID", adjustment: "AI_WITHIN_BOUND", note: "The AI moved this 1 step up from the rules, with a stated reason." },
        { id: "reach", label: "Reach", baseline: "firm", baseline_label: "One issuer", baseline_basis: ["a named company is the subject"], ai: null, ai_label: null, ai_reason: null, ai_quote: null,
          final: "firm", final_label: "One issuer", final_says: "one named company", origin: "RULES", adjustment: "NONE", note: "" },
        { id: "certainty", label: "Certainty", baseline: "confirmed", baseline_label: "Confirmed", baseline_basis: ["stated as having happened"], ai: null, ai_label: null, ai_reason: null, ai_quote: null,
          final: "confirmed", final_label: "Confirmed", final_says: "it has happened", origin: "RULES", adjustment: "NONE", note: "" },
        { id: "direction", label: "Direction", baseline: "adverse", baseline_label: "Adverse", baseline_basis: ["adverse indicators (restructuring / job cuts)"], ai: null, ai_label: null, ai_reason: null, ai_quote: null,
          final: "adverse", final_label: "Adverse", final_says: "bad for the affected parties", origin: "RULES", adjustment: "NONE", note: "" },
      ],
      steps: [
        { id: "matrix", label: "Severity matrix", origin: "HYBRID", value: "Significant × one issuer", effect_points: 4.8, running: 4.8, detail: "Magnitude 'Significant' starts at 5.4; reach 'one issuer' moves it -0.6." },
        { id: "certainty", label: "Certainty", origin: "RULES", value: "Confirmed", effect_points: 0, running: 4.8, detail: "Scales the distance above 1 by 1." },
        { id: "direction", label: "Direction", origin: "RULES", value: "Adverse", effect_points: 0, running: 4.8, detail: "Scales the distance above 1 by 1." },
        { id: "regime", label: "Market regime", origin: "DATA", value: "VIX 20.0", effect_points: 0.4, running: 5.2, detail: "VIX 20.0 from the 2026-10-01 close (1 session behind)." },
      ],
      baseline_score: 4, ai_effect: 1,
      omitted: [{ id: "novelty", label: "Novelty", reason: "No issuer was resolved, so there is no earlier report of the same issuer to compare with." }],
      market: { used: true, vix: 20.0, as_of: "2026-10-01", report_session: "2026-10-02", sessions_behind: 1, max_sessions_behind: 1, reason: "VIX 20.0 from the 2026-10-01 close (1 session behind; the last completed session before the report is 2026-10-02)." },
      reliability: { level: "moderate", score: 0.42, basis: "news source (0.70) and 0 independent report(s) that already existed at the time", note: "Reliability says how far to trust the report. It does not change the severity." },
      uncertainty: 0.5,
      formula: "raw = anchor[Significant] 5.4 + offset[One issuer] -0.6; 1 + (raw - 1) x 1 x 1; +0.40 regime; = 5.20 -> 5",
    },
    severity_note: null,
    threshold: { threshold: 7, score: 5, crosses: false, status: "BELOW_TRIGGER", message: "m", can_run_what_if: true },
    reference: { available: false, model_id: null, lifecycle: null, origin: null, score: null, score_low: null, score_high: null, note: "The trained model gave no score for this signal." },
    conflict: null,
    corroborating_at_event_time: 0,
    later_reports_excluded: 0,
    provenance: [
      { part: "Event class and subtype", origin: "RULES", detail: "cue phrases in the text" },
      { part: "Severity indicators", origin: "RULES", detail: "1 quoted, 0 matched by a configured phrase, 0 inferred by the AI (an inference is never shown as a quote)" },
      { part: "Rubric answers (magnitude, reach, certainty, direction)", origin: "HYBRID", detail: "deterministic rules, then the AI may move each answer one step" },
      { part: "Market regime", origin: "DATA", detail: "VIX 20.0 from the 2026-10-01 close" },
      { part: "Scenario", origin: "ASSUMPTION", detail: "configured shocks, labelled illustrative" },
    ],
    labels: ["AI-assisted assessment: not validated, not a forecast."],
    limitations: ["Weights and priors are documented judgements."],
    ...over,
  }) as RiskAssessment;

function wrap(ui: React.ReactElement, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("evidence highlighting", () => {
  it("splits the text at span edges and marks only what a span supports", () => {
    const segs = segments("abcdefghij", [{ start: 2, end: 5, supports: "event_type" }, { start: 4, end: 7, supports: "severity" }]);
    expect(segs.map((s) => s.text).join("")).toBe("abcdefghij");
    expect(segs.find((s) => s.text === "cd")?.hit).toEqual(["event_type"]);
    expect(segs.find((s) => s.text === "e")?.hit).toEqual(["event_type", "severity"]);
    expect(segs.find((s) => s.text === "ab")?.hit).toEqual([]);
  });
  it("ignores a span that falls outside the text", () => {
    expect(segments("abc", [{ start: 2, end: 9, supports: "sector" }])).toEqual([{ text: "abc", hit: [] }]);
  });
});

describe("the AI understanding card", () => {
  it("never makes an unknown company an issuer, and says what was checked", () => {
    wrap(<UnderstandingCard a={assessment()} />);
    expect(screen.getByText("UNKNOWN_ENTITY")).toBeInTheDocument();
    expect(screen.getByText("Quantum Dynamics")).toBeInTheDocument();
    expect(screen.getByText(/named in the text, not in the entity master: no company data is used/)).toBeInTheDocument();
    expect(screen.getByText("M&A / Corporate Action")).toBeInTheDocument();
    expect(screen.getByText("Restructuring / divestiture")).toBeInTheDocument();
    expect(screen.getByText(/No calibrated confidence: the cue phrases decided this/)).toBeInTheDocument();
    expect(screen.getByText("No sector identified")).toBeInTheDocument();
    expect(screen.getAllByText("Rule-based reading").length).toBeGreaterThan(0);
    const marks = document.querySelectorAll("mark.hl");
    expect(marks).toHaveLength(1);
    expect(marks[0]!.textContent).toBe("a major restructuring");
  });

  it("lists what was dropped in the disclosure, and states a model fallback instead of hiding it", async () => {
    const a = assessment({ extraction: { ...assessment().extraction, fallback_reason: "the language-model call timed out" } });
    wrap(<UnderstandingCard a={a} />);
    expect(screen.getByText("The language model could not be used for this text")).toBeInTheDocument();
    expect(screen.getByText(/the language-model call timed out/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("How this was read, and what was checked"));
    expect(screen.getByText(/Dropped entity 'Acme'/)).toBeInTheDocument();
  });

  it("labels an AI-assisted reading and shows the model's stated confidence", () => {
    const a = assessment({
      extraction: { ...assessment().extraction, mode: "LLM", model_id: "claude-haiku-4-5-20251001", cached: true },
      reading: { ...assessment().reading, event_confidence: 0.82, uncertainty: 0.2, rationale: "A restructuring announcement." },
    });
    wrap(<UnderstandingCard a={a} />);
    expect(screen.getByText(/AI-assisted · cached/)).toBeInTheDocument();
    expect(screen.getByText(/82% confidence \(stated by the model\)/)).toBeInTheDocument();
    expect(screen.getByText("A restructuring announcement.")).toBeInTheDocument();
  });
});

describe("the threshold notice", () => {
  it("below the trigger: nothing runs by itself, a what-if is offered, and it is not a forecast", () => {
    wrap(<ThresholdNotice score={3} threshold={7} signalId="sig_x" />);
    expect(screen.getByText("Severity 3/10 is below the automatic trigger (7)")).toBeInTheDocument();
    expect(screen.getByText(/No stress runs automatically/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Run as a what-if/ })).toHaveAttribute("href", "/stress?signal=sig_x");
    expect(screen.getByText(/not a forecast/)).toBeInTheDocument();
  });
  it("above the trigger: the scenario is suggested and runs from the link", () => {
    wrap(<ThresholdNotice score={8} threshold={7} signalId="sig_x" />);
    expect(screen.getByText("Severity 8/10 is above the automatic trigger (7)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Run the scenario/ })).toHaveAttribute("href", "/stress?signal=sig_x&run=1");
  });
  it("exactly at the trigger counts as above it", () => {
    wrap(<ThresholdNotice score={7} threshold={7} />);
    expect(screen.getByText(/above the automatic trigger/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("no score: nothing can trigger, and no number is invented", () => {
    wrap(<ThresholdNotice score={null} threshold={7} />);
    expect(screen.getByText("No severity score, so nothing can trigger")).toBeInTheDocument();
  });
});

describe("the severity breakdown", () => {
  it("shows the four answers (rules vs AI vs used), the build-up, the market note, what was left out, reliability and the honest range", () => {
    wrap(<SeverityBreakdown a={assessment()} />);
    const rubric = within(screen.getByRole("list", { name: "The four rubric answers" }));
    expect(rubric.getAllByRole("listitem")).toHaveLength(4);
    expect(rubric.getByText("The AI moved this 1 step up from the rules, with a stated reason.", { exact: false })).toBeInTheDocument();
    expect(rubric.getByText(/Quoted: “a major restructuring”/)).toBeInTheDocument();
    expect(rubric.getAllByText(/No language model read this text/).length).toBeGreaterThan(0); // the three answers the AI did not give
    const table = within(screen.getByRole("table", { name: "How the severity score is built" }));
    expect(table.getByText("Severity matrix")).toBeInTheDocument();
    expect(table.getByText("+0.40")).toBeInTheDocument();
    expect(screen.getByText(/rounds to/)).toBeInTheDocument();
    expect(screen.getByText("Market data used")).toBeInTheDocument();
    expect(screen.getAllByText(/1 session behind/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Novelty not used:/)).toBeInTheDocument();
    expect(screen.getByText(/does not change the severity/)).toBeInTheDocument();
    expect(screen.getByText(/not a statistical interval/)).toBeInTheDocument();
    expect(screen.getByText("4–6")).toBeInTheDocument();
    expect(screen.getByText(/never lowers the score/)).toBeInTheDocument();
  });

  it("says plainly when market data was excluded as too stale", () => {
    const a = assessment();
    a.severity!.market = { used: false, vix: 16.4, as_of: "2026-10-01", report_session: "2026-10-05", sessions_behind: 2, max_sessions_behind: 1, reason: "The market data held ends 2026-10-01, 2 sessions before the last completed session (2026-10-05); the policy allows at most 1. It is too stale to be the market at the time, so it is not used." };
    wrap(<MarketNote m={a.severity!.market} />);
    expect(screen.getByText("Market data not used")).toBeInTheDocument();
    expect(screen.getByText(/too stale to be the market at the time/)).toBeInTheDocument();
  });

  it("flags a conflicting report rather than hiding it", () => {
    const a = assessment({ conflict: { signal_id: "sig_o", headline: "Quantum Dynamics beats estimates", sentiment: 0.7, hours_apart: 3, note: "Another report on Quantum within 48 hours has the opposite tone. Both are kept; neither is discounted." } });
    wrap(<SeverityBreakdown a={a} />);
    expect(screen.getByText("Another report on the same issuer disagrees")).toBeInTheDocument();
    expect(screen.getByText(/Both are kept; neither is discounted/)).toBeInTheDocument();
  });

  it("writes the lede from the four answers and says what the AI changed", () => {
    expect(severityLede(assessment().severity!)).toBe(
      "Significant intensity at one issuer reach, confirmed and adverse: moderate severity. The AI's bounded adjustments moved it up 1 from the rules-only score of 4.",
    );
  });
});

describe("the score build-up", () => {
  it("starts at the matrix, shows signed changes with a running total, and states the rounded result", () => {
    wrap(<ScoreBuildUp steps={assessment().severity!.steps} score={5} points={5.2} />);
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(within(rows[0]!).getAllByText("4.80").length).toBeGreaterThan(0); // the matrix value and the running total start equal
    expect(within(rows[3]!).getByText("+0.40")).toBeInTheDocument();
    expect(within(rows[3]!).getByText("Data")).toBeInTheDocument(); // the regime step is tagged as data
    expect(screen.getAllByText(/5.20/).length).toBeGreaterThanOrEqual(2); // the last running total and the stated result
  });
});

describe("rubric answers when no model read the text", () => {
  it("shows the rules answer and says no AI answer exists, rather than inventing one", () => {
    wrap(<RubricTable rubric={assessment().severity!.rubric} mode="RULES" />);
    expect(screen.getAllByText("No language model read this text (rule-based mode).").length).toBe(3);
  });
});

describe("provenance", () => {
  it("counts the origins at a glance and lists each part with its origin and detail", async () => {
    wrap(<ProvenanceStrip lines={assessment().provenance} />);
    await userEvent.click(screen.getByText("Where each part comes from"));
    const list = within(screen.getByRole("list", { name: "Provenance of each part" }));
    expect(list.getByText("Market regime")).toBeInTheDocument();
    expect(list.getAllByText("Data").length).toBeGreaterThan(0);
    expect(list.getByText("Assumption")).toBeInTheDocument();
    expect(list.getByText("Hybrid")).toBeInTheDocument();
  });
});

describe("the scale", () => {
  it("shows five labelled bands and marks the score in its band", () => {
    wrap(<ScaleBar score={7} />);
    const items = screen.getAllByRole("listitem");
    expect(items.map((i) => i.textContent?.replace(/\d+–\d+/, ""))).toEqual(["Negligible", "Low", "Moderate", "High", "Extreme"]);
    expect(items[3]).toHaveAttribute("data-on", "true");
    expect(items.filter((i) => i.getAttribute("data-on") === "true")).toHaveLength(1);
  });
});

describe("evidence classes in the understanding card", () => {
  it("separates what the report shows from what the AI inferred, and never presents an inference as a quote", () => {
    wrap(<UnderstandingCard a={assessment()} />);
    expect(screen.getByText("Shown by the report itself")).toBeInTheDocument();
    expect(screen.getByText(/AI inference: no phrase in the report shows these, so they are not quotes/)).toBeInTheDocument();
    expect(screen.getByText("inferred")).toBeInTheDocument();
    expect(screen.getByText(/The AI's reason: price pressure suggests inflation is not fading/)).toBeInTheDocument();
    // the inferred indicator is never highlighted: only the one verbatim span is marked in the text
    expect(document.querySelectorAll("mark.hl")).toHaveLength(1);
  });
});

const timeline = (): TimelineView => ({
  signal_id: "sig_q", report_time: AS_OF, assessed_at: AS_OF, timestamp_origin: "SOURCE", note: "Items marked 'used' were available when the report appeared.",
  excluded: ["Reports published after this one (later coverage): shown on the timeline, never scored", "The realised market move (shown for audit only)"],
  items: [
    { at: null, label: "Market state as of the last session", detail: "VIX only.", kind: "MARKET_STATE", phase: "BEFORE_REPORT", known_at_assessment: true, used_in_severity: true, used_by_reference_model: true, number_kind: "MARKET_STATE" },
    { at: AS_OF, label: "Report published: wire", detail: "primary input", kind: "REPORT", phase: "AT_REPORT", known_at_assessment: true, used_in_severity: true, used_by_reference_model: true, number_kind: "SOURCE" },
    { at: "2026-10-01T15:00:00Z", label: "Later report: Second wire", detail: "Published after the report: shown for audit, never scored.", kind: "CORROBORATION", phase: "AFTER_REPORT", known_at_assessment: false, used_in_severity: false, used_by_reference_model: false, number_kind: "SOURCE" },
    { at: "2026-10-01T16:00:00Z", label: "SEC 8-K filing (2.02)", detail: "after", kind: "FILING", phase: "AFTER_REPORT", known_at_assessment: false, used_in_severity: false, used_by_reference_model: false, number_kind: "MARKET_STATE" },
  ],
});

describe("what was known when", () => {
  it("puts everything after the report in its own column, tagged as never used", () => {
    wrap(<AssessmentTimeline tl={timeline()} />);
    const after = within(screen.getByRole("region", { name: "After the report" }));
    expect(after.getByText("Later report: Second wire")).toBeInTheDocument();
    expect(after.getByText("SEC 8-K filing (2.02)")).toBeInTheDocument();
    expect(after.getAllByText("not used")).toHaveLength(2);
    expect(after.queryByText("used in the severity score")).not.toBeInTheDocument();
    const at = within(screen.getByRole("region", { name: "At the report" }));
    expect(at.getByText("used in the severity score")).toBeInTheDocument();
    expect(screen.getByText("Deliberately excluded from the severity score")).toBeInTheDocument();
    expect(screen.getByText(/later coverage/)).toBeInTheDocument();
  });
});

describe("the three kinds of evidence", () => {
  it("keeps source evidence, model inference and scenario assumptions in separate boxes", () => {
    const ev: EvidenceView = {
      signal_id: "sig_q",
      source_evidence: { headline: TEXT, text: TEXT, spans: [{ quote: "a major restructuring", start: 27, end: 48, supports: "event_type" }], note: "Quotes are verbatim.", entity_match: null,
        reports: [{ source: "manual paste", source_type: "NEWS", published_at: AS_OF, headline: TEXT, url: null, relation: "THIS_REPORT", phase: "AT_REPORT", used_in_score: true },
                  { source: "Second wire", source_type: "NEWS", published_at: "2026-10-01T15:00:00Z", headline: TEXT, url: null, relation: "SAME_EVENT", phase: "AFTER_REPORT", used_in_score: false }] },
      model_inference: { lines: [{ label: "Event", value: "M&A / Restructuring", kind: "EXTRACTION", detail: "read by deterministic rules" }], agreement: assessment().agreement, note: "Model inference is not source evidence." },
      scenario_assumptions: { scenario_id: "scn_ma", scenario_name: "M&A repricing", illustrative: true, reference_impact: 7, shocks: ["Equity prices, market-wide: -2.0% at reference severity 7"], trigger_threshold: 7, severity_scaling: "shock x clamp(severity / 7, 0.5, 1.5)", note: "Scenario shocks are configured assumptions." },
    };
    wrap(<EvidenceGroups ev={ev} />);
    for (const name of ["Source evidence", "Model inference", "Scenario assumptions"]) expect(screen.getByRole("region", { name })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Source evidence" })).getByText(/published afterwards: shown, never scored/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Scenario assumptions" })).getByText("M&A repricing")).toBeInTheDocument();
    expect(screen.getByText("Source text")).toBeInTheDocument();
    expect(screen.getByText("Scenario assumption")).toBeInTheDocument();
  });
});

describe("the mode chip", () => {
  it("says what read the text, including a fallback", () => {
    const { rerender } = wrap(<ModeChip a={assessment()} />);
    expect(screen.getByText("Rule-based reading")).toBeInTheDocument();
    rerender(<ModeChip a={assessment({ extraction: { ...assessment().extraction, fallback_reason: "x" } })} />);
    expect(screen.getByText("Rules (model unavailable)")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------ the Analyze page, end to end
const meta = (llm: object | null) => ({
  app: "EventShock", version: "0.1.0", mode: "REPLAY", profile: "replay", data_origin: "REAL_SOURCE_MIXED_NLP", as_of: AS_OF, trigger_threshold: 7, base_currency: "USD",
  signal_count: 1, asset_count: 1, scenario_set_version: "1", engine_version: "1.0.0", notices: [], replay: null, taxonomy: [{ id: "MA_CORPORATE_ACTION", label: "M&A / Corporate Action", description: "", default_scenario: "scn_ma" }],
  impact: null, capabilities: { analyze: true, live_enabled: false, assessment: true, llm },
});
const llmRules = { mode: "RULES", enabled: false, model: null, reason: "switched off", llm_calls: 0, cache_hits: 0, fallbacks: 0, last_fallback_reason: null, sends_text_off_machine: false };
const llmOn = { ...llmRules, mode: "LLM", enabled: true, model: "claude-haiku-4-5-20251001", reason: null, sends_text_off_machine: true };

const summary = {
  id: "sig_q", headline: TEXT, source: "manual paste", source_type: "NEWS", published_at: AS_OF, entity_id: "UNKNOWN_ENTITY", entity_name: null, ticker: null, sector: null,
  category: "MA_CORPORATE_ACTION", event_status: "UNCERTAIN", sentiment_score: -0.5, impact_score: null, impact_origin: null, impact_lifecycle: null, impact_score_low: null, impact_score_high: null,
  status: "PARTIAL", source_count: 1, data_origin: "REAL_SOURCE_MIXED_NLP", scope_level: "UNRESOLVED", scope_sector: null, scope_strength: null, scope_themes: [], scope_regions: [], channel: "MANUAL",
  first_seq: 1, updated_seq: 1, relevance_level: "UNDETERMINED", relevance_share: null,
  severity_score: 5, severity_low: 5, severity_high: 6, severity_basis: "SCORECARD", assessed_category: "MA_CORPORATE_ACTION", assessed_sector: null, extraction_mode: "RULES", above_trigger: false,
};

const calls: { url: string; body?: string }[] = [];
let llmInfo: object | null = llmRules;
let analyzeResp: object | Error;

beforeEach(() => {
  calls.length = 0;
  llmInfo = llmRules;
  analyzeResp = { outcome: "NEW", signal_id: "sig_q", signal: summary, rejection: null, headline: TEXT, analysed_chars: TEXT.length, truncated: false, notes: ["No publication time was given, so the time you pasted it is used."], assessment: assessment() };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), body: init?.body as string | undefined });
    const u = String(url);
    const ok = (b: unknown) => ({ ok: true, status: 200, json: async () => b }) as Response;
    if (u.endsWith("/api/meta")) return ok(meta(llmInfo));
    if (u.endsWith("/api/analyze")) {
      if (analyzeResp instanceof Error) throw analyzeResp;
      return ok(analyzeResp);
    }
    if (u.endsWith("/api/scenarios")) return ok({ version: "1", default_by_category: { MA_CORPORATE_ACTION: "scn_ma" }, scenarios: [{ id: "scn_ma", name: "M&A repricing", version: "1", category: "MA_CORPORATE_ACTION", description: "", illustrative: true, reference_impact: 7, shocks: [] }] });
    if (u.includes("/relevance")) return ok({ signal_id: "sig_q", scope_level: "UNRESOLVED", level: "UNDETERMINED", share: null, summary: "Nothing was identified, so relevance cannot be stated.", path: [], slices: [], reach: null });
    return { ok: false, status: 404, statusText: "nf", json: async () => ({ detail: "nf" }) } as Response;
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("Analyze page with the risk assessment", () => {
  it("walks news -> AI understanding -> risk signal -> scenario -> portfolio and offers a what-if below the trigger", async () => {
    wrap(<AnalyzePage />, "/analyze");
    await userEvent.type(await screen.findByRole("textbox", { name: /Text to analyse/ }), TEXT);
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    const result = within(await screen.findByRole("region", { name: "Assessment result" }));
    const chain = within(result.getByRole("list", { name: /How EventShock got from this text to a portfolio/ }));
    for (const k of ["News", "AI understanding", "Risk signal", "Scenario", "Portfolio impact"]) expect(chain.getByText(new RegExp(k))).toBeInTheDocument();
    expect(chain.getByText("Severity 5/10")).toBeInTheDocument();
    expect(chain.getByText(/below the trigger \(7\)/)).toBeInTheDocument();
    expect(result.getByText("Severity 5/10 is below the automatic trigger (7)")).toBeInTheDocument();
    expect(result.getByRole("link", { name: /Run as a what-if/ })).toHaveAttribute("href", "/stress?signal=sig_q");
    expect(result.getByRole("link", { name: /Open the full analysis/ })).toHaveAttribute("href", "/events/sig_q");
    // the trained model is a labelled reference, collapsed, and says it does not drive the trigger
    expect(result.getByText(/Reference: the trained market-reaction model gave no score/)).toBeInTheDocument();
    expect(JSON.parse(calls.find((c) => c.url.endsWith("/api/analyze"))!.body!)).toMatchObject({ text: TEXT, source_type: "NEWS" });
  });

  it("sends the optional source name", async () => {
    wrap(<AnalyzePage />, "/analyze");
    await userEvent.type(await screen.findByRole("textbox", { name: /Text to analyse/ }), TEXT);
    await userEvent.click(screen.getByText("Set where and when it was published"));
    await userEvent.type(screen.getByPlaceholderText(/Reuters/), "Desk note");
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    await screen.findByRole("region", { name: "Assessment result" });
    expect(JSON.parse(calls.find((c) => c.url.endsWith("/api/analyze"))!.body!)).toMatchObject({ source: "Desk note" });
  });

  it("offers one example per event class", async () => {
    wrap(<AnalyzePage />, "/analyze");
    await userEvent.click(await screen.findByText("More examples: one per event class"));
    const group = within(screen.getByRole("group", { name: "More examples" }));
    for (const n of ["Regulatory", "Monetary policy", "Geopolitical", "Earnings", "M&A", "Unknown company"]) expect(group.getByRole("button", { name: n })).toBeInTheDocument();
    await userEvent.click(group.getByRole("button", { name: "Unknown company" }));
    expect(screen.getByRole("textbox", { name: /Text to analyse/ })).toHaveValue(TEXT);
  });

  it("the privacy note follows the mode: nothing leaves in rule mode, the provider gets the text in LLM mode", async () => {
    wrap(<AnalyzePage />, "/analyze");
    expect(await screen.findByText(/Nothing leaves this server: the text is read by deterministic rules/)).toBeInTheDocument();
    expect(screen.getByText("Rule-based demo mode")).toBeInTheDocument();
  });

  it("in LLM mode it says the text is sent, and which model reads it", async () => {
    llmInfo = llmOn;
    wrap(<AnalyzePage />, "/analyze");
    expect(await screen.findByText(/The text is sent to the language model \(claude-haiku-4-5-20251001\) to be read/)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing leaves this server/)).not.toBeInTheDocument();
  });

  it("states a model fallback in the result and still shows the assessment", async () => {
    analyzeResp = { ...(analyzeResp as object), notes: ["The language model could not be used (the language-model call timed out); the deterministic rules read the text instead."],
      assessment: assessment({ extraction: { ...assessment().extraction, fallback_reason: "the language-model call timed out" } }) };
    wrap(<AnalyzePage />, "/analyze");
    await userEvent.type(await screen.findByRole("textbox", { name: /Text to analyse/ }), TEXT);
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    const result = within(await screen.findByRole("region", { name: "Assessment result" }));
    expect(result.getAllByText(/the language-model call timed out/).length).toBeGreaterThan(0);
    expect(result.getByText("Severity 5/10 is below the automatic trigger (7)")).toBeInTheDocument();
  });

  it("a text that is not a market event gets no number and no trigger", async () => {
    analyzeResp = { ...(analyzeResp as object), signal: { ...summary, severity_score: null, severity_low: null, severity_high: null, assessed_category: "NO_EVENT", above_trigger: null },
      assessment: assessment({ severity: null, threshold: null, severity_note: "The text does not describe a market event, so nothing is scored for it.",
        reading: { ...assessment().reading, event_type: "NO_EVENT", event_label: "Not a market event", severity_indicators: [] } }) };
    wrap(<AnalyzePage />, "/analyze");
    await userEvent.type(await screen.findByRole("textbox", { name: /Text to analyse/ }), "Lovely weather in the city this weekend");
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    const result = within(await screen.findByRole("region", { name: "Assessment result" }));
    expect(result.getByText("No severity score, so nothing can trigger")).toBeInTheDocument();
    expect(result.getByText(/does not describe a market event/)).toBeInTheDocument();
    expect(result.queryByRole("link", { name: /Run the scenario|Run as a what-if/ })).not.toBeInTheDocument();
  });
});
