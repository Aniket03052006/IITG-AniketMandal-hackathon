import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventPage } from "./EventPage";
import { EvidencePage } from "./EvidencePage";
import { FeedPage } from "./FeedPage";
import { StressPage } from "./StressPage";

const AS_OF = "2026-10-01T12:00:00Z";

const meta: Record<string, unknown> = {
  app: "EventShock", version: "0.1.0", mode: "REPLAY", profile: "demo", replay: null, data_origin: "DEMO_FIXTURE", as_of: AS_OF,
  trigger_threshold: 7, base_currency: "USD", signal_count: 2, asset_count: 3, scenario_set_version: "1",
  engine_version: "1.0.0", notices: [], capabilities: { analyze: false, live_enabled: false },
  taxonomy: [
    { id: "CREDIT_FUNDING", label: "Credit / Funding", description: "", default_scenario: "scn_credit" },
    { id: "PRODUCT_OPERATIONS", label: "Product / Operations", description: "", default_scenario: "scn_ops" },
  ],
};

const row = (over: object) => ({
  id: "sig_1", headline: "Meridian flags funding gap", source: "Ledger Wire", source_type: "NEWS",
  published_at: "2026-10-01T08:30:00Z", entity_id: "ENT_M", entity_name: "Meridian Bancorp", ticker: "MRDB",
  sector: "Financials", category: "CREDIT_FUNDING", event_status: "CLASSIFIED", sentiment_score: -0.72, impact_score: 9, status: "COMPLETE",
  source_count: 5, data_origin: "DEMO_FIXTURE",
  scope_level: "COMPANY", scope_sector: "Financials", scope_strength: null, scope_themes: [], scope_regions: ["US"],
  channel: "REPLAY", first_seq: null, updated_seq: null, relevance_level: "DIRECT", relevance_share: 0.05, ...over,
});

const feed = {
  total: 2,
  seq: 0,
  items: [
    row({}),
    row({ id: "sig_2", headline: "Kestrel launches jet", entity_name: "Kestrel", ticker: "KSTR", category: "PRODUCT_OPERATIONS", sentiment_score: 0.7, impact_score: 2, source_count: 2 }),
  ],
};

const detail = (impact: number | null) => ({
  id: "sig_2",
  document: { id: "d", source: "Ledger Wire", source_type: "NEWS", published_at: "2026-10-01T08:30:00Z", ingested_at: "2026-10-01T08:31:00Z", author: null, headline: "Kestrel launches jet", body: "Body text", url: "https://demo.invalid/x", language: "en", raw_metadata: {} },
  entity: { entity_id: "ENT_K", entity_name: "Kestrel", ticker: "KSTR", sector: "Industrials", country: "FR", link_confidence: 0.99 },
  scope: { level: "COMPANY", sector: "Industrials", regions: ["FR"], themes: [], basis: "ENTITY_RESOLVER", strength: null, matched_terms: {}, note: "Kestrel was named in the text.", resolver_version: "entity-only" },
  sentiment: { positive: 0.8, neutral: 0.1, negative: 0.1, score: 0.7 },
  event: { category: "PRODUCT_OPERATIONS", status: "CLASSIFIED", no_event_probability: null, probabilities: { PRODUCT_OPERATIONS: 0.73, CREDIT_FUNDING: 0.03, GEOPOLITICAL: 0.03, MACROECONOMIC: 0.03, MA_CORPORATE_ACTION: 0.03, REGULATORY_LEGAL: 0.03, EARNINGS_FINANCIAL_PERFORMANCE: 0.1, MARKET_VALUATION: 0.02 } },
  impact: impact === null ? null : { score: impact, raw: impact / 10, drivers: [{ feature: "event_type", contribution: 0.05, note: "" }], quantisation: "ceil(raw * 10), min 1" },
  evidence: { source_count: 2, unique_domain_count: 2, recent_mention_count: 5, coverage_velocity: 0.3, novelty_score: 0.45, novelty_measured: true, model_confidence: 0.85, contradicted_by: [], corroborating: [] },
  status: impact === null ? "PARTIAL" : "COMPLETE",
  status_reason: impact === null ? "Impact model unavailable" : null,
  data_origin: "DEMO_FIXTURE",
  model_versions: { sentiment: "fixture-v0", event: "fixture-v0", impact: impact === null ? null : "fixture-v0", entity_resolver: "fixture-v0", feature_schema: "1" },
  created_at: "2026-10-01T08:32:00Z",
});

const scenarios = {
  version: "1",
  default_by_category: { PRODUCT_OPERATIONS: "scn_ops", CREDIT_FUNDING: "scn_credit" },
  scenarios: [
    { id: "scn_ops", version: "1.0", name: "Product / operations disruption", category: "PRODUCT_OPERATIONS", description: "", illustrative: true, reference_impact: 7, shocks: [{ factor: "EQUITY", scope: "ISSUER", value: -0.09, rationale: "Revenue-at-risk repricing." }] },
    { id: "scn_credit", version: "1.0", name: "Credit and funding stress", category: "CREDIT_FUNDING", description: "", illustrative: true, reference_impact: 7, shocks: [] },
  ],
};

const audit = { mode: "REPLAY", data_origin: "DEMO_FIXTURE", engine_version: "1.0.0", scenario_version: "1.0", portfolio_id: "pf", portfolio_hash: "abc", threshold: 7, forced: false, impact_overridden: false, calculated_at: AS_OF, calculation: "deterministic engine" };

const notTriggered = { run_id: "run_1", status: "NOT_TRIGGERED", reason: "Impact 2 is below the trigger threshold 7.", signal_id: "sig_2", scenario: null, severity: null, shocks: [], summary: null, positions: [], contributions: null, uncovered: null, audit };

const completed = {
  run_id: "run_2", status: "COMPLETED", reason: null, signal_id: "sig_2",
  scenario: { id: "scn_ops", version: "1.0", name: "Product / operations disruption", category: "PRODUCT_OPERATIONS", illustrative: true },
  severity: { impact_used: 7, reference_impact: 7, min_scale: 0.5, max_scale: 1.5, raw_ratio: 1, scale: 1, formula: "scale = 1.0000" },
  shocks: [{ factor: "EQUITY", scope: "ISSUER", base_value: -0.09, scaled_value: -0.09, applicable: true, rationale: "Revenue-at-risk repricing." }],
  summary: { baseline_value: 1_000_000, stressed_value: 900_000, pnl: -100_000, pnl_pct: -0.1 },
  positions: [{ asset_id: "EQ-K", name: "Kestrel - Common Equity", asset_class: "EQUITY", entity_id: "ENT_K", sector: "Industrials", baseline_value: 1_000_000, stressed_value: 900_000, delta: -100_000, delta_pct: -0.1, shocks: [{ factor: "EQUITY", scope: "ISSUER", value: -0.1 }], by_factor: { EQUITY: -100_000 }, formula: "dV = V x s" }],
  contributions: {
    by_asset_class: [{ key: "EQUITY", label: "EQUITY", baseline_value: 1_000_000, delta: -100_000, share_of_loss: 1 }],
    by_sector: [{ key: "Industrials", label: "Industrials", baseline_value: 1_000_000, delta: -100_000, share_of_loss: 1 }],
    by_entity: [{ key: "ENT_K", label: "ENT_K", baseline_value: 1_000_000, delta: -100_000, share_of_loss: 1 }],
    by_factor: [{ key: "EQUITY", label: "EQUITY", baseline_value: 0, delta: -100_000, share_of_loss: 1 }],
    top_positions: [{ key: "EQ-K", label: "Kestrel - Common Equity", baseline_value: 1_000_000, delta: -100_000, share_of_loss: 1 }],
  },
  uncovered: { asset_count: 0, market_value: 0, share_of_portfolio: 0, asset_ids: [] },
  audit,
};

const portfolio = {
  summary: { portfolio_id: "pf", name: "Synthetic book", description: "SYNTHETIC portfolio", as_of: AS_OF, base_currency: "USD", total_value: 1_000_000, asset_count: 3, entity_count: 2, synthetic: true },
  exposure: { by_asset_class: [], by_sector: [], by_entity: [{ key: "ENT_K", label: "Kestrel Aerospace", market_value: 1, share: 1, asset_count: 1 }], by_geography: [] },
};

const realMeta = {
  ...meta, profile: "replay", data_origin: "REAL_SOURCE_PLACEHOLDER_NLP",
  replay: { snapshot_id: "replay-test", description: "d", window_start: "2026-09-17T00:00:00Z", window_end: "2026-09-30T23:59:59Z", output_digest: "ab".repeat(32), pipeline_version: "pipeline-2.0", stage_origins: { ingestion: "REAL", sentiment: "PLACEHOLDER" }, sources: ["gdelt-doc"] },
};

const provenance = {
  adapter: "gdelt-doc", snapshot_id: "replay-test", record_ref: "gdelt/articles.jsonl:42", content_sha256: "c".repeat(64),
  timestamp_origin: "GDELT_FIRST_SEEN", pipeline_version: "pipeline-2.0",
  entity_audit: { rule: "WEAK_ALIAS", matched_text: "Apple", multi_entity: false, candidates: [], rejected: [{ entity_id: "ENT_V", matched_text: "Visa", reason: "ambiguous name, no finance context" }], unmatched_cashtags: ["BYND"] },
  dedup: { cluster_id: "cl_1", member_count: 3, exact_duplicates_folded: 2, members: [] },
  stage_origins: { sentiment: "PLACEHOLDER_RULES", event: "PLACEHOLDER_RULES", impact: "PLACEHOLDER_RULES" },
};

const report = {
  snapshot_id: "replay-test", description: "d", replay_as_of: AS_OF, window_start: "2026-09-17T00:00:00Z", window_end: "2026-09-30T23:59:59Z",
  pipeline_version: "pipeline-2.0", entity_resolver_version: "dictionary-er-v1", enrichment_version: "placeholder-v0", output_digest: "ab".repeat(32),
  counts: { records_read: 10, quarantined: 2, accepted: 8, exact_duplicates_folded: 1, reports_in_signals: 7, signals: 5, entity_resolved: 4, entity_unknown: 1, multi_entity: 1, rejected_ambiguous_mentions: 2, syndicated: 1, near_duplicates: 1, same_event: 0 },
  sources: [{ name: "gdelt-doc", source_type: "NEWS", license: "GDELT terms", attribution: "The GDELT Project", origin_url: "u", notes: "n", records: 10, quarantined: 2, accepted: 8, exact_duplicates_folded: 1, signals: 5 }],
  quarantine_by_code: { NON_ENGLISH: 2 }, quarantine_sample: [{ source: "gdelt-doc", record_ref: "a:1", code: "NON_ENGLISH", detail: "language 'es'", preview: "x" }],
  stage_origins: { ingestion: "REAL", sentiment: "PLACEHOLDER (TFN: source label)" },
  superseded_requests: 5,
  fetch_log: [
    { query: '("Pfizer Inc" OR "Eli Lilly")', status: "error", attempts: 3, returned: 0, added: 0, last_error: "gave up after 3 attempts (HTTP 429)" },
    { query: '("Exxon Mobil" OR "Chevron Corp")', status: "ok", attempts: 1, returned: 97, added: 76, last_error: "" },
  ],
};

