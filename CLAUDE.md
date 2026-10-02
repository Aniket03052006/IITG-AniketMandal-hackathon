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

## Current repo state (Stage 3: sentiment model, 2026-10-02)
- Git: branch `main`, incremental commits already exist; commit only when asked.
- **Sentiment is now a trained model** (`tfidf-lr-v1`: TF-IDF + logistic regression + temperature scaling; `src/eventshock/pipeline/sentiment_model.py`, artifact + card in `models/sentiment/tfidf-lr-v1/`, config `configs/sentiment_model.yaml`, `make train-sentiment`). Event type and impact are **still placeholder rules**; signals carry `data_origin = REAL_SOURCE_MIXED_NLP`, `stage_origins` sentiment=`MODEL`, and `provenance.sentiment` (artifact sha256, confidence, `seen_in_training`). Read `docs/SENTIMENT_MODEL.md` (results, domain gap, failure policy) before changing it. The server refuses to start without the verified artifact; there is no lexicon fall-back. Gold labels and PhraseBank are evaluation-only.
- Stage 1: FastAPI + Pydantic backend (`src/eventshock/`), deterministic stress engine, React/Vite/TS/Tailwind UI (`web/`),
  configs, fixtures, tests, docs. Stage-1 fictional fixtures remain as the `demo` profile (`EVENTSHOCK_PROFILE=demo`).
- Stage 2 (default `replay` profile; its sentiment stage has since been replaced by the model above): real documents (GDELT DOC 2.0 metadata + Twitter Financial News sample) from a
  hash-pinned snapshot in `data/replay/` run through `src/eventshock/pipeline/` (normalise → validate/quarantine → entity
  resolution → dedup → placeholder enrichment) into the same `RiskSignal` → stress → UI path. Signals carry
  `data_origin = REAL_SOURCE_PLACEHOLDER_NLP` (plain `PlaceholderEnricher`) or `REAL_SOURCE_MIXED_NLP` (the served path) and a `provenance` block. Sentiment (except TFN labels), event type and impact
  are **placeholder rules** (`configs/placeholder_enrichment.yaml`); keep that distinction visible in any new code or UI.
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
make types      # re-export OpenAPI and regenerate web/src/api/schema.d.ts after changing API models
make logo       # rebuild SVG logos (web/public/*.svg) with outlined wordmark
```
Dependency pins: edit `requirements.in` / `requirements-dev.in`, then
`uv pip compile requirements.in --python-version 3.14 --only-binary :all: -o requirements.txt` (same for dev).
