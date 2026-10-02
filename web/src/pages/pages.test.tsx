import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, vi } from "vitest";
import { EventPage } from "./EventPage";
import { FeedPage } from "./FeedPage";
import { PipelinePage } from "./PipelinePage";
import { StressPage } from "./StressPage";

const AS_OF = "2026-10-01T12:00:00Z";

const meta: Record<string, unknown> = {
  app: "EventShock", version: "0.1.0", mode: "REPLAY", profile: "demo", replay: null, data_origin: "DEMO_FIXTURE", as_of: AS_OF,
  trigger_threshold: 7, base_currency: "USD", signal_count: 2, asset_count: 3, scenario_set_version: "1",
  engine_version: "1.0.0", notices: [],
  taxonomy: [
    { id: "CREDIT_FUNDING", label: "Credit / Funding", description: "", default_scenario: "scn_credit" },
    { id: "PRODUCT_OPERATIONS", label: "Product / Operations", description: "", default_scenario: "scn_ops" },
  ],
};

const row = (over: object) => ({
  id: "sig_1", headline: "Meridian flags funding gap", source: "Ledger Wire", source_type: "NEWS",
  published_at: "2026-10-01T08:30:00Z", entity_id: "ENT_M", entity_name: "Meridian Bancorp", ticker: "MRDB",
  sector: "Financials", category: "CREDIT_FUNDING", sentiment_score: -0.72, impact_score: 9, status: "COMPLETE",
  source_count: 5, data_origin: "DEMO_FIXTURE", ...over,
});

const feed = {
  total: 2,
  items: [
    row({}),
    row({ id: "sig_2", headline: "Kestrel launches jet", entity_name: "Kestrel", ticker: "KSTR", category: "PRODUCT_OPERATIONS", sentiment_score: 0.7, impact_score: 2, source_count: 2 }),
  ],
};

const detail = (impact: number | null) => ({
  id: "sig_2",
  document: { id: "d", source: "Ledger Wire", source_type: "NEWS", published_at: "2026-10-01T08:30:00Z", ingested_at: "2026-10-01T08:31:00Z", author: null, headline: "Kestrel launches jet", body: "Body text", url: "https://demo.invalid/x", language: "en", raw_metadata: {} },
  entity: { entity_id: "ENT_K", entity_name: "Kestrel", ticker: "KSTR", sector: "Industrials", country: "FR", link_confidence: 0.99 },
  sentiment: { positive: 0.8, neutral: 0.1, negative: 0.1, score: 0.7 },
  event: { category: "PRODUCT_OPERATIONS", probabilities: { PRODUCT_OPERATIONS: 0.73, CREDIT_FUNDING: 0.03, GEOPOLITICAL: 0.03, MACROECONOMIC: 0.03, MA_CORPORATE_ACTION: 0.03, REGULATORY_LEGAL: 0.03, EARNINGS_FINANCIAL_PERFORMANCE: 0.1, MARKET_VALUATION: 0.02 } },
  impact: impact === null ? null : { score: impact, raw: impact / 10, drivers: [{ feature: "event_type", contribution: 0.05, note: "" }], quantisation: "ceil(raw * 10), min 1" },
  evidence: { source_count: 2, unique_domain_count: 2, recent_mention_count: 5, coverage_velocity: 0.3, novelty_score: 0.45, model_confidence: 0.85, contradicted_by: [], corroborating: [] },
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

let stressResponse: unknown = completed;
let metaResponse: unknown = meta;
let reportResponse: unknown = report;
let signalDetail: unknown = detail(2);

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/api/meta")) return json(metaResponse);
      if (url.endsWith("/api/pipeline/report")) return json(reportResponse);
      if (url.endsWith("/api/models/sentiment")) return json(modelCard);
      if (url.includes("/api/signals?") || url.endsWith("/api/signals")) {
        const q = new URL(url, "http://x").searchParams;
        const cat = q.get("category");
        const items = feed.items.filter((i) => !cat || i.category === cat);
        return json({ total: items.length, items });
      }
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
          <Route path="/pipeline" element={<PipelinePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  reportResponse = report;
  mockFetch();
  stressResponse = completed;
  signalDetail = detail(2);
  metaResponse = meta;
});
afterEach(() => vi.unstubAllGlobals());

describe("Risk Feed", () => {
  it("lists signals with impact, entity and event type", async () => {
    renderAt("/");
    expect(await screen.findByText("Meridian flags funding gap")).toBeInTheDocument();
    expect(screen.getByText("Kestrel launches jet")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Impact 9 of 10, Critical" })).toBeInTheDocument();
    expect(screen.getByText(/1 of 1|2 of 2/)).toBeInTheDocument();
  });

  it("filters by event type through the API", async () => {
    renderAt("/");
    await screen.findByText("Meridian flags funding gap");
    await userEvent.click(screen.getByRole("button", { name: /Product \/ Operations/ }));
    await waitFor(() => expect(screen.queryByText("Meridian flags funding gap")).not.toBeInTheDocument());
    expect(screen.getByText("Kestrel launches jet")).toBeInTheDocument();
  });

  it("explains an API outage instead of failing silently", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    renderAt("/");
    expect(await screen.findByText(/Cannot reach the EventShock API/)).toBeInTheDocument();
  });
});

describe("Event Intelligence", () => {
  it("shows sentiment, event type, impact, evidence and audit, and offers a what-if when below threshold", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByRole("heading", { name: "Kestrel launches jet" })).toBeInTheDocument();
    expect(screen.getByText("Impact assessment")).toBeInTheDocument();
    expect(screen.getByText("Event type")).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText(/Below the trigger threshold/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Run as what-if/ })).toHaveAttribute("href", "/stress?signal=sig_2");
    expect(screen.getByText(/Fixture drivers/)).toBeInTheDocument();
  });

  it("never invents an impact for a partial signal", async () => {
    signalDetail = detail(null);
    renderAt("/events/sig_2");
    expect(await screen.findByText("Impact unavailable for this signal")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Run stress test|Run as what-if/ })).not.toBeInTheDocument();
  });
});

