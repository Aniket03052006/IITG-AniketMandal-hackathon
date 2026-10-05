import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { OutcomeCheck, OutcomeSplit } from "../../api/types";
import { OutcomeCheckView } from "./OutcomeCheckTab";

const split = (name: string, n: number, m1: [number, number, number]): OutcomeSplit => ({
  split: name, n, abstained_share: 0.77, tail_rate: 0.074,
  metrics: [
    { name: "M1_overall_rank", estimate: m1[0], lo: m1[1], hi: m1[2] },
    { name: "M4_increment_over_regime", estimate: m1[0], lo: m1[1], hi: m1[2] },
    { name: "placebo_rank", estimate: -0.02, lo: -0.05, hi: 0.01 },
  ],
  bands: [{ band: "abstained", n: 3561, tail_rate: 0.068, lo: 0.06, hi: 0.077 }, { band: "low", n: 817, tail_rate: 0.081, lo: 0.064, hi: 0.101 }],
});

const o: OutcomeCheck = {
  label: "HEURISTIC_UNCALIBRATED", label_reading: "A transparent triage scale, not an outcome-calibrated one.", preregistration_sha256: "ab".repeat(32),
  splits: [split("dev", 14039, [0.054, 0.036, 0.072]), split("test", 4636, [0.007, -0.025, 0.039]), split("live", 963, [-0.021, -0.086, 0.04])],
  market_scope: [split("test", 1079, [0.098, 0.041, 0.154])], market_scope_note: "POST-HOC extension, not in the pre-registration.",
  audit: { quiet_days_sampled: 60000, news_episodes: 19638, auc: 0.523, auc_lo: 0.512, auc_hi: 0.532, share_move_news: 0.074, share_move_quiet: 0.06, auc_without_earnings: 0.508,
    auc_without_earnings_lo: 0.5, auc_without_earnings_hi: 0.517, auc_with_earnings: 0.796, effective_sample: 8995, nominal_sample: 19638, sigma_decision: "outcome-v3", sigma_reading: "A volatility estimate that adapts faster was used." },
  retrieval: { served_retriever: "e5-large", similarity_floor: 0.78, floor_curve: [], decision: "No analogue-derived quantity enters the severity score: retrieval is display evidence only",
    relevance: [{ queries: "The 149 event queries", base_rate: 0.071, p_at_5_e5: 0.389, p_at_5_tfidf: 0.255, delta: 0.134, delta_lo: 0.094, delta_hi: 0.179 }],
    value: [{ candidate: "C_knn", split: "test", delta_mae: 0.0005, lo: 0.0001, hi: 0.0009 }, { candidate: "G_reference_class", split: "live", delta_mae: 0.0002, lo: -0.0009, hi: 0.0013 }] },
  missing: [], note: "Written before the results were seen.",
};

describe("OutcomeCheckView", () => {
  it("states the honest verdict first: heuristic, not calibrated to outcomes", () => {
    render(<OutcomeCheckView o={o} />);
    expect(screen.getByText("Heuristic: not calibrated to outcomes")).toBeInTheDocument();
    expect(screen.queryByText("Outcome-validated")).toBeNull();
  });

  it("shows the out-of-sample intervals that include zero, by period", () => {
    render(<OutcomeCheckView o={o} />);
    const t = screen.getByRole("table", { name: /rank correlation of severity with realised moves/i });
    expect(within(t).getByText(/2025 test/)).toBeInTheDocument();
    expect(within(t).getAllByText(/\+0\.007\s+\[−0\.025, \+0\.039\]/).length).toBeGreaterThan(0);
  });

  it("says ordinary news is barely distinguishable from an ordinary day, with the earnings exception", () => {
    render(<OutcomeCheckView o={o} />);
    expect(screen.getByText(/barely distinguishable from an ordinary day/)).toBeInTheDocument();
    expect(screen.getByText("0.796")).toBeInTheDocument();
  });

  it("reports retrieval as display evidence and shows the failed information test, not just the successful relevance one", () => {
    render(<OutcomeCheckView o={o} />);
    expect(screen.getByText(/retrieval is display evidence only/)).toBeInTheDocument();
    expect(screen.getByText(/did not improve its error/)).toBeInTheDocument();
    expect(screen.getByText("Outcomes of the nearest past reports")).toBeInTheDocument();
  });

  it("names a missing evidence file and the command that produces it", () => {
    render(<OutcomeCheckView o={{ ...o, audit: null, retrieval: null, missing: ["outcome_audit.json: run `make outcome-audit`"] }} />);
    expect(screen.getByText(/make outcome-audit/)).toBeInTheDocument();
  });
});
