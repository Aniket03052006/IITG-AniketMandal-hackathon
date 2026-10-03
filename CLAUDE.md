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
11. **Excluded from MVP:** Kafka, Neo4j, autonomous agents, runtime RAG, other heavy infra.

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

## Current repo state (Stage 4 frozen: submission hardening, 2026-10-03)
- Git: branch `main`, incremental commits already exist; commit only when asked.
- **Sentiment is a trained model** (`tfidf-lr-v1`; `pipeline/sentiment_model.py`, `models/sentiment/`, `make train-sentiment`; read `docs/SENTIMENT_MODEL.md` before changing it).
- **Event type is a trained model** (`tfidf-lr-event-v1`, 9-way with abstention; `pipeline/event_model.py`, `models/event/`, `make train-event`; read `docs/EVENT_MODEL.md`). Labels are AI-annotated; its pre-registered bar is **not met** on gold. Gold and the replay check set are evaluation-only.
- **Impact is now a trained model, labelled *experimental*** (`impact-v1`; read `docs/IMPACT_MODEL.md` before touching it). Two scopes in one artifact: `ISSUER` (abnormal return of one resolved company) and `MARKET` (S&P 500's own move, for documents naming no company), each with its own lifecycle
  `NOT_AVAILABLE → DATASET → BASELINE → TRAINED → CALIBRATED → PRODUCTION` derived from a **pre-registered acceptance bar** in `configs/impact_model.yaml` (never edit it after seeing results; the git history is the proof). Both scopes are `CALIBRATED` (UI: "experimental model"): market-state skill is real, event-specific skill is not measurable (placebo skill ≥ real skill).
  Code: `pipeline/impact_model.py` (serving), `impact_card.py`, `impact_features.py` (the one feature schema), `market_context.py` (anchoring + frozen market pack); `modeling/impact_dataset.py`, `impact_train.py`, `impact_stats.py`, `market_pack.py`; `ImpactModelEnricher` in `pipeline/enrich.py` runs impact as a **post-pass after novelty**.
  Signals the model cannot score (several issuers, weak link, replay-assigned clock, no market data) keep the labelled placeholder rule, with the reason in `provenance.impact_note`; impact origin is **per signal** (`stage_origins.impact`), and the UI never shows an unvalidated number as authoritative. Missing artifact → labelled heuristic (`require: false`); modified artifact → `ConfigError`.
  Commands: `make market-context impact-table train-impact` (the last takes ~45 min; `--dev-only OUT` skips test/live). Training must stay chronological: rolling-origin folds, 5-session embargo, test and live scored once; features must be registered `AT_EVENT_TIME` in `modeling/leakage.py` (`unique_domains`, `source_count`, `ticker`, … are banned).
  The serving market context (`data/replay/market/context.json`, derived statistics only, hash-pinned in the replay manifest) must be rebuilt (`make market-context`) whenever prices or the feature schema change.
- **FROZEN (2026-10-03): no more model experimentation unless a correctness bug is found.** Final model table, lifecycle decisions and per-model can/cannot-use: `docs/FINAL_MODEL_REPORT.md` (numbers are test-checked against the cards). All three trained stages are *experimental*; the event model's independent-evaluation check fails until a set outside its adoption is scored (human adjudication of `data/gold_v2/adjudication_v2.csv` and `data/gold/adjudication.csv` was **skipped by decision**; protocol in `docs/EVIDENCE_V2.md` §10). `make freeze-check` verifies `docs/freeze_manifest.json` (models, configs, gold, calendar, replay, evidence); after any deliberate change run `make freeze-write` and journal it. `make smoke` starts the real server and checks API/model ids/hashes/evidence/stress/UI. `tests/e2e/test_replay_served.py` pins the served configuration (impact-v2 + hybrid event + TF-IDF parity model).
- **Stage 4 (evidence foundation; read `docs/EVIDENCE_V2.md` first).** Pre-registration: `configs/evidence_v2.yaml` (never edit after seeing results; post-dry-run additions are marked in it and disclosed). New data: `data/events/` (SEC 8-K filings with exact acceptance times + FOMC dates; committed, derived), 2023-25 GKG (six fixed 15-min files/day; raw is git-ignored), `data/gold_v2/` (doubly annotated, evaluation-only), `data/probes/`.
  **Served event model is the hybrid `hybrid-event-v2`** (TF-IDF ‖ e5-large vectors; replay vectors hash-pinned in `data/replay/embeddings/`, no torch at run time; live encoder optional via `requirements-embed.txt`; `served_model_dir` vs reference `model_dir` in `configs/event_model.yaml`). **Served impact model is `impact-v2`** (`configs/impact_model.yaml: served_model_dir`; v1 is the reference/fallback), experimental: it reads an `EventCalendar` (feature availability classes a/b allowed, c = known only after = refused `POST_EVENT`; `pipeline/event_context.py`, `calendar_future_invariance` check), and the impact stage keeps reading the TF-IDF event probabilities (train/serve parity). Finding to keep visible: the calendar adds real skill, text-model outputs add none, the rest is volatility regime; **nothing is validated; never label it so.** `GET /api/evidence` + the Model-evidence page are built only from committed cards and `docs/evidence/*.json`.
- Stage 1: FastAPI + Pydantic backend (`src/eventshock/`), deterministic stress engine, React/Vite/TS/Tailwind UI (`web/`),
  configs, fixtures, tests, docs. Stage-1 fictional fixtures remain as the `demo` profile (`EVENTSHOCK_PROFILE=demo`).
- Stage 2 (default `replay` profile; its sentiment stage has since been replaced by the model above): real documents (GDELT DOC 2.0 metadata + Twitter Financial News sample) from a
  hash-pinned snapshot in `data/replay/` run through `src/eventshock/pipeline/` (normalise → validate/quarantine → entity
  resolution → dedup → placeholder enrichment) into the same `RiskSignal` → stress → UI path. Signals carry
  `data_origin = REAL_SOURCE_PLACEHOLDER_NLP` (plain `PlaceholderEnricher`) or `REAL_SOURCE_MIXED_NLP` (the served path) and a `provenance` block. The plain enricher's sentiment (except TFN labels),
  event type and impact are **placeholder rules** (`configs/placeholder_enrichment.yaml`); in the served path only impact still is. Keep that distinction visible in any new code or UI.
  Network access exists only in `ingestion/fetch.py` (`make fetch-gdelt|fetch-tfn`, resumable); the server never calls out.
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
make freeze-check  # verify docs/freeze_manifest.json (final model/config/data state); `make freeze-write` only after a deliberate, journaled change
make smoke      # real server (replay profile): API, served model ids/hashes, evidence, stress, UI (~2 min)
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