describe("Portfolio Stress", () => {
  it("runs on arrival from an event and shows before/after, contributors and audit", async () => {
    signalDetail = detail(8);
    renderAt("/stress?signal=sig_2&run=1");
    const hero = await screen.findByRole("region", { name: /before and after stress/i });
    expect(within(hero).getByText("$1.0M")).toBeInTheDocument();
    expect(within(hero).getByText("$900.0K")).toBeInTheDocument();
    expect(within(hero).getByText("−$100.0K")).toBeInTheDocument();
    expect(screen.getByText("Largest loss contributors")).toBeInTheDocument();
    expect(screen.getByText("Illustrative scenario assumptions")).toBeInTheDocument();
    expect(screen.getByText("Computed · deterministic engine")).toBeInTheDocument();
    expect(screen.getByText("run_2")).toBeInTheDocument();
  });

  it("reports a non-triggered run honestly and offers a what-if", async () => {
    stressResponse = notTriggered;
    renderAt("/stress?signal=sig_2");
    await userEvent.click(await screen.findByRole("button", { name: /Run stress test/ }));
    expect(await screen.findByText("Not triggered")).toBeInTheDocument();
    expect(screen.getByText(/below the trigger threshold/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run as what-if anyway/ })).toBeInTheDocument();
    expect(screen.queryByText("Largest loss contributors")).not.toBeInTheDocument();
  });

  it("blocks the run for a partial signal", async () => {
    signalDetail = detail(null);
    renderAt("/stress?signal=sig_2");
    expect(await screen.findByText("This signal has no impact score")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run stress test/ })).toBeDisabled();
  });
});