const sentAudit = (over: object = {}) => ({ model_id: "tfidf-lr-v1", model_version: "tfidf-lr-v1", artifact_sha256: "a1".repeat(32), confidence: 0.87, calibrated: true, seen_in_training: false, ...over });
const modelProvenance = (over: object = {}) => ({ ...provenance, stage_origins: { sentiment: "MODEL", event: "PLACEHOLDER_RULES", impact: "PLACEHOLDER_RULES" }, sentiment: sentAudit(over) });
const modelMeta = {
  ...realMeta, data_origin: "REAL_SOURCE_MIXED_NLP",
  replay: { ...realMeta.replay, stage_origins: { ingestion: "REAL", sentiment: "MODEL (tfidf-lr-v1, trained on Twitter Financial News)", event: "PLACEHOLDER", impact: "PLACEHOLDER" } },
};
const evalMetrics = (f1: number, n: number) => ({
  n, weighted: false, labels: ["negative", "neutral", "positive"], accuracy: 0.8, macro_f1: f1, macro_f1_ci95: [f1 - 0.03, f1 + 0.03],
  per_class: { negative: { precision: 0.8, recall: 0.6, f1: 0.69, support: 10 }, neutral: { precision: 0.86, recall: 0.95, f1: 0.9, support: 70 }, positive: { precision: 0.8, recall: 0.7, f1: 0.75, support: 20 } },
  confusion: [[6, 3, 1], [2, 66, 2], [1, 5, 14]], log_loss: 0.43, brier: 0.2, ece: 0.024, spearman_score_vs_label: 0.63,
  mean_score_by_class: { negative: -0.4, neutral: 0.01, positive: 0.5 }, product_rule: { accuracy: 0.81, macro_f1: 0.76 },
});
const base = (m: number) => ({ placeholder_lexicon: { accuracy: 0.6, macro_f1: m }, majority_class: { accuracy: 0.65, macro_f1: 0.26 }, audit_probe_tfidf_logreg: { accuracy: 0.8, macro_f1: 0.78 } });
const modelCard = {
  id: "tfidf-lr-v1", version: "tfidf-lr-v1", algorithm: "TF-IDF -> logistic regression -> temperature scaling", preprocessing: "normalised",
  classes: ["negative", "neutral", "positive"], score_definition: "p_pos - p_neg", artifact_file: "model.joblib", artifact_sha256: "a1".repeat(32), artifact_bytes: 1_660_000,
  libraries: { "scikit-learn": "1.9.1" },
  training: { dataset: "Twitter Financial News sentiment", licence: "MIT", table: "t", table_sha256: "b".repeat(64), rows: { train: 9355, valid: 1170, test: 1169 }, label_distribution: {}, split_note: "", seed: 1, config_digest: "x" },
  selection_rule: "valid_log_loss_after_temperature",
  candidates: [{ preprocessing: "normalised", C: 3, class_weight: null, temperature: 1.03, valid_log_loss: 0.478, valid_macro_f1: 0.735, selected: true }, { preprocessing: "raw", C: 1, class_weight: "balanced", temperature: 0.75, valid_log_loss: 0.537, valid_macro_f1: 0.73, selected: false }],
  calibration: { method: "temperature", temperature: 1.03, fitted_on: "valid", ece_test_before: 0.018, ece_test_after: 0.024, reliability_test: [] },
  evaluations: [
    { id: "tfn_test", title: "Twitter Financial News, held-out test", role: "in_domain", description: "In-domain.", status: "ok", note: "", model: evalMetrics(0.778, 1169), baselines: base(0.527) },
    { id: "phrasebank", title: "Financial PhraseBank (external)", role: "external", description: "External.", status: "skipped", note: "Raw file not present.", model: null, baselines: {} },
    { id: "gold_history", title: "Gold set, our own sources (AI-annotated)", role: "indicative", description: "Ours.", status: "ok", note: "", model: evalMetrics(0.44, 280), baselines: base(0.296) },
  ],
  confident_errors: [], limitations: ["Trained on Twitter Financial News only.", "Gold labels are AI-annotated."],
};

const eventAudit = (over: object = {}) => ({ model_id: "tfidf-lr-event-v1", model_version: "tfidf-lr-event-v1", artifact_sha256: "e1".repeat(32), confidence: 0.64, no_event_probability: 0.12, calibrated: true, unreliable_class: false, seen_in_training: false, ...over });
const bothProvenance = (over: object = {}) => ({ ...provenance, stage_origins: { sentiment: "MODEL", event: "MODEL", impact: "PLACEHOLDER_RULES" }, sentiment: sentAudit(), event: eventAudit(over) });
const eventMeta = {
  ...modelMeta,
  replay: { ...modelMeta.replay, stage_origins: { ingestion: "REAL", sentiment: "MODEL (tfidf-lr-v1, trained on Twitter Financial News)", event: "MODEL (tfidf-lr-event-v1, trained on AI-annotated in-domain labels; abstains)", impact: "PLACEHOLDER" } },
};
const EVENT_LABELS = ["GEOPOLITICAL", "MACROECONOMIC", "CREDIT_FUNDING", "MA_CORPORATE_ACTION", "REGULATORY_LEGAL", "PRODUCT_OPERATIONS", "EARNINGS_FINANCIAL_PERFORMANCE", "MARKET_VALUATION", "NONE"];
const eventMetrics = (f1: number, served: number, n: number) => ({
  n, weighted: true, labels: EVENT_LABELS, accuracy: 0.7, macro_f1: f1, macro_f1_ci95: [f1 - 0.05, f1 + 0.05], event_macro_f1: f1 - 0.05,
  per_class: { PRODUCT_OPERATIONS: { precision: 0.4, recall: 0.6, f1: 0.48, support: 100 }, NONE: { precision: 0.86, recall: 0.86, f1: 0.86, support: 900 } },
  confusion: EVENT_LABELS.map((_, i) => EVENT_LABELS.map((__, j) => (i === j ? 8 : 1))), log_loss: 1.1, brier: 0.5, ece: 0.05,
  served: { macro_f1: served, accuracy: 0.65, coverage: 0.86, accuracy_when_decided: 0.76, classified_precision: 0.57, status_mix: { CLASSIFIED: 0.2, NO_EVENT: 0.66, UNCERTAIN: 0.14 }, detection: { precision: 0.58, recall: 0.87, f1: 0.696 } },
  served_f1_ci95: [served - 0.06, served + 0.05],
});
const ebase = (m: number) => ({ placeholder_keywords: { accuracy: 0.2, macro_f1: m, detection_f1: 0.488 }, majority_class: { accuracy: 0.68, macro_f1: 0.09, detection_f1: 0 }, tfn_topic_probe: { accuracy: 0.1, macro_f1: 0.14, detection_f1: 0.49 } });
const eventCard = {
  id: "tfidf-lr-event-v1", version: "tfidf-lr-event-v1", algorithm: "TF-IDF -> logistic regression over 9 classes -> temperature scaling", preprocessing: "normalised",
  classes: EVENT_LABELS, output_definition: "o", artifact_file: "model.joblib", artifact_sha256: "e1".repeat(32), artifact_bytes: 1_820_000, libraries: { "scikit-learn": "1.9.1" },
  training: { labels_file: "l", labels_sha256: "c".repeat(64), table: "t", table_sha256: "d".repeat(64), annotator: "ai:claude", rows: { "train/annotated": 2520, "train/silver": 0, dev: 765, replay_check: 200 },
    label_distribution_train: {}, label_distribution_dev: {}, silver_note: "TFN topic crosswalk rows were tested and NOT used.", consistency: { n: 200, agreement: 0.92, kappa: 0.88, share_none_first_pass: 0.55, note: "n" }, seed: 1, config_digest: "x" },
  selection_rule: "valid_log_loss_after_temperature", ablation: { dev_log_loss_without_silver: 0.87, dev_log_loss_with_silver: 0.9, silver_used: 0 },
  candidates: [{ preprocessing: "normalised", C: 10, class_weight: "balanced", temperature: 0.84, dev_log_loss: 0.87, dev_macro_f1: 0.55, selected: true }],
  calibration: { method: "temperature", temperature: 0.84, fitted_on: "dev", ece_dev_population_before: 0.062, ece_dev_population_after: 0.04, reliability_dev_population: [] },
  abstention: { commit_threshold: 0.5, rationale: "r", dev_population_n: 522, dev_coverage: 0.88, dev_classified_share: 0.19, dev_classified_precision: 0.57, dev_no_event_precision: 0.88, route_unreliable_to_uncertain: true, unreliable_classes: ["MA_CORPORATE_ACTION"] },
  class_reliability: [
    { label: "PRODUCT_OPERATIONS", train_examples: 380, annotated_train: 380, dev_support: 126, dev_f1: 0.53, status: "ok", reason: "dev F1 0.53 on 126 rows" },
    { label: "MA_CORPORATE_ACTION", train_examples: 572, annotated_train: 572, dev_support: 26, dev_f1: 0.32, status: "unreliable", reason: "dev F1 0.32 on 26 rows is below 0.35" },
  ],
  evaluations: [
    { id: "dev_history", title: "Held-out dev rows, our own sources (selected on)", role: "in_domain", description: "Dev.", status: "ok", note: "", model: eventMetrics(0.505, 0.4, 522), baselines: ebase(0.29) },
    { id: "gold_history", title: "Gold set, our own sources (AI-annotated)", role: "indicative", description: "Gold ours.", status: "ok", note: "", model: eventMetrics(0.527, 0.325, 280), baselines: ebase(0.332) },
    { id: "replay_check", title: "Replay-pack check set (fresh documents)", role: "in_domain", description: "Replay.", status: "ok", note: "", model: eventMetrics(0.616, 0.508, 199), baselines: ebase(0.251) },
    { id: "tfn_topic_test", title: "TFN topic test split (crosswalk labels)", role: "secondary", description: "Old.", status: "skipped", note: "not run here", model: null, baselines: {} },
  ],
  acceptance: { rule: "Pre-registered bar", met: false, checks: [
    { name: "served macro-F1 on gold history rows: CI lower bound above the best baseline", model: 0.264, baseline: 0.332, detail: "model 0.325 [0.264, 0.381] vs best baseline 0.332", passed: false },
    { name: "event-vs-NONE F1 on gold history rows at least the best baseline's", model: 0.696, baseline: 0.488, detail: "model 0.696 vs 0.488", passed: true },
  ] },
  confident_errors: [{ eval_set: "gold_history", text: "Apple earnings call at 4pm today", truth: "NONE", served: "CLASSIFIED:EARNINGS_FINANCIAL_PERFORMANCE", top_class: "EARNINGS_FINANCIAL_PERFORMANCE", p_none: 0.1, confidence: 0.8 }],
  limitations: ["Labels are produced by an AI annotator.", "Roughly 3,000 annotated rows."],
};

