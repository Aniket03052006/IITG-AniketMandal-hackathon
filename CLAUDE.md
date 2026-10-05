# CLAUDE.md — EventShock

Guidance for Claude Code working in this repo. Read fully before any task.

## Project
**EventShock** — an event-driven financial risk intelligence & stress-testing engine, built solo (team size 1) for the
S&P Global & Crisil Campus Hackathon 2026 (IIT Guwahati, candidate Aniket Mandal).

Core pipeline:
raw data → validation → dedup → entity resolution → sentiment → event classification → calibrated impact
→ `RiskSignal` → portfolio exposure → scenario mapping → deterministic stress test → explainable dashboard.

Architecture is **finalized**. Do not redesign unless there is a concrete contradiction or blocker; if so, state it and ask.

## Problem statement (what is graded)
**Core deliverable — AI/NLP Risk Engine**
- Ingest text from **≥ 2 different sources** (e.g. news + social posts).
- For a company/event, emit structured output with:
  - **Sentiment Score**: numeric, −1.0 … 1.0
  - **Event Classification**: categorical (Geopolitical, Macroeconomic, Credit Event, Merger/Acquisition, Product Launch, …)
  - **Impact Score**: severity, 1–10
- Expose signals to downstream consumers (simple API or file output).

**Downstream — at least ONE of:**
- **Module A** — tactical index rebalancer: 10–20 mock stocks (e.g. S&P 100); sentiment up → weight up, down → weight down;
  dashboard of weights over time.
- **Module B** — strategic stress tester: synthetic wholesale-banking portfolio (loans, bonds, derivatives) built from sample
  transaction data; high-impact event (e.g. Geopolitical & Impact > 7) triggers shocks (e.g. −10% equities, +2% rates);
  dashboard of portfolio value before vs after. EventShock's pipeline targets **Module B**.

**Suggested data** (all free, no proprietary data): GDELT, Kaggle financial-news sentiment, NewsAPI, Kaggle stock tweets,
`yfinance`, Alpha Vantage, Salad Money Open Banking transactions, Kaggle Financial Transactions dataset.

## Submission requirements (from `1.Submission Guidelines_External.docx.md`)
- **Public** GitHub repo; incremental commit history preferred over one final commit; no large binary/data dumps.
- Layout must include: `README.md`, `requirements.txt`, `LICENSE` (MIT), `src/`, `data/`, `docs/presentation.pdf`
  (5–7 slides), `docs/architecture.png`.
- `README.md` must follow the mandatory template (sections 1–5, header fields) and state the **exact run command**.
- `/data` must hold all CSV/JSON used to run the prototype, with sources + assumptions documented ("Dataset Used").
- Demo video: YouTube **unlisted**, link in README. (Guidelines say 10 min; the problem statement says ≤ 5 min live demo — target
  ≤ 5 min.) Live jury pitch + technical Q&A for finalists: design choices, code, data assumptions must be defensible.
- Never use real/confidential S&P Global or Crisil data. Synthetic or public only.
- AI assistance is allowed with honesty/integrity.

## Working method — BASIC → TEST → VERIFY → FREEZE → MOVE ON
We build **one stage at a time**. For every stage:
1. Implement only the requested stage; never pre-build future stages.
2. Define interfaces/contracts first.
3. Write tests before or alongside code; cover happy paths, malformed inputs, and key edge cases.
4. Give exact commands and expected output. Identify what a human must verify manually.
5. "It runs" ≠ "it's verified". Never claim verification that wasn't performed.
6. Never silently swallow errors. Fail loudly with clear messages.
7. No unnecessary dependencies. Prefer deterministic, reproducible behavior (fixed seeds, pinned fixtures).
8. Configuration lives outside code (`configs/`, `.env`); `.env.example` is committed, `.env` never.
9. Provider-specific logic (GDELT, EDGAR, NewsAPI, yfinance, …) sits behind adapters.
10. No LLM where a deterministic/classical method suffices.
11. **Excluded from MVP:** Kafka, Neo4j, autonomous agents, generative RAG, other heavy infra. (Stage 8 adds read-only *retrieval* over a static, hash-pinned index of past reports: nothing generative reads retrieved text and it never feeds the score.)

When modifying existing code: list files changed and why, preserve verified behavior, add regression tests.

### End-of-stage report (always, in this order)
IMPLEMENTED · FILES CHANGED · TESTS ADDED · COMMANDS TO RUN · EXPECTED RESULT · MANUAL VERIFICATION · KNOWN LIMITATIONS · NEXT STAGE