describe("Real-source replay", () => {
  beforeEach(() => {
    metaResponse = realMeta;
    signalDetail = { ...detail(8), data_origin: "REAL_SOURCE_PLACEHOLDER_NLP", provenance, model_versions: { sentiment: "placeholder-v0-lexicon", event: "placeholder-v0-keywords", impact: "placeholder-v0-heuristic", entity_resolver: "dictionary-er-v1", feature_schema: "1" } };
  });

  it("labels the feed honestly as real documents with placeholder NLP", async () => {
    renderAt("/");
    expect(await screen.findByText(/Real documents, placeholder sentiment\/event\/impact/)).toBeInTheDocument();
  });

  it("shows where a signal came from, how its entity was chosen and what was folded away", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByText("What happened before this screen")).toBeInTheDocument();
    expect(screen.getByText("gdelt/articles.jsonl:42")).toBeInTheDocument();
    expect(screen.getByText("When GDELT first saw the page")).toBeInTheDocument();
    expect(screen.getByText(/Ambiguous name with finance context/)).toBeInTheDocument();
    expect(screen.getByText(/Refused: Visa/)).toBeInTheDocument();
    expect(screen.getByText(/2 exact duplicates folded away/)).toBeInTheDocument();
    expect(screen.getByText("Placeholder heuristic · not a trained model")).toBeInTheDocument();
    expect(screen.getByText("Real source · placeholder NLP", { selector: "span" })).toBeInTheDocument();
  });

  it("explains the pipeline: record accounting, quarantine reasons and real vs placeholder", async () => {
    renderAt("/pipeline");
    expect(await screen.findByText("From records to signals")).toBeInTheDocument();
    expect(screen.getByText("10 read = 2 quarantined + 1 folded + 7 kept")).toBeInTheDocument();
    expect(screen.getAllByText("NON_ENGLISH").length).toBeGreaterThan(0);
    expect(screen.getByText("PLACEHOLDER (TFN: source label)")).toBeInTheDocument();
  });

  it("does not hide failed download requests", async () => {
    renderAt("/pipeline");
    expect(await screen.findByText("1 of 2 requests succeeded")).toBeInTheDocument();
    expect(screen.getByText("FAILED")).toBeInTheDocument();
    expect(screen.getByText(/gave up after 3 attempts \(HTTP 429\)/)).toBeInTheDocument();
    expect(screen.getByText("76 new / 97 · 1 attempt")).toBeInTheDocument();
  });

  it("says plainly that the demo profile has no pipeline", async () => {
    metaResponse = meta;
    renderAt("/pipeline");
    expect(await screen.findByText("No pipeline in the demo profile")).toBeInTheDocument();
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

  it("shows the model behind a sentiment score, its confidence and its held-out and own-source results", async () => {
    renderAt("/events/sig_2");
    expect((await screen.findAllByText("Trained model")).length).toBe(2); // sentiment card tag + provenance step 4
    expect(screen.getByText("87%", { exact: false })).toBeInTheDocument();
    expect(await screen.findByText(/macro-F1 0\.78; on our own AI-labelled sources only 0\.44/)).toBeInTheDocument();
    expect(screen.getByText("Real source · model sentiment", { selector: "span" })).toBeInTheDocument();
    expect(screen.queryByText(/In-sample/)).not.toBeInTheDocument();
  });

  it("keeps event type and impact visibly placeholder next to the model-backed sentiment", async () => {
    renderAt("/events/sig_2");
    expect(await screen.findByText("Placeholder heuristic · not a trained model")).toBeInTheDocument();
    expect(screen.getAllByText("Placeholder rules")).toHaveLength(3); // event type card, provenance event, provenance impact
    expect(screen.getAllByText("Trained model").some((e) => e.classList.contains("text-pos"))).toBe(true); // provenance step 4
  });

  it("warns when the model has seen the exact text, so the score is not evidence of accuracy", async () => {
    signalDetail = { ...(signalDetail as object), provenance: modelProvenance({ seen_in_training: true }) };
    renderAt("/events/sig_2");
    expect(await screen.findByText("In-sample: the model trained on this exact text")).toBeInTheDocument();
    expect(screen.getByText(/in-sample/)).toBeInTheDocument();
  });

  it("falls back to the placeholder wording for a signal the lexicon scored", async () => {
    signalDetail = { ...detail(8), data_origin: "REAL_SOURCE_PLACEHOLDER_NLP", provenance, model_versions: { sentiment: "placeholder-v0-lexicon", event: "placeholder-v0-keywords", impact: "placeholder-v0-heuristic", entity_resolver: "dictionary-er-v1", feature_schema: "1" } };
    renderAt("/events/sig_2");
    expect(await screen.findByText(/Sentiment is tone only/)).toBeInTheDocument();
    expect(screen.queryByText("Trained model", { selector: "span" })).not.toBeInTheDocument();
  });

  it("explains the model on the pipeline page: results per evaluation set, baselines, errors and limits", async () => {
    renderAt("/pipeline");
    const panel = (await screen.findByRole("heading", { name: "Sentiment model" })).closest("section") as HTMLElement;
    const w = within(panel);
    expect((await w.findAllByText("Twitter Financial News, held-out test")).length).toBeGreaterThan(0);
    expect(w.getAllByText("0.778").length).toBeGreaterThan(0); // model macro-F1 on held-out TFN
    expect(w.getAllByText("0.527").length).toBeGreaterThan(0); // the lexicon it replaces
    expect(w.getByText(/Not run: Raw file not present/)).toBeInTheDocument(); // skipped sets are shown, not hidden
    expect(w.getByText("Gold labels are AI-annotated.")).toBeInTheDocument();
    expect(w.getByText("Event type: placeholder rules")).toBeInTheDocument();
    await userEvent.click(w.getByRole("button", { name: /Gold set, our own sources/ }));
    expect(await w.findByText(/Ours\./)).toBeInTheDocument();
    const stages = screen.getByText("What is real and what is a stand-in").closest("section") as HTMLElement;
    expect(within(stages).getByText(/MODEL \(tfidf-lr-v1/)).toHaveClass("text-pos");
  });

  it("does not show a model card on the demo profile", async () => {
    metaResponse = meta;
    renderAt("/pipeline");
    expect(await screen.findByText("No pipeline in the demo profile")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sentiment model" })).not.toBeInTheDocument();
  });
});