let impactCardResponse: unknown = null;
let evidenceResponse: unknown = null;
let feedItems: object[] = [];
let stressResponse: unknown = completed;
let metaResponse: unknown = meta;
let reportResponse: unknown = report;
let signalDetail: unknown = detail(2);
let contextResponse: unknown = null;

// ---------------------------------------------------------------------------------------------- the impact model
const est = (value: number | null, lo: number | null = null, hi: number | null = null) => ({ value, lo, hi });
const iScore = (id: string, mae: number, rho: number, d: number) => ({
  id, mae: est(mae, mae - 0.01, mae + 0.01), rmse: 0.4, spearman: est(rho, rho - 0.1, rho + 0.1), top_decile_lift: 1.4,
  placebo_spearman: est(rho + 0.1, rho, rho + 0.2), delta_mae_vs_constant: est(d, d - 0.005, d + 0.005), delta_mae_vs_market_state: est(0, -0.003, 0.003),
});
const iBin = (lo: number, hi: number, n: number, p: number) => ({
  score_low: lo, score_high: hi, n_episodes: n, severity_q10: 0.2, severity_q50: 0.6 + lo * 0.1, severity_q90: 2, realised_score_q10: 1, realised_score_q90: 5, p_extreme: est(p, p / 2, p * 2),
});
const iScope = (scope: string, lifecycle: string, met = false) => ({
  scope, lifecycle, served: true, summary: `${lifecycle}: R3-full selected out of fold. Held-out rank skill +0.12 (95% interval +0.01 to +0.22).`,
  target: "t", selected_id: "R3-full", algorithm: "gradient boosting on log1p(|z|)", features: ["f_sigma_60"],
  training: { table_sha256: "f".repeat(64), rows: { train: 68823, val: 8494, test: 7282, live: 16630 }, episodes: { train: 9133, val: 166, test: 181, live: 963 }, train_period: "2015-01-02..2022-03-24", folds: "21 rolling-origin folds", excluded: {}, seed: 1, config_sha256: "e".repeat(64) },
  ladder: [
    { id: "R0-constant", family: "constant", rung: null, servable: false, params: {}, n_features: 0, oof_mae: est(0.306, 0.3, 0.31), oof_spearman: est(-0.008), delta_mae_vs_previous_choice: est(0), chosen: false, verdict: "baseline: the training mean" },
    { id: "R3-full", family: "hgb_full", rung: "R3", servable: true, params: {}, n_features: 30, oof_mae: est(0.297, 0.29, 0.3), oof_spearman: est(0.226, 0.2, 0.25), delta_mae_vs_previous_choice: est(-0.002, -0.003, -0.001), chosen: true, verdict: "adopted: beats R3-additive out of fold" },
  ],
  evaluations: [
    { id: "val+test", title: "2022 Q2+Q3 pooled", role: "pooled for the acceptance checks", n_episodes: 347, n_rows: 15776, period: "2022-04-01..2022-09-30", models: [iScore("R0-constant", 0.284, 0, 0), iScore("R3-full", 0.284, 0.119, 0)] },
    { id: "live", title: "2026 news", role: "live-like", n_episodes: 963, n_rows: 16630, period: "2026-02-17..2026-09-30", models: [iScore("R0-constant", 0.259, 0, 0), iScore("R3-full", 0.248, 0.084, -0.011)] },
  ],
  calibration: { method: "rank-calibrated", reference_episodes: 6786, reference_period: "2017-01-03..2022-03-24", extreme_score: 7, base_rate_extreme: 0.039, bins_reference: [iBin(1, 1, 2906, 0.015), iBin(8, 10, 130, 0.28)], bins_heldout: [iBin(1, 1, 107, 0.0)],
    nominal_coverage: 0.8, heldout_coverage: est(0.945, 0.916, 0.965), monotonicity_spearman: null, extreme_brier: 0.0249, extreme_brier_base_rate: 0.0254 },
  strata: [{ dimension: "event type", value: "PRODUCT_OPERATIONS", n_episodes: 40, spearman: est(0.1, -0.1, 0.3), mae_model: 0.28, mae_constant: 0.29 }],
  attribution: { kind: "sensitivity", exact: false, max_abs_error: 0.0453, units: "ln(1 + |z|): baseline + contributions = prediction" },
  horizon: [{ window_sessions: 1, spearman: est(0.15) }, { window_sessions: 2, spearman: est(0.12) }], direction: { n: 570, hit_rate: est(0.528, 0.454, 0.594), note: "n" },
  leakage_findings: ["[INFO] feature_availability: all features are registered event-time features"],
  acceptance: { rule: "Pre-registered bar", met, checks: [
    { id: "C1", label: "Rank skill on held-out episodes (val+test)", passed: true, value: "+0.119 [+0.014, +0.220]", detail: "d1" },
    { id: "C7", label: "More skill on the real window than on the pre-event placebo (val+test)", passed: met, value: "-0.110", detail: "d7" },
    { id: "C4", label: "Score buckets ordered by realised severity", passed: null, value: "n/a", detail: "d4" },
  ] },
  limitations: ["Held-out evidence is 347 episodes."],
});
const impactCard = (lifecycle = "CALIBRATED", met = false) => ({
  id: "impact-v1", version: "impact-v1", feature_schema: "impact-features-v1", output_definition: "Per scope: predicted log1p(|z|).", artifact_file: "model.joblib",
  artifact_sha256: "ac".repeat(32), artifact_bytes: 112_000, libraries: { "scikit-learn": "1.9.1" }, dataset: {}, selection_rule: "rolling-origin out-of-fold MAE",
  scopes: [iScope("ISSUER", lifecycle, met), { ...iScope("MARKET", "CALIBRATED"), calibration: null }],
});
const impactMeta = (lifecycle = "CALIBRATED") => ({
  ...eventMeta,
  replay: { ...eventMeta.replay, stage_origins: { ...eventMeta.replay.stage_origins, impact: "MODEL (impact-v1: ISSUER calibrated, MARKET calibrated; placeholder heuristic for signals it cannot score)" } },
  impact: { mode: "MODEL", model_id: "impact-v1", scopes: { ISSUER: lifecycle, MARKET: "CALIBRATED" }, served_scopes: ["ISSUER", "MARKET"], reason: null },
});
const impactAudit = (over: object = {}) => ({
  model_id: "impact-v1", model_version: "impact-v1", artifact_sha256: "ac".repeat(32), lifecycle: "CALIBRATED", scope: "ISSUER", feature_schema: "impact-features-v1", calibrated: true,
  session: "2026-10-01", timing: "OFF_HOURS", timing_reliable: true, market_context_as_of: "2026-10-01", inputs: { f_sigma_60: 0.0123, f_vix_level: 16.3, novelty: 1 }, missing_inputs: [], ...over,
});
const impactDetail = (audit: object | null, impactOver: object = {}) => ({
  ...detail(8),
  event: { ...detail(8).event, status: "CLASSIFIED", no_event_probability: 0.12 },
  status: "COMPLETE", status_reason: null,
  provenance: { ...bothProvenance(), stage_origins: { sentiment: "MODEL", event: "MODEL", impact: audit ? "MODEL" : "PLACEHOLDER_RULES" }, impact: audit, impact_note: audit ? null : "the document has no real timestamp (replay assigned one): there is no event time to measure from" },
  impact: {
    score: 7, raw: 0.62, quantisation: "ceil(raw * 10), min 1; raw = rank-calibrated severity", scope: audit ? "ISSUER" : null,
    drivers: audit ? [{ feature: "baseline", contribution: 0.5, note: "the model's output for a typical event (training medians)", value: null }, { feature: "f_sigma_60", contribution: 0.12, note: "volatility regime", value: 0.0123 }, { feature: "ev_p_none", contribution: -0.04, note: "event type (text model)", value: 0.1 }]
      : [{ feature: "event_category_prior", contribution: 0.3, note: "Placeholder heuristic, not a trained model" }],
    predicted_severity: audit ? 1.42 : null, comparable_events: audit ? 130 : null, score_low: audit ? 3 : null, score_high: audit ? 9 : null, realised_severity_low: audit ? 0.3 : null,
    realised_severity_median: audit ? 1.1 : null, realised_severity_high: audit ? 3.1 : null, p_extreme: audit ? 0.28 : null, driver_basis: audit ? "log-severity, ln(1 + |z|): each feature moved alone from its typical value (does not sum to the prediction)" : null, ...impactOver,
  },
  data_origin: "REAL_SOURCE_MIXED_NLP", model_versions: { sentiment: "tfidf-lr-v1+a1a1a1a1", event: "tfidf-lr-event-v1+e1e1e1e1", impact: audit ? "impact-v1+acacacac" : "placeholder-v0-heuristic", entity_resolver: "dictionary-er-v1", feature_schema: "1" },
});
const evidence = (over: object = {}) => ({
  schema_version: 1,
  generated_from: [{ file: "docs/evidence/impact_study.json", sha256: "ab".repeat(32) }],
  stages: [
    { stage: "sentiment", model_id: "tfidf-lr-v1", kind: "experimental", summary: "Trained TF-IDF logistic regression, calibrated.", passed: [], failed: [], not_evaluable: [], artifact_sha256: "a1".repeat(32) },
    { stage: "event", model_id: "tfidf-lr-event-v1", kind: "experimental", summary: "Trained 9-way classifier that can abstain. It did NOT meet its pre-registered bar on the gold set.", passed: [], failed: ["served macro-F1 on gold history rows"], not_evaluable: [], artifact_sha256: "e1".repeat(32) },
    { stage: "impact", model_id: "impact-v1", kind: "experimental", summary: "issuer: calibrated; market: calibrated", passed: ["C1 (issuer)"], failed: ["C7 (issuer)", "C2 (issuer)"], not_evaluable: ["C4 (issuer)"], artifact_sha256: "ac".repeat(32) },
  ],
  data: {
    available: true, command: "make impact-study",
    sources: [{ name: "SEC EDGAR filings", kind: "filing", period: "2014-2026", records: 9772, timestamps: "exact SEC acceptance time (UTC)", note: "public domain" }],
    episodes_by_year: [{ year: "2023", issuer: 800, market: 100, filing_events: 380 }, { year: "2024", issuer: 900, market: 120, filing_events: 389 }],
    held_out: {}, calendar_filings: 9772, calendar_fomc: 102, exclusions: {},
    gold: [{ name: "Gold v1 (frozen)", rows: 400, labelled_by: "one AI annotator", agreement: null, kappa: null, agreed_rows: null, human_reviewed: 0, note: "evaluation only" },
      { name: "Gold v2 (2023-2025)", rows: 300, labelled_by: "two independent blind AI passes", agreement: 0.81, kappa: 0.77, agreed_rows: 243, human_reviewed: 0, note: "same-family agreement" }],
    known_gaps: ["News for 2023-2025 is a deterministic sample, not a complete archive."],
  },
  features: [
    { name: "earn_window", group: "earnings calendar (known in advance)", availability: "a", allowed: true, used_by: ["issuer:R2s"], why: "a: expected earnings release is within a day" },
    { name: "f8k_earnings_24h", group: "recent SEC filings (published before the report)", availability: "b", allowed: true, used_by: ["issuer:R2s"], why: "b: an earnings 8-K accepted in the last 24 hours" },
    { name: "f_sigma_60", group: "volatility regime", availability: "t", allowed: true, used_by: ["issuer:R2"], why: "trailing residual vol" },
    { name: "eps_surprise", group: "market state", availability: "c", allowed: false, used_by: [], why: "realised EPS minus consensus: known only once results are out" },
    { name: "ticker", group: "market state", availability: "shortcut", allowed: false, used_by: [], why: "issuer identity" },
  ],
  study: {
    available: true, command: "make impact-study", preregistration: { file: "configs/evidence_v2.yaml", sha256: "cd".repeat(32) }, p1_regression: "every v1 row is reproduced exactly in the v2 table",
    runs: [{
      protocol: "P2_extended", scope: "ISSUER", status: "ok", episodes: { train: 11000, test: 400 }, selected: "R2-ridge", best_state: "R2-ridge", best_block: "R2s-full", years_helpful: "3 of 4 years", verdict: "failed C10",
      checks: [{ id: "C9", label: "Regime-neutral rank skill (test)", value: "+0.04 [-0.03, +0.11]", passed: false, detail: "lower bound must exceed 0" }, { id: "C4", label: "Score buckets ordered", value: "n/a", passed: null, detail: "needs calibration" }],
      increments: [
        { block: "calendar block (earnings dates, 8-K recency, FOMC)", family: "ridge", where: "test", delta_mae: est(-0.012, -0.02, -0.004), verdict: "helps" },
        { block: "text-model outputs, given the calendar", family: "ridge", where: "test", delta_mae: est(0.001, -0.004, 0.006), verdict: "no measurable effect" },
      ],
      battery: [{ model: "R2-ridge", role: "selected", set: "test", neutral_skill: est(0.04, -0.03, 0.11), within_issuer_skill: 0.01, placebo_gap: -0.08 }],
      ablation: [{ block: "calendar", method: "shuffled among the same issuer and month", spearman_lost: 0.03, mae_added: 0.01, mae_added_lo: 0.005, mae_added_hi: 0.015 }],
    }],
    track_f: { available: true, pairs: 4713, note: "controls: same issuer", headline: { label: "all filing events vs matched quiet sessions", pairs: 4713, lift: est(0.24, 0.22, 0.26), auc: 0.63 },
      by_item: [{ label: "earnings (item 2.02)", pairs: 1084, lift: est(0.64, 0.6, 0.68), auc: 0.82 }, { label: "officer changes (5.02)", pairs: 813, lift: est(0.04, 0.0, 0.07), auc: 0.51 }],
      earnings_by_year: [], non_earnings_by_year: [], item_code_increment: [] },
  },
  representation: {
    available: true, command: "make bakeoff", decision: "no candidate met every pre-registered check; the shipped TF-IDF model stays", baseline: "tfidf-lr-event-v1", sets: { pooled: 600 }, baseline_pooled_f1: 0.43,
    candidates: [{ id: "H1[e5-base]", family: "H1", detail: "intfloat/multilingual-e5-base", pooled_delta_f1: est(0.05, -0.02, 0.12), checks_passed: ["log_loss_delta"], checks_failed: ["served_macro_f1_delta"], adopt: false }],
    cost: [{ model: "intfloat/multilingual-e5-base", kind: "dense", parameters_m: 278, ms_per_text_batch1: 30, ms_per_text_batch32: 12.5, peak_rss_mb: 1300, controlled: true, deterministic: true }],
    probe: [{ channel: "ProsusAI/finbert (P(pos)-P(neg))", pairs: 30, share_correct: 0.93, lo: 0.79, hi: 0.98 }],
  },
  limitations: ["All labels are AI-annotated."],
  ...over,
});