## Project journey (mandatory)
Maintain `docs/PROJECT_JOURNEY.md`: **what we did, what broke, how we fixed it**, per stage, in chronological order.
Update it **after every task** (not only at stage end), and whenever something notable breaks, before reporting the task done:
a small task gets a short dated entry under the current stage; a new stage gets its own section.
Be honest — failed approaches and dead ends belong there; it feeds the deck's "challenges" slide and jury Q&A.

## Git rules
- **Never add Claude/AI co-authorship in any visible place**: no `Co-Authored-By` trailers, no "Generated with Claude Code"
  lines, in commit messages, PR descriptions, README, docs, or file headers. `.claude/settings.json` blanks the attribution
  settings; do not override that.
- Commit only when the user asks. Small, incremental commits, imperative messages.
- `1.Submission Guidelines_External.docx.md` is git-ignored on purpose; leave it that way.

## Current repo state (Stage 11 event-to-portfolio propagation and adjustable side-cars on top; Stage 10 multi-scope event intelligence; Stage 9 personal portfolios; Stage 4 frozen: submission hardening; Stage 5 UI pass; Stage 6 one-engine pass; Stage 7 risk assessment on top; Stage 8 outcome audit + historical analogues, 2026-10-05)
- Git: branch `main`, incremental commits already exist; commit only when asked.
- **Stage 11 (event → portfolio propagation, materiality, generated scenarios, attribution, concentration, and manual adjustment of the side-cars, 2026-10-05; models, severity, the replay pack and every pinned digest untouched; read `docs/PORTFOLIO_PROPAGATION.md` first).** A derived side-car like Stage 10: `src/eventshock/propagation/` + `configs/propagation.yaml` (judgement priors, in the freeze manifest) and `src/eventshock/adjust/`; nothing is stored on a `RiskSignal`, and nothing in `assessment/ pipeline/ stress/ modeling/ domain/ retrieval/ portfolio/ intelligence/ llm/ ingestion/ services/` may import either package (`tests/unit/test_propagation_architecture.py`). `GET /api/signals/{id}/propagation` returns the mapping graph (every edge: rule, basis, status OBSERVED / SCENARIO_ASSUMPTION / USER_ASSUMPTION; a mapping, never "causal"; it abstains when nothing defensible exists), the materiality of the event to the portfolio (LOW / MEDIUM / HIGH / CRITICAL by an exposure × severity **lookup** with a bump and two named caps, never a weighted score; NONE / UNDETERMINED states) and the scenario it would generate (the catalog scenario of the event class + propagated explicit-sector shocks from the transmission table; gated on severity, relevance, direction, mapping and reach; **SCENARIO UNAVAILABLE** with the failed gate otherwise; always labelled "SCENARIO SIMULATION — NOT A PREDICTION"; version = hash of its shocks). `POST /api/signals/{id}/portfolio-stress` runs it through the unchanged engine (`StressService.run_scenario`) with the exposure chain and `StressAttribution` (by shock kind, issuer, sector, industry, market factor, risk factor, asset class, position; every table reconciles to the total within a cent or the builder raises). `GET /api/concentration` flags only meaningful concentration; `/concentration/overlaps` shows independent events on the same text-evidenced risk factor and the same holdings. The only engine edit is additive (`ShockSpec.sector`: a SECTOR shock may name its sector; catalog scenarios name none, so `GOLDEN_RUN_ID` is unchanged). **Adjustable by hand** (`/api/adjustments`, the *Adjust assumptions* drawer, `?open=adjust`): a whitelist (`adjust/registry.py`) of scenario gates and sizes, relevance and concentration thresholds, the transmission table (weights, on/off, edges you add) and the Stage 10 intelligence priors; stored in git-ignored `data/live/overrides/overrides.json` (`EVENTSHOCK_OVERRIDES_PATH`; tests redirect it in `tests/conftest.py`), patched into the raw YAML **before** the strict models validate it, rebuilt and swapped under a lock, rolled back on failure, labelled `USER_ASSUMPTION` and counted on every answer (`adjustments`); a reset restores every byte. Overrides are server-global; the shipped configs and freeze manifest are never touched. Known limits to keep visible: all edges and sizes are unvalidated priors; no FX or commodity engine factor (oil acts only through sector proxies; FX is reported, never simulated); industry is known only for the 25 mapped tickers. UI: `web/src/components/propagation/*` (in the Event page's Stress chapter, the Stress page, the portfolio editor) and `web/src/components/adjust/*`. Tests: `tests/unit/test_propagation_*.py`, `test_adjust.py`, `test_stress_sector_shock.py`, `tests/integration/test_propagation_api.py`, `tests/e2e/test_propagation_replay.py`, `web/src/components/{propagation,adjust}/*.test.tsx`; `make smoke` covers it.
- **Stage 10 (multi-scope event intelligence, 2026-10-05; models, severity, scenarios, replay pack and every pinned digest untouched; read `docs/EVENT_INTELLIGENCE.md` first).** A derived side-car, `src/eventshock/intelligence/` + `configs/intelligence.yaml`: nothing is stored on a `RiskSignal` (any new field would move `GOLDEN_SERVED_DIGEST`), nothing in `assessment/`, `pipeline/`, `stress/`, `modeling/` may import it (`tests/unit/test_intel_architecture.py`). Per signal it returns `EventIntelligence` (`GET /api/signals/{id}/intelligence?as_of=`, and on `POST /api/analyze`, which also takes optional `headline` and `url`; the url is attribution only and is **never fetched**): hierarchical scope (COMPANY/INDUSTRY/SECTOR/GEOGRAPHY/MACRO/MARKET/THEME/UNRESOLVED, path, evidence, resolution status, rule-tier confidence that is not a probability; a level with no evidence is omitted, never filled; it never resolves a company), event grouping over report clusters with every report kept, independent sources, an evidence-strength tier **kept apart from model confidence**, novelty class, narrative velocity, closed-lexicon claim contradiction (never from tone), a rule-driven lifecycle with a timeline (RESOLVED only on explicit evidence, never from falling volume), affected view, relevance, stress, and per-section abstention. Replay-assigned clocks make velocity, lifecycle and novelty UNAVAILABLE. Every threshold and vocabulary is an unvalidated judgement prior; say so. UI: `web/src/components/intelligence/*` (panel under the Event hero, summary on Analyze, scope chips and filters on the Feed). Parity of replay and engine is tested (`tests/e2e/test_intelligence_replay.py`). Deferred on purpose: URL fetching, region shocks, a learned grouping or claim model, paraphrase-robust contradiction, embedding-based grouping for live text.
- **Stage 9 (optional personal portfolios, 2026-10-05; models, severity, scenarios, replay pack and every pinned digest untouched; read `docs/PORTFOLIOS.md` first).** The synthetic book is the default and read-only; a personal portfolio is used only when a request carries `portfolio_id` (client state: localStorage / `?portfolio=`; "Use default portfolio" resets). `src/eventshock/portfolio/` (resolver with labelled sources, atomic file store in git-ignored `data/live/portfolios/`, exposure, exposure chain, comparison), `configs/portfolio.yaml`, `data/portfolio/instruments.json`, `data/replay/market/betas.json` (`make portfolio-betas`; Vasicek-shrunk single-factor beta, clipped to [0, 3] when used). Engine additions only: `AssetClass.CASH`/`OTHER`, bond `spread_sensitivity` (omitted at default so `content_hash` and `GOLDEN_RUN_ID` are unchanged; pinned by a test). Keep four things apart everywhere: event severity (uncalibrated), portfolio relevance (your holdings), scenario assumptions, modeled impact (never "forecast"). Rejected on purpose: convexity, vol-regime scaling, invented sector transmission, region shocks, FX. Known behaviour: scenario sector shocks are always adverse. Tests: `tests/unit/test_portfolio_*`, `test_stress_user_portfolio.py`, `tests/integration/test_portfolio_api.py`, `web/src/pages/portfolio.test.tsx`; tests redirect the store with `EVENTSHOCK_PORTFOLIO_STORE_PATH` (conftest).
- **Sentiment is a trained model** (`tfidf-lr-v1`; `pipeline/sentiment_model.py`, `models/sentiment/`, `make train-sentiment`; read `docs/SENTIMENT_MODEL.md` before changing it).
- **Event type is a trained model** (`tfidf-lr-event-v1`, 9-way with abstention; `pipeline/event_model.py`, `models/event/`, `make train-event`; read `docs/EVENT_MODEL.md`). Labels are AI-annotated; its pre-registered bar is **not met** on gold. Gold and the replay check set are evaluation-only.
- **Impact is now a trained model, labelled *experimental*** (`impact-v1`; read `docs/IMPACT_MODEL.md` before touching it). Two scopes in one artifact: `ISSUER` (abnormal return of one resolved company) and `MARKET` (S&P 500's own move, for documents naming no company), each with its own lifecycle
  `NOT_AVAILABLE → DATASET → BASELINE → TRAINED → CALIBRATED → PRODUCTION` derived from a **pre-registered acceptance bar** in `configs/impact_model.yaml` (never edit it after seeing results; the git history is the proof). Both scopes are `CALIBRATED` (UI: "experimental model"): market-state skill is real, event-specific skill is not measurable (placebo skill ≥ real skill).
  Code: `pipeline/impact_model.py` (serving), `impact_card.py`, `impact_features.py` (the one feature schema), `market_context.py` (anchoring + frozen market pack); `modeling/impact_dataset.py`, `impact_train.py`, `impact_stats.py`, `market_pack.py`; `ImpactModelEnricher` in `pipeline/enrich.py` runs impact as a **post-pass after novelty**.
  Signals the model cannot score (several issuers, weak link, replay-assigned clock, no market data) keep the labelled placeholder rule, with the reason in `provenance.impact_note`; impact origin is **per signal** (`stage_origins.impact`), and the UI never shows an unvalidated number as authoritative. Missing artifact → labelled heuristic (`require: false`); modified artifact → `ConfigError`.
  Commands: `make market-context impact-table train-impact` (the last takes ~45 min; `--dev-only OUT` skips test/live). Training must stay chronological: rolling-origin folds, 5-session embargo, test and live scored once; features must be registered `AT_EVENT_TIME` in `modeling/leakage.py` (`unique_domains`, `source_count`, `ticker`, … are banned).
  The serving market context (`data/replay/market/context.json`, derived statistics only, hash-pinned in the replay manifest) must be rebuilt (`make market-context`) whenever prices or the feature schema change.
- **FROZEN (2026-10-03): no more model experimentation unless a correctness bug is found (Stage 8 ran additive, pre-registered evidence studies and side-cars only: no frozen artifact changed).** Final model table, lifecycle decisions and per-model can/cannot-use: `docs/FINAL_MODEL_REPORT.md` (numbers are test-checked against the cards). All three trained stages are *experimental*; the event model's independent-evaluation check fails until a set outside its adoption is scored (human adjudication of `data/gold_v2/adjudication_v2.csv` and `data/gold/adjudication.csv` was **skipped by decision**; protocol in `docs/EVIDENCE_V2.md` §10). `make freeze-check` verifies `docs/freeze_manifest.json` (models, configs, gold, calendar, replay, evidence); after any deliberate change run `make freeze-write` and journal it. `make smoke` starts the real server and checks API/model ids/hashes/evidence/stress/UI. `tests/e2e/test_replay_served.py` pins the served configuration (impact-v2 + hybrid event + TF-IDF parity model).
- **Stage 8 (finance-grounded validation, historical analogues, scenario reality check, 2026-10-05; additive: trained models, `severity.yaml`, the replay pack and every pinned digest untouched; read `docs/FINANCE_THEORY.md` and `docs/ANALOGUES.md` first).** Pre-registered in `configs/evidence_v3.yaml` (never edit after seeing a result; every evidence file records its sha256 and `tests/unit/test_stage8_evidence.py` fails if they diverge). Findings to keep visible, none to be softened: (1) the realised outcome around ordinary company headlines is barely distinguishable from an ordinary day (stratified AUC 0.523, 0.508 without earnings; earnings are the exception), so a realised move cannot label "how serious is this headline" (`outcome_audit.json`); (2) the **severity scorecard is `HEURISTIC_UNCALIBRATED`** against realised moves (2025 test +0.007 [-0.025, +0.039], 2026 live -0.021 [-0.086, +0.040]; `severity_validity.json`), shown on the Evidence page's *Outcome check* tab; the claim is "transparent triage scale, not outcome-calibrated", never "validated"; (3) the EWMA sigma was adopted as **`outcome-v3` for side-car layers only** by the pre-registered rule (`modeling/outcome_v3.py`; the frozen v2 table and models keep outcome-v2); (4) **historical analogues** (`retrieval/`, `services/analogues.py`, `GET /api/signals/{id}/analogues`, `data/replay/analogues/` = 6,531 trusted-clock episodes as e5-large vectors + outcomes, hash-pinned, no prices) are RETRIEVED evidence with hindsight outcomes, point-in-time (future-invariance tested), story-collapsed, with an explicit `NO_RELIABLE_ANALOGUE` state and unresolved reports refused; e5 beats TF-IDF at retrieving same-event precedent (P@5 0.504 vs 0.443; event queries 0.389 vs 0.255) but **retrieval adds no information about the realised move beyond regime + calendar, so no analogue-derived quantity enters the severity score** (`analogue_outcome_value.json`); the similarity floor (0.78) is read from `analogue_floor.json` (`similarity_floor: rule` in `configs/retrieval.yaml`), never typed; (5) `GET /api/scenarios/{id}/history-check` ranks scenario shocks against 1/5/21-session history since 2014 (`stress/history_check.py`, `data/replay/market/shock_history.json`, quantiles only); credit/PD/LGD shocks are reported not checkable; the stress arithmetic is unchanged. New provenance members `Origin.RETRIEVED` / `Kind.RETRIEVED`. Commands: `make outcome-audit severity-validity analogue-corpus analogue-embed analogue-index analogue-eval shock-history` (research commands need git-ignored prices/impact table; `analogue-embed` ~45 min in `.venv-emb`). Post-hoc analyses are labelled as such in the evidence and never change a label. Deferred: LLM arm of the validity study (quota), a stricter display floor, ex-earnings sigma windows, a learned analogue re-ranker.
- **Stage 7 (risk assessment, 2026-10-05; trained models, the replay pack and every pinned digest untouched; read `docs/RISK_ASSESSMENT.md` first).** An additive side-car layer: `assessment/` + `llm/`, `AssessmentService` derives a `RiskAssessment` from a `RiskSignal` (never stored on it, so digests/fixtures/goldens stay valid). **The LLM reads, code decides**: a language model (Groq `openai/gpt-oss-120b` by default or the Anthropic Messages API, both over `urllib` with a forced tool/function call and closed enums; OFF by default: `EVENTSHOCK_LLM=1` + `GROQ_API_KEY`/`ANTHROPIC_API_KEY` from the environment or the git-ignored `.env`, `EVENTSHOCK_LLM_PROVIDER`, `make run-llm`; 30 s total budget per call, 30 calls/min cap) fills a closed schema that `assessment/grounding.py` checks against the text (entities must appear and can never become the issuer; quotes must be verbatim; ids must be in `configs/semantics.yaml`); any failure falls back, labelled, to the deterministic `RuleExtractor`, and the app works with no key ("rule-based demo mode"). Answers are cached (`data/live/llm_cache.jsonl`, `EVENTSHOCK_LLM_CACHE_PATH`; tests must never touch it, `tests/conftest.py` sets a temp path and `EVENTSHOCK_LLM=0`; **no test calls the real API**, use `tests/fakes.py::FakeLLM`). **The headline number is a transparent scorecard, `severity-v2`** (`assessment/rubric.py`, `severity.py`, `freshness.py`; `configs/severity.yaml` + `configs/semantics.yaml` indicator levels; replaces the v1 weighted average, which compressed the scale to 4-7: see `docs/RISK_ASSESSMENT.md`). Four anchored answers (intensity 0-4, reach, certainty, direction) → fixed matrix (anchors are the middles of the five semantic bands 1-2/3-4/5-6/7-8/9-10) → certainty × direction scaling → two bounded data adjustments (VIX regime under an explicit freshness policy: last completed session, at most one session behind, else excluded with the reason; novelty) → 1-10. Tone, model confidence, outlet count and source reliability are NOT inputs (reliability is shown beside the score). Each answer is first derived by rules; the AI (prompt `extract-v6`) answers the same four questions with a reason and may move one step from the rules baseline (a verbatim quote lets it stand only where the rules had no evidence: `baseline_informed`); `ai_effect` and the rules-only score are reported. Every part carries an origin (AI / DATA / RULES / HYBRID / ASSUMPTION) in `RiskAssessment.provenance`; indicator evidence is QUOTED / KEYWORD / INFERRED. Never edit `severity.yaml` anchors or the benchmark expectations to fit a result. **Benchmark** (`data/benchmarks/`: 64 dev, 32 held-out, pre-registered; `scripts/severity_benchmark.py evaluate|record`, `scripts/severity_ablation.py`; evidence pinned in `docs/evidence/`): the held-out set must never be used to tune a cue; rules-fallback on held-out is weak (spearman 0.39) and that is documented, not hidden. **Pending:** no live-model recording exists for prompt v6 (provider quota); record dev `--fresh` then held-out and re-evaluate before quoting an LLM score distribution. It is not supervised and not validated; say so everywhere. The trained `impact-v2` stays frozen and appears only as a collapsed, labelled *reference* (its acceptance bar is not met: skill ≈ volatility regime), it never drives the trigger. Temporal rule: the score reads only the report, its extraction, the novelty/corroboration that existed at its time and market state ≤ 5 days old; later coverage, filings and realised moves are shown on the timeline but never scored (`tests/unit/test_assessment_temporal.py`). `StressService(severity_provider=…)` makes the trigger, scaling, scenario class and a sector read from the text follow the assessment (audit `impact_origin: ASSESSMENT`); with no provider (demo profile) behaviour and `GOLDEN_RUN_ID` are unchanged. New endpoints: `/signals/{id}/assessment|evidence|timeline`, `/stress-runs?signal_id=`; `POST /analyze` returns `assessment`. UI: the five-step chain (news → AI understanding → risk signal → scenario → portfolio) on Feed/Analyze/Event, `components/assessment/*`; the Feed, Event, Stress and Analyze pages show severity when `meta.capabilities.assessment` is true and the trained-model view otherwise. The three new configs are in the freeze manifest (`make freeze-write` after any deliberate change, journalled).
- **Stage 6 (one risk engine, 2026-10-04; models, thresholds, scenarios and the replay pack untouched).** Read the Stage 6 sections of `docs/PROJECT_JOURNEY.md` and `docs/ARCHITECTURE.md` first. Every `RiskSignal` now has a `scope` (COMPANY / SECTOR / MARKET / UNRESOLVED; `pipeline/scope.py`, `configs/scope.yaml`, deterministic vocabulary rules, measured by `make scope-eval` → `docs/evidence/scope_eval.json`) and `evidence.novelty_measured`; company resolution is an enrichment, not a gate. Stress shocks bind by scope; a scenario with no shock that reaches the event returns `NOT_APPLICABLE` (it used to return a zero P&L). `pipeline/engine.py::RiskEngine` is the one incremental door (pasted text via `POST /api/analyze`, the live GDELT feed, a capture file) built from the same `prepare_record` / `cluster_items` / `build_signal` as the batch run; signals land in `store.LiveSignalStore`, served with the frozen replay run through `CombinedSignalRepository`. New text is scored by the TF-IDF event model when no encoder is installed (labelled in `model_versions` and `/api/live/status`). Live is **off by default**: `make run-live` / `make run-capture`, `configs/live.yaml`; the server calls out only then, through `ingestion/fetch.py`'s transport. `GET /api/signals/{id}/relevance` = what the event means for the book (exposure only). The replay digest moved from `d265604e…` to `70478b2d…` only because of the two new fields: `tests/e2e/test_replay_served.py::test_no_pre_existing_signal_field_changed` pins that the old digest is reproduced without them. Tests must not touch the developer's journal (`EVENTSHOCK_JOURNAL_PATH`, set in `tests/conftest.py`). Deferred on purpose: Kalshi, a learned scope model, contradiction detection, region shocks, live market-context refresh.
- **Stage 5 (judge-facing UI/UX pass, 2026-10-03; UI only, models untouched).** One story, five chapters: Risk Feed (story strip + featured event) → Event Intelligence (hero verdict, chain graphic, *Understand*, *Impact*, *Evidence* with comparables and the "what did EventShock know at this moment?" timeline, *Stress* bridge) → Portfolio Stress (before/after hero, waterfall, drill-down, what-if severity) → Evidence ("how much evidence supports EventShock?" tiles + tabs; the old Data Pipeline is its *How it is built* tab, `/pipeline` redirects). Progressive disclosure: `Why?` / `Show inputs` / `How calculated?` (KaTeX, lazy) / `Technical details` / `Audit trail` open drawers addressed by `?open=`; tabs by `?tab=`; theme by `?theme=`. **Light theme is the default** with a dark toggle (`web/src/styles/tokens.css`: light base in `@theme`, dark in `:root[data-theme="dark"]`; `tokens.test.ts` checks WCAG contrast of both and bans raw colour literals outside the file). Four kinds of number are never blurred (`ProvenanceKind`: model prediction / historical observation / scenario assumption / realised outcome). New read-only backend: `GET /api/signals/{id}/context` (grouped model inputs, issuer 8-Ks before/after the report using the calendar's own strict point-in-time rule, realised outcome) from `services/signal_context.py`; realised outcomes are exported by `make outcomes` to `data/outcomes/replay_outcomes.json` (derived, committed, read only by that endpoint, never on `RiskSignal`). No comparable-*event* retrieval exists: "comparable events" are bucket statistics and the UI says so. Demo: `docs/DEMO_SCRIPT.md`; screenshots: `node scripts/screenshots.mjs docs/screenshots http://127.0.0.1:8000` (Chrome over CDP, motion off).
- **Stage 4 (evidence foundation; read `docs/EVIDENCE_V2.md` first).** Pre-registration: `configs/evidence_v2.yaml` (never edit after seeing results; post-dry-run additions are marked in it and disclosed). New data: `data/events/` (SEC 8-K filings with exact acceptance times + FOMC dates; committed, derived), 2023-25 GKG (six fixed 15-min files/day; raw is git-ignored), `data/gold_v2/` (doubly annotated, evaluation-only), `data/probes/`.
  **Served event model is the hybrid `hybrid-event-v2`** (TF-IDF ‖ e5-large vectors; replay vectors hash-pinned in `data/replay/embeddings/`, no torch at run time; live encoder optional via `requirements-embed.txt`; `served_model_dir` vs reference `model_dir` in `configs/event_model.yaml`). **Served impact model is `impact-v2`** (`configs/impact_model.yaml: served_model_dir`; v1 is the reference/fallback), experimental: it reads an `EventCalendar` (feature availability classes a/b allowed, c = known only after = refused `POST_EVENT`; `pipeline/event_context.py`, `calendar_future_invariance` check), and the impact stage keeps reading the TF-IDF event probabilities (train/serve parity). Finding to keep visible: the calendar adds real skill, text-model outputs add none, the rest is volatility regime; **nothing is validated; never label it so.** `GET /api/evidence` + the Model-evidence page are built only from committed cards and `docs/evidence/*.json`.
- Stage 1: FastAPI + Pydantic backend (`src/eventshock/`), deterministic stress engine, React/Vite/TS/Tailwind UI (`web/`),
  configs, fixtures, tests, docs. Stage-1 fictional fixtures remain as the `demo` profile (`EVENTSHOCK_PROFILE=demo`).
- Stage 2 (default `replay` profile; its sentiment stage has since been replaced by the model above): real documents (GDELT DOC 2.0 metadata + Twitter Financial News sample) from a
  hash-pinned snapshot in `data/replay/` run through `src/eventshock/pipeline/` (normalise → validate/quarantine → entity
  resolution → dedup → placeholder enrichment) into the same `RiskSignal` → stress → UI path. Signals carry
  `data_origin = REAL_SOURCE_PLACEHOLDER_NLP` (plain `PlaceholderEnricher`) or `REAL_SOURCE_MIXED_NLP` (the served path) and a `provenance` block. The plain enricher's sentiment (except TFN labels),
  event type and impact are **placeholder rules** (`configs/placeholder_enrichment.yaml`); in the served path only impact still is. Keep that distinction visible in any new code or UI.
  Network access exists only in `ingestion/fetch.py` (`make fetch-gdelt|fetch-tfn`, resumable); the server never calls out unless the live feed is explicitly enabled (`EVENTSHOCK_LIVE=1`, Stage 6), and then only through that module's transport.
  Data layout and licences: `docs/DATA_LICENSES.md`. Architecture: `docs/ARCHITECTURE.md`.
- Stage 3 prep (modeling-data audit, no models trained): `src/eventshock/modeling/` builds the modeling tables, leakage checks and
  the gold set; `configs/modeling.yaml` defines the impact target, splits and gold quotas; `configs/topic_mapping.yaml` carries a
  trust `tier` per topic. Read `docs/MODELING_READINESS.md` before training anything. Rules that must hold: placeholder
  event/impact fields are never labels; impact features may use only event-time information (`leakage.FEATURE_REGISTRY`);
  gold labels are AI-annotated (`ai:claude`) until a human overrides in `data/gold/adjudication.csv`. The gold sample is frozen
  (do not re-run `gold-sample --force`). Commands: `make audit`, `make probe` (needs `requirements-ml.txt`), `make gold-score`.
- Still outstanding for submission: `docs/architecture.png`, `docs/presentation.pdf`, demo video, README email/video fields.
- Python 3.14 works (wheels verified); `pyproject.toml` requires >= 3.12. UI design system: `web/src/styles/tokens.css`
  (Hallmark; always use `/hallmark` for UI work; tokens are locked, no inline colours).
- Tests: `tests/conftest.py` pins the `demo` profile for Stage-1 tests; use the `replay_*` fixtures for real-pack tests.

## Stage 1 tensions (resolved)
- Stage 1 asks for `pyproject.toml` + `src/eventshock/` layout, while submission rules require `requirements.txt` and a
  README run command. Plan: keep both (`requirements.txt` mirrors runtime deps) and make the README command real.
- Python 3.14 is new; some scientific/NLP wheels may lag. Check wheel availability before adding any heavy dependency
  (record outcome in the journey).
- Stage 1 tree adds `tests/ configs/ scripts/ notebooks/` and `data/{raw,processed,fixtures}`; guidelines want sample data
  committed in `data/` — raw bulk downloads must stay git-ignored, fixtures committed.
- Folder name guideline: `<college>-<candidate-name>-hackathon`; local dir is `IITG-Aniket-Mandal-hackathon`.

## Commands
```bash
make setup      # uv venv + Python deps (requirements-dev.txt, editable install) + npm ci in web/
make run        # build UI, serve UI + API on http://127.0.0.1:8000   (or: python src/main.py)
make dev        # API --reload on :8000 and Vite on :5173
make test       # pytest + vitest        (make test-api / make test-web)
make lint       # ruff + tsc
make fixtures   # regenerate deterministic Stage-1 demo data (tests assert it is byte-stable)
make ingest     # run the ingestion pipeline over data/replay, export to data/processed
make fetch-gdelt fetch-tfn   # download source data into data/raw (network); then `make replay-pack` freezes it
make train-sentiment  # train + select + calibrate + evaluate the sentiment model -> models/sentiment/ (~2 min)
make train-event      # train + calibrate + evaluate the event model -> models/event/ (~2 min; --dev-only OUT iterates without scoring held-out sets)
make market-context  # freeze event-time market features (derived stats, no prices) for the replay window -> data/replay/market/context.json
make impact-table    # build data/modeling/impact_table.jsonl + manifest (both scopes, text features, exclusions by reason)
make train-impact    # select/calibrate/evaluate the impact model -> models/impact/ (~45 min; deterministic; --dev-only OUT skips test/live)
make fetch-edgar fetch-fomc events-calendar   # Stage 4: SEC filings (needs EVENTSHOCK_SEC_CONTACT in .env) + FOMC dates -> data/events/ (committed, derived)
make fetch-gkg-2023   # Stage 4: GDELT GKG 2023-25, six fixed 15-min files per UTC day (~3 h, resumable, zips discarded) -> data/raw/gdelt_gkg/filtered_2023_25.jsonl
make history-v2 ingest-history-v2 impact-table-v2 filing-events   # Stage 4: history v2 -> pipeline -> v2 impact table (protocol splits, calendar features) + Track F filing events
make bakeoff-texts bakeoff-embed bakeoff      # Stage 4: representation comparison (embed needs the optional .venv-emb) -> docs/evidence/representation_bakeoff.json
make train-event-hybrid train-impact-v2   # Stage 4: serve-ready artifacts (hybrid event model ~min; impact-v2 ~1 h, needs impact-table-v2 + impact-study)
make impact-study     # Stage 4: incremental-value study + regime-vs-event battery -> docs/evidence/impact_study.json (long; reads configs/evidence_v2.yaml, the pre-registration)
make outcome-audit severity-validity analogue-corpus analogue-index analogue-eval shock-history  # Stage 8 research + evidence (needs git-ignored prices/impact table; analogue-embed ~45 min)
make freeze-check  # verify docs/freeze_manifest.json (final model/config/data state); `make freeze-write` only after a deliberate, journaled change
make smoke      # real server (replay profile): API, served model ids/hashes, evidence, stress, UI (~2 min)
make run-llm    # like run, with a language model reading new text (needs ANTHROPIC_API_KEY; sends pasted text to the provider)
make types      # re-export OpenAPI and regenerate web/src/api/schema.d.ts after changing API models
make logo       # rebuild SVG logos (web/public/*.svg) with outlined wordmark
```
Dependency pins: edit `requirements.in` / `requirements-dev.in`, then
`uv pip compile requirements.in --python-version 3.14 --only-binary :all: -o requirements.txt` (same for dev).

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