const ctxFixture = (over: object = {}) => ({
  signal_id: "sig_2", report_time: "2026-10-01T08:30:00Z", timestamp_origin: "SOURCE", assessed_at: AS_OF, impact_scored: true,
  inputs: [
    { name: "f_sigma_60", group: "volatility regime", availability: "t", value: 0.0123 },
    { name: "f_vix_level", group: "market conditions", availability: "t", value: 16.3 },
    { name: "earn_window", group: "earnings calendar (known in advance)", availability: "a", value: 1 },
    { name: "f8k_count_24h", group: "recent SEC filings (published before the report)", availability: "b", value: 0 },
    { name: "ev_p_none", group: "event type (text model)", availability: "t", value: 0.1 },
    { name: "novelty", group: "novelty of the report", availability: "t", value: 1 },
  ],
  missing_inputs: [],
  not_used: ["how many outlets carried the story (it would leak later coverage)", "any report published after this one", "SEC filings accepted at or after the report", "the realised market move"],
  filings: [
    { accession: "A1", form: "8-K", items: ["5.02"], acceptance_utc: "2026-09-30T12:00:00Z", hours_from_report: -20.5, role: "FEEDS_MODEL", role_note: "the most recent 8-K before the report: it sets the 'hours since the last 8-K' feature", known_at_assessment: true },
    { accession: "A2", form: "8-K", items: ["2.02", "2.05"], acceptance_utc: "2026-10-02T00:15:00Z", hours_from_report: 15.75, role: "AFTER_REPORT", role_note: "x", known_at_assessment: false },
  ],
  filings_note: null,
  outcome: { scope: "ISSUER", ticker: "KSTR", session: "2026-10-01", window_sessions: 2, abs_z: 0.41, z: -0.41, score: 1, note: "n" },
  outcome_note: "definition",
  ...over,
});

const liveStatus = {
  enabled: false, state: "OFF", source_mode: null, simulated: false, poll_interval_seconds: null, last_attempt_at: null, last_success_at: null,
  next_attempt_at: null, last_error: null, consecutive_failures: 0, fetched_total: 0, new_total: 0, updated_total: 0, quarantined_total: 0,
  live_signal_count: 0, seq: 0, retention_hours: 48, event_model: "tfidf-lr-event-v1", event_model_note: null, market_context_through: "2026-10-01",
};
const relevanceResponse = {
  signal_id: "sig_2", scope_level: "COMPANY", level: "DIRECT", share: 0.05, summary: "The book holds Kestrel directly: 3 positions, 5.0% of its value.",
  path: ["Kestrel: held, 5.0% of the book in 3 positions"],
  slices: [{ kind: "ISSUER", key: "ENT_K", label: "Kestrel", market_value: 50000, share: 0.05, asset_count: 3, by_asset_class: { EQUITY: 50000 } }],
  reach: { scenario_id: "scn_ops", scenario_name: "Product / operations disruption", shocks_total: 1, shocks_bound: 1, note: "every shock reaches this event" },
};
const scopeInfo = {
  version: "scope-v1", rules: ["A resolved company is the scope."], sectors: { Energy: 3 }, themes: { rates: 2 }, regions: ["US"],
  replay_mix: { COMPANY: 3, UNRESOLVED: 1 }, live_mix: {},
  evaluation: { snapshot_id: "replay-test", single_issuer_documents: 100, vocabulary_fired: 30, coverage: 0.3,
    by_strength: { STRONG: { predicted: 5, correct: 4, precision: 0.8 }, WEAK: { predicted: 25, correct: 20, precision: 0.8 } },
    per_sector: { Energy: { documents: 10, recall: 0.5, precision: 0.9 } }, limits: ["an optimistic proxy"] },
};

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/api/meta")) return json(metaResponse);
      if (url.endsWith("/api/pipeline/report")) return json(reportResponse);
      if (url.endsWith("/api/models/sentiment")) return json(modelCard);
      if (url.endsWith("/api/models/event")) return json(eventCard);
      if (url.endsWith("/api/evidence")) return evidenceResponse ? json(evidenceResponse) : json({ detail: "no evidence" }, 404);
      if (url.endsWith("/api/models/impact")) return impactCardResponse ? json(impactCardResponse) : json({ detail: "no impact model" }, 404);
      if (url.includes("/api/signals?") || url.endsWith("/api/signals")) {
        const q = new URL(url, "http://x").searchParams;
        const cat = q.get("category");
        const items = (feedItems as typeof feed.items).filter((i) => !cat || i.category === cat);
        return json({ total: items.length, seq: 0, items });
      }
      if (url.endsWith("/api/live/status")) return json(liveStatus);
      if (url.endsWith("/relevance")) return json(relevanceResponse);
      if (url.endsWith("/api/scope")) return json(scopeInfo);
      if (url.endsWith("/context")) return contextResponse ? json(contextResponse) : json({ detail: "no context" }, 404);
      if (url.includes("/api/signals/")) return json(signalDetail);
      if (url.endsWith("/api/scenarios")) return json(scenarios);
      if (url.endsWith("/api/portfolio/summary")) return json(portfolio.summary);
      if (url.endsWith("/api/portfolio/exposure")) return json(portfolio.exposure);
      if (url.endsWith("/api/stress-test") && init?.method === "POST") return json(stressResponse);
      return json({ detail: "not found" }, 404);
    }),
  );
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<FeedPage />} />
          <Route path="/events/:id" element={<EventPage />} />
          <Route path="/stress" element={<StressPage />} />
          <Route path="/evidence" element={<EvidencePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  feedItems = feed.items;
  reportResponse = report;
  impactCardResponse = null;
  evidenceResponse = null;
  contextResponse = null;
  mockFetch();
  stressResponse = completed;
  signalDetail = detail(2);
  metaResponse = meta;
});
afterEach(() => vi.unstubAllGlobals());

const dialog = async (name: string) => within(await screen.findByRole("dialog", { name }));

// =============================================================================================== Risk Feed
describe("Risk Feed", () => {
  it("lists signals with impact, entity and event type", async () => {
    renderAt("/");
    expect(await screen.findAllByText("Meridian flags funding gap")).not.toHaveLength(0);
    const table = screen.getByRole("region", { name: "Risk signals" });
    expect(within(table).getByText("Kestrel launches jet")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Impact 9 of 10, Extreme" })).toBeInTheDocument();
    expect(screen.getByText("2 of 2 signals shown", { exact: false })).toBeInTheDocument();
  });

  it("opens with the story in four real numbers and a featured event, before any filter", async () => {
    renderAt("/");
    const story = await screen.findByRole("list", { name: "What EventShock did with the data" });
    expect(within(story).getByText("reports and posts")).toBeInTheDocument();
    expect(within(story).getByText("market events found")).toBeInTheDocument();
    expect(within(story).getByText("scored by the impact model")).toBeInTheDocument();
    expect(within(story).getByText("reach impact ≥ 7")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Open the event story/ })).toHaveAttribute("href", "/events/sig_1");
  });

  it("filters by event type through the API", async () => {
    renderAt("/");
    await screen.findAllByText("Kestrel launches jet");
    await userEvent.click(screen.getByText("More filters and sorting"));
    await userEvent.click(screen.getByRole("button", { name: /Product \/ Operations/ }));
    const list = screen.getByRole("region", { name: "Risk signals" });
    await waitFor(() => expect(within(list).queryByText("Meridian flags funding gap")).not.toBeInTheDocument());
    expect(within(list).getByText("Kestrel launches jet")).toBeInTheDocument();
  });

  it("explains an API outage instead of failing silently", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    renderAt("/");
    expect(await screen.findByText(/Cannot reach the EventShock API/)).toBeInTheDocument();
  });
});

// ============================================================================================ Event page
describe("Event Intelligence", () => {
  it("tells the story in chapters: text, NLP, impact, evidence, scenario", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByRole("heading", { level: 1, name: "Kestrel launches jet" })).toBeInTheDocument();
    for (const name of ["What the text says", "How severe a reaction is likely", "What supports it, and what was known when", "What a scenario does to the portfolio"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("list", { name: /How EventShock got from this text to a portfolio/ })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "EventShock chain" })).toBeInTheDocument();
  });

  it("states that sentiment is tone, not impact, and keeps them in separate readings", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByText(/Sentiment is tone, not impact/)).toBeInTheDocument();
    expect(screen.getByText(/a finding about that model, not about the news/)).toBeInTheDocument();
    expect(screen.queryByText(/the text models' outputs add none/)).not.toBeInTheDocument(); // the overbroad claim is gone
    expect(screen.getByText(/Tone is not impact/)).toBeInTheDocument();
  });

  it("offers a what-if when the impact is below the threshold, and labels a fixture honestly", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByText(/is below the threshold/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Run as what-if/ })).toHaveAttribute("href", "/stress?signal=sig_2");
    expect(screen.getAllByText("Fixture · illustrative").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/a hand-authored fixture value/i).length).toBeGreaterThan(0);
  });

  it("never invents an impact for a partial signal", async () => {
    signalDetail = detail(null);
    renderAt("/events/sig_2");
    expect(await screen.findByText("No impact estimate for this signal")).toBeInTheDocument();
    expect(screen.getByText(/never substitutes a default score/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Run scenario|Run as what-if/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show inputs" })).not.toBeInTheDocument();
  });

  it("says an unresolved event has no subject, why, and keeps offering the market-wide shocks", async () => {
    signalDetail = {
      ...detail(8),
      entity: { entity_id: "UNKNOWN_ENTITY", entity_name: null, ticker: null, sector: null, country: null, link_confidence: 0 },
      scope: { level: "UNRESOLVED", sector: null, regions: [], themes: [], basis: "NONE", strength: null, matched_terms: {}, note: "Kept as reported, not guessed about: no company, sector or market-wide theme could be identified.", resolver_version: "scope-v1" },
    };
    renderAt("/events/sig_2");
    expect((await screen.findAllByText("No subject identified")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Kept as reported, not guessed about/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "See what market-wide shocks would do" })).toHaveAttribute("href", "/stress?signal=sig_2");
    expect(screen.getByText("Why no company?", { selector: "summary" })).toBeInTheDocument();
  });

  it("tells the placeholder drivers apart from a model's and says the number is not authoritative", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByText(/illustrative, not attributions of a model/)).toBeInTheDocument();
  });
});

describe("Event page: progressive disclosure", () => {
  beforeEach(() => {
    metaResponse = impactMeta();
    reportResponse = { ...report, stage_origins: impactMeta().replay.stage_origins };
    impactCardResponse = impactCard();
    contextResponse = ctxFixture();
    signalDetail = impactDetail(impactAudit());
  });

  it("opens a drawer from a button, puts it in the URL, and closes it with Escape returning focus", async () => {
    renderAt("/events/sig_2");
    const btn = (await screen.findAllByRole("button", { name: "Show inputs" }))[0]!;
    btn.focus();
    await userEvent.click(btn);
    const d = screen.getByRole("dialog", { name: "What the model saw" });
    expect(d).toHaveAttribute("aria-modal", "true");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(btn).toHaveFocus();
  });

  it("Show inputs: grouped by where they come from, with availability, and what is deliberately not used", async () => {
    renderAt("/events/sig_2?open=inputs");
    const d = await dialog("What the model saw");
    expect(await d.findByText("The report")).toBeInTheDocument();
    for (const t of ["What the text models read", "Calendar context", "Market state", "Model output", "Deliberately not used"]) expect(d.getByText(t)).toBeInTheDocument();
    expect(d.getByText("Company's usual daily move (60-session volatility)")).toBeInTheDocument();
    expect(d.getByText("1.23%")).toBeInTheDocument();
    expect(d.getByText("Inside the earnings window (within 1.5 days)")).toBeInTheDocument();
    expect(d.getAllByText("Known in advance").length).toBeGreaterThan(0);
    expect(d.getAllByText("Published before the report").length).toBeGreaterThan(0);
    expect(d.getByText(/how many outlets carried the story/)).toBeInTheDocument();
    expect(d.getByText(/the realised market move/)).toBeInTheDocument();
    expect(d.getByText("1.42σ expected move")).toBeInTheDocument();
    // the realised outcome is never listed as an input
    expect(d.queryByText(/0\.41σ/)).not.toBeInTheDocument();
  });

  it("Show inputs: a placeholder signal has no model inputs and says why", async () => {
    signalDetail = impactDetail(null);
    renderAt("/events/sig_2?open=inputs");
    expect(await (await dialog("What the model saw")).findByText(/This signal has no model inputs/)).toBeInTheDocument();
  });

  it("Why?: plain-named drivers, their units, and what the score does not tell you", async () => {
    renderAt("/events/sig_2?open=why");
    const d = await dialog("Why this impact?");
    expect(await d.findByText("Company's usual daily move (60-session volatility)")).toBeInTheDocument();
    expect(d.getByText(/does not sum to the prediction/)).toBeInTheDocument();
    expect(d.getByText(/It is not a probability of loss/)).toBeInTheDocument();
    expect(d.getByText(/direction is not modelled/)).toBeInTheDocument();
  });

  it("How calculated?: typeset formulas with a plain reading under each", async () => {
    renderAt("/events/sig_2?open=math");
    const d = await dialog("How impact is calculated");
    expect(await d.findByText(/converted from the model's continuous estimate and calibrated against the severity/)).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('[data-tex="ready"]')).not.toBeNull());
    expect(d.getByText(/The thing the model predicts/)).toBeInTheDocument();
    expect(d.getByText(/continuous estimate r = 0\.620 gives a score of 7/)).toBeInTheDocument();
    expect(document.querySelector(".katex")).not.toBeNull();
  });

  it("Technical details: model, lifecycle, failing checks and limits", async () => {
    renderAt("/events/sig_2?open=tech");
    const d = await dialog("Technical details");
    expect(await d.findByText(/impact-v1 · impact-v1/)).toBeInTheDocument();
    expect(d.getByText("Calibrated (here)")).toBeInTheDocument();
    expect(await d.findByText("More skill on the real window than on the pre-event placebo (val+test)")).toBeInTheDocument();
    expect(d.getByText("Not met")).toBeInTheDocument();
    expect(d.getByText("Not evaluable")).toBeInTheDocument();
    expect(d.getByText("Held-out evidence is 347 episodes.")).toBeInTheDocument();
    expect(d.getByText(/no per-event retrieval/)).toBeInTheDocument();
  });

  it("NLP Why?: every class probability, the abstention rule, and held-out results from the model cards", async () => {
    signalDetail = { ...impactDetail(impactAudit()), provenance: { ...impactDetail(impactAudit()).provenance, event: eventAudit(), sentiment: sentAudit() } };
    renderAt("/events/sig_2?open=nlp");
    const d = await dialog("How EventShock read this text");
    expect(await d.findByText("Not an event")).toBeInTheDocument();
    expect(await d.findByText(/macro-F1 0\.78/)).toBeInTheDocument();
    expect(await d.findByText(/separates events from non-events with F1 0\.70 \(the old keyword rules: 0\.49\)/)).toBeInTheDocument();
  });

  it("Audit trail: provenance, entity refusals and de-duplication stay available, one click away", async () => {
    signalDetail = { ...impactDetail(impactAudit()), provenance: { ...impactDetail(impactAudit()).provenance, impact: impactAudit() } };
    renderAt("/events/sig_2?open=audit");
    const d = await dialog("Audit trail");
    expect(await d.findByText("gdelt/articles.jsonl:42")).toBeInTheDocument();
    expect(d.getByText("When GDELT first saw the page")).toBeInTheDocument();
    expect(d.getByText(/Refused: Visa/)).toBeInTheDocument();
    expect(d.getByText(/2 exact duplicates folded away/)).toBeInTheDocument();
    expect(d.getByText(/Impact artifact/)).toBeInTheDocument();
  });

  it("shows the raw prediction, calibrated score with range, extreme-move share and lifecycle in words", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByRole("img", { name: /Impact 7 of 10, comparable events realised 3 to 9, experimental model, High/ })).toBeInTheDocument();
    expect(screen.getAllByText("Model prediction").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1.42σ").length).toBeGreaterThan(0);
    expect(screen.getAllByText("28.0%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Experimental model").length).toBeGreaterThan(0);
    expect(screen.getByText(/On experimental model output/)).toBeInTheDocument();
    expect(screen.queryByText(/hand-authored fixture/i)).not.toBeInTheDocument();
  });

  it("says why an experimental model is not validated, using the failing checks from its card", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByText(/calibrated, not production/)).toBeInTheDocument();
    expect(await screen.findByText(/more skill on the real window than on the pre-event placebo/)).toBeInTheDocument();
  });

  it("draws a validated model plainly, with no experimental warning", async () => {
    metaResponse = impactMeta("PRODUCTION");
    impactCardResponse = impactCard("PRODUCTION", true);
    signalDetail = impactDetail(impactAudit({ lifecycle: "PRODUCTION" }));
    renderAt("/events/sig_2");
    expect((await screen.findAllByText("Validated model")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/not production/)).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /validated model/ })).toBeInTheDocument();
  });

  it("flags a weak timestamp", async () => {
    signalDetail = impactDetail(impactAudit({ timing: "FIRST_SEEN", timing_reliable: false }));
    renderAt("/events/sig_2");
    expect(await screen.findByText(/thinner, so read the score as less certain/)).toBeInTheDocument();
    expect(screen.getByText(/a crawl time, which lags publication/)).toBeInTheDocument();
  });

  it("keeps a signal the model could not score visibly on the placeholder rule, with the reason", async () => {
    signalDetail = impactDetail(null);
    renderAt("/events/sig_2");
    expect((await screen.findAllByText("Placeholder rule")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/no real timestamp/).length).toBeGreaterThan(0);
    expect(screen.queryByText("Model prediction")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show inputs" })).not.toBeInTheDocument();
    expect(screen.getByText(/No comparable events for this score/)).toBeInTheDocument();
  });
});

describe("Event page: comparable events and the knowledge timeline", () => {
  beforeEach(() => {
    metaResponse = impactMeta();
    impactCardResponse = impactCard();
    contextResponse = ctxFixture();
    signalDetail = impactDetail(impactAudit());
  });

  it("shows comparable events as an aggregate of the model's own history, never as individual events", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByText("Comparable historical events")).toBeInTheDocument();
    expect(screen.getByText(/not a list of individual events/)).toBeInTheDocument();
    expect(screen.getAllByText("Historical observation").length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: /Comparable events realised 0\.30σ to 3\.10σ, median 1\.10σ; the model estimates 1\.42σ/ })).toBeInTheDocument();
  });

  it("never shows a later fact in an earlier state: filings after the report and the outcome appear only once the slider reaches them", async () => {
    renderAt("/events/sig_2");
    const slider = await screen.findByRole("slider", { name: /Move through time/ });
    await screen.findByText(/8-K filed · item 5\.02/);
    // the moment it was scored: only what was available at the time
    expect(screen.getByText(/The moment it was scored/)).toBeInTheDocument();
    expect(screen.queryByText(/items 2\.02, 2\.05/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Realised move/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Available at the time").length).toBeGreaterThan(0);
    // move to the end
    fireEvent.change(slider, { target: { value: slider.getAttribute("max") } });
    expect(await screen.findByText(/items 2\.02, 2\.05/)).toBeInTheDocument();
    expect(screen.getByText(/Accepted after EventShock's replay clock/)).toBeInTheDocument();
    expect(screen.getAllByText(/Realised move 0\.41σ \(down\)/).length).toBeGreaterThan(0);
    expect(screen.getByText(/What actually happened/)).toBeInTheDocument();
    expect(screen.getByText(/lies inside the range the model stated \(3 to 9\)|lies outside the range the model stated \(3 to 9\)/)).toBeInTheDocument();
    // and back: the later facts leave the page again
    fireEvent.change(slider, { target: { value: "0" } });
    await waitFor(() => expect(screen.queryByText(/Realised move/)).not.toBeInTheDocument());
    expect(screen.getByText(/Before the report/)).toBeInTheDocument();
    expect(screen.queryByText(/The moment it was scored/)).not.toBeInTheDocument();
  });

  it("explains a missing realised outcome instead of leaving a gap", async () => {
    contextResponse = ctxFixture({ outcome: null, outcome_note: "the reaction window had not completed" });
    renderAt("/events/sig_2");
    expect(await screen.findByText(/Realised outcome: the reaction window had not completed/)).toBeInTheDocument();
  });

  it("draws no timeline for a post whose time was assigned by the replay", async () => {
    signalDetail = { ...impactDetail(impactAudit()), provenance: { ...impactDetail(impactAudit()).provenance, timestamp_origin: "SYNTHETIC_REPLAY_CLOCK" } };
    renderAt("/events/sig_2");
    expect(await screen.findByText("No timeline for this post")).toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: /Move through time/ })).not.toBeInTheDocument();
  });

  it("degrades with a reason when the context cannot be loaded", async () => {
    contextResponse = null;
    renderAt("/events/sig_2");
    expect(await screen.findByText("The filing and outcome context could not be loaded")).toBeInTheDocument();
  });
});

// ============================================================================================ Portfolio Stress
describe("Portfolio Stress", () => {
  it("runs on arrival from an event and shows before and after, labelled as a scenario simulation", async () => {
    signalDetail = detail(8);
    renderAt("/stress?signal=sig_2&run=1");
    const hero = await screen.findByRole("region", { name: /Portfolio value before and after the scenario/i });
    expect(within(hero).getAllByText("$1.0M").length).toBeGreaterThan(0);
    expect(within(hero).getAllByText("$900.0K").length).toBeGreaterThan(0);
    expect(within(hero).getAllByText("−$100.0K").length).toBeGreaterThan(0);
    expect(within(hero).getByText("−10.00% of portfolio value")).toBeInTheDocument();
    expect(within(hero).getByText("Scenario simulation")).toBeInTheDocument();
    expect(within(hero).getByText("Deterministic engine")).toBeInTheDocument();
    expect(within(hero).getByText(/illustrative assumptions, scaled by the event's impact, not forecasts/)).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "EventShock chain" })).toBeInTheDocument();
  });

  it("drills from the portfolio to an asset class, an issuer and a position", async () => {
    signalDetail = detail(8);
    renderAt("/stress?signal=sig_2&run=1");
    await userEvent.click(await screen.findByRole("button", { name: /Equities, −\$100\.0K\. Drill into issuers/ }));
    expect(screen.getByText("Asset class: Equities")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /Kestrel Aerospace/ }));
    expect(await screen.findByText("Kestrel - Common Equity", { selector: "span" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Portfolio" }));
    expect(screen.getByRole("button", { name: /Equities/ })).toBeInTheDocument();
  });

  it("says the drill-down is exposure to the assumptions, not what caused the event", async () => {
    signalDetail = detail(8);
    renderAt("/stress?signal=sig_2&run=1");
    expect(await screen.findByText("Sensitivity, not cause")).toBeInTheDocument();
    expect(screen.getByText(/It shows exposure to the assumptions, not what caused the event/)).toBeInTheDocument();
  });

  it("recomputes with the real engine when the severity slider moves, and labels it a simulation", async () => {
    signalDetail = detail(8);
    renderAt("/stress?signal=sig_2&run=1");
    const slider = await screen.findByRole("slider", { name: /Impact score applied/ });
    expect(screen.getByText("Scenario simulation, not a prediction")).toBeInTheDocument();
    fireEvent.change(slider, { target: { value: "9.5" } });
    await waitFor(() => {
      const calls = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.filter(([u]) => String(u).endsWith("/api/stress-test"));
      expect(calls.some(([, init]) => JSON.parse(String(init.body)).impact_override === 9.5 && JSON.parse(String(init.body)).force === true)).toBe(true);
    });
    expect(screen.getByText(/Base · the event's own impact \(8\)/)).toBeInTheDocument();
  });

  it("shows how it is calculated with typeset formulas, and keeps assumptions, positions and audit in drawers", async () => {
    signalDetail = detail(8);
    renderAt("/stress?signal=sig_2&run=1&open=math");
    const d = await dialog("How the scenario is calculated");
    expect(await d.findByText(/The scenario's shocks are chosen assumptions/)).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('[data-tex="ready"]')).not.toBeNull());
    expect(d.getByText(/gives a scale of 1\.000, kept between 0\.5 and 1\.5/)).toBeInTheDocument();
    expect(d.getByText("Equities")).toBeInTheDocument();
  });

  it("keeps the audit trail one click away", async () => {
    signalDetail = detail(8);
    renderAt("/stress?signal=sig_2&run=1&open=audit");
    expect(await (await dialog("Audit trail")).findByText("run_2")).toBeInTheDocument();
  });

  it("reports a non-triggered run honestly: what happened, why, and what to do next", async () => {
    stressResponse = notTriggered;
    renderAt("/stress?signal=sig_2");
    await userEvent.click(await screen.findByRole("button", { name: /Run scenario/ }));
    expect(await screen.findByText("Below the trigger threshold")).toBeInTheDocument();
    expect(screen.getByText(/below the trigger threshold/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run as what-if anyway/ })).toBeInTheDocument();
    expect(screen.queryByText("Where the change comes from")).not.toBeInTheDocument();
  });

  it("blocks the run for a partial signal and says why", async () => {
    signalDetail = detail(null);
    renderAt("/stress?signal=sig_2");
    expect(await screen.findByText("This signal has no impact score")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run scenario/ })).toBeDisabled();
  });

  it("shows uncovered exposure when part of the book was outside the scenario", async () => {
    signalDetail = detail(8);
    stressResponse = { ...completed, uncovered: { asset_count: 84, market_value: 550_000, share_of_portfolio: 0.638, asset_ids: [] } };
    renderAt("/stress?signal=sig_2&run=1");
    expect(await screen.findByText(/63\.8% of the book \(84 positions\) was outside this scenario's reach/)).toBeInTheDocument();
    expect(screen.getByText(/Not treated as safe/)).toBeInTheDocument();
  });
});

// ============================================================================================ Real-source replay
describe("Real-source replay", () => {
  beforeEach(() => {
    metaResponse = realMeta;
    signalDetail = { ...detail(8), data_origin: "REAL_SOURCE_PLACEHOLDER_NLP", provenance, model_versions: { sentiment: "placeholder-v0-lexicon", event: "placeholder-v0-keywords", impact: "placeholder-v0-heuristic", entity_resolver: "dictionary-er-v1", feature_schema: "1" } };
  });

  it("labels the feed honestly as real documents with placeholder NLP", async () => {
    renderAt("/");
    expect(await screen.findByText(/Real documents, placeholder sentiment\/event\/impact/)).toBeInTheDocument();
  });

  it("keeps where a signal came from, how its entity was chosen and what was folded away in the audit trail", async () => {
    renderAt("/events/sig_2?open=audit");
    const d = await dialog("Audit trail");
    expect(await d.findByText("gdelt/articles.jsonl:42")).toBeInTheDocument();
    expect(d.getByText("When GDELT first saw the page")).toBeInTheDocument();
    expect(d.getByText(/Ambiguous name with finance context/)).toBeInTheDocument();
    expect(d.getByText(/Refused: Visa/)).toBeInTheDocument();
    expect(d.getByText(/2 exact duplicates folded away/)).toBeInTheDocument();
    expect(d.getByText(/\$BYND/)).toBeInTheDocument();
  });

  it("marks the placeholder impact as a rule, not a model", async () => {
    renderAt("/events/sig_2");
    expect((await screen.findAllByText("Placeholder rule")).length).toBeGreaterThan(0);
    expect(screen.getByText(/A fixed placeholder rule set this score/)).toBeInTheDocument();
    expect(screen.getAllByText("Placeholder rules").length).toBeGreaterThan(0); // the event stage badge
  });

  it("explains the pipeline: record accounting, quarantine reasons and real vs placeholder", async () => {
    evidenceResponse = evidence();
    renderAt("/evidence?tab=pipeline");
    expect(await screen.findByRole("list", { name: "Pipeline stages in order" })).toBeInTheDocument();
    expect(screen.getByText("10 read = 2 quarantined + 1 folded + 7 kept")).toBeInTheDocument();
    expect(screen.getAllByText("NON_ENGLISH").length).toBeGreaterThan(0);
    expect(screen.getByText("PLACEHOLDER (TFN: source label)")).toBeInTheDocument();
  });

  it("does not hide failed download requests", async () => {
    evidenceResponse = evidence();
    renderAt("/evidence?tab=pipeline");
    expect(await screen.findByText("1 of 2 requests succeeded")).toBeInTheDocument();
    expect(screen.getByText("FAILED")).toBeInTheDocument();
    expect(screen.getByText(/gave up after 3 attempts \(HTTP 429\)/)).toBeInTheDocument();
    expect(screen.getByText("76 new / 97 · 1 attempt")).toBeInTheDocument();
    expect(screen.getByText(/5 requests of an earlier, abandoned plan/)).toBeInTheDocument();
  });

  it("says plainly that the demo profile has no evidence or pipeline", async () => {
    metaResponse = meta;
    renderAt("/evidence?tab=pipeline");
    expect(await screen.findByText("No evidence in the demo profile")).toBeInTheDocument();
  });
});

describe("Real-source replay with the trained sentiment model", () => {
  beforeEach(() => {
    metaResponse = modelMeta;
    reportResponse = { ...report, enrichment_version: "placeholder-v0+sentiment:tfidf-lr-v1", stage_origins: modelMeta.replay.stage_origins };
    signalDetail = { ...detail(8), data_origin: "REAL_SOURCE_MIXED_NLP", provenance: modelProvenance(), model_versions: { sentiment: "tfidf-lr-v1+a1a1a1a1", event: "placeholder-v0-keywords", impact: "placeholder-v0-heuristic", entity_resolver: "dictionary-er-v1", feature_schema: "1" } };
  });

  it("says on the feed which stage is a model and which is still a placeholder", async () => {
    renderAt("/");
    expect(await screen.findByText("Sentiment: trained model")).toBeInTheDocument();
    expect(screen.getByText("Event type: placeholder rules")).toBeInTheDocument();
    expect(screen.getByText("Impact: placeholder rules")).toBeInTheDocument();
    expect(await screen.findByText(/Sentiment is a trained model; event type and impact are placeholder rules/)).toBeInTheDocument();
  });

  it("shows the sentiment reading with its confidence, and the model's held-out and own-source results behind Why?", async () => {
    renderAt("/events/sig_2?open=nlp");
    expect(await screen.findByText(/87% confident in its top class/)).toBeInTheDocument();
    expect(await (await dialog("How EventShock read this text")).findByText(/macro-F1 0\.78\. On our own AI-labelled sources only 0\.44/)).toBeInTheDocument();
    expect(screen.queryByText(/In-sample/)).not.toBeInTheDocument();
  });

  it("keeps event type and impact visibly placeholder next to the model-backed sentiment", async () => {
    renderAt("/events/sig_2");
    expect((await screen.findAllByText("Placeholder rule")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Placeholder rules").length).toBeGreaterThan(0);
  });

  it("warns when the model has seen the exact text, so the score is not evidence of accuracy", async () => {
    signalDetail = { ...(signalDetail as object), provenance: modelProvenance({ seen_in_training: true }) };
    renderAt("/events/sig_2");
    expect(await screen.findByText(/In-sample: this text is in the data the model learned from/)).toBeInTheDocument();
  });

  it("falls back to the placeholder wording for a signal the lexicon scored", async () => {
    signalDetail = { ...detail(8), data_origin: "REAL_SOURCE_PLACEHOLDER_NLP", provenance, model_versions: { sentiment: "placeholder-v0-lexicon", event: "placeholder-v0-keywords", impact: "placeholder-v0-heuristic", entity_resolver: "dictionary-er-v1", feature_schema: "1" } };
    renderAt("/events/sig_2");
    expect(await screen.findByText(/Tone of the wording/)).toBeInTheDocument();
    expect(screen.queryByText("Trained text models")).not.toBeInTheDocument();
  });

  it("explains the model card on the evidence page: results per evaluation set, baselines, errors and limits", async () => {
    evidenceResponse = evidence();
    renderAt("/evidence?tab=evaluation");
    await userEvent.click(await screen.findByText("Sentiment model card"));
    const panel = (await screen.findByRole("heading", { name: "Sentiment model" })).closest("section") as HTMLElement;
    const w = within(panel);
    expect((await w.findAllByText("Twitter Financial News, held-out test")).length).toBeGreaterThan(0);
    expect(w.getAllByText("0.778").length).toBeGreaterThan(0);
    expect(w.getAllByText("0.527").length).toBeGreaterThan(0);
    expect(w.getByText(/Not run: Raw file not present/)).toBeInTheDocument();
    expect(w.getByText("Gold labels are AI-annotated.")).toBeInTheDocument();
    await userEvent.click(w.getByRole("button", { name: /Gold set, our own sources/ }));
    expect(await w.findByText(/Ours\./)).toBeInTheDocument();
  });
});

describe("Real-source replay with the trained event model", () => {
  const eventDetail = (status: string, over: object = {}, prov: object = {}) => ({
    ...detail(status === "CLASSIFIED" ? 8 : null), data_origin: "REAL_SOURCE_MIXED_NLP", provenance: bothProvenance(prov),
    model_versions: { sentiment: "tfidf-lr-v1+a1a1a1a1", event: "tfidf-lr-event-v1+e1e1e1e1", impact: status === "CLASSIFIED" ? "placeholder-v0-heuristic" : null, entity_resolver: "dictionary-er-v1", feature_schema: "1" },
    event: { ...detail(8).event, status, no_event_probability: 0.12, ...over },
    status: status === "CLASSIFIED" ? "COMPLETE" : "PARTIAL",
    status_reason: status === "NO_EVENT" ? "No market event identified: the event model judged this text not to be a market event" : status === "UNCERTAIN" ? "Event type uncertain: the event model will not commit to a type, so no impact is scored" : null,
  });
  beforeEach(() => {
    metaResponse = eventMeta;
    reportResponse = { ...report, enrichment_version: "placeholder-v0+sentiment:tfidf-lr-v1+event:tfidf-lr-event-v1", stage_origins: eventMeta.replay.stage_origins };
    signalDetail = eventDetail("CLASSIFIED");
    feedItems = [
      row({}),
      row({ id: "sig_2", headline: "Kestrel launches jet", category: "PRODUCT_OPERATIONS", impact_score: 8 }),
      row({ id: "sig_3", headline: "Great chart lol join discord", category: "MARKET_VALUATION", event_status: "NO_EVENT", impact_score: null, status: "PARTIAL" }),
      row({ id: "sig_4", headline: "Regional bank may be eyeing a deal", category: "MA_CORPORATE_ACTION", event_status: "UNCERTAIN", impact_score: null, status: "PARTIAL" }),
    ];
  });

  it("marks sentiment and event type as trained models and impact as a placeholder, on the feed", async () => {
    renderAt("/");
    expect(await screen.findByText("Sentiment: trained model")).toBeInTheDocument();
    expect(screen.getByText("Event type: trained model")).toBeInTheDocument();
    expect(screen.getByText("Impact: placeholder rules")).toBeInTheDocument();
    expect(await screen.findByText(/Sentiment and event type are trained models/)).toBeInTheDocument();
  });

  it("hides what the model judged not to be a market event, says how many, and can show them", async () => {
    renderAt("/");
    expect((await screen.findAllByText("Kestrel launches jet")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Great chart lol join discord")).not.toBeInTheDocument();
    expect(screen.getByText("Regional bank may be eyeing a deal")).toBeInTheDocument();
    expect(screen.getByText("Type uncertain")).toBeInTheDocument();
    expect(screen.getByText(/1 judged not to be market events are hidden/)).toBeInTheDocument();
    expect(screen.getByText(/1 were judged not to be events and 1 left uncertain/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Show non-events \(1\)/ }));
    expect(await screen.findByText("Great chart lol join discord")).toBeInTheDocument();
    expect(screen.getByText("No market event")).toBeInTheDocument();
  });

  it("shows a classified event with its calibrated confidence and the model behind it", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByText(/64% calibrated confidence/)).toBeInTheDocument();
    expect(await screen.findByText(/commits at 50% or more/)).toBeInTheDocument();
    expect(screen.getAllByText("tfidf-lr-event-v1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Trained text models").length).toBeGreaterThan(0);
    expect(screen.getByText(/EventShock interpreted this text as/)).toBeInTheDocument();
  });

  it("says plainly that a non-event is not a finding and scores no impact", async () => {
    signalDetail = eventDetail("NO_EVENT");
    renderAt("/events/sig_2");
    expect(await screen.findByText(/likely not to describe a market event/)).toBeInTheDocument();
    expect(screen.getAllByText("No market event").length).toBeGreaterThan(0);
    expect(screen.getByText("Not treated as a market event")).toBeInTheDocument();
    expect(screen.getByText("No impact will be scored")).toBeInTheDocument();
    expect(screen.queryByText(/If it were an event/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Run scenario|Run as what-if/ })).not.toBeInTheDocument();
  });

  it("shows an uncertain event as a lean, not a type", async () => {
    signalDetail = eventDetail("UNCERTAIN");
    renderAt("/events/sig_2");
    expect(await screen.findByText(/The model will not commit to a type here/)).toBeInTheDocument();
    expect(screen.getByText(/If it were an event, the model's lean/)).toBeInTheDocument();
    expect(screen.getAllByText("Type uncertain").length).toBeGreaterThanOrEqual(2);
  });

  it("explains why a type the model never asserts is shown as uncertain", async () => {
    signalDetail = eventDetail("UNCERTAIN", { category: "PRODUCT_OPERATIONS" }, { unreliable_class: true });
    renderAt("/events/sig_2");
    expect(await screen.findByText(/This event type is one the model does not assert/)).toBeInTheDocument();
  });

  it("warns when the event model has seen the exact text", async () => {
    signalDetail = eventDetail("CLASSIFIED", {}, { seen_in_training: true });
    renderAt("/events/sig_2");
    expect(await screen.findByText(/In-sample: the model trained on this exact text/)).toBeInTheDocument();
  });

  it("explains the event model card: not-met acceptance bar, per-set results, reliability, mistakes and limits", async () => {
    evidenceResponse = evidence();
    renderAt("/evidence?tab=evaluation");
    await userEvent.click(await screen.findByText("Event model card"));
    const panel = (await screen.findByRole("heading", { name: "Event model" })).closest("section") as HTMLElement;
    const w = within(panel);
    expect(await w.findByText("Acceptance bar not met")).toBeInTheDocument();
    expect(w.getByText("FAIL")).toBeInTheDocument();
    expect(w.getByText("PASS")).toBeInTheDocument();
    expect((await w.findAllByText("Gold set, our own sources (AI-annotated)")).length).toBeGreaterThan(0);
    expect(w.getAllByText("0.527").length).toBeGreaterThan(0);
    expect(w.getAllByText("0.332").length).toBeGreaterThan(0);
    expect(w.getByText(/Not run: not run here/)).toBeInTheDocument();
    expect(w.getByText("Never asserted")).toBeInTheDocument();
    expect(w.getByText(/dev F1 0\.32 on 26 rows is below 0\.35/)).toBeInTheDocument();
    expect(w.getByText("Labels are produced by an AI annotator.")).toBeInTheDocument();
    expect(w.getByText(/Apple earnings call at 4pm today/)).toBeInTheDocument();
    await userEvent.click(w.getByRole("button", { name: /Replay-pack check set/ }));
    expect(await w.findByText(/Replay\./)).toBeInTheDocument();
  });

  it("does not show model cards when the app has no impact model", async () => {
    evidenceResponse = evidence();
    renderAt("/evidence?tab=evaluation");
    expect(await screen.findByText("Event model card")).toBeInTheDocument();
    expect(screen.queryByText("Impact model card")).not.toBeInTheDocument();
  });
});

describe("Real-source replay with the trained impact model: the feed and the model card", () => {
  beforeEach(() => {
    metaResponse = impactMeta();
    reportResponse = { ...report, stage_origins: impactMeta().replay.stage_origins };
    impactCardResponse = impactCard();
    evidenceResponse = evidence();
  });

  it("shows the stage strip with the impact stage as experimental, not as a plain trained model", async () => {
    feedItems = [row({ id: "sig_2", headline: "Kestrel launches jet", data_origin: "REAL_SOURCE_MIXED_NLP", impact_origin: "MODEL", impact_lifecycle: "CALIBRATED" }),
      row({ id: "sig_9", headline: "Old rule", data_origin: "REAL_SOURCE_MIXED_NLP", impact_origin: "PLACEHOLDER", impact_lifecycle: null, impact_score: 6 })];
    renderAt("/");
    expect(await screen.findByText("Impact: experimental model")).toBeInTheDocument();
    expect(screen.getAllByText("experimental model").length).toBeGreaterThan(0);
    expect(screen.getAllByText("placeholder rule").length).toBeGreaterThan(0);
    expect(await screen.findByText(/impact is a experimental model where it can score a signal/)).toBeInTheDocument();
  });

  it("explains the impact model card: lifecycle, acceptance, baseline ladder, calibration and limits, per scope", async () => {
    renderAt("/evidence?tab=evaluation");
    await userEvent.click(await screen.findByText("Impact model card"));
    const panel = (await screen.findByRole("heading", { name: "Impact model" })).closest("section") as HTMLElement;
    const w = within(panel);
    expect(await w.findByLabelText("Lifecycle of the Issuer events model")).toBeInTheDocument();
    expect(w.getByText("5 · Calibrated").closest("li")).toHaveAttribute("aria-current", "step");
    expect(w.getByText("PASS")).toBeInTheDocument();
    expect(w.getAllByText("FAIL").length).toBeGreaterThan(0);
    expect(w.getByText("N/A")).toBeInTheDocument();
    expect(w.getByText("Held-out evidence is 347 episodes.")).toBeInTheDocument();
    await userEvent.click(w.getByRole("button", { name: /Market-wide events/ }));
    expect(await w.findByLabelText("Lifecycle of the Market-wide events model")).toBeInTheDocument();
  });
});

// ============================================================================================ Evidence
describe("Evidence page", () => {
  beforeEach(() => {
    metaResponse = impactMeta();
    evidenceResponse = evidence();
  });

  it("opens with 'how much evidence supports EventShock?' as four plain verdicts", async () => {
    renderAt("/evidence");
    expect(await screen.findByRole("heading", { level: 1, name: "How much evidence supports EventShock?" })).toBeInTheDocument();
    for (const n of ["Sentiment", "Event understanding", "Impact", "Stress engine"]) expect(screen.getByRole("heading", { name: n })).toBeInTheDocument();
    expect(screen.getAllByText("Experimental model").length).toBe(3);
    expect(screen.queryByText("Validated model")).not.toBeInTheDocument();
    expect(screen.getAllByText("Not called validated.").length).toBe(3);
    expect(screen.getByText("Deterministic")).toBeInTheDocument();
    expect(screen.getByText(/Not a model\./)).toBeInTheDocument();
  });

  it("counts the checks in words and keeps what failed one click away", async () => {
    renderAt("/evidence");
    expect(await screen.findByRole("img", { name: "1 of 4 checks passed, 2 not met, 1 not evaluable" })).toBeInTheDocument();
    expect(screen.getByText(/served macro-F1 on gold history rows/)).toBeInTheDocument();
    expect(screen.getByText(/C7 \(issuer\); C2 \(issuer\)/)).toBeInTheDocument();
  });

  it("offers methodology, evaluation, datasets, mathematics, limitations and how it is built as tabs", async () => {
    renderAt("/evidence");
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Methodology", "Evaluation", "Datasets", "Mathematics", "Limitations", "Outcome check", "Scope", "How it is built"]);
    expect(screen.getByRole("tab", { name: "Methodology" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Datasets" }));
    expect(screen.getByRole("tab", { name: "Datasets" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("SEC EDGAR filings")).toBeInTheDocument();
  });

  it("moves between tabs with the arrow keys", async () => {
    renderAt("/evidence");
    const first = await screen.findByRole("tab", { name: "Methodology" });
    first.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Evaluation" })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "How it is built" })).toHaveAttribute("aria-selected", "true");
  });

  it("states the temporal discipline and separates what a model may see from what it is refused", async () => {
    renderAt("/evidence");
    expect(await screen.findByText(/Temporal discipline: nothing from the future/)).toBeInTheDocument();
    expect(screen.getByText("What a model may see")).toBeInTheDocument();
    const refused = screen.getByText(/Refused: only known after the event/).closest("section") as HTMLElement;
    expect(within(refused).getByText("eps_surprise")).toBeInTheDocument();
    expect(within(refused).getByText("ticker")).toBeInTheDocument();
    expect(within(refused).queryByText("earn_window")).not.toBeInTheDocument();
    const calendar = screen.getByText(/Structured calendar/).closest("section") as HTMLElement;
    expect(within(calendar).getByText("earn_window")).toBeInTheDocument();
  });

  it("lists the four kinds of number and what each means", async () => {
    renderAt("/evidence");
    expect(await screen.findByText("Four kinds of number, never blurred")).toBeInTheDocument();
    for (const k of ["Model prediction", "Historical observation", "Scenario assumption", "Realised outcome"]) expect(screen.getAllByText(k).length).toBeGreaterThan(0);
  });

  it("states every verdict in words: a helpful block, a block with no measurable effect", async () => {
    renderAt("/evidence?tab=evaluation");
    expect(await screen.findByText("helps", { selector: "span" })).toBeInTheDocument();
    expect(screen.getAllByText(/no measurable effect/).length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: /calendar block.*, ridge, test: .*95% interval/ })).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText("N/A")).toBeInTheDocument();
  });

  it("shows the decision, cost and the finance-in-context probe for the representation comparison", async () => {
    renderAt("/evidence?tab=evaluation");
    expect(await screen.findByText(/the shipped TF-IDF model stays/)).toBeInTheDocument();
    expect(screen.getByText("not adopted")).toBeInTheDocument();
    expect(screen.getByText(/controlled benchmark/)).toBeInTheDocument();
    expect(screen.getByText("93%", { exact: false })).toBeInTheDocument();
  });

  it("shows the event-versus-quiet-session lift by filing type", async () => {
    renderAt("/evidence?tab=evaluation");
    expect(await screen.findByText("earnings (item 2.02)")).toBeInTheDocument();
    expect(screen.getByText("officer changes (5.02)")).toBeInTheDocument();
  });

  it("says plainly when a study has not been run instead of showing anything", async () => {
    evidenceResponse = evidence({ study: { available: false, command: "make impact-study", p1_regression: "", runs: [], track_f: { available: false, pairs: 0, by_item: [], earnings_by_year: [], non_earnings_by_year: [], item_code_increment: [], note: "" } },
      representation: { available: false, command: "make bakeoff", decision: "", baseline: "", sets: {}, candidates: [], cost: [], probe: [] } });
    renderAt("/evidence?tab=evaluation");
    expect(await screen.findByText("The incremental-value study has not been produced")).toBeInTheDocument();
    expect(screen.getByText("The representation comparison has not been produced")).toBeInTheDocument();
    expect(screen.getAllByText(/make /).length).toBeGreaterThan(1);
  });

  it("writes the mathematics once, typeset, for every stage", async () => {
    renderAt("/evidence?tab=mathematics");
    expect(await screen.findByText(/Worked example at impact 7 against a reference of 7/)).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('[data-tex="ready"]')).not.toBeNull());
    expect(document.querySelectorAll(".katex").length).toBeGreaterThan(3);
  });

  it("states the limitations plainly", async () => {
    renderAt("/evidence?tab=limitations");
    expect(await screen.findByText("All labels are AI-annotated.")).toBeInTheDocument();
  });

  it("is not available in the demo profile", async () => {
    metaResponse = meta;
    renderAt("/evidence");
    expect(await screen.findByText("No evidence in the demo profile")).toBeInTheDocument();
  });
});
