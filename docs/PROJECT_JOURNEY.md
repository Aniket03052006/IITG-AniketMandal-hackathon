# EventShock — Project Journey

Chronological log: **what we did · what broke · how we fixed it**. Updated after every task and at the end of every stage.

## Journey at a glance (written 2026-10-08, after Stage 15)

This section is a reader's map of the log below, for a reviewer or a jury: the whole path in one page, with pointers to the stage that holds the detail.
Everything in it is taken from the stage entries; nothing here is new. (The project journey is this file. A separate `BUILD_LOG.md` was deliberately not created:
two logs would drift apart.)

### 1. Starting point
- **Problem.** The S&P Global & Crisil case: ingest text from ≥ 2 sources, emit sentiment (−1…1), event class and impact (1-10), expose the signals, and build
  **Module A** (tactical rebalancer) or **Module B** (strategic stress tester). Solo (team size 1), free and public sources only, no proprietary data.
- **Interpretation.** Choose Module B; treat the three outputs as three different questions; make every number auditable; never invent a number (Stage 0, 1).
- **Constraints.** One person, public/synthetic data, a ≤ 5-minute live demo, a public repository, reproducibility on a clean clone, Python 3.14 wheels (checked in Stage 0-1).

### 2. Research and datasets
Considered: GDELT (DOC API and GKG bulk), Kaggle financial-news/tweet datasets, Twitter Financial News, NewsAPI, Alpha Vantage, `yfinance`, Salad Money Open Banking, a
Kaggle financial-transactions dataset. **Used:** GDELT, Twitter Financial News (sentiment and topic), Yahoo daily prices, SEC EDGAR filings, FOMC dates, the Kaggle
card-transaction dataset (for the book's sector mix only). **Rejected or unavailable:** NewsAPI and Alpha Vantage (personal keys), Salad Money (not an open download), the
Loughran-McDonald lexicon (licence), Financial PhraseBank for training (CC BY-NC-SA: evaluation only). See `DATA_LICENSES.md` and Stage 2-3 prep.

### 3-4. Architecture exploration and the decision
| Candidate | For | Against | Outcome |
|---|---|---|---|
| LLM-first reading and scoring | strong semantics, little data | non-reproducible, cost, hard to audit, rate limits | **rejected as the engine**; kept as an optional *reader* behind grounding (Stage 7) |
| Fine-tuned transformer for every stage | state of the art on benchmarks | torch at run time, long training, hard to reproduce on a laptop | rejected; frozen encoders were evaluated instead (Stage 4 bake-off) |
| Classical supervised models (TF-IDF/LR, boosting) + deterministic engine | cheap, reproducible, inspectable, calibratable | weaker semantics, domain shift | **chosen** for sentiment, event and impact |
| Streamlit dashboard | fastest to build | cannot give a product-grade, accessible multi-page UI | **React** chosen (Stage 1) |
| SQLite / DuckDB store | durability | nothing needed it; adds moving parts | deferred; repositories sit behind Protocols |
| Kafka, Neo4j, vector database, autonomous agents | production patterns | overkill for one process and one window | excluded; a static, hash-pinned retrieval index was added instead (Stage 8) |

### 5. Implementation phases (all completed; dates in the stage entries)
Stage 1 schemas, deterministic stress engine, API, UI on fixtures → Stage 2 real-source ingestion, validation, entity resolution, dedup, frozen replay → Stage 3 sentiment, event and impact
models → Stage 4 evidence foundation (SEC/FOMC calendar, 2023-25 history, pre-registered studies, hybrid event model, impact-v2) → Stage 5 judge-facing UI → Stage 6 one engine
for replay, paste and live → Stage 7 risk assessment and the severity scorecard → Stage 8 outcome audit, analogues, scenario reality check → Stage 9 personal portfolios →
Stage 10 multi-scope event intelligence → Stage 11 event-to-portfolio propagation → Stage 12 decision intelligence and external markets → Stage 13 sentiment v2 and stress-engine mechanics →
Stage 14-15 judge-first UI, live switch, EDGAR source, heatmaps, contagion map, review queue → 2026-10-08 documentation and submission pass.

### 6. Problems that shaped the project (full detail in the stage entries)
| Problem | Investigation → decision → fix → result |
|---|---|
| GDELT rate limits and unreliable queries (Stage 2, 6, 15) | observed HTTP 429 and non-JSON answers → checkpointed, resumable fetch; a frozen replay pack; live made opt-in; a committed capture built from real pack articles |
| Placeholder labels were circular (Stage 3 prep) | 80.6 % of history signals were the default class → placeholders can never be labels; a test forbids a `label` field |
| Cluster counts leak the future (Stage 3 prep) | `source_count`, velocity count reports up to 72 h later → registered `POST_EVENT` and banned from impact features |
| Impact has no event-specific skill (Stage 3c, 4, 8) | placebo window scored higher than the real one → labelled *experimental*; the severity scorecard became the headline, the trained score a reference |
| Severity-v1 compressed the scale to 4-7 (Stage 7) | weighted average → replaced by an anchored scorecard; pre-registered benchmark; held-out set never used for tuning |
| Golden digests moved when fields were added (Stage 3, 6) | instead of re-pinning blindly, tests prove the old digest is reproduced with the new fields removed |
| An LLM evaluation was invalid (Stage 7) | the rubric was optional so the model skipped it → discarded, rubric required again, hard error on non-LLM replay |
| A real bug in the stress path (Stage 13) | event-driven path dropped `currency` from FX shocks so base-currency positions took the shock → fixed, regression-tested |
| Generated-vs-catalog scenario difference (found in the 2026-10-08 documentation audit) | the Desk shows the catalog scenario's loss, `/portfolio-stress` the propagation-generated one → documented, not hidden |

### 7. Important revisions
Streamlit → React (Stage 1); placeholder rules → three trained models (Stage 3-4); TF-IDF event model → hybrid with pinned vectors (Stage 4); impact-v1 → impact-v2 with an event calendar (Stage 4);
severity-v1 → severity-v2 scorecard (Stage 7); sentiment v1 → v2 for serving while v1 stays the impact reference (Stage 13); Stage 14 "Wire → Ledger" look → Stage 15 "Harbour" re-skin.

### 8. Current state (2026-10-08)
- **Works:** the whole chain on a frozen replay (2,330 signals; 1,082 scored; 27 at severity ≥ 7), the stress engine and its attribution, personal portfolios, the live switch,
  eight UI pages, 85 API operations, `make freeze-check`, 668 frontend tests and 2,174 collected backend tests.
- **Partial:** all three models are *experimental*; live ingestion was not observed end to end against both real sources; human adjudication was skipped by decision.
- **Open (submission):** public repository, slide deck, demo video, e-mail confirmation: see `SUBMISSION_CHECKLIST.md`.
- **Known limits:** synthetic book, assumed shocks, weak event classes, sentiment weak out of domain, no authentication, no persistence.

### 9. Lessons learned
Technical: write the acceptance bar before the result and never edit it; leakage is mostly in features that look innocent (counts, velocities); a model that scores well on a regime proxy is not reading the
news; a derived view must not be stored on the thing it derives from; a deterministic fallback makes an optional LLM safe. Domain: a headline's realised market move is a poor label for "how serious is this";
severity, relevance to *your* book, scenario assumptions and modelled impact are four different things and must never share one number.

### 10. Future evolution
Next: human-adjudicated labels, an independent event evaluation, a FinBERT sentiment head compared with the shipped one, an LLM recording for the severity benchmark. Production: queue + workers, a signal store, authentication, drift monitoring,
licensed data. Deliberately out of scope: Kafka, Neo4j, autonomous agents, generative RAG, and trading decisions.


## Stage 0 — Repository inspection (2026-10-01)

**What we did**
- Inspected the repo: git on `main` with no commits; untracked `README.md` (unfilled template), `LICENSE` (MIT),
  `requirements.txt` (comments only), `.gitignore`, empty `src/ data/ docs/` (`.gitkeep`).
- Read the problem statement and the submission guidelines; distilled both into `CLAUDE.md`.
- Added `.claude/settings.json` to suppress Claude co-author/attribution lines in commits and PRs.

**What broke**
- Nothing yet.

**Decisions / open items**
- Target Module B (stress testing) as the downstream application.
- Open: Python 3.14 wheel availability; `pyproject.toml` vs `requirements.txt` coexistence; demo length (5 vs 10 min).

**Status:** no code written. Awaiting go-ahead for Stage 1 (project foundation).

## Stage 1 — Foundation and first vertical slice (2026-10-01)

**Goal:** a runnable, tested full-stack slice `event → intelligence → risk signal → scenario → portfolio stress → result`
on deterministic fixtures, with clean extension points for every later stage.

**What we did**
- Read the PRD, architecture and research docs; confirmed the product name is EventShock (docs say SignalForge) and
  kept the PRD's eight-class event taxonomy.
- Verified Python 3.14 wheels (`uv pip compile --python-version 3.14 --only-binary :all:`) for FastAPI, pydantic-core,
  pydantic-settings, pyyaml, httpx2 and pytest before committing to the stack. No heavy NLP dependency was added.
- **Backend** (`src/eventshock/`): Pydantic contracts for documents, entities, sentiment, event, impact, evidence,
  `RiskSignal`, portfolio assets, scenarios and stress results; YAML configs with startup validation; Protocol-based
  extension points (`ports.py`); in-memory repositories; a deterministic stress engine (equity, bond, loan,
  derivative) with scope precedence, severity scaling, per-factor attribution, uncovered-exposure reporting and
  deterministic run ids; FastAPI routers; SPA serving for single-process deployment.
- **Fixtures** (`scripts/generate_fixtures.py`, fixed seed and clock): 15 hand-authored signals from two source types
  including failure cases (contradiction, unresolved entity, partial signal), a 51-position synthetic book across 14
  fictional issuers, and the entity master.
- **Frontend** (`web/`): React + Vite + TypeScript + Tailwind v4 + TanStack Query. Risk Feed, Event Intelligence,
  Portfolio Stress, built with the Hallmark design flow (dark risk-desk custom theme, locked OKLCH tokens, Space
  Grotesk + IBM Plex, slop-test sweep). Hand-built SVG logo (an E whose middle arm is a shock spike), generated with
  outlined type via `scripts/build_logo.py`. Frontend types are generated from the FastAPI OpenAPI schema.
- Tests: 140 backend (pytest) and 41 frontend (Vitest) at the end of the stage; verified from a clean copy
  (fresh venv, `npm ci`, build, run).

**What broke, and how we fixed it**
- *Generated TypeScript types were full of optional fields.* Pydantic marks fields with defaults as optional in the
  response schema. Fixed with a shared `ContractModel` base (`json_schema_serialization_defaults_required`), kept
  request bodies on plain `BaseModel`, and passed `--default-non-nullable=false` to `openapi-typescript`.
- *Two service tests failed on a wrong assumption.* A signal with impact 8 scales shocks by 8/7, not 1.0; the tests
  expected unscaled numbers. Fixed the tests to use impact 7 (the reference), so the arithmetic is checkable by hand.
- *Loan validator test passed when it should fail.* The loan value tolerance has a 1.0 absolute floor; the test used
  a notional of 100. Re-expressed the test with a realistic notional.
- *`hash()` in the fixture generator made output non-deterministic across runs* (Python hash randomisation). Switched
  to `zlib.crc32`; a test now regenerates fixtures and compares them to the committed files.
- *Feed rows collapsed at 1024–1280 px.* A six-column grid with fixed widths left the headline column almost empty
  once the side rail took 240 px. Moved the event-type tag under the headline and used the column layout only from
  1280 px.
- *Cards nested in cards, and low-contrast faint text.* The Hallmark slop test flagged a bordered panel inside the
  impact card and a placeholder colour below 4.5:1. Replaced the panel with a divided row (`InlineNote`) and raised
  the `faint`, `neg` and `sev-crit` lightness.
- *Smaller papercuts:* BSD `sed -i` needs an empty suffix on macOS (a chained command silently skipped a file write);
  Starlette now warns that `httpx` is deprecated for `TestClient`, so the dev dependency is `httpx2`; the SPA route
  needed `HEAD` as well as `GET`; the page did not scroll to top on route change.

**Decisions**
- React instead of Streamlit (the architecture doc's own alternative) for a product-grade UI.
- No SQLite and no model code yet; signals carry `data_origin = DEMO_FIXTURE` and `fixture-v0` model versions.
- Hand-built CSS/SVG charts instead of a charting library.
- Deliberate departures from Hallmark gate 38: IBM Plex Mono is used for all numerals (a data-dense tool needs
  tabular figures; three families total, which stays inside the 2+1 ceiling).
- `web/dist` is not committed. Decide at submission time whether to commit a build so evaluators without Node can see
  the UI (the API still runs without it).

**Open items / risks**
- `docs/architecture.png`, `docs/presentation.pdf`, demo video and README header fields (email, video link) are still
  outstanding submission items.
- Scenario magnitudes are illustrative; they need a clear "assumptions" slide and, later, sensitivity analysis.
- Stage 2 should pick real replay datasets and confirm licences before committing any data.

**Status:** Stage 1 complete and verified locally.


## Stage 2 — Real-source ingestion and deterministic replay (2026-10-01 / 02)

**Goal:** real financial text → the existing EventShock product, through one pipeline, replayable without a live
service. Keep Stage 1 working.

**What we did**
- Probed the sources before designing. GDELT DOC 2.0 `artlist` is keyless JSON but returns only url, title,
  first-seen time, domain, language (no body, no tone). The Twitter Financial News dataset (HF, MIT per card) has text
  and a human sentiment label only: no timestamp, id or author. Both facts shaped the design.
- Architecture: adapters (`ingestion/gdelt.py`, `tfn.py`) → normalise → validate/quarantine → entity resolution →
  de-duplication → enricher port (placeholder) → `RiskSignal` with a new `provenance` block → the existing repository,
  stress service, API and UI. No second pipeline; the container just gets a profile switch (`replay` default,
  `demo` = Stage-1 fixtures, so all Stage-1 tests and the golden run are untouched).
- Replay: a hash-pinned snapshot (`data/replay/manifest.json`), a fixed replay clock, content-derived ids, total
  ordering, an order-independent output digest. The network is touched only by explicit `make fetch-*`.
- Entity master of 34 real issuers plus a synthetic book on them (Stage-1's fictional issuers could never be hit by
  real news). Entity resolution is dictionary-first with a guard for ambiguous words ("Apple", "Visa", "Target"),
  confidence caps for multi-company texts and a first-class `UNKNOWN_ENTITY`.
- Dedup: exact / syndicated / near-duplicate / same-event relations, star clustering, blocked by entity; duplicates
  are folded and do not inflate corroboration.
- Placeholder enrichment (keyword/lexicon, TFN human labels) so real documents can reach the stress engine; every
  stage is labelled in `stage_origins`, `model_versions` and the UI.
- UI: data-driven origin labels (the four hard-coded "demo fixture" strings), a Provenance card on the event page,
  relation chips on corroborating coverage, and one new "Data Pipeline" page.
- Tests: pipeline unit tests (normalise, validate, adapters on malformed matrices, entity resolution traps, dedup,
  enricher), a seeded fuzz test, fetcher tests on a fake transport (429, HTML-in-200, retries, resume, atomic writes),
  snapshot tamper tests, determinism/shuffle tests, pack invariants, API and stress end-to-end on real-sourced signals.

**What broke, and how we fixed it**
- *GDELT rate-limits far harder than documented.* The 1-request-per-5-seconds guidance still produced runs of HTTP
  429; requests also take 10-15 s. The first fetch ran for 20+ minutes with no output because results were only written
  at the end. Fixed: per-query checkpointing with resume, progress lines, longer backoff and a 20 s throttle. Failed
  queries are recorded in the manifest's fetch log, never swallowed.
- *Per-issuer GDELT queries failed three different ways, so the request plan was redesigned (2026-10-02).* The first plan
  was 34 one-company queries plus 6 market queries. Observed over ~25 attempts: (1) **HTTP 429** on roughly half of the
  requests even with 8 s and 20 s spacing and exponential backoff, because each failing query burned 3-5 retries and kept
  the limiter hot; (2) **"The specified phrase is too short."** for `"Visa"` (GDELT's minimum is 5 characters; `"Visa"`
  has 4), returned as a plain-text body under HTTP 200; (3) **"Queries containing OR'd terms must be surrounded by ()."**
  for `"Alphabet" OR "Google"`. A bare short word is also a bad query on its own merits (it is the ambiguity problem we
  then have to undo in entity resolution). The 12 queries that had succeeded (358 unique articles) were kept: the fetcher
  checkpoints after every query and resumes without re-fetching or discarding anything. New plan
  (`scripts/replay_universe.py`): **6 parenthesised OR-queries, one per sector**, each built from that sector's issuer
  phrases at 250 records (GDELT's cap), plus the 6 unchanged market-wide queries at 50. Every phrase is quoted and at
  least 5 characters; ambiguous names are longer phrases (`"Visa Inc"`, `"Target Corporation"`, `"Ford Motor"`,
  `"Shell plc"`, `"Meta Platforms"`, `"Apple Inc"`, `"Intel Corporation"`). Tests pin this (no short phrase, every issuer
  covered by its sector query, market queries unchanged). A query that still fails after its retries is logged with its
  error in the manifest's `fetch_log` and the run moves on; the end-of-run report lists failed queries and `make
  fetch-gdelt` retries only those. Entity resolution still ignores the query: a sector query returns off-topic pages and
  the attribution must come from the text (tested).
- *The sector plan hit two more walls.* The Technology OR-query (233 characters) was refused with "Your query was too
  short or too long." (the length cap is undocumented; ~150 works), so it was trimmed to one phrase per issuer and a
  `MAX_QUERY_CHARS = 200` test pins it. 429s then continued at roughly three failures per success even at 45-60 s spacing,
  so the final run (three resumed passes) ended with **8 of 12 planned requests succeeded**: Financials, Technology, Energy,
  Industrials, Consumer and 3 market queries. The **Healthcare sector query and 3 market-wide queries (Federal Reserve,
  stock market selloff, credit rating downgrade) failed** and are recorded as failed in the manifest and shown on the
  Data Pipeline page. The pack is knowingly partial (Healthcare issuers get news only through Twitter posts and the
  earlier per-issuer queries that happened to succeed); `make fetch-gdelt` retries only the failed requests. Result:
  1,479 unique articles (+300 tweets).
- *Entity resolution on real titles found three bugs that synthetic tests had not.* (1) "price target" / "bold 2030
  Target" produced a Target Corporation candidate, polluting confidence for Exxon/Goldman stories: weak aliases now
  ignore everyday phrases via configurable neutralisers (and record the refusal). (2) GDELT tokenises "Amazon.com" as
  "Amazon. com", which fell through to the fuzzy tier: dotted names are now indexed in both spellings. (3) The bigger one:
  "$BYND - JPMorgan reels in expectations" resolved to **JPMorgan**, although the subject is BYND and JPMorgan is the
  analyst; issuer shocks would have hit the wrong company. When a text carries a ticker that is not in the master and no
  listed cashtag, a name-only match is now refused (`SUBJECT_UNRESOLVED`, candidate and reason kept in the audit).
  Known remaining limitation: multi-company headlines ("Amazon Blocks Meta Muse. A Gift for Walmart") still pick one
  issuer by confidence/position, capped at 0.6.
- *GDELT ignores the requested end time.* Results included `seendate`s after `enddatetime` and even after the replay
  clock. Windows are now enforced by our validator (`OUTSIDE_WINDOW`, `FUTURE_TIMESTAMP`) and the quarantine report
  shows them.
- *GDELT titles are word-tokenised* (`( NYSE : GS )`, `$5 . 7 billion`). Resolved in the adapter (`untokenise`);
  the raw record hash is unchanged.
- *Relevance ranking returns unrelated articles* (a bank query returning a German securities filing). Entity
  resolution decides from the text, never from the query that fetched the document.
- *Ambiguous names:* "Apple harvest festival", "Visa waiver", "Target date funds" all contain a company alias. Weak
  aliases now need exact case plus finance context or another strong mention; refusals are recorded in the audit.
  A genuine "US jury says Apple owes $5.7bn in patent case" was initially refused (no finance word) because
  the context list was too small; it was widened (patent, jury, court, bn…).
- *`str.splitlines()` split JSON lines* on U+2028 inside tweet text and corrupted the pack builder. The pipeline's
  reader works on bytes split by newline only; the builder now does the same.
- *`ingested_at < published_at` is a contract error*, so a future-dated GDELT record cannot even be built as a
  `RawDocument`. The adapter checks the clock first and emits a `FUTURE_TIMESTAMP` rejection instead of raising.
- *Regenerating Stage-1 fixtures once* was necessary because the new optional `provenance` and `relation` fields
  appear in the serialised output; the byte-stability test then passes again. The golden stress run is unchanged.
- *Lint:* the new data-pipeline modules use dense argument lists; E501 is relaxed for `pipeline/` and `ingestion/` only.

**Decisions**
- Placeholder enrichment instead of leaving real signals PARTIAL: PARTIAL signals cannot be stress-tested, so the
  real flow would never have reached the stress screen. The placeholder is loud about being one.
- Twitter text redistribution: a 300-row sample is committed under the dataset card's MIT declaration with
  attribution and a removal note; the full dataset is download-only. The risk (tweet content originates on X) is
  documented in `docs/DATA_LICENSES.md`.
- No new dependencies (stdlib `urllib`, `difflib`); exact pairwise Jaccard within entity blocks is fast enough for
  thousands of documents; MinHash is the scale-up path.
- TFN timestamps are synthetic and flagged; those documents are never correlated with others by time.

**Open items / risks**
- Placeholder sentiment/event/impact are not models; evaluation against labels is the next stage's job.
- Contradiction detection (`contradicted_by`) is not implemented.
- A report with an unresolved entity never clusters with the same story where the entity resolved; strict blocking
  is the safe choice but under-counts corroboration.
- EDGAR 8-K (timestamped, typed, free) is the recommended next source; GDELT text is headline-only.
- `docs/architecture.png`, `docs/presentation.pdf`, demo video and README fields are still outstanding.

**Addendum — GKG bulk download (2026-10-02).** Because the DOC API stayed rate-limited, we added GDELT's bulk GKG files
(`data.gdeltproject.org/gdeltv2/`, listed in the 128 MB `masterfilelist.txt`). `ingestion/gkg_fetch.py` downloads each
15-minute file, decompresses it **in memory**, filters it (`ingestion/gkg.py`) and appends the kept rows; the zips are never
written to disk (`--keep-zips` to keep them), so the 5.8 GB window cost no disk. Append-only checkpoints, 4 threads,
resumable. Result for 17-30 Sep: **1,344 of 1,344 files, 0 failures, 1.28 M rows read, 127,592 kept** (107,619 issuer
rows, 12,714 market-theme rows, 2,279 without a title). Things worth knowing:
- GKG carries the **publisher's own timestamp** (`PAGE_PRECISEPUBTIMESTAMP`); we use it (flag `SOURCE`) when it is not later
  than the crawl time. Some rows are "published" years earlier (min 2008): validation quarantines them (`OUTSIDE_WINDOW`).
- GKG organisations are NER output, so they are matched generously **for filtering only**. Attribution still reads the
  title only. Consequence: of 127k kept rows only about 2.5k name an issuer in the title; Meta (58k) and Google (22k) dominate
  the org-only rows (the NER tags "Meta"/"Google" liberally). The committed slice therefore prefers rows the pipeline's own
  resolver can tie to an issuer.
- The first run stopped at once: the master list says `http://`, and the fetcher refuses non-https. URLs are now upgraded.
- Rewriting the whole output after every file would have been quadratic (~60 MB x 1,344); checkpoints are append-only.
- **Cross-source duplicates exposed two bugs the single-source pack could not:** the same URL in DOC and GKG produced the *same
  document id* (so a signal-id collision was possible), and ties in the clustering sort made the digest depend on input order
  (the shuffled-input test caught it). Ids are now per source (`gdelt-…`, `gkg-…`) and the sort key is total (time, id, source,
  record position).
- A weak-alias false positive on real GKG titles ("studio reduced to a **Shell**" -> Shell plc) was added to the
  neutralisers; the old ER tests for "Shell" had been vacuous because Shell was not in the test entity master (fixed).
- Cross-source dedup now works for real: 76 DOC articles were also in the GKG slice and fold into one story each.

**Addendum 2 — modelling data (2026-10-02).** Collected everything the later stages need, all outside git:
- **Prices:** a ~100-line Yahoo chart fetcher (`ingestion/prices.py`, stdlib only; the `yfinance` package is not installed, same
  source): 37 symbols x ~2,954 days (2015-01-02..2026-10-01), no failures. Yahoo rejects a bare User-Agent, so the shared agent
  string is now browser-compatible.
- **Event labels:** Twitter Financial News topic dataset (21,107 tweets) + `configs/topic_mapping.yaml`, a deliberately incomplete
  crosswalk of 20 topics to our 8 classes (17,855 map; "General News", "Energy | Oil", "Gold | Metals", "Personnel Change" stay
  unmapped). Class balance is poor (Credit/Funding 1.9%, Regulatory 2.9%, M&A 3.1%), which matters for evaluation.
- **Kaggle** (`ingestion/kaggle.py`, `configs/external_datasets.yaml`): stock tweets with real timestamps, 53k dated headlines, 3.7M
  top-company tweets, the Financial Transactions dataset, and the NC-licensed PhraseBank derivative (local evaluation only).
  The token is read from `KAGGLE_API_TOKEN` or `~/.kaggle/access_token` and is never written by our code. (An attempt to save
  the token under `~/.kaggle` on the user's behalf was refused by the tooling's permission system and not retried; it was
  passed inline per command instead. It should be revoked now that the downloads are done.)
- **History snapshot** (`scripts/build_history_pack.py`, final run with 2 months of GKG): 174,038 curated documents (stock tweets, headlines, top tweets, GKG;
  documents the entity resolver ties to an issuer plus a sample of the rest) run through the *same* pipeline: 136,236 signals,
  130,328 resolved to an issuer (all 34 issuers); 18,692 exact duplicates folded; ~6 minutes. Coverage is uneven and should be
  stated up front: Tesla (52.6k) and Apple (27.7k) dominate because of the tweet sources, 2020 has only 1.7k and 2023-2025
  are empty (no source covers them), 2026 has 21k (GKG). A natural split is train 2015-2022, test Sep 2026.
- **What broke at scale:** (1) dedup scanned every cluster of an entity per document (O(n^2) on 25k-cluster blocks): replaced by URL,
  text-key and inverted-token candidate indexes, proven equal to the exhaustive scan by a randomised test; (2) the novelty feature
  scanned all clusters for every cluster (a 20+ minute hang): replaced by per-entity sorted times and `bisect`; (3) the history
  signals export became a 400 MB JSON array: now JSONL; (4) Reuters/Guardian headlines carry a date but no time, so a new
  `SOURCE_DATE_ONLY` timestamp origin was added (trusted for windows, never pretending to a time of day).
- **Transaction data -> portfolio:** `scripts/derive_sector_mix.py` streams 13.3M transactions (12.4M positive, error-free),
  maps merchant categories to our six sectors by keyword (`configs/mcc_sector_map.yaml`, 98.6% of spend mapped) and writes an
  11 KB aggregate; the synthetic book's notionals are tilted by it (Consumer 36%, Industrials 19%, Financials 17%...).
  It is a crude proxy and is labelled so; only the aggregate is committed.

**Result on the shipped pack (before the GKG slice was added; see the end-of-stage report for current numbers):** 1,779 records read → 166 quarantined (118 `FUTURE_TIMESTAMP`, 44 `OUTSIDE_WINDOW`, 4 `TOO_SHORT`)
→ 27 exact duplicates folded → 1,586 reports → 1,185 signals (455 resolved to an issuer, 730 `UNKNOWN_ENTITY`); 357 syndicated copies,
32 near-duplicates and 12 same-event reports folded into multi-report stories.

**Status:** Stage 2 implemented and verified locally (295 pytest + 46 Vitest, ruff and tsc clean; see the end-of-stage report).

---

## Stage 3 prep — modeling-data audit and foundation (2026-10-02)

**Goal.** Before training anything, find out whether the data is ready and leave a trustworthy base: audit, targets, splits,
leakage checks, a gold set. No model was trained (three seconds-long probes excepted). Full numbers: `docs/MODELING_READINESS.md`.

**What we did**
- Profiled the 136k history signals, 37 price series and the TFN/PhraseBank label sets before writing code, and let the numbers
  choose the design (impact target, splits, tiers). New package `src/eventshock/modeling/`, config in `configs/modeling.yaml`.
- Refetched prices from 2014-01-01 so 2015 events have a full trailing window (the first fetch started 2015-01-02, which would
  have dropped about 8.9k signals).
- Built: a point-in-time impact target (market + sector-peer abnormal return, 2-session window, trailing beta and sigma),
  time splits with embargo, a leakage module (group straddle, time order, duplicates, feature-availability registry,
  future-perturbation invariance, metadata-only baseline), and a blind, stratified gold-set workflow.
- Labelled the 400-row gold set myself as a disclosed AI annotator (`ai:claude`), blind to every weak label, then re-labelled 40
  rows blind for a self-consistency figure. A 60-row adjudication list is ready for a human.

**What broke or surprised us, and what we did**
- *The placeholder labels are circular.* 80.6% of history signals are `MARKET_VALUATION` (the no-keyword default) and `impact.score`
  is a function of that class. Decision: they only help find disagreements; no field called `label`/`target` exists on `HistoryDoc`
  and a test keeps it that way.
- *Cluster evidence leaks the future.* `source_count`, `unique_domain_count`, `coverage_velocity` count reports up to 72 h after the
  first one, and `recent_mention_count` is measured against the replay clock. Registered as `POST_EVENT` and banned from impact features.
- *130k signals are about 10k price windows.* Effective sample size is the ticker-session. TSLA is 46% of rows but 14% after episode weighting.
- *The TFN topic corpus is dirtier than it looked.* 2.4k exact duplicates; 23% of the published validation rows have a near-duplicate in
  train. We re-split by near-duplicate group (0.1% leakage afterwards).
- *The 20-topic -> 8-class crosswalk is not good enough as truth.* No topic is a clean GEOPOLITICAL or PRODUCT_OPERATIONS source, so
  those two classes have no trainable silver data. The gold review then showed that the "Earnings" topic is about 70% scheduling
  notices and previews, not results (683 of 987 by regex; 0/6 in gold), "Stock Movement" names its cause rather than being
  an event (2/6), and M&A is 4/6. All three were demoted (`topic_mapping.yaml` v3). The sample was frozen before this
  change, because the demotion alters the probe used to pick disagreement rows (the manifest records the frozen mapping version).
- *A naive "placebo" check was not a clean leak test.* Tabular event-time features predict a placebo window just before the
  event almost as well as the real one (volatility clustering and the lag in trailing sigma). It is kept as a control, not a pass/fail
  gate; any text model must beat the tabular baseline **and** show no extra skill on the placebo.
- *Performance traps:* `has_near_duplicate` over 136k documents against 30k references was quadratic on common tokens (a 2-minute
  command that never finished); it now proposes candidates only through tokens that are rare in the reference set.
- *Gold sampler bug found by its own test:* the issuer cap could leave a stratum under quota; the cap now relaxes rather than
  shortening the stratum. The test data also collapsed under the template key (digits are masked), which proved the collapse works.
- *Labelling ambiguities worth knowing:* scheduling notices and earnings previews (labelled `NONE`; a model could reasonably call
  them EARNINGS), domestic politics with a market channel (Draghi's coalition), insider sales, executive hires. The labelling guide
  states the rules; the self-consistency pass disagreed mostly on exactly these.
- *Inline helper mishap:* a first gold-sample run blocked the shell for two minutes; moved to the background and the slow
  function fixed instead of waiting it out.

**Decisions**
- Fixed (not quantile) impact cut points so the label cannot drift between splits. Score 7+ is a >= 3 sigma idiosyncratic move.
- Two-factor abnormal returns (market + equal-weight sector peers ex-self), because it cuts residual sigma by about 40% for
  Financials and Energy and costs nothing elsewhere.
- Tweets whose source tagged another ticker are excluded from impact rows (3,060 dropped): they are about another company.
- Optional `ml` extra (`requirements-ml.txt`: numpy, scikit-learn) only for the probes; the server and the audit stay stdlib.
- No UI change: the audit is a document plus JSON; a panel belongs with the models.

---

## Stage 3 — First real model: sentiment (2026-10-02)

**Goal.** Replace the sentiment placeholder with a trained, evaluated, reproducible model and carry it through pipeline, provenance, API and UI,
without touching the event and impact placeholders or the stress engine. Details: [SENTIMENT_MODEL.md](SENTIMENT_MODEL.md).

**What we did**
- Chose TF-IDF (word + char n-grams) + logistic regression + temperature scaling on the Stage-3-prep evidence (9.4k labels, 0.79 macro-F1 baseline, a domain gap that data, not capacity, may explain); no transformer.
- Ran a 16-candidate grid on train → valid only (`configs/sentiment_model.yaml`), selected by calibrated log-loss, evaluated once on TFN test, PhraseBank and the gold set, with baselines (majority, the old lexicon, the audit probe re-fitted).
- Added `pipeline/sentiment_model.py` (serving, integrity-checked), `ModelSentimentEnricher`, `SentimentAudit` provenance, `DataOrigin.REAL_SOURCE_MIXED_NLP`, `RejectCode.UNSCORABLE_TEXT`, `GET /api/models/sentiment`, and the UI: stage strip on the feed, model block on the event sentiment card, per-stage provenance, a "Sentiment model" panel on the pipeline page.
- numpy / scikit-learn / joblib became runtime dependencies; `models/sentiment/tfidf-lr-v1/` (1.7 MB) and `data/modeling/sentiment.jsonl` (2 MB) are committed so the model can be loaded and retrained from a clone.

**What broke or surprised us, and what we did**
- *The selected model is not the best on arg-max macro-F1.* The pre-registered rule (calibrated log-loss) chose an unweighted model; the audit probe (class-balanced) is ahead out of domain (PhraseBank 0.54 vs 0.47, gold 0.50 vs 0.44). A diagnostic over four candidates showed identical rank correlation, so the difference is where labels fall, not how well scores order texts; with the UI's own score cut the models are level or ahead (0.54 / 0.52). We kept the rule we had set and reported both, instead of switching after seeing external results.
- *Two trainings gave different bytes.* sklearn stores `id(stop_words)` in `_stop_words_id` and every pruned term in `stop_words_`. Both are removed before pickling; retraining is now byte-identical (artifact and card), and a test does it on a toy corpus.
- *Adding an optional provenance field changed the Stage-2 golden digest* even for the unchanged placeholder run. A test now removes the new null field and proves the placeholder output still hashes to the old digest (`b8074b43…`), so "no behaviour change" is demonstrated rather than asserted. The model run has a new pinned digest.
- *Real sentiment moved impact.* Placeholder impact reads `0.2·|sentiment|`; mean |score| went 0.11 → 0.19 and known-issuer signals at impact ≥ 7 went 12 → 21 (33 → 44 overall). Intended, documented, and the stress engine stays sentiment-blind (tested).
- *The training data is in the demo.* 261 of 290 replay tweets are exact training texts. `seen_in_training` is in provenance and the UI marks them in-sample; their agreement with the human label (92%) is a sanity floor, not accuracy.
- *Four documents cannot be scored* (a bare link ×2, `$SPY $IWM …` ×2). They passed validation, so they are quarantined as `UNSCORABLE_TEXT` instead of getting an invented neutral.
- *Gold TFN rows overlap the sentiment training texts* (the sample came from the topic corpus): one near-duplicate was removed before scoring.
- *Startup went from ~2 s to ~11 s* (about 3,000 sparse transforms, the pre-check plus scoring). Acceptable for a pinned replay; noted for live mode.

**Decisions**
- No fall-back to the lexicon: a missing or altered artifact stops the server with the fix command.
- `data_origin` gets a coarse `REAL_SOURCE_MIXED_NLP`; the per-stage truth lives in `stage_origins`, so the event and impact stages can flip to `MODEL` without another enum.
- Calibration is reported honestly: in domain it is a no-op (T = 1.03); out of domain the model is over-confident (ECE 0.16–0.26).
- Gold and PhraseBank stay evaluation-only; the AI-annotated gold labels are never training data.

| Part | Status |
|---|---|
| Sentiment | **Trained model**, evaluated, calibrated, reproducible |
| Event type | Placeholder rules |
| Impact | Placeholder heuristic (reads the model's tone magnitude) |
| Stress engine | Real, deterministic, unchanged |

**Status:** verified locally with `make test` (pytest + Vitest), `ruff` and `tsc` clean; see the end-of-stage report.


### Process note (2026-10-02)
- Rule change from the project owner: this journey is updated after **every task**, not only at stage end. `CLAUDE.md` now says so; small tasks get a short dated entry under the current stage.
- Pushed the sentiment slice to `origin/main` (commits `ffcf584`, `3345419`). `.claude/` and `.hallmark/` are untracked and git-ignored (files kept locally); `CLAUDE.md` still relies on the local `.claude/settings.json` to blank AI attribution, so a fresh clone must recreate it.


---

## Stage 3b — Event classification v1 and the GDELT fetch cleanup (2026-10-02)

**Goal.** Replace the event-type placeholder with a trained, evaluated, reproducible model that can abstain, carry it through pipeline,
`RiskSignal`, provenance, API and UI, and fix the failed-download rows on the Pipeline page. Sentiment, impact (still placeholder) and the
stress engine are unchanged. Details: [EVENT_MODEL.md](EVENT_MODEL.md).

**Part A: the failed GDELT rows**
- Nine "FAILED" rows were two different things. Five came from an **abandoned first plan** (`"Alphabet" OR "Google"`, `"Citigroup"`, `"Meta Platforms" OR "Meta"`,
  `"Visa"` (GDELT rejects phrases under 5 characters), and a 12-phrase OR query that was too long); their coverage was replaced by the sector queries that
  succeeded. Four were **current-plan** queries that GDELT rate-limited on every earlier pass: the Healthcare group, `"Federal Reserve" interest rate`,
  `credit rating downgrade`, `stock market selloff`.
- Current-plan failures were worth fixing (a whole sector, and exactly the macro/credit/market events the event model needs): added `GDELT_THROTTLE` to the Makefile,
  re-ran the resumable fetch at 45 s between requests (three of four succeeded; `stock market selloff` still returned 429 and succeeded on a 90 s retry), and re-froze the pack.
  The pack grew from 3,087 to 3,455 records (GDELT DOC 1,479 → 1,847).
- Abandoned-plan rows are no longer listed: the manifest records the current plan (`fetch_plan`), `summarise_fetch_log` counts the rest (`superseded_requests`, 5), and the page
  says so. The raw attempt log stays in the manifest. Failures of the *current* plan are never hidden (unit test with a synthetic log).
- Consequence: the replay digests had to be re-pinned. We proved the placeholder enricher is byte-identical by running it over the **old** pack from git
  (reproduces the Stage-2 digest `b8074b43…`) before pinning its new-pack digest.

**Part B: building the data (the real work)**
- The audit already showed TFN-topic labels do not transfer (0.89 on TFN, 0.16–0.30 on gold) and that two classes had no data and NONE did not exist. So the constraint was labels.
  We drew blind pools (random samples of our own sources, keyword-hit candidates for rare classes, TFN topic rows to be relabelled, a 200-row replay check set, a 200-row
  consistency set), all disjoint from the gold set by id and near-duplicate text, and had an AI annotator (blind subagents) label 3,270 rows by the gold labelling guide.
- *First annotation attempt failed:* the session hit the usage limit with nine annotators running in parallel and none had written a file. Re-ran in waves of five.
  Some annotators wrote answer files with a helper script rather than the Write tool; checked by the merge validator (vocabulary, ids, order), which rejects anything off.
- *Bug found by running it:* the group-aware split helper assumed a `test` side and crashed on a two-way split; fixed (and covered).
- *Another:* the pools contained texts with no words (only tickers), which the model must refuse. Tuning crashed on them; they are now excluded from tuning and evaluation
  exactly as the pipeline quarantines them.

**Part C: the model**
- 9-way TF-IDF + logistic regression + temperature scaling, selected on dev log-loss. The TFN crosswalk silver rows were tested as extra training data and made dev log-loss worse
  (0.896 vs 0.871), so they are not used. The held-out sets (gold, replay check, TFN topic test) are scored once at the end; a `--dev-only` mode exists to iterate without scoring them.
- *Dead end 1 (classifier family):* variants of the same classical family (C = 10/30/100, word-only, raw text, linear SVM) all landed at dev macro-F1 0.53–0.59. More hyper-parameters would
  be chasing noise; embeddings are the next experiment, not another grid.
- *Dead end 2 (the abstention policy):* the first design tuned two thresholds on dev with a 75% precision target. The target was unreachable (the best weighted precision of a committed
  class on dev is about 0.6), the fallback committed to 11% of dev rows, and the first full evaluation read 0.236 as-served macro-F1 on gold history. We replaced it with one untuned 0.5
  commit threshold on the calibrated posterior (a dev-only analysis showed a strictly better coverage/precision frontier). **This was a design change after seeing held-out numbers.** The first
  run's card is kept in `docs/evidence/` and the doc discloses it. The pre-registered acceptance bar was not changed, and it is **not met** on the gold set (0.33 [0.26, 0.38] vs 0.33).
- *Artifact serialisation:* scikit-learn sorts classes alphabetically, so the artifact reorders logits into the fixed 9-class order; load checks that the fitted classes are exactly the nine.

**Part D: integration and UI**
- `EventStatus` (`CLASSIFIED | NO_EVENT | UNCERTAIN`), `no_event_probability`, `EventAudit` provenance, `ModelEnricher`, `GET /api/models/event`, `event_status` in the feed and a filter.
  A non-event is `PARTIAL` with a reason and no impact, so the stress engine cannot fire on chatter. The category filter matches classified events only.
- UI: event model panel on the Pipeline page (acceptance verdict, per-set results, per-class reliability, mistakes, limits), status/abstention/confidence on the Event page, a "No market event"
  / "Type uncertain" tag and a "Show non-events" chip on the Feed (non-events hidden by default), maturity tags now read the pipeline report instead of constants.
- Signal-level origin text is derived from the signal's own `stage_origins` ("trained sentiment and event" vs "trained sentiment"), not from the coarse data origin.

**What changed in the numbers.** On the served replay pack 756 of 2,330 signals are classified (32%), 890 are "not an event" (38%), 684 uncertain (29%); impact ≥ 7 drops to 33 signals
(all on known issuers). Start-up grew from about 11 s to 16 s.

| Part | Status |
|---|---|
| Sentiment | Trained model (unchanged) |
| Event type | **Trained model, can abstain; weak and flagged per class; acceptance bar not met on gold** |
| Impact | Placeholder heuristic (reads the model's category and tone), none for non-events |
| Stress engine | Real, deterministic, unchanged |

**Open:** human adjudication of the gold rows and of a slice of the training labels; more labels for the thin classes; an embedding experiment; impact.

## Stage 3c — Impact model v1: from placeholder to a measured (and honestly weak) predictor (2026-10-02 / 03)

**Goal.** Replace the last placeholder stage, impact, with a leak-free, chronologically evaluated, calibrated and explained model, carried through pipeline, `RiskSignal`, API and UI,
or say clearly that the data cannot support it. Details and every number: [IMPACT_MODEL.md](IMPACT_MODEL.md).

**What we found first (the plan changed because of it).** Stage 3 prep had already built the target, the splits and the leakage tooling, so no new data was needed for a first model.
What was missing was plumbing: the impact table had no text, serving had no way to compute event-time price features (prices are git-ignored and licensed non-redistributable),
and `novelty` is only known after clustering, so impact had to become a post-pass.

**What we built**
- `pipeline/market_context.py` (one `anchor_session` for training and serving, the frozen per-session feature pack) and `modeling/market_pack.py` + `make market-context`: derived statistics only,
  hash-pinned in the replay manifest. `modeling/market.py` gained the market-wide scope (S&P 500's own excess move over trailing sigma) and two volatility-regime features.
- `modeling/impact_dataset.py` + `make impact-table`: the table with text-model features, **every exclusion counted by reason**, a manifest of input hashes, and fatal leakage gates (group straddle, time order, feature registry, future invariance for both scopes).
- `modeling/impact_train.py` + `make train-impact`: rolling-origin out-of-fold selection over a nine-step ladder with a paired-bootstrap adoption rule, rank-calibrated 1-10 score, empirical uncertainty, exact-or-labelled attributions,
  chronological held-out evaluation (val, test once, live once), placebo skill, strata, horizon sensitivity, a pre-registered acceptance bar and a lifecycle derived from it. The artifact is reloaded through the serving loader before the card is written.
- Backend: `ImpactAssessment` (+ prediction, range, `p_extreme`), `ImpactAudit`/`ImpactLifecycle`, `ImpactModelEnricher` (post-pass), `GET /api/models/impact`, `Meta.impact`, stress audit records the impact stage, notices derived from the loaded card.
- UI (Hallmark rules: locked tokens, no nested cards, mono numerals, colour never the only signal): lifecycle tag (placeholder rule / experimental model / validated model), the impact card (raw prediction, calibrated score with range, extreme-move share, drivers, what the model knew, timestamp caveat, provenance),
  a meter with dashed/dotted outline per kind and a range bracket, an Impact-model panel on the Pipeline page, per-signal markers on the Feed and Stress pages.

**What the data said (the honest result).** Market-state skill is real; event-specific skill is not measurable. Issuer scope: held-out rank correlation +0.12 [+0.01, +0.22], placebo +0.23; paired error vs the constant on 2022: +0.000 [−0.007, +0.007]. Market scope +0.25, placebo +0.34.
Text-model outputs, TF-IDF n-grams and sentence embeddings (e5-small, e5-base, FinBERT) added nothing with an interval that excludes zero; within an issuer the rank skill is +0.0004. Four of eight pre-registered checks fail on the issuer scope: lifecycle `CALIBRATED`, shown as *experimental*.

**What broke, and how we fixed it (dead ends included)**
- *The first golden-digest failure was not a regression.* Growing the contract (new null impact fields) changes every digest. Instead of re-pinning blindly, the e2e test now removes the new fields and requires the **old** digests (event-only, sentiment-only, placeholder) to reproduce byte for byte, then pins the new impact-run digest separately.
- *A constant predictor scored Spearman −0.095.* Averaging identical predictions per episode leaves ~1e-16 float noise, and ranking noise is not zero skill. `spearman` now returns NaN when a prediction has no spread; a test pins it.
- *The issuer weight cap was wrong.* Scaling one issuer to 15% of the original mass and renormalising leaves it above 15%. Replaced with water-filling, with a test (and a skip when the cap is unmeetable). The first full training run (35 min) used the buggy version and was discarded and rerun.
- *The first training run looked stuck.* It was not: 21 folds × 9 steps of boosting on 68k rows takes ~38 minutes. The grid was already cut to one learning rate and two depths; we kept the pre-registered ladder rather than shrink it to save time.
- *Hugging Face calls failed with 401.* An expired token in the environment broke even public downloads; FinBERT was fetched anonymously (`token=False`) with the cached e5 models loaded offline. We did not touch the user's credentials.
- *Attribution exactness.* The ladder's own rule selected the interacting model (R3-full) over the additive one, so the explanations are labelled *sensitivity*, not exact; the UI says so under the bars. We kept the pre-registered rule instead of overriding it for tidier explanations.
- *Disclosure.* The market scope was run once as a smoke test before the full run and its held-out numbers were seen; nothing in `configs/impact_model.yaml` was changed afterwards.
- *The placeholder over-scores.* On the replay pack 12 signals reach score 7: 9 are placeholder-rule signals, 3 model-scored. The model's calibration puts 7+ at the top few percent of historical events; the heuristic's category prior put chatter there.

| Part | Status |
|---|---|
| Sentiment | Trained model (unchanged) |
| Event type | Trained model, can abstain; weak; acceptance bar not met (unchanged) |
| Impact | **Experimental trained model per scope (issuer, market-wide); labelled placeholder rule for signals it cannot score; none for non-events** |
| Stress engine | Real, deterministic; audit now records which stage produced the impact |

- *The embedding experiment had a surprise for the event model, not for impact.* e5-base cut event dev log-loss from 0.872 to 0.719 and its gold point estimate is higher, but the paired interval on 280 weighted gold rows includes zero, so by the rule written beforehand it is **not adopted**. For impact no encoder helped. Nothing was added to the product's dependencies.

**Open:** earnings-calendar features (known in advance; the one class with a lift); news for 2023-2025 so text can be tested on enough episodes; human adjudication of the gold set; a within-issuer evaluation with more than 34 issuers; confirming the e5-base lead for the event model on a larger gold set.

## Stage 4 — Strengthening the empirical foundation (2026-10-03)

**Goal.** `impact-v1` is honest but thin: market-state skill is real, event skill is not measurable, the held-out set is 347 episodes of 2022, there is no 2023-2025 news, and the gold set is 400 AI-only
labels. Stage 4 improves the *evidence*, then lets rules written beforehand decide what (if anything) to adopt. Pre-registration: `configs/evidence_v2.yaml` (protocols, adoption rules, added checks C9-C11).

**What we found first (and changed the plan).** The GDELT DOC API is rate-limited, but the bulk GKG files are reachable (the master list covers 2023-2025); SEC EDGAR's submissions index gives exact acceptance
timestamps and 8-K *item codes* for free; Hugging Face works anonymously; the large multisource news dataset is gated. A web search of the literature supported a hybrid keyword + dense design (finance benchmark: general
embedding rank is a poor predictor of finance performance and bag-of-words still wins some tasks) and warned that zero-shot NLI is weak and costly. A pasted note on emotion models was checked: "FinRoBERTa" and a financial
DeBERTa are community checkpoints of unknown quality and StockEmotions has no hosted model, so the affect channels are finbert-tone, FinBERT and a general emotion model, with a self-written finance lexicon.

**What we built so far**
- `ingestion/edgar.py`, `ingestion/fomc.py`, `scripts/build_event_calendar.py`, `data/events/` (9,772 filings, 102 FOMC decisions, manifest with hashes and known gaps); `configs/sec_items.yaml` (item -> official title -> event class, tiered).
- `pipeline/event_context.py` (calendar features with availability classes a/b; class c is registered POST_EVENT and refused), `pipeline/impact_features_v2.py` (nested rungs R2/R2s/R3/R3s/R3h; v1 untouched), `calendar_future_invariance` in the leakage suite.
- GKG slot sampling (`--slots`), a 2023-2025 pull of six fixed 15-minute files per day (resumable, zips discarded), `scripts/build_history_v2.py`.
- `modeling/representations/` (encoder cache with cost measurement, lexicon channel, corpus, bake-off with the pre-registered adoption rule), `data/probes/` (60-sentence minimal-pair polarity probe), `modeling/gold_v2.py` (additive, doubly annotated gold).
- `modeling/impact_dataset_v2.py`, `impact_episodes.py`, `impact_regime.py` (regime-vs-event battery), `filing_events.py` (Track F), `impact_study.py`.

**What broke, and how we fixed it**
- *Two issuers looked nearly empty on EDGAR.* XOM had 4 filings and GOOGL started in October 2015: both reorganised (a 2026 holding company; Alphabet replaced Google Inc.). Found only because we printed the per-issuer counts; fixed with verified predecessor CIKs, merged by accession.
- *FOMC pages differ by era.* Historical pages say "April 30-May 1", the current page has "Apr/May" and "30-1", plus unscheduled and cancelled meetings and a notation vote. A parser test per shape; unscheduled meetings are kept but flagged so no feature uses them as "known in advance".
- *A test expected the wrong clock.* Apple's results 8-K was accepted at 00:30 UTC on 3 May (8:30 pm ET on the 2nd); the feature correctly refused to know it at 22:00 UTC. The test was wrong, the code was right.
- *The first history-v2 curation wasted its budget.* Capping documents per issuer-hint-day before entity resolution kept 8,050 unresolved and only 2,516 resolved documents, because GKG's organisation hints are not what the title-only resolver confirms. We now resolve first, then cap per resolved issuer per day (5,804 resolved from the same slice).
- *A battery test was too strict.* A pure volatility model keeps skill inside a volatility bucket because volatility varies continuously within it; the honest claim is that a model with text beats one without only when the text carries signal. The test now asserts that.
- *First look at Track F (before any model).* An earnings 8-K moves prices far more than a matched quiet session of the same issuer and volatility bucket (paired lift +0.64 in log-severity, AUC 0.82, 1,084 pairs); leadership and deal filings barely differ (+0.04, +0.06). Event information exists in structured form; whether it reaches the news model is what the study measures.

### Stage 4, continued: the data pull, gold v2, the representation study and the hybrid event model (2026-10-03)

**The 2023-2025 news pull.** Six fixed 15-minute GKG files per UTC day (6,460 files, no failures, 8.6M rows read, about 841k kept in the window) became `data/history_v2/`. Held-out issuer episodes under the
extended protocol went from 347 (impact-v1, 2022 only) to **5,261 (val 2024) and 4,636 (test 2025)**; market-wide sessions from 119 to 247 and 249. The legacy protocol's counts and every v1 row are reproduced exactly (a regression gate, not a hope).
- *The pull slowed from about 50 files a minute to about 5 while a debugging run of the study shared the machine.* Its output was buffered, so we could not see how far it was. We killed it, replaced it with a fast synthetic end-to-end test of the study code, and ran the real study only when the pull was done.
- *The synthetic study test was worth more than the debugging run.* It showed the study adopts and certifies a planted calendar effect (C10, C11, neutral skill, permutation) and refuses to certify the same dataset with the effect removed. Along the way it found a real flaw (ablations ran on the single "best block model", which in a null dataset may not contain the block at all; now each block is ablated on the best model that contains it) and two wrong test assumptions of ours (a pure-volatility model keeps within-bucket skill; a placebo window with the same structure gives a coin-flip gap).

**Gold v2.** 300 rows from the 2023-2025 sample (a random stratum, four thin-class strata, a filing-anchored stratum), disjoint from every existing label set, annotated by two independent blind AI passes with different prompts and orderings: 93.3% agreement, kappa 0.91
(same annotator family: it bounds label noise, not shared bias); 280 rows agreed, 20 queued for human adjudication. Annotation ran in waves of two agents each after an earlier run hit the usage limit with nine in parallel.

**The representation study (keywords, semantics or both).** Eight frozen encoders (five dense, three affect), a finance lexicon written for this project, three fixed fusion designs, scored on pooled held-out sets by a rule written beforehand.
- *A dry run on gold v1 plus the replay check (before gold v2 existed, to debug the code) already showed early fusion beating TF-IDF by about +0.27 served macro-F1 while dense vectors alone showed about zero.* A result that large needed an audit, not applause. Dense encoders can exploit semantic near-duplicates (the same story reworded) that a token-overlap check cannot see: about 31% of gold-history rows sit within cosine 0.90 of a training text, and "watchOS 27.0.1" appears in both the replay check and training in different words.
  So we added, **after seeing the dry run**, a decontaminated evaluation (rows near a training text removed, for baseline and candidate alike, and the gain must hold there) and a cost rule (cheapest candidate within 0.02 of the best). Both only make adoption harder or cheaper, are marked as added-after in `configs/evidence_v2.yaml`, and are disclosed in the card and the evidence JSON.
- *Result:* early fusion (H1) beats TF-IDF on every held-out set and on the decontaminated pooled set (+0.22 with e5-large, +0.19 with e5-base); log-loss falls by 0.23, calibration is no worse, abstention precision at equal coverage is +0.09. Dense alone (best +0.04, interval spans zero) and late fusion do not clear the bar.
  The pre-registered rule picked H1 on e5-large (the cheapest candidate within 0.02 of the best: 105 ms per text, 2.7 GB, against 36 ms for e5-base at 0.034 lower).
- *The cost benchmark had an anomaly:* gte-base is slower at batch 32 than at batch 1 (143 ms against 67), probably padding behaviour; it was re-measured once and the number kept, since gte-base never reached a decision.
- *Bug found by looking at the output:* the evidence summary of evaluation-set sizes was overwritten by the decontaminated sizes (it showed 193 gold-history rows instead of 280); fixed.

**Integrating the adopted model properly.** `hybrid-event-v2` (TF-IDF || 2 x e5-large, one logistic regression, the same temperature and the same fixed 0.5 commit rule). The product never imports torch: the frozen replay pack's 2,324 scored strings have hash-pinned float16 vectors (4.4 MB, pinned in the replay manifest); a new document needs the optional encoder, a missing one is a loud error, never a substitute.
- *The trainer first fitted on integer labels and the loader (like v1's) requires class names.* The unit test for the loader caught it before any artifact shipped.
- *Two identical trainings wrote different bytes:* scikit-learn stores a memory address in a used vectorizer. The v1 trainer already strips it; the hybrid reuses that vectorizer and needed the same treatment. The artifact is now byte-identical across runs (checked twice).
- *Impact parity.* impact-v1 was trained on the TF-IDF event model's probabilities, so feeding it the hybrid's would be train/serve skew. The impact stage keeps reading the TF-IDF probabilities (stated in the app's notices); an end-to-end test pins that every signal scored by the impact model in both configurations gets the identical estimate.
- *Honesty about "validated".* On the TF-IDF model's own pre-registered bar the hybrid passes (gold history lower bound 0.417 against 0.332; replay check 0.655 against 0.251; gold v2 0.508 against 0.376). But those sets also fed the adoption statistic, so passing them is not independent evidence. Rather than let the page call it "validated", we added an explicit failing check to its acceptance block ("a set that took no part in adopting this model") and the stage stays *experimental* until human-adjudicated rows exist.
- On the replay pack the served event stage now classifies 41% of signals (was 32%), says "not an event" for 45%, and abstains on 14% (was 29%); 725 signals get a model-scored impact (was 582).

### Stage 4, continued: the incremental-value study, the evidence endpoint and page (2026-10-03)

**The study (`make impact-study`, `docs/evidence/impact_study.json`).** Four runs (legacy and extended protocol, issuer and market scope), a nested ladder (constant, market state, + calendar, + text-model outputs; ridge, additive, full boosting), the regime-vs-event battery, and Track F
(4,713 matched filing / quiet-session pairs). The pre-registered selection rule picked R3s-full for issuers. Headline in `docs/EVIDENCE_V2.md`: the calendar is the real, consistent increment (10 of 10 years, intervals below zero on test and live); text-model outputs add nothing once the calendar is known; the placebo check (C7) still fails for issuers, so the model remains experimental.
- *The result changed what we thought was going on.* With the calendar left out, text looked helpful out of fold (-0.0033 [-0.0047, -0.0020]). With it in, the same text block adds -0.0001 on test. The "text skill" in impact-v1 was largely the earnings calendar arriving through the event-type probabilities. Permuting each block within issuer-month at prediction time says the same (calendar costs 0.0059 of error, text 0.0001).
- *C2 flipped from fail to pass* only because the held-out sample grew from 347 to 9,897 issuer episodes (val + test); the 2022 protocol, rerun, reproduces v1 (+0.114 against +0.119). The model did not get better at the old question; we got enough data to see its small skill.
- *Market scope tells a different story.* Skill is larger (+0.359) and survives the placebo (C7 passes), but the calendar and text blocks make it worse on 2026 (+0.0127 [+0.0051, +0.0202]): a market-wide score is a volatility meter.

**Evidence endpoint and page.** `GET /api/evidence` is assembled only from the model cards and the committed evidence JSON (never recomputed per request) and `/evidence` ("Model evidence") shows verdicts per stage, data foundation, the availability table, representation results, increments with a learner selector, Track F, reproducibility hashes and limitations.
- *Layout problems found by looking at it in the browser, not in a test:* row headers inherited the uppercase, no-wrap column-header style and clipped; the verdict column sat off-screen; 44 rows per run was unreadable and the default tab was the legacy protocol. Fixed with a row-header style, a learner selector, reordered columns, the extended protocol first and increments restricted to out-of-fold, test and live.
- *A "Increments" label bug:* the filing's item flags were grouped under an anonymous "other" family; labelled as "the filing's own item codes (published with it)".
- *Writing the doc, then checking it.* After drafting `EVIDENCE_V2.md` we re-read its numbers against the JSON files. Most matched; six statements were wrong or loose and were corrected before the doc was reported done: the pooled set is 759 rows, not 760; the adopted hybrid's ECE rises 0.019 (it passes inside a 0.02 tolerance, it is not "no worse"); the cost rule's 100 ms cap is exceeded on purpose by the chosen encoder; bge-base fails the decontaminated check (not "log-loss"); shuffling the text block *gains* 0.0007 rank skill, it does not cost it; and "about ten times" more held-out data is thirteen.

### Stage 4, continued: impact-v2 trained, compared with v1, and served (2026-10-03)

**Training (`make train-impact-v2`, about 1 h 45 min of an otherwise busy machine).** Document-level, extended protocol, same nested ladder and rules as v1 (the v1 trainer was parameterised, not forked). Issuer: R3s-additive selected out of fold; market: R2-additive. Both CALIBRATED, neither PRODUCTION.
Issuer fails C5 (interval coverage 0.93, intervals too wide) and C7 (placebo); market fails C5, C10, C11. The artifact reloads through `ImpactModel.load` and is byte-reproducible by construction (the same sklearn-pickle stripping as the other artifacts).

**Paired comparison with v1 decided what serves.** Issuer: v2 is better on 2024-25 (error -0.0036 [-0.0052, -0.0018], 9,897 episodes) and on 2026 news (-0.0047 [-0.0080, -0.0016]). Market: v2 is *worse* (+0.0042 [+0.0013, +0.0070]) with the same rank skill (+0.351 vs +0.358).
- *We had said v2 would serve only if at least as good.* For one scope it is not. The options were two models (two cards, two lifecycles and two attribution sets in every response and screen) or one artifact with the regression disclosed. We served impact-v2 whole and wrote the regression down on the card (`vs_previous`), in `EVIDENCE_V2.md` section 8 and on the page. The score is rank-calibrated and its ordering did not change; the difference is the level of the unsigned error. Reverting market-wide signals to v1 is a small change if the jury disagrees.
- *Two C8s.* The study reported C8 "not evaluable (76 episodes)" and the trained card reports it passing (+0.084 [+0.013, +0.156], 743 episodes). Both are right: the study demotes an episode if any one of its documents has an unreliable clock; the served model scores documents individually. Found only because the card and the study disagreed; both are now in the docs with the reason.

**Serving wiring.** `served_model_dir` in `configs/impact_model.yaml` (v1 stays the reference and the labelled fallback), the committed `EventCalendar` loaded in `api/deps.py` when the card's feature schema is v2, hash-pinned by the card and refused if modified. On the replay pack 725 signals are model-scored (same as before), all CALIBRATED; on a Nike earnings preview the top drivers are `earn_days_since_last` and `earn_days_to_expected`, labelled "known in advance".
- *Tests that pinned v1 failed, as they should* (card id, C1-C8 list, feature schema, model-version string): updated deliberately. New tests: the loader refuses a missing or modified calendar, the committed calendar matches the card's hashes, issuer inputs include the calendar block, a missing v2 artifact falls back to v1, the card's paired comparison shows v2 better for issuers and worse for the market.
- *The event stage's summary on the Evidence page said "did NOT meet its pre-registered bar on the gold set" for the hybrid*, which passes every scored bar and fails only the "independent set" check. Fixed: the sentence now says what passed and what is missing.
- *A stale sentence on the Pipeline page* ("impact-v1 was trained on the TF-IDF probabilities") was baked into the hybrid's card; reworded in the trainer and the card.
- *Rebuilding the bake-off evidence* (to fix the evaluation-set sizes label) reproduced every adoption number exactly (determinism check) and changed only the labels (gold history 280, 193 after decontamination).
- Known and not fixed: at an 800 px window the impact card's three headline numbers crowd the score bracket on the event page (it fits at 1280 px; the layout predates this stage).

### Stage 4, final: submission hardening and the model freeze (2026-10-03)

**Goal.** Stop modelling; establish the strongest *defensible* final state, freeze it, prove it end to end, and document it with the numbers the cards actually hold. The brief asked for human adjudication of the gold disagreement queue and an independent event-model evaluation, a lifecycle decision by the existing rules, a freeze, a full-system run, a final model table and a final regression.

**What we found first (and what it changed).**
- *Human adjudication could not be done by us.* `data/gold_v2/adjudication_v2.csv` has 20 rows (V0007 … V0275) and `data/gold/adjudication.csv` 60; every `human_*` cell is blank. Only the person can supply human labels, and labelling them ourselves would have produced "human" labels that are not. Decision (the user's): **skip human labels**; no AI tie-break; apply the existing check as-is. So the independent event evaluation does *not* exist and Definition-of-done items 1-2 are **not met**. We wrote the protocol and the missing code list into `docs/EVIDENCE_V2.md` §10 instead of pretending.
- *Even a filled queue would have changed nothing.* No code reads `adjudication_v2.csv` (`load_gold_v2` takes agreed rows only) and the "independent set" check on the hybrid's card is hard-coded `passed=False` in `hybrid_train.py`. Only the 20 disagreement rows were outside the adoption statistic (the 280 agreed rows fed it), and 20 deliberately hard rows give an interval too wide to clear any bar. Filling the file is therefore not enough: a loader, a separate scorer and a computed check are needed, or, better, a fresh blind sample scored once.
- *`make replay-pack` would have un-pinned the embeddings.* It rewrites `data/replay/manifest.json` and re-adds the `market_context` pin but not the `embeddings` pin that `make replay-embeddings` writes, so re-freezing the pack would silently turn the served event model back into the TF-IDF fallback. Fixed in `scripts/build_replay_pack.py` (same keep-if-present rule as the market context). **Not re-run**, to avoid changing the frozen manifest: the fix is by inspection only.
- *The impact golden test pinned impact-v1, not what is served.* `test_replay_pack.py` and `test_replay_hybrid.py` load `ICFG.model_dir`. The served configuration (impact-v2 + hybrid event + TF-IDF parity model) had no pin.
- *Clean clone was broken.* HEAD is still the Stage-3b commit; the hybrid, both impact models, the calendar, gold v2, the pinned embeddings, the market context and the Evidence page are untracked, while the committed replay manifest pins files that are not tracked. Exporting `git ls-files -co --exclude-standard` shows everything needed is 24 MB, so the fix is to commit (not done: we commit only when asked), and the agent-config clutter (`.cursor`, `.gemini`, `.kiro`, `AGENTS.md`, …) should stay out.
- *Pre-registration provenance is weaker than the comments say.* `configs/evidence_v2.yaml` and `configs/impact_model.yaml` are untracked, so "git history shows it" is not yet true for them. What does hold: the evidence_v2 file's sha256 is stamped in `docs/evidence/impact_study.json` and in impact-v2's card, and `make freeze-check` verifies both. `impact_model.yaml` changed after impact-v1 was trained (it gained `served_model_dir`), so its hash no longer equals the one in impact-v1's card; disclosed in the final report.

**Lifecycle, by the existing rules (no threshold touched).** Sentiment *experimental* (no bar was ever written); event `hybrid-event-v2` *experimental* (3 of 4 checks pass; the independent-set check fails); impact-v2 *experimental* (ISSUER and MARKET both CALIBRATED; ISSUER fails C5 and C7, MARKET fails C5, C10, C11 with C4, C8 not evaluable); stress engine is a deterministic rules engine, not a statistical model. Nothing promoted; `tests/unit/test_final_lifecycle.py` pins these verdicts.

**What we built.**
- `scripts/freeze_manifest.py` + `make freeze-check` / `freeze-write` → `docs/freeze_manifest.json`: sha256 of 57 files (all model artifacts and cards, configs, gold v1/v2 including the adjudication queues, the event calendar, the replay snapshot with pinned embeddings and market context, the evidence JSONs) and the five model ids and hashes. It also cross-checks card hashes against artifacts, the pre-registration hash against impact-v2's card and the study file, the calendar hashes, the full snapshot verification, and that two loads of each text model give identical probabilities. `tests/unit/test_freeze.py` runs it inside `make test`.
- `scripts/smoke_e2e.py` + `make smoke`: starts the real server on a free port and checks 20 things, among them that the model ids and artifact hashes on `/api/models/*`, `/api/evidence` and every signal's audit equal the committed cards, that all three stages are experimental, that impact's TF-IDF reference is announced, that the stress test reconciles to the P&L and is deterministic, and that the UI is served.
- `tests/e2e/test_replay_served.py`: pins the served run (output digest, status mix, impact mix, artifact hashes and feature schema on every signal), a second start-up reproducing it exactly, and the train/serve parity (impact reads `tfidf-lr-event-v1`).
- `docs/FINAL_MODEL_REPORT.md` (the final table and per-model can/cannot-use/protocol/limits) with `tests/unit/test_final_report.py`, which fails if a quoted number stops matching its card. First run of that test caught two numbers we had rounded the wrong way (0.4175 → 0.418, 0.5275 → 0.528 as half-up; Python's default rounding printed 0.417/0.527); the test now rounds half-up on the card's own digits.
- Updated stale docs: README event row (it still described the TF-IDF model's numbers), `ARCHITECTURE.md` (said "Stages 1-2"), CLAUDE.md state, banners in `EVENT_MODEL.md` and `IMPACT_MODEL.md`.

**End-to-end and UI check.** The preview server's `/evidence` page lists the same ids, hashes, lifecycle words and failing checks as `/api/evidence`; an event page shows `tfidf-lr-v1`, `hybrid-event-v2` and `impact-v2`, no "validated" wording anywhere; the Pipeline page states that impact reads the TF-IDF event model. `make smoke` passes against the real server in the working tree **and** in a clean export of the repository's non-ignored files (identical hashes, identical stress P&L −833,426).

**What broke along the way.** A ruff import-order error in the new test (fixed); our first draft of `test_final_lifecycle.py` asserted the adjudication queues must stay blank, which would have blocked the user's own future adjudication, so it was removed. The full pytest suite is slow (it rebuilds the replay pipeline in several modules and trains small synthetic models): about 30 minutes on a loaded machine.

**Regression (all run, 2026-10-03).** Full pytest in a clean export of the repository's non-ignored files: 823 passed, 5 skipped, 0 failed (the 5 skips are `test_impact_dataset.py`, which needs the 590 MB git-ignored `data/modeling` table, so a fresh clone does not exercise them); the same suite passed in the working tree before the new test files were added. `ruff check src tests scripts` clean; `tsc --noEmit` clean; vitest 101 passed; production `npm run build` ok; `make freeze-check` passed in both trees; `make smoke` 20/20 in both trees.

**Known and not done.** Human adjudication (by decision) and therefore any independent event evaluation; the clean-clone commit; no CI workflow exists; `make replay-pack` fix untested by running; at the freeze, `docs/freeze_manifest.json` does not cover `docs/*.md`, which are protected by the number tests instead.

## Stage 5: the judge-facing UI/UX pass (2026-10-03)

**Goal.** Models frozen; make the product a coherent, explainable, demonstrable decision-support story instead of an audit console: *unstructured text → event understanding → sentiment + event type → impact → evidence/comparables → scenario → portfolio stress → explainable result*, with one deterministic 3–4 minute path, progressive disclosure, a light theme (the user's direction at plan review: **light is the default**, dark is a toggle), proper maths, and visible honesty about what each number is. UI work follows `/hallmark`: the "Risk Desk" token system is preserved and extended, not rotated.

**What exploration found before any design (and what it changed).**
- *There is no similar-historical-events retrieval anywhere.* "Comparable events" (`comparable_events`, `realised_severity_*`, `p_extreme`) are aggregate statistics of the model's own score bucket. The brief's "92 % similar / 2024 event / 3.2σ" list would have been fabricated. We show a distribution (10th–90th percentile band, median, the model's estimate, the 3σ line) labelled *historical observation*, state in words that it is an aggregate, and list the missing retrieval under Technical details.
- *Only 725 of 2,330 signals are model-scored;* 1,368 are partial. Every chapter has a designed degraded state (placeholder rule, not-an-event, uncertain, unresolved company, no timestamp) that says what happened, why and what to do next.
- *The impact stage reads the TF-IDF event model, the card shows `hybrid-event-v2`.* The inputs drawer says "as seen by the impact stage" instead of reusing the event card's numbers.
- *The model's inputs were already persisted* (`provenance.impact.inputs`), so "Show inputs" needed no model change, only grouping and availability classes.
- *Realised outcomes live only in the git-ignored impact table.* Decision (the user's): export all of them as a tiny derived file. Our first idea (match by signal id) covered only 186 of 725 model-scored signals because the table keeps one representative per episode; joining on (scope, issuer, reaction session), which fully determines the realised move, covers 706 of 725 (185 of 194 distinct keys; the 9 missing keys have a reaction session that had not traded by the replay clock). The file is `data/outcomes/replay_outcomes.json` (25 KB), read only by the new endpoint, never attached to a `RiskSignal`.
- *Hero event.* Nike's Q3 earnings preview (`sig_90ee2542ae`): model-scored, a clean driver story (earnings due), an 8-K before the report, the earnings-release 8-K after it (2 Oct 00:15Z, after the replay clock), and a recorded outcome of 0.41σ (score 1), inside the model's stated range of 1–9. The unflattering realised number is shown deliberately.

**What we built.**
- *Backend (additive, read-only):* `GET /api/signals/{id}/context` (`services/signal_context.py`): inputs grouped by family and availability class, the issuer's 8-Ks around the report using the calendar's own strict point-in-time rule (each labelled *feeds the model* / *before, not used* / *after the report*), and the realised outcome; `make outcomes`; `Container` now keeps the loaded `EventCalendar`.
- *Design system:* `tokens.css` is now a light base plus `:root[data-theme="dark"]`; first load is always light (system preference ignored so the demo is identical everywhere), `?theme=` for captures, a no-flash inline script, a labelled toggle. `tokens.test.ts` computes WCAG contrast from the real OKLCH values for 22 pairs in both themes and bans raw colour literals outside the token file (the "no inline colours" rule had no mechanical guard before).
- *The story, on screen:* a sticky **FlowRail** (Event → Understand → Impact → Evidence → Stress; scroll-spy on the event page), a one-time chain graphic on the event page, and the Feed's story strip (2,330 → 962 → 725 → 19) with a featured event. Four kinds of number are never blurred (`ProvenanceKind`: model prediction / historical observation / scenario assumption / realised outcome, each an icon + pattern + word).
- *Event page (flagship):* hero verdict (score resolves once, bracket, lifecycle tag), *Understand* (input text → event type with a calibrated-confidence meter and the commit mark, sentiment gauge; abstention states), *Impact* (plain-named drivers, three facts), *Evidence* (comparables plot, coverage, the **"what did EventShock know at this moment?"** timeline with *available at the time / learned later / realised outcome*), *Stress* bridge. Drawers (`?open=`): Why?, Show inputs, How calculated? (KaTeX, lazy-loaded), Technical details, Audit trail.
- *Portfolio Stress:* before → after hero labelled *Scenario simulation*, a to-scale bar and a hatched bar for the uncovered share, a propagation strip, a change waterfall, a Portfolio → class/sector/factor → issuer → position drill-down, and a severity slider that recomputes with the real engine (BASE vs SCENARIO).
- *Evidence:* "How much evidence supports EventShock?" four verdict tiles (check strips with counts) over tabs Methodology / Evaluation / Datasets / Mathematics / Limitations / How it is built. The old Data Pipeline became the last tab as a visual flow; `/pipeline` redirects.
- *Tooling:* `scripts/screenshots.mjs` (Chrome over CDP, true device emulation, motion off) → `docs/screenshots/` (3 MB, palette-quantised); `docs/DEMO_SCRIPT.md`.

**What broke along the way.**
- *Our own role logic for filings was wrong.* We first called an 8-K "not used" if it was outside the 24-hour window. `f8k_hours_since_last` actually reads the most recent 8-K before the report (capped at 30 days), so Nike's 17 Sept filing *does* feed the model. Found by comparing the inputs (`f8k_hours_since_last` = 314.6) with the filing times; fixed and pinned by a test.
- *The build also typechecks tests,* so the 843-line `pages.test.tsx` had to be rewritten before anything could ship (41 of 101 tests failed on the new structure). Honesty assertions were kept and re-pointed; the suite grows from 101 to 261 tests (drawers and focus, the timeline's future-invariance, drill-down, what-if, tabs, theme, token contrast and the colour-literal guard).
- *`vi.unstubAllGlobals()` in the page tests removed our `matchMedia` stub,* so numbers tweened mid-assertion; the stub now lives on `window`.
- *`overflow-x: clip` hid real overflow.* The Evidence tabs' grid items grew to their widest table and were silently clipped at 375 px. A same-origin iframe sweep (every route × 375/768/1024/1280/1440) found it, and a stress hero grid that overflowed at 1024; fixed with `min-width: 0` on grid children and a later breakpoint. The only remaining hits are KaTeX's visually hidden MathML and formulas scrolling inside their own box.
- *Headless Chrome will not lay out narrower than ~500 px,* which first looked like clipped mobile layouts (it was not: a real 375 px viewport has `scrollWidth` = 375). The iframe workaround rendered skeletons only (no network under virtual time), so screenshots are now taken over the DevTools protocol with real emulation.
- *Smaller:* a hash-only navigation does not reload the page (stale bundle in the preview); another session owned port 8010, so a second launch config was added; a "saturates at impact 10" line in the demo script was wrong (the clamp is 0.5–1.5, so it bites outside ≈3.5–10.5) and was corrected from the engine's real output; a scenario was shown for a text the model said is not an event (now none); `ruff` flagged 35 long lines in new code (wrapped, plus the same per-file exemption `services/evidence.py` has for copy-heavy modules).

**Regression (all run, 2026-10-03).** Full pytest on this working tree: 852 passed, 0 failed (the earlier 828 = 823 passed + 5 skipped, which now run because the local data is present, plus 24 new tests: 18 unit tests for the context service on a synthetic calendar and 6 replay-API tests). `ruff` clean; `tsc --noEmit` clean; `vitest` 263 passed (was 101); production build passes (KaTeX is its own lazy chunk); `make freeze-check` passes (57 files, 5 models; nothing frozen was touched); `make smoke` passes against the real server. The 7-step demo path was walked from a fresh server start and every figure in `docs/DEMO_SCRIPT.md` was read back from the page.

A late finding from that fresh-start walk: the count-up numbers (portfolio value, the score) relied on `requestAnimationFrame`, so in a hidden or throttled tab they stayed at $0 and "1". A timer fallback now guarantees the true value (regression test added); the animation remains a transition, never the only way the value arrives.

**Honesty decisions (kept visible).** Impact stays *Experimental* everywhere (never validated); sentiment is never drawn as the cause of impact (the chain note says our evaluation found the calendar and market state carry the measurable skill and text outputs add none); the drill-down is labelled *Sensitivity, not cause*; scenarios and what-if are *Scenario simulation, not a prediction*; the 63.8 % of the book outside the scenario is shown, not hidden.

**Not done / known.** No individual-event retrieval (would be a modeling feature; the UI says so). Realised outcomes exist for 706 of 725 model-scored signals only. The Claude Design sync tool was not used (it only syncs design-system projects through a user-started skill). Screenshot of the dark theme covers 1440 px only. Event-page scroll-spy and the drawer focus trap are covered by unit tests, not by a browser end-to-end test.

### Stage 5, docs and history (2026-10-03)

Added `docs/FEATURES_AND_PAIN_POINTS.md`: every feature of the final UI mapped to the frustration it removes, who feels it, where to see it and how we know it works (a test, a rule or a file). Writing it was a useful audit: two rows had to be softened because the claim was stronger than the evidence ("three clipping bugs" became "several"), and the comparable-events row is explicitly marked as a limit. README gained a short pain-point table and the replay headline figures (the old figures there were demo-profile only). The Stage-5 work was then pushed as a series of small commits (backend context endpoint, design system and shared components, event page, stress page, feed/evidence/pipeline plus the rewritten page tests, then docs and screenshots) instead of one dump; the page commits are not individually green under vitest, because the page tests were rewritten as one unit and land with the last page commit.


## Stage 6: one risk engine (scope, pasted text, live feed) (2026-10-04)

**Goal.** Move from a company-centric, batch, replay-only analyser to one engine with several doors: UNSTRUCTURED INFORMATION → UNDERSTANDING → RISK SIGNAL → EVIDENCE → EXPOSURE → SCENARIO → PORTFOLIO CONSEQUENCE, for events that name a company, a sector, the market, or nothing, entering as pasted text, a live feed or a replay. Models, thresholds and the replay pack stay frozen.

**What exploration found (and what it changed).**
- *Unresolved documents were never dropped* (`UNKNOWN_ENTITY` is a first-class state; 847 of the 2,330 replay signals end up unresolved and 301 more name a sector or the market), but nothing said what an unresolved event is *about*. The stress service bound the sector only from a resolved company, so a pure sector event could never apply sector shocks, and the UI called a valid market-wide event "company not identified".
- *A real defect:* an unresolved signal whose default scenario has no market-wide shock (M&A, product/operations, earnings: 3 of 8 scenarios) returned `COMPLETED` with P&L 0 and 100 % "uncovered". 12 of the 19 replay signals at impact ≥ 7 are unresolved. It now returns `NOT_APPLICABLE` with the reason. This changes behaviour on purpose; it is journalled here and pinned by a test.
- *Nothing could be fed to the app.* The container threw the enricher away after start-up and the signal store had no `add`. Two traps for ad-hoc text: the served hybrid event model needs an e5-large vector per text and `torch` is not installed (it would raise `EmbeddingUnavailable` on any new text), and the frozen market context ends 2026-10-01, so later reports get the labelled placeholder impact. Both now degrade labelled, never silently.
- *Novelty was 1.0 for every unresolved signal,* which reads as a measurement. The value is kept (the impact model was fitted on it) but `evidence.novelty_measured` says it is not one, and the UI shows "not measured".

**What we built.**
- *Scope layer.* `domain/scope.py`, `pipeline/scope.py`, `configs/scope.yaml`: COMPANY / SECTOR / MARKET / UNRESOLVED from an ordered, explainable rule table (entity resolver → not-an-event → ≥2 sector terms → macro/geopolitical class or market vocabulary → one sector term → unresolved with the reason). Deterministic vocabulary, no model. `RiskSignal.scope` is derived from the entity when a producer sets none, so fixtures and old JSON still validate.
- *Measured, not asserted.* `make scope-eval` runs the sector vocabulary on the 1,549 replay documents that name exactly one company (whose sector is therefore known): it fires on 27 %, STRONG matches (≥2 terms) agree with the issuer's sector 90 % of the time (27/30), WEAK ones 81 % (314/387). The vocabulary was written before that run and has not been edited since. The bias is stated in the file: these documents also name the company, so the number is an optimistic proxy for the no-company case. There is no labelled set of no-company documents.
- *Stress and relevance.* Shocks bind by scope (`ISSUER` needs a company, `SECTOR` a sector, named or implied, `MARKET` always) with a stated reason when one is skipped; `NOT_APPLICABLE` for the defect above. `services/relevance.py` answers "what does this mean for this portfolio?" from the book alone (issuer / sector / region / whole book, shares, the path, how many of the default scenario's shocks reach this kind of event). Geography is exposure-only: region shocks would need new assumptions in the frozen `scenarios.yaml`.
- *One engine.* `run_documents` now calls `prepare_record`, `build_signal` and the novelty helpers, which `pipeline/engine.py::RiskEngine` reuses for incremental ingestion over a bounded live window (cluster membership fingerprints, only changed clusters rebuilt, an alias when a late earlier report takes over a cluster). `store.py` gained `LiveSignalStore` (age and count bounded, change counter) and `CombinedSignalRepository`. Start-up picks the TF-IDF event model for new text when no encoder is installed and says so on every signal and in `/api/live/status`.
- *Pasted text.* `POST /api/analyze` → an ordinary signal (`adapter manual-paste`, time marked `ANALYSIS_TIME` or `USER_ASSERTED`), idempotent, joins a story already in the feed, rejected with the reason when it cannot be scored.
- *Live information.* `ingestion/live.py` + `services/live.py`: GDELT DOC 2.0 through the existing `fetch.get_json` and `GdeltAdapter.parse`, an asyncio poller with back-off, `LiveStatus` (OFF/OK/DEGRADED/ERROR/IDLE), an input journal (git-ignored) for warm restarts, and a capture source that replays a GDELT file on its own clock, labelled "simulated". Off by default (`make run-live`, `make run-capture`). A failed poll changes the status, never the data.
- *Clustering of reports that name no company* (`unknown_same_event`, stricter than the issuer rule, set only in `configs/live.yaml`; the replay config leaves it off so its digest is unchanged).
- *UI.* Analyze page (four examples, one per kind of subject), Risk Feed → Risk Monitor (live bar, channel and scope filters, scope / relevance / new / updated chips), scope-aware Event Intelligence (the wrong "company not identified" copy for market-wide events is gone; a "what it is about" card and a portfolio-relevance panel), a Scope tab in Evidence (rules, mix, the measured vocabulary and its limits).

**What broke along the way.**
- *Calling GDELT for real found two bugs the fake transport could not:* a bare `a OR b` query is rejected ("Queries containing OR'd terms must be surrounded by ()") and arrives as non-JSON (every query in the first `live.yaml` was wrong); and querying faster than one request per five seconds gets HTTP 429 for minutes. Fixed the queries; the failure paths (non-JSON, 429, partial failure) were exactly what the status line was built for and behaved.
- *A test that shared the developer's journal:* pasted text is journalled, so the session-scoped app in the existing suite warm-started text pasted by another test and broke two model-id assertions. Every test app now gets its own journal (`EVENTSHOCK_JOURNAL_PATH`).
- *`RiskSignal.scope` as an optional field* made the OpenAPI type nullable and the whole UI needed `!`; a `before` validator derives it, so the contract is non-null.
- *The golden digest* changed because every signal gained `scope` and `novelty_measured`. Rather than re-pin blindly, `test_no_pre_existing_signal_field_changed` hashes the served run with only those two fields removed and requires the Stage-5 digest `d265604e…`; the new digest is `70478b2d…`.
- *Lint:* the repo's strict E501 passed at HEAD; the new modules carry long contract docstrings, so they were added to the existing per-file ignores like the pipeline modules.

**Decisions kept visible.** Impact is still Experimental everywhere and is *not* a sector model: a sector or market event gets the existing MARKET-scope estimate, labelled; nothing blended. The trained event model cannot embed new text without an encoder, so live and pasted text use `tfidf-lr-event-v1` (impact was fitted on its outputs anyway) and say so. Kalshi was **deferred**: it would need a curated theme→contract mapping and a verified API, and it must stay an independent, labelled observation, so it is not worth a half-built version. A learned scope model, contradiction detection (`contradicted_by` is still always empty), region shocks and a live market-context refresh (prices) are also not done.

**Not done in Stage 6 (honest list).** No sample capture is committed: GDELT answered HTTP 429 to every request for the rest of the session after our first, too-fast attempts (the live source and `scripts/capture_gdelt.py` throttle at 6-20 s and retry with back-off, but the block did not lift), so the offline *simulated live* mode was verified with a ten-record hand-made file in the scratchpad (queries, clustering, scoring, UI) and `make capture-gdelt` creates a real one. The live poller therefore has been exercised against the real API only up to its failure handling, never to a successful poll: its success path is tested with a fake transport. The freeze manifest changed by exactly three added files (`configs/live.yaml`, `configs/scope.yaml`, `docs/evidence/scope_eval.json`); no existing hash moved. Older golden tests (Stage 2-4 digests) now hash the run with the two Stage-6 fields removed and still match their original pins.


## Stage 7: LLM understanding + a transparent severity score (2026-10-05)

**Goal.** Turn "raw financial text → structured understanding → impact → scenario → portfolio stress → evidence" into a product that is statistically honest. Three weaknesses were
checked against the code before anything changed: understanding was shallow (8-class TF-IDF/e5 event type, TF-IDF sentiment, keyword scope; no subtype, entity list, asset classes,
severity indicators or evidence spans); the headline impact (`impact-v2`) fails its own pre-registered bar (placebo ≥ real), so it cannot defensibly trigger a stress test; and the UI said
"the text models' outputs add none" next to a per-event score.

**What exploration corrected.** There is *no* XGBoost in the repo (the impact model is `HistGradientBoosting` / Ridge) and real outcome labels *do* exist (two-session abnormal returns) — so
"no legitimate labels" was not the reason to leave supervised learning; the reason is that the trained model's own evaluation says it measures the volatility regime. No labels were created or
inferred. This contradicted CLAUDE.md's "architecture finalised / models frozen" status; the brief authorised it, and the change was kept narrow: an additive layer, trained models and the frozen replay
pack untouched.

**What we built.**
- *LLM adapter* (`llm/`): Anthropic Messages API over `urllib` (no new dependency), forced tool-call JSON schema, closed enums, timeout / retry-with-back-off / `Retry-After`, typed errors, JSONL cache keyed by
  text + model + prompt version (so a restart that re-ingests the journal costs nothing). Off by default (`EVENTSHOCK_LLM=1` + `ANTHROPIC_API_KEY`).
- *Grounding* (`assessment/grounding.py`): entities must appear in the text and can never become the issuer; quotes must be verbatim (found by position so the UI highlights them); every id must be in the
  closed vocabulary (`configs/semantics.yaml`); what was dropped is shown.
- *Rule extractor* (`assessment/rules.py`): the no-key demo mode and the fallback for every provider failure; cue phrases anchored to the trained models' readings.
- *Hybrid severity* (`assessment/hybrid.py`, `configs/impact_hybrid.yaml`): seven explicit factors, configurable weights each with a rationale, renormalised over what is available, uncertainty discount,
  assumption-sensitivity range, drivers generated by rule from the computed values. Not supervised, not validated, said everywhere.
- *Side-car, not a `RiskSignal` change* (`assessment/service.py`): an `AssessmentService` derives the assessment from a signal. A new field on `RiskSignal` would have moved the pinned digests, fixtures and goldens;
  the side-car leaves all of them valid (`GOLDEN_SERVED_DIGEST` etc. unchanged).
- *Stress hook*: `StressService(severity_provider=…)`: the trigger and scaling read the severity score, the scenario follows the *assessed* class, a sector read from the text binds sector shocks where the vocabulary scope
  found none. Audit records `ASSESSMENT`, basis, version and mode. No provider → byte-identical behaviour (`GOLDEN_RUN_ID`).
- *API*: `/signals/{id}/assessment`, `/evidence` (source · inference · assumptions), `/timeline`, `/stress-runs?signal_id=`; `POST /analyze` returns the assessment and takes an optional `source`.
- *UI* (Hallmark, existing tokens, no new colours): the five-step chain on the Feed, Analyze and Event pages; `UnderstandingCard` with highlighted evidence; `SeverityBreakdown` (drivers, the full table, omitted
  factors and why); one shared `ThresholdNotice`; "What the assessment used" replaces "What the model saw" as the primary inputs drawer (NLP signals / market state / calendar / deliberately excluded); a three-box
  evidence view and a phase-grouped timeline where everything after the report is tagged "not used"; a mode-aware privacy note. The trained model sits in a collapsed *Reference* panel.

**What broke / what we got wrong, and the fix.**
- *Pasted text borrowed a stale market state.* The frozen market pack ends 2026-10-01; a text pasted later was given that VIX as "the market at the time". Fixed: the regime factor is refused when the state is older than
  5 days at the report's time, and the reason is listed.
- *The first rule extractor over-claimed.* "Escalating tensions" was filed under *armed conflict* (weight 0.85). Split into a separate, lower-weight *geopolitical tension* indicator.
- *A name inside another word matched the entity master* ("Pineapple Co" for Apple). Containment is now whole-word only, with a regression test.
- *"Uncertainty 50%"* was shown as the reading's own when the rule extractor states none. The contract now carries `uncertainty_stated`, and the UI says a neutral value was assumed.
- *Feed and detail disagreed*: rows still showed the trained model's event class beside the assessed one. The tag, the non-event filter, the category filter and the flow-rail context now all follow the assessment.
- *Existing UI tests pinned the overbroad copy* ("the text models' outputs add none"). Replaced by a scoped statement about the reference model only, with a test that the old claim is gone; textbox queries now use the
  accessible name because the Analyze form gained a second field.
- *The backend suite is slow* (each replay-profile app builds in ~85 s), so it was run in three parallel groups (unit, integration, e2e).
- *Dead ends considered and rejected:* adding the assessment to `RiskSignal` (moves every pinned digest); feeding LLM outputs into the trained impact model (train/serve skew; the feature registry would refuse it);
  counting later corroborating reports in the score (violates the temporal rule: they are shown, never scored).

**Verified.** Deterministic tests only: a scripted fake LLM client (success, timeout, 429, malformed JSON, ungrounded entity/quote, invalid class, cache hit with zero calls, restart over the cache file), the seven required
cases through both extractors, the hybrid maths (contributions sum to the score, renormalisation, monotonicity, omitted factors, stale market data), temporal future-invariance, conflict detection, the stress provider,
API behaviour through the real replay app, and the UI components and Analyze page. **Not verified: the real Anthropic API** (no key was available in this environment); the HTTP adapter is tested against a scripted opener.

**Honest list of what is not done.** Weights are judgement priors (the range is sensitivity, not an interval); duplicate detection remains the token-overlap rule; the reference model is still experimental; no
learned scope model, no region shocks, no live market-data refresh; the real-API path is unverified here.

**Freeze.** `make freeze-write` was run once after adding `configs/semantics.yaml`, `configs/llm.yaml` and `configs/impact_hybrid.yaml` (the manifest globs `configs/*.yaml`); the models, replay pack, gold sets and
evidence hashes in it are unchanged (63 files, up from 60 + the three new configs). A local call cap (`max_calls_per_minute`, default 30) was added to `configs/llm.yaml` before the freeze: a demo left open cannot run up a
bill, and overflow text is read by the rules, labelled.

**Late fix (found by driving the real app with `EVENTSHOCK_LLM=1` and no key).** The service only passed "use the model" to the extractor when a client existed, so a pasted text in "switched on but no key" mode reported no
`fallback_reason` and the UI showed a plain rule-based reading instead of saying why. It now asks for the model whenever the text is new (a paste or the live feed), and the extractor labels the unavailability; replay text never
asks, so it never apologises. Regression test: `test_a_model_wanted_but_not_available_says_why_on_new_text_only`.


### Stage 7, live provider test: Groq (2026-10-05)

A Groq key was supplied and put in the git-ignored `.env` (never echoed, never in a config file). The provider layer was generalised (`llm/client.py`: a shared HTTP core with `AnthropicClient` and an OpenAI-compatible `GroqClient`;
`configs/llm.yaml` now has a `providers` table; `GROQ_API_KEY` / `EVENTSHOCK_LLM_PROVIDER` in `Settings`).

**What the real service showed that the scripted client could not.**
- *The documented default model was refused:* `llama-3.3-70b-versatile` returned `404 model_not_found` for this key. The 404 was reported as "answer does not match the schema" (wrong: it was a refused request). Fixed: a new `LLMRejected` carries the provider's own words (`model_not_found: The model … does not exist`), and the default is `openai/gpt-oss-120b`, taken from `GET /openai/v1/models`. Every refusal still fell back to the rules and nothing crashed; that was the accidental proof of the fallback.
- *Quotes were the whole sentence.* The first live run "quoted" the entire headline for most claims, which highlights nothing. Prompt v2 asks for 2-4 short phrases and says institutions are entities; grounding drops a quote covering more than 80 % of a text longer than 40 characters, and says so. The prompt version is in the cache key, so v1 answers are not reused.
- *One call took 107 s* (rate-limit waits plus retries). Added `max_total_seconds: 30` across retries (and a 15 s per-attempt timeout); a person waiting on a paste gets the rules, labelled, instead.
- *A reasoning model spends tokens thinking:* `reasoning_effort: low` (a per-provider `request_extra`) and `max_output_tokens: 1500`.

**Live results (7 headlines, `openai/gpt-oss-120b`, about 1-1.6 s each, repeat served from the cache with zero calls).** All seven read as expected (regulatory, monetary, geopolitical, earnings, M&A, unknown-company, non-event); Quantum Dynamics stayed a mention
with issuer `UNKNOWN_ENTITY`; the weather headline was `NO_EVENT` with no severity. Failure modes exercised against the real service: bad key (`HTTP 401 … invalid_api_key`), unknown model (404), 1 ms timeout, unreachable host (connection refused), wrong URL (404): each returned `mode: RULES` with the reason, and the text was still read by the rules.
The real app, started from `.env`, reported `mode: LLM, openai/gpt-oss-120b, sends_text_off_machine: true` and served pasted text with `extraction.mode: LLM`.
The Anthropic path remains verified only against the scripted opener.


### Stage 7b: severity-v2, fixing the compressed scale (2026-10-05)

**Problem.** Most events scored 4-7. Measured first (64 hand-written headlines from routine to systemic, expected bands fixed in advance in `data/benchmarks/README.md`): with the LLM nothing above 8 and 30 of 64 in one band; rules rho 0.22 (`docs/evidence/severity_baseline_v1.json`). The cause was the formula, not the model: a weighted average of bounded factors regresses to the middle; one factor measured scale; source reliability was a constant (0.42); tone counted as severity; an uncertainty discount shrank every score; nothing encoded systemic scale. Re-weighting would not have fixed it.

**What was built.** The weighted average was replaced by a scorecard (`severity.yaml`): four anchored ordinal answers → a fixed matrix whose anchors are the middles of the five semantic bands → certainty/direction scaling → two bounded data adjustments. The AI answers the same four questions as the rules and may move one step from the rules baseline; each answer needs a reason. Provenance (AI / Data / Rules / Hybrid / Assumption), evidence classes (QUOTED / KEYWORD / INFERRED: the RBI "inflation pressure builds" → "persistent inflation" inference is now labelled an inference, never a quote), a market freshness policy (a report on 5 Oct with data from 1 Oct is shown with its lag, or excluded) and the UI (score build-up table, scale bar, rubric table, origin chips) followed.

**What broke, honestly.**
- The rule extractor abstained on texts that had severity indicators; indicators now imply an event class.
- "global" double-counted; an opposite-polarity cue inside a longer phrase ("lowering tariffs") flipped direction; singular sector nouns inflated reach. Fixed with longest-match suppression and plural-only sector reach.
- I wrote some benchmark-derived cues into the vocabulary. They were pruned, but the author had seen the dev set, so dev rules results are optimistic. A 32-item held-out set was written and **not** used for tuning: there the rules fallback ranks weakly (rho 0.39, 17/32 negligible). Documented, not tuned away.
- The prompt contradicted itself on levels 3 vs 4 (the model never said "critical": 0 extreme in the recorded run). Rewrote the definitions (v5, v6: intensity separated from breadth).
- An early Qwen "LLM" evaluation was invalid: the rubric was optional in the schema, so the model silently skipped it and the result was just the rules. Discarded; the rubric is required again.
- The replay harness silently fell back to rules because the cache key used the current prompt version; fixed with a prompt-version override and a hard error on any non-LLM replay.
- Groq: provider-side tool-schema validation failures (relaxed schema, retried), 404 on a model, then 429s and finally the 200k-token daily quota on all three models. Added fast-fail on a daily quota and a 60 s circuit breaker (a doomed call used to hold a paste for ~30 s).
- An ablation on recorded answers (dev only) showed that letting AI answers move further than one step lowered agreement (strict 0.905, two steps 0.849, unbounded 0.833), so the bound is strict, with one principled exception where the rules have no evidence (an unseen phrasing must not cap a correct answer at a default).
- A failing guard test (rules held-out max 7 < 9) was not "fixed" by tuning: the guard now applies to dev; held-out pins the finding.

**Open.** No live-model recording exists for the shipped prompt (quota); held-out has never been run with a model. Commands to do it are in `docs/RISK_ASSESSMENT.md`. Until then, no LLM score distribution is claimed for the final prompt.

**Verification (2026-10-05, end of Stage 7b).** Backend: full pytest passed (three skips: the recorded-answer guards, which only run for a recording made with the current prompt). Frontend: 339 vitest tests, `tsc`, `npm run build`. `make lint`, `make freeze-write` + `freeze-check` (66 files), `make smoke` passed. Live check on the real app with a Groq key: one call succeeded (a 25 bp expected hike read by `gpt-oss-120b`: AI asked for more than one step, was clamped, final 3/10 with the rules baseline 1), the following calls hit the daily quota and fell back to rules with the provider's own words shown, no crash; "Bank run spreads…" scored 10/10 in rules mode and ran the credit/funding scenario (17 % of the book reached). Two UI test assertions were ambiguous (the build-up legitimately shows a value twice) and were made explicit.


## Stage 8: finance-grounded validation, historical analogues, outcome audit (2026-10-05)

**Why.** Three read-only investigations of the repository (outcome data, severity/LLM/stress layer, embeddings/API/UI) found that severity-v2 had never been tested against a market outcome (its 96 benchmark headlines are the author's judgement; rules-only held-out Spearman 0.39), that `impact-v2` fails its own bar (placebo skill 0.236 >= real skill 0.168: the skill is the volatility regime), that no analogue retrieval exists ("comparable events" are bucket statistics), and that scenario shocks were never compared with history. The plan (kept in the session plan file, summarised in `docs/FINANCE_THEORY.md` and `docs/ANALOGUES.md` as they are written) is additive: no frozen model, replay digest or stress formula changes; every new component is a side-car with its own pre-registered decision rule.

### Phase 0 (2026-10-05): hygiene and baseline
- Removed stale references to the deleted `assessment/hybrid.py` / `configs/impact_hybrid.yaml` (module docstrings, two config comments, two UI strings, one test comment, one test fixture that still said `TRANSPARENT_HYBRID`), and fixed "seven groups" to "eight groups (A-H)" for the benchmark. The "seven factors" wording that remains describes the v1 weighted average and is correct history.
- The two config edits are comment-only but `configs/llm.yaml` and `configs/semantics.yaml` are in the freeze manifest, so `make freeze-check` failed on exactly those two files; I ran `make freeze-write` deliberately (66 files, diff = two hashes) and `freeze-check` passes again.
- A sub-investigation reported a scikit-learn mismatch (1.8.0 installed vs 1.9.1 artifacts) that would make `freeze-check` crash; in this environment `.venv` has 1.9.1 and the check runs, so no action was needed. Noted so it is not rediscovered.
- `make lint` (ruff + tsc) passes. Frontend `assessment` + `pages` vitest files pass (101 tests).

### Phase 1-2 (2026-10-05): pre-registration, theory, and the outcome audit
**Pre-registration first.** `configs/evidence_v3.yaml` (sha256 `99c0ff9b...` at the time it was written, before any audit or validity number existed) fixes the audit's one decision rule, the severity-validity test and its label conditions, the retrieval design and the "may it enter the score" rule. Every evidence file records the sha256 of the file it was produced under. Note: the working tree has not been committed (commits are made only when asked), so "the git history is the proof" cannot hold until it is; the recorded hash plus this entry are the interim record.

**Citations verified, not recalled.** Every reference in `docs/FINANCE_THEORY.md` was looked up (MacKinlay 1997 JEL 35(1) 13-39; Brown & Warner 1985 JFE 14 3-31; Boehmer-Musumeci-Poulsen 1991 JFE 30 253-272; Kolari & Pynnonen 2010 RFS 23(11) 3996-4025; Campbell-Lo-MacKinlay 1997; RiskMetrics 1996; Engle 1982 Econometrica 50(4); Whaley 2000 JPM 26(3) 12-17; Tetlock 2007 JF 62 1139-1168; Loughran & McDonald 2011 JF 66(1) 35-65; Bernanke & Kuttner 2005 JF 60(3) 1221-1257; Billio et al. 2012 JFE; Artzner et al. 1999 Math. Finance 9(3) 203-228; Acerbi & Tasche 2002 JBF 26(7) 1487-1503; BCBS 155 (2009, superseded); Gneiting & Raftery 2007 JASA 102 359-378; Guo et al. 2017 ICML; Niculescu-Mizil & Caruana 2005 ICML; White 2000 Econometrica 68(5) 1097-1126; Hansen 2005 JBES 23 365-380; Lopez de Prado 2018 Wiley; Wang et al. 2022 (E5) arXiv 2212.03533; Reimers & Gurevych 2019 EMNLP).

**Outcome audit (`make outcome-audit`, `docs/evidence/outcome_audit.json`, deterministic: two runs are byte-identical).** 60,000 random quiet (ticker, session) pairs, 34 tickers, 2016-2026.
- *Identity:* the table's `z` equals `PriceStore.target` exactly (3,000 rows) and `f_sigma_60` is the residual sigma (max difference 5e-8), so CAR = z * sigma * sqrt(2) is recoverable from the table; an earlier note of mine that `f_sigma_60` was a different sigma was wrong.
- *Pre-registered decision:* the EWMA sigma (lambda 0.94) removes 88% of sigma60's regime variance gap (|ln Var(z|high VIX)/Var(z|low VIX)|: 0.090 -> 0.010) and the reduction holds in both halves (83% in 2016-20, 39% in 2021-26); the overall null variance is 1.32 (inside 0.6-1.6). Rule satisfied: `outcome-v3` = EWMA sigma, for the side-car layers only (`modeling/outcome_v3.py`; CAR, fit and clock are unchanged; the frozen v2 table, models and digests keep outcome-v2).
- *What the numbers actually say about the target:* on the pre-registered null z has variance 1.26 and excess kurtosis 11.8 (P(|z|>2) = 6.0%, Gaussian 4.55%). **A mistake in my own null:** "quiet" was defined as no corpus episode within two sessions, which still lets earnings reactions in (2.7% of the sample). I added a post-hoc, disclosed block with a null that also excludes earnings windows (not part of the pre-registration, and the adoption decision does not use it): there sigma60 is nearly perfectly calibrated (variance 0.98, kurtosis 4.6, P(|z|>2) 4.9%) and EWMA is similar (1.03), so the fat tail was earnings, not the normalisation. Earnings contamination of the sigma window is common (87% of windows) and inflates sigma by about 15% on average.
- *The uncomfortable finding:* news episodes are barely distinguishable from quiet days. Stratified (ticker x year) AUC of |z| for news episodes vs quiet days is 0.523 [0.512, 0.532]; P(|z|>=2) is 7.4% vs 6.0%. Excluding episodes whose own window holds an earnings reaction: AUC 0.508 [0.500, 0.517], 5.1% vs 4.9%. With earnings in the window: AUC 0.80 (1,006 episodes). By detected class only EARNINGS stands out (0.657, n=54 usable); PRODUCT_OPERATIONS 0.503, MARKET_VALUATION 0.516. By clock: FIRST_SEEN 0.496, IN_SESSION 0.511, OFF_HOURS 0.474, PRE_OPEN 0.544, DATE_ONLY 0.564; placebo/real mean log-severity is about 1.0 for FIRST_SEEN, IN_SESSION and OFF_HOURS (no more signal after the report than before it). This is the same story as Stage 4 (placebo skill >= real skill) from a different angle, and it means: realised moves around ordinary headlines about large caps are not a usable severity label, and "what happened after similar headlines" will mostly look like an ordinary day unless earnings are involved.
- *Other diagnostics:* reaction dates cluster (intraclass correlation 0.067, design effect 2.18, effective n 8,995 of 19,638, so naive intervals are about 1.5x too narrow: every interval in Stage 8 is a cluster bootstrap over reaction dates); 5.5% of episodes fall on days the S&P moved >= 2 sigma; 3.8% of episodes have a same-ticker near-duplicate story within 10 sessions (5 pairs straddle splits).

**What broke / was fixed in code.** A local variable named `clean` shadowed the JSON-cleaning helper (found by the first run, 28 s in); NaN is not valid JSON so the evidence writer now maps non-finite floats to null; a test for "degenerate sampler input" was wrong (the sampler legitimately draws with replacement; the real degenerate case is "no session has 120 sessions of history"); `modeling/severity_validity.monotone_check` reused a Spearman that refuses fewer than 5 points although the pre-registered rule needs only 4 bands (a test found it; fixed before the final run, and the study was restarted so the evidence comes from the final code).

### Phase 3 (2026-10-05): does the severity scorecard mean anything? `make severity-validity`
Pre-registered test (`configs/evidence_v3.yaml: severity_validity`; `docs/evidence/severity_validity.json`): the TEXT-ONLY severity-v2 scorecard (rules extractor, rubric, matrix; no VIX regime, no novelty, no LLM; unchanged) applied to the earliest headline of each of 19,638 news episodes, against the episode's realised outcome-v3 move; cluster bootstrap over reaction dates (2,000 resamples).

**Label: HEURISTIC_UNCALIBRATED.** The conditions for both stronger labels fail on the 2025 test and the 2026 live split.
| split | n | M1 rank(score, log1p abs z) | M3 real minus placebo | M4 beyond a regime baseline |
|---|---|---|---|---|
| dev (2018-2024) | 14,039 | +0.054 [+0.036, +0.072] | +0.040 [+0.016, +0.063] | +0.049 [+0.031, +0.067] |
| test (2025) | 4,636 | +0.007 [-0.025, +0.039] | +0.028 [-0.015, +0.070] | +0.009 [-0.022, +0.041] |
| live (2026) | 963 | -0.021 [-0.086, +0.040] | -0.038 [-0.131, +0.056] | -0.027 [-0.088, +0.032] |
- A small positive rank correlation exists on dev (about 0.05, and it beats the placebo window there), and it does not replicate out of sample. There are no fitted parameters in the scorecard, so this is not overfitting; the likelier reasons are a source/period mix that changes across the split (2018-2020 Reuters/CNBC/Guardian headlines vs 2023-2026 GDELT titles) and a weak effect.
- The rules extractor reads 73-82% of these company headlines as "no market event" (score 0). Tail rates (P(|z|>=2)) by band show no gradient inside the scored bands (dev: 12.6, 11.3, 14.8, 11.2, 13.3% from negligible to extreme; the abstained class 6.8%): "an event was detected" carries a weak lift on dev (about 12% vs 6.8%), the 1-10 level carries none. Band monotonicity fails (dev Spearman -0.4 over four bands).
- Secondary, unlabelled: outcome-v2 gives the same picture; excluding episodes with earnings in the reaction window does not rescue it (test M1 -0.020); scored-only (score >= 1, n = 1,075 test) is also null.
- **Post-hoc extension, disclosed as such (not pre-registered, does not change the label):** the pre-registered corpus asks whether a single large cap moved, but severity is defined as intrinsic consequence scale and reach, which matches market-scope reports and the S&P 500's excess move better. Market scope (6,051 documents): dev -0.039 [-0.075, -0.001], test +0.098 [+0.041, +0.154], live +0.020 [-0.019, +0.056] (the 2026 sample is nearly flat: 0.1% of documents had |z| >= 2). Inconsistent sign across periods = no replicated skill.
- **What this means for the product.** The honest label is "transparent triage scale, not outcome-calibrated". It was designed to read how serious a kind of development usually is and how far it reaches, and the historical data available here (headline-only company news, a 6% GDELT sample, thin tails, 34 large caps) is not able to confirm or refute that. It is not evidence that the scale is wrong either; it is evidence that this data cannot validate it. Nothing in `severity.yaml` or `semantics.yaml` was touched.
- Bug found by the test-first process: see Phase 2 (`monotone_check` floor); the study was re-run after the fix so the evidence matches the final code.

### Phase 5a (2026-10-05): retrieval relevance. `make analogue-relevance`
Pre-registered (`retrieval.relevance_eval`): queries = the 280 doubly annotated gold-v2 titles where both blind annotators agree (unseen wording: other period and source mix), labelled corpus = the 3,270 AI-annotated `event_train` rows, relevant = same event-type label, baseline = TF-IDF (1-2-gram, sublinear) cosine.
| queries | base rate | P@5 e5-large | P@5 TF-IDF | difference (95% bootstrap) |
|---|---|---|---|---|
| all 280 | 0.307 | 0.504 | 0.443 | +0.061 [+0.026, +0.093] |
| 149 non-NONE | 0.071 | 0.389 | 0.255 | +0.134 [+0.094, +0.179] |
| 267 decontaminated (no corpus near-duplicate, e5 cosine < 0.90) | 0.310 | 0.503 | 0.443 | +0.059 [+0.027, +0.094] |
Rule met (lower bound above 0): **e5-large is the served retriever**. On event queries it retrieves the right event type 5.5x more often than chance (TF-IDF 3.6x). Caveat recorded in the evidence file: "relevant" means same kind of event under AI labels, not same market outcome.

### Phase 4-5 (2026-10-05): the analogue index, the floor rule, and whether retrieval adds information
**Built** (`src/eventshock/retrieval/`; `make analogue-corpus analogue-embed analogue-index`): a corpus of 25,689 past news reports (19,638 issuer episodes, one per ticker-session with the earliest report; 6,051 market-scope documents) each with its realised outcome (outcome-v3 for companies, the S&P 500's excess move for market-wide reports), and an `available_from` date (reaction session + 2-session window + 5-session embargo). Only **TRUSTED-clock** rows (an exact publisher timestamp before the open or after the close, so the whole reaction window follows the report) are served as analogues: 4,811 issuer episodes + 1,720 market documents = **6,531**. e5-large vectors (the encoder already adopted and cached; no new dependency; about 80 ms per text on CPU; the 25.6k unique texts took about 45 minutes), packed as float16 with the headline and outcome into `data/replay/analogues/` (12.3 MB vectors + 3.5 MB rows, hash-pinned by its manifest; slightly over my 15 MB target, kept).
**The search** (`search.py`, pinned by 25 unit tests): point-in-time eligibility (`available_from <= query date`, with a future-invariance test: adding later episodes changes nothing), one analogue per outcome, story collapse (same ticker, within 10 sessions, cosine >= 0.92), per-company and per-month diversity caps, and a reliability bar (>= 5 distinct episodes and >= 3 stories above the floor) below which the answer is `NO_RELIABLE_ANALOGUE`: nothing is padded and the nearest matches are listed separately as "below the bar, not precedent".
**The floor rule (pre-registered, dev data only; `docs/evidence/analogue_floor.json`):** the smallest grid value with event-type precision lift >= 1.3 and >= 30% of dev episodes answerable. Result: **0.78**. Honest note on the rule: precision lift is about 5x chance at every floor (4.97 at 0.78 to 9.0 at 0.90), so the lift condition never binds and the rule picks the most permissive floor (97% answerable at 0.78, 37% at 0.84, 0.4% at 0.90). The full curve is in the evidence file; the reliability bar and the "distinguishable from an ordinary day" test are what keep a permissive floor from over-claiming.
**Does retrieval add information about the realised move beyond regime + earnings calendar?** (`make analogue-value`, `docs/evidence/analogue_outcome_value.json`, paired MAE difference on log1p|z|, 2,000 date-clustered resamples.) **No.**
| candidate vs B0 (ridge on market state + timing + calendar) | 2025 test: delta MAE | 2026 live: delta MAE | real-minus-placebo improves? |
|---|---|---|---|
| C_knn (similarity-weighted neighbour outcomes, n_eff, max similarity) | +0.0005 [+0.0001, +0.0009] (slightly worse) | +0.0012 [+0.0004, +0.0019] (worse) | no |
| G_reference_class (event class x VIX tercile cell mean) | -0.0006 [-0.0012, -0.0001] | +0.0002 [-0.0009, +0.0013] | no |
Pre-registered rule: both splits must improve and the real-minus-placebo gap must widen: **no analogue-derived quantity enters the severity score; retrieval is display evidence.** This is the outcome the earlier evidence predicted (embeddings never helped impact error, `docs/IMPACT_MODEL.md` section 11) and it is reported as a failed experiment, not hidden. Side finding worth keeping: under the regime-neutral outcome-v3, the baseline's rank skill is event-specific, +0.149 on the real window and -0.007 on the placebo window (2025 test), i.e. it comes from the earnings calendar, not the volatility regime (the Stage 4 `impact-v2` failed this placebo check under outcome-v2; nothing about `impact-v2` was changed).

**What I got wrong and fixed.** (1) A first probe of the real replay signals showed 2,322 of 2,330 reports getting an "OK" answer, including reports that could not be tied to any company: the market-scope corpus pairs documents that name no *listed* company with the S&P's move, which is meaningless for an unresolved report. Routing is now by scope: company -> company analogues, sector -> company analogues of that sector, market-wide -> market analogues, **unresolved -> refused with the reason** (the encoder is never called). (2) The per-ticker diversity cap treated "no ticker" as one company and limited market-wide answers to 3 items; it now applies to companies only, with a per-month cap for market-wide reports (tests added). (3) After the fix a hand-check of examples reads sensibly (an OPEC+ report retrieves OPEC+ precedent; mortgage-rate news retrieves mortgage-rate news; a credit-card report retrieves bank headlines), and nearly all groups read "not distinguishable from an ordinary day", which is what the audit predicts.

### Phase 6-7 (2026-10-05): API, UI, and the scenario history check
- Backend (all additive side-cars; `RiskSignal`, the replay digests and `GOLDEN_RUN_ID` untouched): `AnalogueService` (`services/analogues.py`), `GET /api/signals/{id}/analogues`, `GET /api/scenarios/{id}/history-check?severity_scale=`, `capabilities.analogues` / `.history_check`, `Origin.RETRIEVED` and `Kind.RETRIEVED` (a past report found by similarity: precedent about other events). `configs/retrieval.yaml` has `similarity_floor: rule`, resolved from the committed floor evidence at start-up, so the served floor cannot drift from it. A missing index, an unrun floor rule or no encoder for new text is a labelled `UNAVAILABLE`, never an empty answer; a modified pack stops start-up.
- Scenario history check (`stress/history_check.py`, `data/replay/market/shock_history.json`, 127 KB of quantiles and tails, no prices): equity (S&P 500, sector baskets, single names) and 10-year-yield shocks ranked against 1-, 5- and 21-session moves since 2014; credit-spread, PD and LGD shocks reported "not checkable" (no free history held). Examples: -8% S&P 500 in one session about 1 window in 1,600; the macro scenario's +100 bp parallel rate shock exceeds the worst 21-session change on record (+93 bp). The stress arithmetic, the scenario catalogue and every run id are unchanged.
- UI: `AnaloguesPanel` in the Evidence chapter (retrieved chip, the move after each past report as a signed percent plus sigma units, similarity, the VIX then, the group against the ordinary-day yardstick, an explicit "No reliable historical analogue found" state with the nearest matches in a collapsed "not precedent" disclosure, caveats and the hindsight note); `HistoryCheck` in the Stress page's assumptions drawer at the severity-scaled magnitudes actually applied. 12 new vitest tests (351 total).

### Freeze, docs and tests for Stage 8 (2026-10-05)
- `make freeze-check` flagged exactly 11 additions and **no changed file** (the trained models, the replay pack, every other config and the earlier evidence are byte-identical): `configs/evidence_v3.yaml`, `configs/retrieval.yaml`, the three analogue pack files, `data/replay/market/shock_history.json`, and the five new evidence JSONs. `make freeze-write` was run deliberately (now 77 files). The pre-registration's sha256 is still `99c0ff9b...`, the value recorded before any result existed; a unit test now fails if any evidence file was produced under a different pre-registration.
- Docs: `docs/FINANCE_THEORY.md` (theory, formulas, the ten-question assessment of each method, verified references), `docs/ANALOGUES.md`, addenda in `RISK_ASSESSMENT.md`, `ARCHITECTURE.md`, `FINAL_MODEL_REPORT.md`, `DEMO_SCRIPT.md`, README commands and CLAUDE.md. One reference I had written from memory (Diebold and Yilmaz) was removed because I had not looked it up.
- A numeric floor override lost its (0, 1) range check when the config gained the `rule` option; a test caught it.

### Validation run (2026-10-05) and what it caught
- First full run: unit passed (1m17s), e2e passed (12m), integration had 3 failures. (a) `test_demo_profile_has_no_engine_and_says_so` pins the exact `capabilities` dict, which gained `analogues` and `history_check`: a deliberate contract change, test updated (the shock history is real market history and applies to any profile, so the demo profile reports `history_check: true`, `analogues: false`). (b) Two event-model tests in `test_replay_api.py` saw the TF-IDF model id instead of `hybrid-event-v2`: **my own new test** pasted text into the shared session-scoped app; with no encoder installed the engine (by design, once, and labelled) switches to the TF-IDF event model, and that state leaked into other modules that share the container. The two tests pass in isolation; the paste test now uses its own module-scoped app, like the assessment tests. This is also a reminder that the served-model claim is a property of the process state, which is why `make smoke` checks it against a freshly started server.
- Browser check (real app, replay profile): the Event page's *Historical analogues* panel, the Stress page's assumptions drawer with the history check, and the Evidence page's *Outcome check* tab all render. The visual check found one honesty problem that unit tests had not: the aggregate card said "59 distinct past stories" while its statistics came from the 15-20 most similar (the Wilson interval, 2% to 47%, gave it away). The aggregate now carries `n_used` and the card says "statistics are based on N most similar of M distinct past stories". Also fixed: readings used a hyphen-minus where the UI uses a true minus.

**Final validation (2026-10-05, end of Stage 8).** `make lint` (ruff + tsc) clean. Backend: unit 1m21s (3 expected skips, as at baseline), integration 10m (all pass after the isolation fix), e2e 12m (all pass; the served-configuration and digest pins are unchanged). Frontend: 357 vitest tests (339 at the start of the stage), `npm run build` ok. `make freeze-check` passes (77 files, 5 models). `make smoke` passes on a freshly started real server, including `/analogues` and `/history-check`. Not done and stated: no live-model recording for prompt `extract-v6` (provider quota), so the optional LLM arm of the validity study did not run; nothing was committed (commits only on request), so the pre-registration's git history does not yet exist and the recorded sha256 is the interim proof.

## Stage 9: optional personal portfolios and portfolio-aware stress (2026-10-05)
Goal: turn "analyze an event and stress a generic synthetic book" into "analyze an event and understand how it affects *my* portfolio", **optional, with one click back to the default**. Models, `severity.yaml`, the scenario catalogue, the replay pack and every pinned digest untouched. Design and methodology: `docs/PORTFOLIOS.md`.

**What the investigation found (before any code).** The stress engine was already instrument-aware (beta, duration, PD/LGD, delta) and already returned per-factor and per-position attribution, so it was reused, not redesigned. Real constraints: (1) `Portfolio.content_hash()` hashes the whole model dump, so *any* new field would have changed `GOLDEN_RUN_ID`, the committed fixtures and the replay run ids; (2) only 34 issuers are nameable from text and sectors are exactly six strings compared by equality, so an unknown ticker can only be hit by sector/market shocks; (3) the engine widened credit spreads on *every* bond (wrong for Treasuries) and had no cash class; (4) the market context's `beta_market` is a two-factor partial slope, not the single-factor beta the `V x beta x s` market shock needs; (5) CORS allowed only GET/POST; the relevance cache was a single slot.

**Built.** `portfolio/` package (models, resolver + quick-text parser, atomic file store, exposure, exposure chain, comparison), `configs/portfolio.yaml`, `data/portfolio/instruments.json`, `make portfolio-betas` -> `data/replay/market/betas.json`; `StressService.run(portfolio=)`, `RelevanceService` per-portfolio (LRU of 8 indexes, relevance band, market-wide share = what a market shock can move); endpoints `/api/portfolios` (CRUD, duplicate, parse, validate, compare, exposure), `portfolio_id` on `/stress-test`, `/stress-runs`, `/signals`, `/signals/{id}/relevance`, `/portfolio/*`, `/stress-runs/{id}/exposure-chain`. UI: portfolio switcher (rail and mobile) with "Use default portfolio", Portfolios page, editor (quick text and detailed rows, live resolve, source chips), and on the Stress page the three-answer strip (severity / relevance / modeled impact), "Why is my portfolio exposed?", comparison and the history check inline. Selection is client state (localStorage, `?portfolio=` override) so nothing is selected by default.

**Methodology decisions** (the six questions, table in `docs/PORTFOLIOS.md`). Added: `CASH`, `OTHER`, bond `spread_sensitivity` (default omitted from serialisation, so the default book's hash, JSON and run ids are byte-identical; a test pins it), single-factor trailing betas. Rejected with reasons: convexity, volatility-regime shock scaling, invented sector transmission, region shocks.
- **Betas, first attempt and what changed.** I first used a fixed Blume adjustment (0.67 x OLS + 0.33). The data showed standard errors of about 0.1 against a cross-sectional spread of about 0.83, so the fixed weight was arbitrary (it pulled a precisely estimated -0.56 to -0.05). Switched to Vasicek shrinkage with the prior variance taken from the cross-section (barely moves precise estimates, shrinks noisy ones). The data also say XOM -0.53, CVX -0.47, KO -0.22: a one-year negative co-movement. A stress should not credit a stock with a gain from a market fall, so the beta *used* is clipped to [0, 3] and the basis string says so. The file keeps the unclipped values. This is an assumption, labelled, and the reason personal portfolios are visibly less sensitive to a market shock than the synthetic book (whose betas are random draws around 1.0-1.3).

**What broke / what the checks caught.**
- `test_fixtures` asserted the demo book spans `set(AssetClass)`; narrowed to the four wholesale classes (CASH/OTHER exist only for personal portfolios).
- First attempt at `GOLDEN_RUN_ID` safety was a plain new field: it would have moved the hash. Fixed with a wrap serializer that drops the field at its default; verified the replay portfolio hash is still `113e375df67648a6`.
- Visual check found a **pre-existing bug** unrelated to portfolios but distorting this feature: the what-if slider was initialised from the trained model's impact (which arrives first) and never followed the assessed severity (which arrives later), so a sector event with severity 8 was shown as "What-if severity 3" and the headline number was the milder what-if (-1.21% instead of -2.78%). The slider now follows the event's severity; a regression test fails without the fix.
- The same check showed cash topping the "largest issuers" list and the single-issuer concentration metric; cash is no longer an issuer.
- One existing test pinned the badge text "Scenario simulation, not a prediction"; I kept it and added a separate "What-if assumption, not the assessed severity" tag instead of rewriting verified text.

**Behaviour worth knowing (not hidden).** Scenario sector shocks are always adverse, so an oil-supply event is modeled as a loss for an energy-heavy book (-9.2% in the demo run), although such an event may help energy producers. This is the existing scenario assumption, now visible because personal books can be energy-heavy. The brief's "energy-import-sensitive exposure" example is therefore *not* implementable honestly: there is no transmission data. Listed under limitations in `docs/PORTFOLIOS.md`.

**End-to-end check (real replay server, 6 events x default + 3 personal portfolios).** Company held (Apple patent verdict): default relevance LOW 0.9%, personal HIGH 20%, chain "You hold Apple Inc.: 20.0%...". Company not held: "You do not hold ...". Sector event on a book with no Energy: relevance NONE, market shocks only. Macro (yield rise): rates step on the 25% Treasury sleeve (+114 bp, duration 17). Geopolitical (Hormuz): market-wide. Unresolved: relevance UNDETERMINED, only market shocks. Cash-only book: modeled change exactly zero, empty chain, "None of your holdings responds". Runs are deterministic (same portfolio, event, scenario => same run id); a request with no `portfolio_id` returns the identical default run as before.

**Freeze.** `configs/portfolio.yaml` and `data/replay/market/betas.json` fall in the freeze globs; `make freeze-write` run deliberately (79 files); nothing else changed.

## Stage 10: multi-scope event intelligence (2026-10-05)
Goal: turn "analyze a company headline" into "analyze any text": a company, an industry, a sector, a place, a macro theme, the market, or nothing that can be defended, with the event, its sources, its novelty, its spread, its contradictions and its life shown as separate, abstaining sections. **Additive**: trained models, `severity.yaml`, scenarios, the replay pack and every pinned digest untouched. Design, rules and limits: `docs/EVENT_INTELLIGENCE.md`.

**What the investigation found (before any code).** Much of the brief already existed in weaker form, so it was extended, not rebuilt: a four-level `ScopeLevel` (company / sector / market / unresolved), one `RiskEngine` door for live and pasted text, per-issuer star clustering, a count-based novelty *score*, a mean `coverage_velocity`, an unused `Evidence.contradicted_by`, a sentiment-sign `conflict_for`, and abstention for event, scope, impact, stress and analogues. Real constraints: (1) `output_digest` is the sha256 of every signal's full dump, so **any** new field on `RiskSignal`, `Evidence`, `SignalScope` or `SignalProvenance`, even a defaulted one, would move `GOLDEN_SERVED_DIGEST` and break the frozen replay, so nothing could be stored on a signal; the Stage 7/8 side-car pattern was the only safe seam. (2) The entity master has no industry level and only 34 entities; a level with no evidence must be omitted, not invented. (3) A cluster keeps full text only for its first report (the others keep headline, source, time, url, relation), so claim extraction on folded reports is headline-only. (4) Clusters never join across issuers and never form for unresolved text outside the live config.

**Built.** `src/eventshock/intelligence/` (`model`, `config`, `textutil`, `scope`, `grouping`, `evidence`, `novelty`, `velocity`, `claims`, `lifecycle`, `service`), `configs/intelligence.yaml` (one new config: every number a stated judgement prior), `GET /api/signals/{id}/intelligence?as_of=`, `intelligence` on `POST /api/analyze` plus optional `headline` and `url` on the request, `scope_type` / `scope_value` on the feed row and a `scope_type` filter, `capabilities.intelligence`. UI: `components/intelligence/*` (the Event Intelligence panel under the hero: twelve separate tiles, scope path, source-spread chart, reports table, contradiction view with both sides, lifecycle timeline, novelty comparison, affected view, downstream, a method drawer and an as-of selector), a compact summary on Analyze, a scope chip and finer-scope filters on the Feed.

**Methodology decisions.**
- **Side-car, not schema.** Everything is derived on demand and memoised; a purity test asserts no signal is touched and the digest still matches after intelligence is computed for all 2,330 signals.
- **URL is never fetched.** The brief allowed it "if the architecture supports it". The server makes no outbound call outside `ingestion/fetch.py`; fetching an arbitrary URL is an egress and SSRF risk. The url only attributes the outlet. A test patches the socket to prove no connection is attempted.
- **Replay is not rewritten into the engine.** Unification is proven by a parity test instead: whole clusters of replay records through `RiskEngine.ingest` and through `run_documents` give identical signals field for field (it passed; no divergence to report).
- **Independent source = a distinct outlet not carrying another's identical text.** First attempt counted rewrites (NEAR_DUPLICATE) as copies. A manual check (two pasted reports, one confirming and one denying a sale, from different outlets) showed a contradicting report from another outlet counted as 1 independent of 2. Rewrites by another outlet now count; syndication and exact copies still collapse. Consequence worth knowing: a wire story syndicated on twelve outlets is, correctly, one source (an Insufficient evidence tier).
- **Evidence strength and model confidence are never merged**: separate tiles, separate fields, a test asserts no "confidence" component sits in the strength rule.
- **Lifecycle is rules over explicit evidence.** RESOLVED needs an authoritative source or two independent outlets each carrying a resolution cue; silence only ever leads to STALE, and a later report revives it. A fall in volume is never read as resolution (tested).
- **Contradiction needs a claim, not a tone.** The older sentiment-sign check stays, relabelled "tone divergence, not a contradiction".
- Cue words were tightened before any result: bare `closes`, `opens`, `lifts`, `ends`, `surges`, `bars` and the nouns `outage` / `shutdown` were removed as too ambiguous.

**What broke / what the checks caught.**
- YAML 1.1 parsed the negator `no` as `false`, so the config failed to load; quoted.
- Velocity counted the first *bucket* as the starting point, so six sources over four hours gave 1.0/h instead of 1.25/h; growth is now counted from the first report.
- An escalation cue in the same report that confirmed an event was dropped (the confirmation check ran after the cue); order fixed, with a regression through the service test.
- A later authoritative report that contradicted an earlier non-authoritative one stayed CONFLICTED; it now settles it.
- A multi-region text (e.g. Russia and the Middle East) hit an assertion in the geography rule; several regions are now one GEOGRAPHY scope listing them.
- **A false positive in the real replay pack**: "Facebook and Instagram back online after sudden US outage" against "recover after brief Sunday outage" was reported CONFLICTED (a recovery, read as opposite poles, because the headline contained both). That produced three rules: a report that asserts both poles of an axis is a sequence not a stance; a cue inside a background clause ("after ...") asserts nothing; the nouns outage / shutdown are not cues. Re-run: 0 contradictions in 2,330 events (claims found in 52).
- The parity test's first sample (every ninth record) failed: a cluster's canonical changed when its earlier members were absent, and that text had no pinned embedding vector. The sample is now whole clusters.
- An existing Analyze test pinned the text "Set where and when it was published"; I restored it and added the headline/link fields as a separate disclosure.
- Running pasted-text checks against the real dev server appended to the developer's git-ignored `data/live/journal.jsonl` (that is the journal's job); the test suites use temp journals.

**Behaviour worth knowing (not hidden).** Over the 2,330 replay signals: scope COMPANY 1,182, UNRESOLVED 813, SECTOR 83, MACRO 70, GEOGRAPHY 64, MARKET 64, INDUSTRY 36, THEME 18 (the company and unresolved counts equal the pipeline's own mix because company and unresolved status are unchanged). Evidence tier: INSUFFICIENT 2,103, MODERATE 206, STRONG 19, WEAK 2 (most events have one independent source). Novelty: NEW 1,223, UNKNOWN 974 (untrusted clocks or no subject), RECURRING 78, UPDATE 49, CONTINUATION 6; recurrence is generous because replay events several weeks apart on one issuer with similar wording count after the 7-day gap rule. Velocity is stated for 178 events and abstains for the rest (single reports). 290 events have a replay-assigned clock and abstain on velocity, lifecycle and novelty. The grouping merged 105 events from 2-5 clusters; the thresholds are judgement priors and were not tuned on these, so I do not claim precision for them. Event grouping in a live session builds over the replay and the live overlay and is rebuilt when the live counter moves (about 0.4 s for the replay pack).

**End-to-end check (real replay server).** Pasted: an Exxon "confirms" and an Exxon "denies" a $4.2 billion refinery sale from two outlets an hour apart become one event with both sides shown (Conflicted, evidence capped, lifecycle held at Developing); a Middle East shipping headline resolves to THEME (trade and conflict) → GEOGRAPHY (Middle East) → MARKET; a rates headline resolves to MACRO; a text with no subject is UNRESOLVED with `company`, `sector`, `scope` abstentions and reasons.

**Freeze.** One addition in the freeze globs, `configs/intelligence.yaml`; `make freeze-write` run deliberately (80 files, no changed file).

**Final validation (2026-10-05, end of Stage 10).** `make lint` clean (ruff, tsc). Full backend suite passes (unit, integration, e2e; the served-configuration and digest pins are unchanged; 3 expected skips as before). Frontend: 408 vitest tests, `npm run build` ok. `make freeze-check` passes (80 files, 5 models). `make smoke` passes on a freshly started real server, including the new intelligence checks. Not done and stated: nothing was committed (commits only on request); grouping, novelty, lifecycle and evidence thresholds are unvalidated judgement priors; no gold set exists for event grouping or contradiction, so no precision claim is made for either.

## Stage 11: event to portfolio propagation and adjustable side-cars (2026-10-05) 

**Built.** `propagation/` (mapping graph, materiality lookup, deterministic scenario generation, reconciling attribution, concentration and overlaps), `adjust/` (whitelist, atomic overrides file, validation through the real strict models, rollback), `configs/propagation.yaml`, new endpoints and UI panels (Event page Stress chapter, Stress page, portfolio editor, one *Adjust assumptions* drawer). Additive engine edit: `ShockSpec.sector`. Design note: `docs/PORTFOLIO_PROPAGATION.md`.

**What broke / what the checks caught.** (1) A company's country was shown as an unreached target. (2) A government bond was "reached" by a credit-spread factor (the engine would not move it): reach now respects spread sensitivity and duration. (3) The Herfindahl flag was always on for four asset classes: the bar now scales with 1/n. (4) Risk-factor concentration flagged ~100% reach everywhere: now informational, never flagged. (5) Overlap clusters formed from event classes that merely imply a factor (RATES: 8 events, 99.7% of the book): overlaps now need the factor in the text. (6) The exposure chain keyed shocks by (factor, scope) and would have double counted two explicit-sector shocks: now keyed by sector too. (7) Seen in the browser: a small evidenced reach (8.8%) plus a large assumed reach (75.7%) gave CRITICAL: assumed reach can now lift the exposure row one step at most (`assumed_reach_limit`); the real replay numbers below pre-date this fix. (8) A `sed -i` pitfall on macOS silently skipped a chained heredoc once; caught by listing the directory.

**Replay measurements (2,330 signals, before fix 7).** Relevance: LOW 299, MEDIUM 1,153, HIGH 103, CRITICAL 18, NONE 62, UNDETERMINED 695. Scenario: AVAILABLE 25, soft-gate blocked 901, UNAVAILABLE 1,404. All 25 generated runs reconcile in every attribution table.

**Freeze.** One addition, `configs/propagation.yaml`; `make freeze-write` run deliberately (81 files, no changed file).

**Final validation (2026-10-06).** `make lint` clean (ruff, tsc). Full backend suite passes (unit, integration, e2e, including `tests/e2e/test_propagation_replay.py`; the served digest and `GOLDEN_RUN_ID` pins are unchanged; 3 expected skips). Frontend: 441 vitest tests, `npm run build` ok (the main chunk is now about 740 kB, which trips Vite's size warning). `make freeze-check` passes (81 files, 5 models). `make smoke` passes on a freshly started real server, including generate, run, reconcile, adjust and reset. The `assumed_reach_limit` fix (see 7 above) is in the code, tests and `docs/PORTFOLIO_PROPAGATION.md`; the replay counts above pre-date it. Not exercised by hand: saving an adjustment through the drawer in a browser (the API and the drawer's tests cover it). Nothing was committed.

## Stage 12: decision intelligence and external market intelligence (2026-10-06)

**Goal.** Close the decision loop on top of Stages 6–11 without touching a model, the severity score, the replay pack or any pinned digest: a live/replay risk monitor with event memory, watchlists, a scenario lab, reverse stress, structured "Why?" explanations, an executive "what should I care about" view, analyst feedback, an executive brief, and an external-market (Kalshi) observation side-car that never feeds the risk. Plan: `~/.claude/plans/…` (phases A–J). Decisions taken with the user before coding: the executive view is a new `/today` route; FX and commodity become *real* engine factors (additive, omitted-at-default); Kalshi in replay uses a captured real snapshot plus clearly labelled synthetic fixtures. Deliberate deviation from the pasted phase order: external markets are built before the brief (the brief has a market section); the brief is deterministic-template only (an LLM narrator is a documented seam, not built).

### Phase A: live risk monitor and event memory

**Built.** `src/eventshock/decision/` (shared labelling vocabulary `ObservationKind`/`ProvenanceRef`, the strict config `configs/decision.yaml`; every number a judgement prior) and `src/eventshock/monitor/`: `state.py` (an `EventState` = what EventShock believed about one event at one moment, read only from the grouping, assessment, intelligence, propagation and stress layers), `diff.py` (a pure `diff_states` with fixed order and named rules: NEW_EVENT, EVENT_UPDATED, EVENT_ESCALATED/DE_ESCALATED, EVIDENCE_STRENGTHENED/WEAKENED, CONFLICT_APPEARED/RESOLVED, PORTFOLIO_EXPOSURE_CHANGED, STRESS_CHANGED, LIFECYCLE_CHANGED), `memory.py` (every report of an event classified NEW_EVENT / CONTINUATION / UPDATE / ESCALATION / DE_ESCALATION / RESOLUTION by explicit rules, quoting the lifecycle cue), `store.py` (append-only change log deduplicated by `change_id`, last-state file, atomic writes), `service.py`. REPLAY is a pure function of the frozen signals and a fixed 12-hour clock (29 cycles over 2026-09-17..10-01; cycle 0 is the baseline); LIVE diffs the live overlay after every poll through an observer hook on `LiveService` (additive `on_applied`; a failing observer is logged, never raised into the poller) and persists under git-ignored `data/live/decision/`. API: `GET /api/monitor/{status,cycles,changes}`, `POST /api/monitor/refresh`, `GET /api/events/{id}/timeline` (an event id or any signal id of it). UI: `components/monitor/ChangesFeed.tsx` (mode chips, replay-clock scrubber, type filters, per-change evidence; mounted as a compact strip on the Feed) and `EventMemoryPanel.tsx` (under the intelligence panel on the Event page).

**What broke / what the checks caught.** (1) The first real replay cycle took 28 s: profiling showed `Portfolio.content_hash()` re-serialising 103 holdings on every memo lookup (8 s) and `EventIndex.priors` scanning all events per call (9 s). Fixed in the existing layers with behaviour-preserving caches (a per-object hash memo in `PropagationService`, a per-scope index in `EventIndex`); the Stage 10/11 suites and goldens are unchanged. A cold late cycle is now ~11 s (one-time per-signal work later cycles reuse), and the server warms the last two cycles in the background. (2) A float boundary: a share move of exactly 2 pp computed as 1.9999999999999996 pp and missed its threshold; deltas are rounded to 6 places before comparing. (3) The lead cluster of an event was chosen by severity only, so an event whose portfolio-relevant report was not the earliest of the top severity was never tracked on materiality; ties now go to the cluster that matters most to the book, then the earliest, then the id. (4) My own test assumed "nothing happens after the escalation": the lifecycle's 24-hour hold correctly eased the event to STABILIZING a cycle later, which is reported as EVENT_DE_ESCALATED. The test now asserts that.

**Behaviour worth knowing (not hidden).** In the frozen replay each report cluster's severity, scope and scenario are fixed; what moves between cycles is the number of reports and independent sources, lifecycle, evidence tier and conflicts, so most real replay changes are NEW_EVENT, EVENT_UPDATED, EVIDENCE_* and LIFECYCLE_CHANGED (including quiet events going STALE). Exposure and stress changes are proven by fixtures and appear mainly when a cluster joins an event or the portfolio or an adjustment changes; only 25 of 2,330 replay signals generate a scenario at all (Stage 11). Events whose report times the replay assigned (290 events, social posts) are counted and excluded: placing them on a timeline would invent an order. The tracking floor (severity ≥ 5 or materiality ≥ MEDIUM) and the cap (400 events per cycle) are reported on every response, never silent.

**Tests.** `tests/unit/test_monitor_diff.py` (thresholds, boundaries, idempotence, order), `test_monitor_memory.py`, `test_monitor_service.py` (REPLAY determinism, escalation with evidence, conflict, untracked, untrusted clock, LIVE new/update/escalation/conflict, idempotent polling, restart without duplicates, live off), `test_decision_architecture.py`, `tests/integration/test_monitor_api.py`, `tests/e2e/test_monitor_replay.py` (digest unchanged after a sweep, identical after a side-car rebuild), `web/src/components/monitor/monitor.test.tsx`.

### Phase B: watchlists

**Built.** `src/eventshock/watchlist/`: a domain model (`Watchlist`, `WatchItem` of kind COMPANY / SECTOR / INDUSTRY / GEOGRAPHY / EVENT_TYPE / RISK_THEME / PORTFOLIO_EXPOSURE), a git-ignored one-file-per-list atomic store (same pattern as the portfolio store: id regex against path traversal, damaged files skipped with a warning), a closed vocabulary (`vocabulary.py`, the same object validates the API and fills the UI pickers; a company must be an entity id or ticker in the entity master), matching (`match.py`) that reads the scope EventShock already resolved, and `WatchlistService` which shows, per item, the matching events with severity, lifecycle, novelty, velocity, evidence tier, conflict, portfolio relevance, modeled stress and recent changes, all read from the monitor's `EventState` (nothing re-inferred). Config: a `watchlist:` block in `configs/decision.yaml`. API: `GET/POST /api/watchlists`, `GET /api/watchlists/vocabulary`, `GET/PUT/DELETE /api/watchlists/{id}` (PUT is edit and enable/disable), `GET /api/watchlists/{id}/activity?mode&cycle&window`. UI: a *Watchlists and monitor* tab on the Portfolios page (the current risk monitor strip plus the lists), `WatchlistEditor`, `WatchlistActivityView`, and a *Watch this* control on the Event hero that offers only subjects EventShock resolved.

**Methodology decisions.** (1) A company item matches only an event with a signal whose company the entity resolver resolved to that entity: a text that merely names a company, or an UNRESOLVED event, never matches. (2) Sector/industry/geography items match a node of the resolved scope path; an UNRESOLVED or tied-sector event has none. (3) Free text is refused with a reason (422 listing every problem), so a subject EventShock cannot match cannot be saved. (4) A disabled list is kept and inspectable but matches nothing. (5) REPLAY activity at a cycle and LIVE activity are separate candidate sets (frozen replay events only vs events the live overlay holds); "new" means first seen after the previous window boundary, and the baseline cycle has nothing new. (6) Matching needs no cold intelligence build: candidates are chosen from the memoised scope, and only matched events are assessed (newest first, capped by `max_scan_events`, and the response says when it truncated).

**What broke / what the checks caught.** (1) A first test expected a later Exxon headline to be a second event; the grouping (correctly) folded it into the first one as the same issuer and class within the window. The test now uses a genuinely different story. (2) Tickers were not accepted for PORTFOLIO_EXPOSURE (only the entity id): the lookup table now maps value and ticker for every kind and never accepts the `top:N` template as a value. (3) LIVE mode first listed replay events as live matches; the candidate filter now separates the two channels.

**Tests.** `tests/unit/test_watchlist.py` (CRUD, persistence across a store restart, path traversal, limit, damaged file, the vocabulary refusing free text, company / sector / event-type / exposure matching, unresolved events never match, a name without a resolved entity never matches, disabled inert, determinism, new-in-window, before-an-event-exists), `tests/integration/test_watchlists_api.py`, `tests/e2e/test_watchlist_replay.py` (identical after a side-car rebuild, digest unchanged, no unresolved event under a company), `web/src/components/watchlist/watchlist.test.tsx`.

### Phase C: scenario lab on the existing engine (with real FX and oil factors)

**Decisions taken with the user.** FX and commodity become *real* engine factors (not proxies), additive and omitted-at-default so no existing hash moves. Exposure is **data on the position**, never a prior inside the engine: `PortfolioAsset.currency` (the currency a position is denominated in, when not the base) and `commodity_sensitivity` (an oil elasticity); a position that carries neither is not moved. `RiskFactor` gained `FX_PCT` and `COMMODITY_PCT` (and `LAB_FACTORS` names them); `ShockSpec` gained `currency` and `entity_id` (an ISSUER shock that names its issuer, so a scenario needs no signal); `AppliedShock`/`PositionShock` carry them; all five new fields are dropped from the JSON while unset (a `model_serializer` wrap, the Stage 9 `spread_sensitivity` pattern), so every catalog scenario, the default book's JSON and `Portfolio.content_hash()`, `GOLDEN_RUN_ID` and the served digest are byte-identical (pinned by `tests/unit/test_engine_lab_factors.py`). Foreign-currency cash is exposed to the exchange rate (the engine used to give cash dV = 0 for every shock; only an FX shock on a cash position held in that currency moves it now). Propagation's `engine_factor_map` and `modelled: NOT_MODELLED` for FX were left unchanged on purpose: Stage 11's outputs do not move; the lab passes its own two extra map entries to the unchanged attribution builder.

**Built.** `src/eventshock/lab/`: `models.py`, `build.py` (assumptions → engine shocks: bounds from `configs/decision.yaml: lab`, targets from vocabularies; a risk-factor shock maps to its engine factor or, for a proxy factor (inflation, geopolitical), to sector shocks = size × transmission-edge weight, each edge shown as an assumption), `exposure.py` (opt-in oil elasticity from sector *judgement priors*, applied to a copy of the book, off by default, always disclosed), `service.py`. `StressService.run_custom` runs shocks with no signal and no severity scaling (a NOT_APPLICABLE result, never a zero, when no position carries the exposure; the BASE case with no shock is the identity). Scenario types BASE / ASSESSED (the Stage 11 generated scenario, run by the very same `portfolio_stress`, kept apart and labelled EventShock's) / CUSTOM. `scenario_id = scn_lab_ + hash(portfolio, type, sorted engine shocks)`, so entry order does not matter and the same assumptions on the same book give the same id and result; `created_at` is the replay clock. Every user value is labelled **SCENARIO ASSUMPTION**; the result's own label is "SCENARIO SIMULATION — NOT A PREDICTION". `POST /api/scenarios`, `/scenarios/validate`, `/scenarios/compare` (2-3, side by side with an assumption diff), `GET /api/lab/options`. A saved personal portfolio's holding in another currency now carries its currency into the asset (the old "FX not modelled" warning now says the lab can shock it). UI: `components/lab/{ScenarioLab,ScenarioEditor,LabResultView,CompareView}.tsx`, on the Stress page (a disclosure) and a *Scenario lab* tab on Portfolios; reuses `AttributionPanel`, `Waterfall`, `HistoryCheckView`.

**What broke / what the checks caught.** (1) My first "reach" count said an equity-market shock reached 5 positions including a bond: the engine lists every chosen shock on a position even when the position has no sensitivity to it. Reach is now "the engine revalued the position by that factor" (a Treasury with spread sensitivity 0 correctly reports the spread shock as reaching nothing). (2) Two OpenAPI schema-name collisions (`CompareRequest`, `ValidationIssue` already existed in portfolio/adjust) silently renamed the existing TypeScript aliases; lab models got unique names (`LabCompareRequest`, `LabIssue`). (3) A first e2e test scanned every replay signal for an available scenario, which is minutes of work; it now pre-filters by assessed severity. (4) My own e2e test combined a sector shock and a geopolitical risk-factor shock that both set the Energy equity shock; the validator correctly refused it ("one value per shock") and the test now uses a different sector.

**Behaviour worth knowing (not hidden).** The default synthetic book has no foreign-currency positions and no measured oil elasticity, so an FX or oil shock on it returns NOT_APPLICABLE with the reason (the oil switch estimates an exposure from sector priors, labelled JUDGEMENT PRIOR). History check: equity and rates shocks rank against 2014-2026 moves; credit, default, oil and FX report "not checkable". The engine is first-order (no convexity, no second-round effects).

### Phase D: reverse stress

**Built.** `lab/reverse.py` + `configs/decision.yaml: reverse`. Method **BOUNDED_GRID_MINIMAX**, deterministic and explainable, every candidate valued by the unchanged engine (`StressService.quick_pnl`, which does not store runs): (1) probe each basket axis alone in its adverse direction; (2) keep up to 3 axes chosen by *marginal* loss on top of the ones already kept; (3) evaluate every grid point (7 levels per kept axis); (4) among the points that reach the target, take the one whose largest share of any bound is smallest once scaled to the target (so the loss is spread across the basket), then the smaller total share, then basket order; (5) bisection to scale it to the target within 0.02 pp. If every kept axis at 100% of its bound still falls short the answer is NOT_ACHIEVABLE with the largest loss the bounds allow and the binding axes; if no axis reaches the book it is NO_EXPOSURE. The reported combination is re-run in full by `LabService.run`, so the loss shown is a complete engine run and "Open in the lab" reproduces it exactly. Output: target, achieved, difference, required shocks (each a SCENARIO ASSUMPTION with its share of its limit), dominant drivers/holdings/sectors/risk factors from the engine attribution, every axis' bound, the search method and configuration, evaluation count, assumptions, limitations. `POST /api/reverse-stress`. UI: `components/lab/ReverseStress.tsx` (presets −2 / −5 / −10 and a custom loss, validated before sending; result card; bounds and method on demand; fork into the lab).

**What broke / what the checks caught.** (1) The first version kept the axes with the best *stand-alone* efficiency and answered "equity −12%" for everything: a sector shock replaces the market shock inside its sector (most specific wins), so sector axes looked efficient alone and added nothing beside the market axis. Selection is now by marginal loss, and the answer becomes a combination (e.g. equity −5.4% with rates +41 bp for a −5% loss on the test book; with the oil switch, equity + oil + rates). (2) My own draft ranked candidates by a convoluted tuple; rewritten with an explicit key and a `Found` result.

**Behaviour worth knowing (not hidden).** Many combinations reach the same loss: this reports the one that spreads the shocks most evenly, not the most likely. The basket and bounds are configured judgement. A ~90 evaluation search takes milliseconds on the replay book.

### Phase E: structured "Why?" explanations

**Built.** `src/eventshock/explain/`: `models.py` (an `Explanation` is a list of `Reason`s, each with a **closed code** (`SEVERITY`, `MATERIALITY`, `EXPOSURE_SHARE`, `LIFECYCLE`, `STRESS_DRIVER_SECTOR`, `REVERSE_BINDING`, …), a value, the **kind of statement** it is (`MODEL_OUTPUT` / `PRODUCT_RULE` / `SCENARIO_ASSUMPTION` / `HISTORICAL_OBSERVATION` / `EXTERNAL_MARKET_OBSERVATION`), the output it was read from and a provenance reference), `builders.py` (pure functions from existing structured outputs: the monitor's `EventState`, `EventIntelligence`, `PortfolioMateriality`, the propagation `AutoStressResult` and `StressAttribution`, `RiskChange`, `LabResult`, `ReverseStressResult`; no sentence is written from anything that is not a field), `service.py`. Subjects: PRIORITY (the ranking key's components, in the order the key reads them), VISIBILITY (scope match, watchlist hit, exposure match, severity, evidence, recent changes), CHANGE (rule, fields, supporting evidence), STRESS (the scenario's assumptions, the engine's decomposition by kind / market factor / risk factor / sector / issuer, and historical context for the shock sizes), LAB and REVERSE (assumptions and what each reached; method, shares of limits, unused axes, binding bounds). `GET /api/events/{id}/explanation?subject=&cycle=&change_id=`, `POST /api/scenarios/explanation`, `POST /api/reverse-stress/explanation`. `finish()` raises `ExplanationError` if a material output has no reason (so an empty explanation is a bug, never a blank box). Severity and the event class are labelled MODEL_OUTPUT (and say "a triage level, not outcome-calibrated"); counts, tiers, lifecycle, materiality and the engine's arithmetic are PRODUCT_RULE; every shock size is SCENARIO_ASSUMPTION; the history check is HISTORICAL_OBSERVATION ("a historical frequency, not a probability"). UI: `components/explain/{ReasonList,WhyDrawer,InlineWhy}.tsx`: reasons grouped by kind with their own word and badge; drawers keyed `?open=why-priority|why-visibility|why-stress`, fetched only while open; on the Event page (priority, visibility, stress), the Stress page, and inline on every lab and reverse-stress result.

**What broke / what the checks caught.** (1) A pinned test of the full `capabilities` dict failed as soon as the first new flag existed; it now pins the pre-existing keys exactly and asserts the demo profile serves none of the new side-cars. (2) The watchlist matcher had to be split so the same rules answer both "which events match this item" and "which items match this event" (for "why am I seeing this?"); the existing watchlist tests are the regression guard.

**Behaviour worth knowing (not hidden).** "Priority" is not a new score: it is the deterministic ordering the executive view uses (materiality tier, severity, size of the change, recency, id) and the explanation lists those components. The portfolio-materiality mapping is an assumption-laden lookup and says so in its own reasons.

### Phase F: "What should I care about right now?" (the executive view, `/today`)

**Built.** `monitor/digest.py` (`DigestService`) over the monitor's own changes and states, plus `GET /api/monitor/digest?mode&cycle&window`. Eight sections in config order (`configs/decision.yaml: digest.sections`): top new risks, escalations, largest changes in portfolio exposure, largest changes in modeled stress, important evidence changes, major conflicts, concentration changes (independent events that newly share a risk factor and the same holdings, from the Stage 11 overlap analyzer run over the monitor's states at the cycle and at the start of the window; new `PropagationService.overlaps_of`), and watchlist activity (`WatchlistService.digest_summaries`). **Nothing is scored.** The order is one documented lexicographic key (materiality tier, then severity, then the size of the change the section is about, then recency, then the event id), every card carries its key as five named parts, and the response says so; a test asserts no field with "score" or "importance" exists. A card drills down, in order, event → evidence → scope → portfolio exposure → propagation → stress → attribution as links into the *existing* Event and Stress pages (no new pages). Sections are capped (5) with the true total beside them. UI: a new first nav entry **Today** (`pages/TodayPage.tsx`; `components/digest/{DigestCard,StoryChain}.tsx`, `components/monitor/ReplayClock.tsx`), a link from the Feed header, mode chips and the replay clock, "Why is this here, in this order?" on every card (key + full structured reasons), and a collapsed *How it fits together* strip that walks information → event understanding → scope → clustering → evidence → novelty/velocity → conflict → lifecycle → impact → portfolio materiality → propagation → scenario → stress → attribution → monitoring → decision brief.

**What broke / what the checks caught.** (1) The first real cold digest took 29 s (it needs the states of the window's cycles plus the window start for the overlap diff); the server now warms the last six cycles in the background (a failure there is logged and the first request simply computes). (2) The concentration section on the real replay is dominated by market-wide factors ("Equity market level: 71 events now share it"): that is what the Stage 11 analyzer reports for events that share a market factor, shown as is and ranked by event count then shared share; it is a known weak signal, not a defect I hid. (3) A unit test with six cards failed because of the section cap of five; the test now uses a wider cap and the cap is tested on its own.

**Behaviour worth knowing (not hidden).** In the frozen replay exposure and stress changes are rare (a cluster's severity and scenario are fixed), so those two sections are mostly empty there and say "Nothing in this section for this window"; they are filled by fixtures in tests and by live changes. LIVE says the feed is off, and offers the replay.

### Phase G: analyst feedback

**Built.** `src/eventshock/feedback/` (`models.py`, an append-only JSONL log in git-ignored `data/live/decision/feedback/`, `stats.py`, `service.py`) and `POST /api/feedback`, `GET /api/feedback?event_id=`, `GET /api/feedback/statistics`. A record carries `feedback_id`, `event_id` (an event id or any signal id of it, resolved to the event; an unknown event is refused, never recorded), analyst id (body, else `X-Analyst-Id`, else `anonymous`), type, value, optional comment (capped), timestamp (the replay clock), and the portfolio and cycle in view. Types and answers are paired and validated: RELEVANCE = relevant / partially relevant / irrelevant; SCOPE and EVENT = correct / incorrect. Statistics: volume, relevance agreement (share relevant, and at least partly relevant), scope agreement, event agreement, and **unresolved feedback** (event/type pairs where some analyst's *latest* answer is negative, and where analysts disagree). Every response is labelled "ANALYST FEEDBACK — not ground truth, and not used to train or change any model", and the statistics say EventShock does not learn from it. UI: `FeedbackBar` (relevance, scope, event, comment; only the answers given are sent) on the Event page and on every digest card, and an *Analyst feedback* tab on the Evidence page (shown where the capability is).

**What broke / what the checks caught.** (1) **A real regression, found by the "feedback changes nothing that is served" test.** `GET /signals/{id}/propagation` returned a different body after the monitor had run: Stage 11's `existing_run_id` reports "a run of the generated scenario already made", and the monitor's state builder was creating (and storing) stress runs for every tracked event, so a Stage 11 field now depended on whether a background warm-up had happened. Derived views must not change what exists. Fix: `StressService.run_scenario(..., store=False)` and `PropagationService.portfolio_stress(..., store=False)`; the monitor, the explanation service and the lab pass `store=False`, lab custom runs are no longer stored with event runs (the lab memoises them), and `tests/e2e/test_monitor_replay.py::test_derived_views_never_change_which_stress_runs_exist` pins it. (2) The unpicking of a feedback answer left a key set to undefined and kept the Send button enabled; it now counts defined answers. (3) The pinned Evidence-page tab list failed on the new tab; the tab is added only where the capability is.

**Behaviour worth knowing (not hidden).** Feedback is self-selected, so agreement shares are not accuracy; feedback never touches a model or any served output (the API test compares eight served endpoints before and after three submissions, and the e2e test checks the pinned digest and the configuration).

### Phase H: external market intelligence (Kalshi) as a derived side-car

**Built.** `src/eventshock/markets/` (`config`, `models`, `provider`, `kalshi`, `match`, `interpret`, `service`) + `configs/external_markets.yaml` (judgement priors) + `ingestion/kalshi_capture.py` (the only network code). A provider abstraction (`MarketProvider` Protocol; `ExternalMarketObservation` with category PREDICTION_MARKET; other categories are named, none built). Three providers: the live `KalshiProvider` (opt-in `EVENTSHOCK_MARKETS=live`, keyless, rate-limited, parses the current `trade-api/v2` shape: dollar strings, fixed-point sizes, `active`/`finalized`; a changed shape degrades to UNAVAILABLE, never a guessed number), a hash-pinned **captured snapshot** (`make kalshi-snapshot`, `data/external/kalshi_snapshot.json` + manifest, 49 markets; modified file = `ConfigError`) which is the default, and a **synthetic fixture** (`make market-fixtures`, `EVENTSHOCK_MARKETS=fixture`, every row labelled SYNTHETIC; the tests' default). Replay uses only observations at or before the moment (no look-ahead; the previous observation is 24 h earlier). The event reaches a market only through a curated theme (FED_POLICY, US_INFLATION, US_LABOUR, US_TRADE_POLICY, US_SOVEREIGN_CREDIT) and explicit gates: EVENT_CLASS, SCOPE, SUBJECT (strong = a scope theme or two phrases), GEOGRAPHY (a stated conflicting place blocks; no stated place does not); then OPEN, HORIZON, FRESH on the market. Status MATCHED / LOW_CONFIDENCE_MATCH / NO_MATCH / INSUFFICIENT_DATA with every gate listed. Interpretation (MARKET_REPRICED / ALIGNED / DIVERGENT / LOW_INFORMATION) is descriptive and never says a market "confirms" anything; it is never an input to severity, impact, mapping, stress or reverse stress (architecture test + a replay test that core outputs and the digest are identical with the provider off, failing and on). API: `GET /api/events/{id}/external-markets`, `/market-timeline` (source event / EventShock assessment / external market observation / scenario assumption kept as separate kinds), `/analogues` (alias of the signal endpoint), and a MARKET explanation subject. UI: `ExternalMarketCard` ("External market view", the EXTERNAL MARKET OBSERVATION label, a gates disclosure, the merged timeline, "Why this market?") in the Event page's Evidence chapter beside the historical analogues, and a four-way legend.

**What broke / what the checks caught.** (1) A thin quote (8 cents wide) was treated as a price; `max_spread` is now 0.05 and the snapshot was re-captured under it. (2) Probability moves of exactly 2 pp / 10 pp missed their thresholds on float noise; deltas are rounded to 6 places. (3) The first service tests all failed because the helper's replay clock sat 40 days after the event, so the fixture's observations were stale; the helper now puts the clock 12 h after the latest report. (4) `Kalshi` docs were unreachable (ECONNRESET); the shape was verified from live responses instead, and the capture needs retries (the first capture took ~6 minutes).

**Behaviour worth knowing (not hidden).** The geography gate is conservative: a US tariff headline that names only China resolves to region CN, fails the US theme's geography gate and is NO_MATCH, rather than a guess. The captured snapshot reflects the capture date (2026-10-05), so many replay events honestly show NO_MATCH / INSUFFICIENT_DATA; the nine required cases are proven on the synthetic fixture and labelled as such. The theme-to-series mapping and every threshold are unvalidated priors.

### Phase I: executive risk brief

**Built.** `src/eventshock/brief/` (`models`, `builder`, `service`) and `GET /api/events/{id}/brief?portfolio_id=&cycle=&format=json|md`. Sixteen sections in a fixed order (executive summary, what happened, current status, why it matters, evidence, conflicts, affected entities / sectors, portfolio exposure, propagation, stress, top drivers, historical context, external market view, assumptions, uncertainty, what to monitor). **Template only, no language model**: every sentence is a template over structured fields (the event state, event intelligence, materiality, the mapping graph, the stress run and its attribution, analogues, the external-market view, event memory) and carries the **kind** of statement it is (source report / EventShock assessment / external market observation / scenario assumption / historical observation / product rule) and a list of **source ids** that resolve to a `sources` registry with the endpoint where the same structured output can be read. A statement with no resolvable source, or a section with no statement, raises `BriefError` (a 500, never a brief with an unsupported claim). Absent inputs print fixed sentences ("No relevant external prediction market identified.", "External market data unavailable.", "No reliable historical analogue found.", "No stress scenario was generated for this event.", "SCENARIO UNAVAILABLE: …"); nothing is invented. The "what to monitor" section is rule-driven (M1–M5, each rule named). Markdown is deterministic (same brief, same bytes). The service uses `store=False` for the stress run and a failing side-car becomes a labelled gap in its section. UI: an *Executive brief* button on the Event page and on every digest card opens a drawer (`?open=brief`; sections, kind words, numbered sources, *Copy as Markdown*, *Print*).

**What broke / what the checks caught.** (1) The first rendered brief read "engine by the stress engine" for a risk factor and listed "portfolio stress: unavailable, not requested" under uncertainty although the brief itself runs the stress; both wordings were fixed (the abstention is dropped when the run happened). (2) A full vitest run once timed out `Portfolio Stress > keeps the audit trail one click away` (25 s) under load; it passes alone and on the next two full runs, so it is a load-sensitive test, not a regression; noted rather than hidden.

**Behaviour worth knowing (not hidden).** The brief has no narrative generation: it is a structured reading, and an LLM-narrator seam is deliberately not built (the provider's 30-call cap, no recorded prompt, and the grounding burden for 16 sections). The market statements appear only in their own section and in monitoring rule M5; a replay test asserts a failing provider changes nothing else.

### Phase J: integration and quality gate (2026-10-06)

**Done.** `.env.example` documents `EVENTSHOCK_DECISION_STORE_PATH` and the four `EVENTSHOCK_MARKETS` modes; `docs/DECISION_INTELLIGENCE.md`, `docs/EXTERNAL_MARKETS.md`, the Stage 12 paragraph in `CLAUDE.md` and a Stage 12 addendum in `docs/DEMO_SCRIPT.md`; `scripts/smoke_e2e.py` now drives the monitor, digest, timeline, explanations (incl. MARKET), external markets, market timeline, brief (JSON + Markdown), watchlist CRUD, scenario lab run and compare, reverse stress and feedback against the real server (and redirects the decision store to a temp dir). **One deliberate `make freeze-write`**: `docs/freeze_manifest.json` gained exactly two lines (`configs/decision.yaml`, `configs/external_markets.yaml`); nothing else in the manifest moved, so no model, replay-pack, evidence or earlier-config hash changed.

**Gate results (real output).** `make lint` (ruff on `src tests scripts` + `tsc --noEmit`) passes; `make types` regenerated the OpenAPI schema and `schema.d.ts`; `make build` passes; full backend `pytest` passed except `test_freeze_check_passes`, which failed *only* because of the two new configs and passes after the freeze write; vitest 545 passed; `make freeze-check` passed (83 files, 5 models, snapshot `replay-2026-09-30-v1`); `make smoke` passed. The digest `70478b2d…`, the golden run id and the Stage 11 propagation bytes are asserted unchanged by the e2e tests (monitor, explain, markets, brief, derived-views-never-store-runs).

**What broke / what the checks caught.** (1) `make lint` reported 1,109 findings, almost all E501 in the new side-car packages; the repo's convention is a per-file E501 ignore for dense, doc-heavy modules, so the new packages were added to `pyproject.toml` (the real findings, 23 import-order and a few small ones, were fixed). (2) `ruff --fix` rewrote a *committed* research script (`experiments/embeddings/confirm_event.py`) because the repo-wide check includes it; it was restored from git, since `make lint` only checks `src tests scripts`. (3) A full vitest run once timed out the pre-existing `Portfolio Stress > keeps the audit trail one click away` test under load (passes alone and on the next full run).

**Not done / not verified (stated plainly).** (a) **No browser verification of the UI**: the in-app browser refused to navigate to the local server (and the dev server did not stay up under the preview tool), so the Today page, brief drawer, market card, lab and reverse-stress UI, light/dark and mobile layouts are verified by 545 component and page tests and by the real-server smoke test, **not by eye**; a manual pass is still needed. (b) `scripts/screenshots.mjs` was not extended for the new pages. (c) Live Kalshi was exercised only through the captured snapshot and an injected-transport adapter test, never against the network in the tests. (d) The LLM narrator for the brief, a learned relevance model, and propagation of FX/oil remain deferred.

## Stage 13: model and stress-engine improvements (2026-10-07)

Scope agreed with the user: the NLP models and the Module B stress engine, with deliberate model/config changes allowed (journalled, `make freeze-write`). Impact was reviewed and **not** changed (its skill is calendar plus volatility regime; data-limited).

### A1: sentiment v2 (`tfidf-lr-v2`)

**Built.** `configs/sentiment_model_v2.yaml` (class-balanced grid, `selection_rule: valid_macro_f1`), `make train-sentiment-v2`, `served_model_dir` in `configs/sentiment_model.yaml` (v1 stays the reference in `model_dir`), a new selection rule in `pipeline/config.py` / `modeling/sentiment_train.py` (v1's rule is unchanged and still the default), and `ImpactModelEnricher(impact_sentiment_model=…)` so the impact stage keeps reading v1's sentiment output.

**Result (measured, `models/sentiment/tfidf-lr-v2/model_card.json`).** PhraseBank macro-F1 0.466 → 0.525 (CI [0.508, 0.541], outside v1's), negative recall 0.277 → 0.497; both gold sets improve in the point estimate but the intervals overlap v1's; in domain macro-F1 equal within noise, accuracy −1.4 points. Out-of-domain ECE and positive recall remain weak. Full table: `docs/SENTIMENT_MODEL.md` ("v2").

**What the checks caught / decisions.** (1) The v2 selection rule was fixed *after* v1's out-of-domain results were known, so it is a disclosed choice, not a pre-registered test; no numeric in-domain tolerance was written beforehand. (2) Serving v2 changes every signal's sentiment, so the pinned served digest moved (`70478b2d…` → `078a70ae…`) and 24 e2e/integration tests that pin it failed, as expected. Before re-pinning, the replay was run with both models: event, scope and every model-scored impact were identical (parity wiring works); only sentiment and the 237 placeholder impacts that read tone changed. (3) The old "no pre-existing field changed" test could no longer hold on the v2 run, so it was replaced by a test that points the same code at the v1 reference and requires the old served digest and the Stage-5 legacy digest back, plus a test that only sentiment and the placeholder impact moved. (4) `make freeze-write` re-run (v2 artifact, two configs; the manifest now lists v2).

### B: stress-engine mechanics, Wholesale Book v2, multi-factor scenarios

**Built (all opt-in per position, omitted from the JSON while unset, so `Portfolio.content_hash()`, the default book and `GOLDEN_RUN_ID` are unchanged).** `PortfolioAsset` gained `convexity`, `maturity_years`, `spread_passthrough`, `gamma`, `counterparty_pd`/`counterparty_lgd`, and descriptive `rating`/`spread_bp` (validated per asset class). `stress/engine.py`: bond convexity (`+0.5·C·dy²`, each factor gets its own share of the cross term so the parts sum exactly), a hazard-rate link from a credit-spread shock to loan PD (credit triangle), derivative gamma and a CVA term (exposure effect attributed to EQUITY, the counterparty PD effect to PD_MULTIPLIER, so no new risk factor was needed). `portfolio/book_v2.py` builds Wholesale Book v2 from the profile's default book (seeded; ratings are internal PD buckets read off the book's own loan PDs, not agency ratings); `PortfolioService` serves it as a read-only `PRESET` (`GET /api/portfolios/presets`, accepted as `portfolio_id` everywhere; deliberately not in the normal list because the UI treats every non-DEFAULT item as the user's). `configs/scenarios_multifactor.yaml` adds four FX + oil + rates + spread + equity + credit scenarios, served by id and never an event class's default.

**What broke / what the checks caught.** (1) A pass-through of 0.0 produced float noise (−7e-12) and a spurious CREDIT_SPREAD attribution; a zero pass-through now short-circuits. (2) **A real latent bug, found by the first multi-factor API test:** the event-driven path in `StressService` built `AppliedShock` without `currency`/`entity_id`, so a catalog FX shock named no currency, and `asset.currency != shock.currency` is `None != None` = False, so *every base-currency position took the FX shock* (the default book lost ~$1.75M on Nike alone in the oil scenario). It never bit before because no catalog scenario had an FX shock; the lab path copied the currency. Fixed in the service (currency/entity copied) and defensively in `select_shocks` (a shock that names no currency matches nothing); regression tests in `test_engine_stage13.py` and `test_multifactor_scenarios_api.py`. (3) The Book v2 API test first picked a signal that did not trigger the stress test; tests now pick the highest-severity company event with `force`.

**Measured (illustrative, one run each, not validation).** Highest-severity company event, `scn_market_drawdown`: default book −6.077% (−$52.3M); Book v2 −6.120%, with credit-spread losses −$6.7M → −$10.6M (the loan link) and equity −$45.5M → −$45.1M (oil and FX offsets). Highest market event, `scn_credit_funding_stress`: −1.515% vs −1.730%.

**Not done / dropped.** The planned Herfindahl concentration report was dropped: Stage 11 already ships a concentration view (issuer, sector, industry, geography, asset class, risk factor, overlaps). Curve twist and liquidity haircuts were not built (they would need new risk factors and UI). Book v2 is not offered in the UI selector.

## Stage 14: judge-first UI redesign, "Wire → Ledger" (2026-10-08)

Scope agreed with the user: the frontend only. No backend, API contract, model, config, replay pack or pinned digest was touched; every number on screen comes from an existing endpoint. A design canvas (Desk light/dark, Stress Lab, Event story, system sheet) was published first as the visual target, then implemented in `web/`.

**Why.** The UI read as generic: every block was the same flat bordered box with equal weight, one "equal columns + top rule + eyebrow" pattern repeated six times, tiny icons only in nav/tags, rows of identical grey drawer buttons, and key features (scenario choice, lab, adjust, brief) behind `<details>` links. A judge had to be told where to look.

**Built.**
- **Design system** (`web/src/styles/tokens.css`, re-stamped): warm bone paper / warm graphite dark, one ultramarine accent that is also "the wire", severity/sentiment/P&L ramps kept semantic. Three type voices mapped to provenance: Newsreader (serif, roman only) = what was *reported*, IBM Plex Mono = what was *computed*, IBM Plex Sans = the interface (`@fontsource-variable/space-grotesk` swapped for `@fontsource-variable/newsreader`, the only dependency change). New tokens (`band`, `wire`, `wire-dim`, `hatch`, `shadow`, `--shadow-1/2`), each in a WCAG pair in `tokens.test.ts` for both themes.
- **Shell**: an N13 top bar (grouped nav Desk · Today · Analyze | Event · Stress Lab · Portfolios | Evidence) plus a context strip that always says which portfolio, which data/clock and how many assumptions are adjusted. **⌘K / "/" palette** (`components/CommandPalette.tsx`): every page, the current page's explanation drawers, every event, theme.
- **Desk** (`/`, was Risk Feed): the incoming wire (`components/desk/EventStream.tsx`, J/K, type filter), the selected event in serif, and the **signal trace** (`components/trace/SignalTrace.tsx`): six stations on one wire (what happened → what the AI read → how severe → scenario → what it reaches → portfolio impact), each from a read-only endpoint, each with one action, each with an explicit "unavailable" state; plus **Why trust it** (`components/desk/TrustStrip.tsx`). The full signal table and the pipeline counts stay below.
- **Event page**: the chain redrawn as the same wire with station icons and the intelligence endpoint's stress preview; inspect buttons that say what they open; Event intelligence as four question groups instead of twelve equal cards.
- **Stress Lab** (was Portfolio Stress): visible scenario cards (`components/portfolio/ScenarioRail.tsx`; the event's own one marked, multi-factor ones labelled, a click runs it) and the **value bridge** (`components/portfolio/ValueBridge.tsx`): book by asset class → shocks applied → where it lands → largest positions → after, with linked hover; it refuses to draw a breakdown that does not reconcile to the reported change within a cent.
- **Icon system** (`components/icons.tsx`, `components/Glyph.tsx`): station, risk-factor (equity, rates, spread, PD, LGD, FX, oil), asset-class and evidence glyphs. Event types stay the model's eight classes: FX, oil and supply shocks appear through risk factors and the multi-factor scenarios, never as invented categories.

**What broke / decisions.**
1. **The guided demo's hero no longer completes the chain.** Under the served assessment, Nike's earnings preview (`sig_90ee2542ae`) scores severity 2: its scenario is unavailable and nothing reaches the book, so a Desk opening on it showed a chain that stops. The Desk now opens on a named real signal whose chain completes (Strait of Hormuz, `sig_8f79c8bbd6`: severity 8, generated flight-to-safety scenario, critical materiality, −$37.3M / −4.33 %), with a rule-based fallback (`pickDeskDefault` in `lib/featured.ts`) and its single source shown as *insufficient evidence*. Nike stays reachable and is now the example of a chain that stops honestly.
2. Headlines and amounts now appear in two places (wire + table, bridge + figures), so five existing tests that used `getByText` on them were scoped to their region or switched to `getAllByText`; the outage case showed two identical error boxes and now shows one.
3. A scripted regrouping of the intelligence tiles failed on a one-line JSX element (nothing was written) and was redone by rewriting the function; a mid-edit `Brief` type/icon name clash broke hot reload once.
4. The sticky top bar changed height on narrow screens, so sticky elements (the chain rail, the wire) now read a `--topbar-h` measured by a `ResizeObserver`; at 1024 px the nav was clipped until it moved to its own row below `lg` and the ⌘K pill collapsed to an icon below `xl`.

**Verified.** `npm run typecheck`; `npx vitest run`: 580 tests in 32 files (9 new in `components/trace/trace.test.tsx`: trace stations and unavailable states, wire selection/J/K/filter, palette ⌘K navigation and drawer opening, bridge reconciliation, scenario cards); `npm run build`; `make smoke` passed. By eye in the in-app browser on the replay server: Desk, Event, Stress Lab (including a scenario switch to the oil supply shock: −$32.5M / −3.78 %), Today, Evidence, the palette, light and dark, 1440×900, 1024×768 and 390×844 (no horizontal scroll). Screenshots regenerated (`HERO=sig_8f79c8bbd6`).

**Not done / not verified.** The Analyze page's *Analyze* button was not pressed in the browser: the running server had the language-model reader enabled, so it would have sent text to an external provider (the result view is covered by the existing tests). The production bundle is 873 kB minified and Vite warns about chunk size; no code splitting was added.

## Stage 15: live switch and the missing demo features (2026-10-08)

Plan (approved): a clear Live ON/OFF switch in the UI, then a committed simulated-live capture, a second live source (EDGAR 8-K Atom), an exposure heatmap, a contagion map and an analyst review queue. Audit of the 12 candidate features: seven already exist (alert prioritisation, narrative timeline, what-if lab, additive impact attribution, cross-source contradiction, reverse stress, historical analogues), three are partial (heatmap, contagion map, review queue), and the RAG chatbot and autonomous agents stay out (excluded by the architecture; nothing generative reads text here).

### Task 1 (2026-10-08): runtime Live switch
**Why.** Live was fixed at server start (`EVENTSHOCK_LIVE=1`); the UI could only show it. A judge needs one visible, honest control.

**Built.**
- `LiveService.set_state(enabled, kind)` + `PUT /api/live/state`. `LiveService` is now always built in the replay profile with a source factory and `source_choices` (GDELT; simulated capture, unavailable with its reason while no capture file exists). Off keeps every signal already ingested and starts no new request; a result that arrives after the switch was turned off is dropped. A source that cannot start leaves the feed OFF and returns 409 with the reason. OFF at every start (not persisted), so the offline default and "no outbound call unless explicitly enabled" hold: the click is the explicit enablement.
- The poll loop now lives for the whole process and idles (one tick a second, no request) while off or after a capture finished, so a finished capture can be restarted from the switch. Switching to a capture extends the store's retention (as start-up capture mode already did); switching back restores it.
- UI: `components/live/LiveToggle.tsx`, a `role="switch"` in the context strip (every page) with a status dot and a popover (source choice, last/next poll, Poll now, consent line), plus a ⌘K entry. It shows what the server reports, never an optimistic state; on a refusal it stays off and shows the reason.

**What broke / decisions.**
1. Wiring only built a source at start-up in three places (`main.py` poller, the monitor's `on_applied` hook, `deps` live-status lambda): with the feed off at start the monitor observer would never have been installed, so turning live on later would have updated signals but not the monitor/digest. The hook is now installed whenever a live service exists.
2. The existing loop test assumed `run()` returns when a capture is exhausted; it now stays alive by design, so the test waits for the last batch and then stops it (deliberate contract change).
3. The popover first ran off the right edge (anchored to its own summary); it is now anchored to the context strip (checked at 1024 and 375 px, and in dark).
4. Deferred on purpose: "Clear live signals". It needs the engine's clustering window, the store, the journal and the monitor's live state reset together; a half-clear would make the engine skip re-ingested documents as duplicates. Not needed for the switch.

**Verified.** `ruff` + `tsc`; unit tests for the switch (no request while off, on/off idempotent, signals kept on off, unavailable/failing source stays off with the reason, in-flight result dropped, capture restart and retention, loop idles then polls when switched on); integration test of `PUT /live/state` on the real replay app; 5 component tests; `npx vitest run` 587 passed; in the Browser pane the switch went OFF → ON (server reported `enabled`, source `gdelt`, `IDLE`, capability `live_enabled` true) → OFF (`OFF`, capability false), and the popover stayed on screen at 375 px and in dark.

**Not done / not verified.** The simulated-live choice is selectable only once a capture file exists (next task commits one). The GDELT poll's success path against the real API was still not observed: the switch was turned on and off again within seconds.

### Task 2 (2026-10-08): UI re-skin, sidebar + top bar, "Harbour" palette, Inter + Plex Mono
**Why.** The Stage 14 look (warm paper, serif reported text, one top bar plus a context strip) was replaced at the user's request by a SaaS finance-workstation frame modelled on a reference they supplied: a left sidebar and a top bar on a navy→blue chrome, white rounded cards on a pale blue canvas, navy primary buttons, green/red outlined actions, a pink brand secondary and a navy dark mode. Frontend only: no API, model, config or digest change; routes, nav items (`lib/nav.ts`) and every page's content are unchanged.

**Built.**
- **Tokens** (`styles/tokens.css`): same token names, new values (so ~113 files re-skinned without edits), plus `chrome-*` (gradient stops, ink, muted, active pill, line, hover), `pink`/`pink-dim`, `--radius-xl`, `--gradient-chrome[-bar]`. Every new colour has a dark twin; `tokens.test.ts` gained nine contrast pairs (chrome text ≥ 7 / 4.5 on both gradient ends, selected item, pink). Headings are Inter (new dependency `@fontsource-variable/inter`), computed figures stay IBM Plex Mono; Newsreader and IBM Plex Sans were removed. Type scale trimmed (`text-3xl` 2.5→1.875 rem, hero sizes lowered); `.eyebrow` is now an uppercase overline.
- **Shell** (`components/Shell.tsx`): sticky sidebar (logo, nav in three labelled groups, data-mode badge, collapse), top bar (breadcrumb, ⌘K, portfolio, Live, Adjust, theme) in one row that wraps on narrow screens, replacing the old context strip. ≥1280 px expanded, below that an icon rail by default, below 1024 px an off-canvas drawer (hamburger, scrim, Escape, route change, `inert` content). The collapse choice is stored in `localStorage` inside try/catch. Existing components (`PortfolioSwitcher`, `LiveToggle`, `ThemeSwitch`, `PalettePill`) keep their markup and are restyled by scoped CSS. `.btn-pos` / `.btn-neg` added and used for the watchlist delete confirmation.
- Tests: `components/Shell.test.tsx` (nav gating and groups, active page, drawer open/close paths, collapse + persistence + blocked storage).

**What broke / decisions.**
1. The sidebar takes 4.5-15 rem from every page, so viewport breakpoints written for the old full-width layout fire too early: the six-station signal trace wrapped words ("Geopolitic / al") at 1440 px. The trace now answers to its own width with a container query (`.trace`: 3 columns ≥ 40 rem, 6 ≥ 56 rem). Other multi-column layouts still use viewport breakpoints; they were checked by eye at 1440, 1024 and 390 px (Desk, Event, Stress Lab, Analyze, Evidence) but not every page.
2. First version of the sidebar "what is real here" note was squeezed into a 120 px column (a `<details>` that is `inline-flex`); it now opens in place as a block.
3. A blanket `.topbar .btn` rule recoloured the buttons inside the white Live popover (white on pale); scoped to the bar's own icon buttons.
4. Utility classes live in a later CSS layer than component rules, so `text-muted` on the chrome would have been navy on navy; chrome overrides are written in `@layer utilities` so the longer selector wins, with the popovers mapped back to card colours.
5. The dark chrome's selected pill first failed the 3:1 graphic contrast against the chrome (2.0, then 2.8); the dark `chrome-bot` was darkened and the pill lightened, thresholds untouched.
6. The Browser pane is 800×600, so full-size captures came from `scripts/screenshots.mjs` (headless Chrome) against the already-running Vite server.

**Verified.** `tsc`, `npx vitest run` (613 passed, all 245 token checks on both themes), `npm run build`; by eye: Desk, Event, Stress Lab, Analyze, Evidence in light and dark at 1440 px, Desk/Evidence/Event at 1024 and 390 px, the mobile drawer opening and closing on Escape, no horizontal scroll at 390 px, both popovers open.

**Also checked / regenerated.** Portfolios, the ⌘K dialog and the Adjust drawer were opened in the Browser pane after the re-skin; all 78 committed `docs/screenshots/*` were regenerated (`HERO=sig_8f79c8bbd6`, light and dark, 1440/1024/390).

**Not done / not verified.** Today, the portfolio editor and the Scenario lab tab were not re-inspected after the re-skin; the 1024 px layouts of the other pages were only spot-checked; `make smoke` was not re-run; the production bundle was rebuilt (`npm run build`) but not served through the real API.

### Task 2 (2026-10-08): committed simulated-live capture, built from the replay pack
**Goal.** A small capture committed to the repo so the switch's "Simulated live" choice works with no news-feed access.

**What broke.** Three throttled runs of `scripts/capture_gdelt.py` (12-20 s between requests, 12 h then 24 h windows, different query subsets, about 25 minutes in all) produced 6, then 0 new, then 1 new record: 7 in total and mostly off-topic. GDELT answered HTTP 429 or non-JSON to most queries from this machine, as it did in Stage 6. `capture_gdelt.py` now merges into an existing file (de-duplicated by URL; `--fresh` replaces) and takes `--only 0,2,5` to retry just the failed queries; it is a network script and has no test.

**Decision (user's).** Use the real GDELT articles already in the hash-pinned replay pack instead. `scripts/build_sample_capture.py` (`make capture-from-replay`, `--check`) takes the 216 pack articles first seen on 2026-10-01, the day after the replay window ends, so they are in no REPLAY signal. They keep their true first-seen times (nothing re-dated), are de-duplicated by URL, sorted oldest first, and lose the pack's `x_query` bookkeeping field. Output: `data/live/sample_capture.jsonl` (71 KB, committed; `data/live/` is only ignored file by file). Licence and attribution are the pack's (GDELT terms, citation); the metadata-only note still holds.

**Verified.** `tests/unit/test_sample_capture.py`: the committed file equals the pack's derivation, every record is after `window_end` with its pack timestamp and no `x_query`, `CaptureSource` reads it in batches to the end, the config points at it. Integration: on the real replay app the switch plays the capture (216 fetched, live signals appear, none shadows a replay id, every replay signal is still served, restart works, off keeps what arrived). In the Browser pane: pick "Simulated live", turn on, the wire grew while the header showed "On · simulated"; it ended `IDLE` with 216 fetched, 173 live signals and no error, then turned off. `make freeze-check` still passes (the file is not in the manifest). 614 web tests, ruff and tsc clean.

**Found while checking.** (1) The dev server runs with the language-model reader on, so every new headline is also sent to the configured provider for extraction (it rate-limited, and each batch of 20 took about 25 s instead of the 10 s interval). The "no network" hint on the simulated source was therefore not accurate: it now reads "reads a local file; no news-feed requests". With the reader off, a full play takes about two minutes. (2) The shell layout in the browser had changed to a sidebar since my earlier screenshots; I did not make that change, and the Live switch works in it.

**Not done.** Playback speed control (1x/10x) was dropped: the interval is fixed by `configs/live.yaml` (`capture.interval_seconds`). The stories also exist in the pack's earlier days, but none of these 216 is a duplicate of a REPLAY signal by id; same-story overlap with earlier replay days is possible and was not measured.

### Task 3 (2026-10-08): SEC EDGAR 8-K filings as a second live source
**Why.** The problem statement grades two or more text sources, and live had one (GDELT). EDGAR is a different kind of source: first-party, with an official event type (the 8-K item codes) and an exact acceptance time, free and public.

**Built.**
- `ingestion/edgar_live.py`: `EdgarLiveSource` reads the "current filings" Atom feed (one request per poll, SEC-declared User-Agent from `EVENTSHOCK_SEC_CONTACT`, never anonymous: an explicit contact is validated even when a transport is injected). Each kept filing becomes a `RawDocument` (source `sec.gov`, metadata `form`, `cik`, `accession`, `items`, `synthesized_headline: true`, timestamp origin SOURCE). The headline ("<Company> files Form 8-K: Item 2.04 ...") is composed from published fields only; no filing text is read. The domain has two source types, so a filing is carried as NEWS and says what it is in its metadata.
- Which filings (`configs/live.yaml: source.edgar`, judgement priors, unvalidated): every 8-K from an issuer in the entity master (matched by CIK from `data/events/sec_filings.jsonl`, never by name) plus any 8-K reporting one of items 1.03, 1.05, 2.01, 2.04, 2.06, 3.01, 4.02, 5.01 for any company. Everything else is counted and dropped.
- `CombinedSource` (`kind: both`) polls GDELT and EDGAR in one poll; one failing leaves the poll DEGRADED, not failed. `LivePoll.documents` lets a source hand over documents it built itself; `LiveStatus` gained `fetched_by_adapter` (which sources delivered) and `last_poll_note` ("SEC filings: 100 listed, 40 in the last 6 h, 0 matched").
- Switch: four choices (News + SEC filings, GDELT, SEC filings, Simulated). The default is two sources when SEC filings are available; the SEC choices are disabled with the reason when no contact is configured.
- `configs/live.yaml` is in the freeze manifest: re-pinned deliberately (`make freeze-write`; only that one hash moved).

**What broke / decisions.**
1. The unit tests caught that every real entry would have been dropped as invalid: the feed writes `<b>AccNo:</b> 0001...`, so a regex expecting whitespace after `AccNo:` never matched. Markup is now stripped before matching.
2. A first real poll (100 entries, 10 kept, no failure) showed all ten kept filings were routine Item 1.01 material agreements of small companies (financings). Item 1.01 was removed from the defaults. This rests on one sample, so it is a judgement, not a measurement.
3. The consequence is that the feed is sparse by design: two real polls minutes apart listed 100 filings, 40 within six hours, and matched none. A quiet source looked broken in the UI, so the poll note was added.
4. A test fixture mistake (GDELT retries three times, so one scripted failure was followed by a success) briefly made a "both sources down" poll look healthy.

**Verified.** `tests/unit/test_edgar_live.py` (parsing from the real feed shape; keep rules; counts; failed request / not-an-Atom document / oversized feed are failed polls with no documents; combined source merges and survives one failing or raising; filings flow through the engine, are journalled, counted per adapter and not re-ingested as new; the switch refuses the SEC choices without a contact; config validation; tracked CIKs come from the committed table); integration test of the four choices; 12 component tests; ruff, tsc, `make freeze-check`. Live on the real server: the switch to SEC filings reported source `edgar`, state OK, no error, note "SEC filings: 100 listed, 40 in the last 6 h, 0 matched".

**Not done / not verified.** (1) The combined News + filings mode was exercised in unit tests only, not against the real GDELT, which is rate-limiting this machine. (2) No real SEC filing has yet flowed through the live engine end to end, because none matched the keep rules in the polls made; the same path is covered with feed-shaped test data. (3) The SEC choices need `EVENTSHOCK_SEC_CONTACT`, as `make fetch-edgar` already did.

### Task 4 (2026-10-08): exposure heatmap and loss heatmap
**Why.** The UI showed exposure only one dimension at a time (bars by sector, by asset class, by issuer), so "where does this book sit, and where did the shock land?" needed three tables read side by side.

**Built.** One shared `CrossTab` (`portfolio/models.py`, `portfolio/crosstab.py::build_crosstab`) and one table component (`components/portfolio/Heatmap.tsx`), used twice:
- **Where the value sits**: sector by asset class, from the holdings alone (`PortfolioExposureDetail.matrix`, shown in the Portfolios page's exposure panel; share of the whole book per cell).
- **Where each shock landed**: sector by market factor, from the engine's own per-position, per-factor changes (`StressAttribution.matrix`, shown inside the existing attribution panel, so it appears on the Event page's stress chapter, the Stress Lab and a Lab result with no extra wiring).
- Both fields are additive and optional (older servers and fixtures still type-check). No stress formula, model, config or pinned digest changed; `make freeze-check` still passes.
- The builder raises if the cells do not add up to the total they claim to break down, the same rule as the one-way attribution tables. It is a plain `<table>`: row and column headers, the number in every cell, totals in the margins, an empty cell is printed as "·" with "none" for a screen reader, and a footer says the cells add up. The tint is a share of the largest cell and never the only signal. Colour comes from existing tokens only (`--color-accent`, `--color-neg`, `--color-pos` mixed into paper); no new colour.

**What broke / decisions.**
1. My first CSS insert anchored on a comment of the Live switch that the shell redesign had since reworded, so the script stopped half-way (the component file and the types were written, the CSS and mounts were not). Re-run on the new anchor; nothing was left half-applied after that.
2. Column headers like "equity price shock" were first truncated with an ellipsis; they now wrap (balanced) so the full factor name is always readable.
3. The tint contrast was measured, not assumed: rendered cell background versus text, the lowest of 24 cells is 8.67:1 in the light theme and 7.48:1 in the dark one (the WCAG text bar is 4.5).
4. Not built on purpose: an issuer-by-factor table (34 issuers wide, unreadable at this size) and any chart library.

**Verified.** `tests/unit/test_crosstab.py` (adds up, ordering, a table that does not add up raises, zero cells omitted), `test_portfolio_exposure.py` (matrix regroups the same value and agrees with the one-way breakdowns), `test_propagation_attribution.py` (matrix agrees with the sector and market-factor tables), the API tests for the default and a personal book, and the replay end-to-end test that builds an attribution for every available signal and asserts the matrix reconciles on each. Web: 6 component tests (`Heatmap.test.tsx`), 626 tests in all. Browser: exposure heatmap on the default book (6 sectors by 4 asset classes, adds up to $860.1M), loss heatmap on the featured Hormuz event (adds up to the run's -$37.3M), dark theme, and 375 px (the page stays 375 px wide; only the table scrolls).

**Not done / known limits.** A cell is a regrouping of modeled change under the scenario's assumptions, not causal attribution. Sectors are the portfolio's own labels (six in the default book). No click-through from a cell to its positions: the tooltip gives the amount and the position count.

### Task 5 (2026-10-08): contagion map
**Why.** The exposure chain was a list of edges. It is complete and accessible, but the question "how does this one event reach my book?" is a picture question.

**Built.** `ContagionMap` (`components/propagation/ContagionMap.tsx`) draws the propagation graph the endpoint already returns, with no backend or API change: event → risk factors → where it lands (asset classes, sectors, industries, each with its share of the book as a bar) → the largest holdings reached. Geometry comes from a pure function, `lib/contagion.ts::layoutContagion` (four fixed columns, centred, no force layout, so it is deterministic and testable). Styling: solid line = a fact, dashed = a configured assumption, dotted = the user's own; red = hurts the target, green = benefits it (the sign of the edge weight), thicker = larger weight. A holding is joined to the sector, industry and asset class it is actually in (a fact about the holding, `rule: held_in`, drawn as hairlines). Hover or focus a box and every other line fades while a live caption states the lines that remain, each with its status, weight, evidence and rule. It sits above the existing edge list in `PropagationChain`, which is unchanged and still carries every edge in words, so nothing is only visual. Colours are existing tokens only.

**What broke / decisions.**
1. Measured in the browser, not assumed: the event box's "About:" line ran 13 px past its box and one holding label 3.7 px, because the wrap limits were guessed and the secondary line was joined into one unwrapped string. Limits are now conservative for the 196 px box and both lines wrap; the least room on the right of any text is now 21.7 px, and a test pins that every wrapped line is within its limit and each box is exactly as tall as its text.
2. The map's `<title>` tooltips repeat edge text, which broke an existing test that looked a rule id up page-wide (`getByText` found two). That test is now scoped to the edge list it was written about; its meaning is unchanged.
3. Screenshots of the tall Event page went blank at very large scroll offsets (about 13,500 px), so hover, dark theme and the 375 px width were verified by measuring the DOM; the first screenshot of the map at desktop width was taken and checked by eye.
4. Not drawn: subject nodes (they are the event box's "About:" line), the book's own "held by" edges, and holdings beyond the eight largest (the caption says "the 8 largest of 79", and the table below lists all). A graph with no risk factor or no landing place draws nothing, and an abstained graph keeps showing its explanation.

**Verified.** `lib/contagion.test.ts` (wrapping; four columns left to right; no overlap; edges only between adjacent columns with the right status and tone; holdings joined only to what they are in; drawn count vs reached count; deterministic; null for an abstained or empty graph), `ContagionMap.test.tsx` (labelled focusable boxes, tooltips with status/weight/evidence/rule, line styles, focus fades the rest and states why, legend and note), and the whole web suite (652 tests), `tsc`, `make freeze-check`. In the browser on the featured Hormuz event: 19 boxes and 23 lines; hovering the oil box faded 18 of 23 lines and wrote the caption; at 375 px the page stays 375 px wide and the map scrolls inside its container; dark theme uses the same tokens.

**Not done / known limits.** It draws a mapping, not a causal model, and the assumed lines are unvalidated priors (it says so in the legend). The layout is for graphs of the size the engine produces (a handful of factors and landing places, eight holdings); a much larger graph would need its own pass.

### Task 6 (2026-10-08): analyst review queue
**Why.** Feedback (thumbs on an event) existed, but nothing told a person *which* events deserve a look, and nothing let them say "I looked at this". A review queue is the smallest thing that closes that loop.

**Built.** A derived side-car, `src/eventshock/review/` + `GET /api/review/queue`, `POST/GET /api/review/decisions`, `configs/decision.yaml: review` (judgement priors, in the freeze manifest: re-pinned, only that hash moved besides `live.yaml`'s earlier re-pin), the `/review` page (`pages/ReviewPage.tsx`, `components/review/ReviewCard.tsx`, a nav item gated on `capabilities.review`).
- **What is queued** (`review/rules.py`, named rules over fields the monitor's `EventState` already holds; no model, no score): sources disagree (conflicted claims, never from tone); severity >= 6 with an unresolved subject; severity >= 7 with one independent source; material to the book (HIGH/CRITICAL); a generated-scenario loss of at least 1% of the book; escalating lifecycle; and **changed since reviewed**. Each item shows every rule that fired with the values that fired it.
- **Order** is the digest's idea: a documented lexicographic key (materiality tier, severity, number of rules fired, recency, id), shown on every item under "Why this position?". Not a blended score.
- **Decisions** are REVIEWED / DISMISSED / OPEN (reopen) with an optional note and a reviewer name (kept in the browser). Append-only JSONL in git-ignored `data/live/decision/review/`; the latest decision is current, earlier ones stay as history. A reviewed or dismissed event **reopens when its own evidence changes** (reports, sources, severity, lifecycle, evidence tier, conflict); the fingerprint deliberately excludes the book-dependent fields, so reading the same event against another portfolio does not reopen it.
- Sits beside the others under the architecture guard: `review` added to the side-car list in `tests/unit/test_decision_architecture.py` (no core package may import it); nothing is stored on a `RiskSignal`; a decision changes no served output (an API test hashes signals + digest before and after).

**What broke / decisions.**
1. **My own timing broke a full test run.** I added the `review:` key to `decision.yaml` while the full Python suite was running; the already-loaded config class rejected it (138 errors, all "extra inputs not permitted"). Not a regression, but that run proved nothing, so it was discarded and the suite was re-run clean at the end, with no edits during it.
2. **Decision timestamps used the replay's pinned clock**, so every decision was stamped 1 Oct 12:00 and "newest first" fell back to a random id. Found by an API test. Fixed twice over: history is ordered by recording order (timestamps can tie, the log's order cannot), and decisions are stamped with real time (a decision made today must not read "reviewed on 1 Oct"). Feedback (Stage 12) still uses the replay clock; left as it was.
3. A test helper kept the reviewer's name in memory across tests even after storage was cleared; the in-memory copy now exists only for when storage is blocked.
4. **What the real replay produces**: 75 of 400 tracked events are queued, led by CRITICAL-materiality, high-severity, single-source events. **No event fired the conflict or the escalating rule** in the frozen window, so those two paths are covered by tests with built event states, not by anything seen on real data (a pinned conflicting-claims demo event is still open).
5. Decided against: assignment/owners, SLAs and notifications (this is a single-user prototype; they would be theatre), and a blended priority score.

**Verified.** `tests/unit/test_review.py` (every rule at its threshold and just below, null severity, fingerprint ignores the book and notices new evidence, ordering, the queue only lists events with a reason, decisions move items and counts, reopen, history ties, changed-evidence reopening, a reviewed event stays listed when no rule fires, cap, bad input records nothing, untracked event refused, live vs replay, restart survival and a damaged line skipped, limit, analyst id precedence, config validation); `tests/integration/test_review_api.py` on the real replay (capability, ordering by tier, a decision round trip that restores the queue and leaves signals/digest byte-identical, 404/422, live availability); 10 page tests; web suite 668 passing. In the browser: 75 open items, a real "Mark reviewed" with a note moved it to Reviewed (counts 74/1), it survived a server restart, and Reopen restored 75; 375 px has no overflow and 44 px buttons. The decision made during checking remains in the git-ignored dev log (one REVIEWED and one OPEN line).

**Not done / known limits.** The thresholds are unvalidated priors. The queue reads only what the monitor tracks (severity or materiality at its floor). One reviewer identity per browser, no authentication: a name on a decision is a label, not a login.

## Documentation and submission-readiness pass (2026-10-08)

**Why.** The README still said *Stage 1 — fixtures*, `docs/ARCHITECTURE.md` described Stages 1-4, there was no `docs/architecture.png` or submission checklist, and the early guiding notes still carried the working name *SignalForge*. The task: make every public document describe what is actually implemented, under the name **EventShock**, and say honestly what is still open.

**What was audited first.** Repository tree, README, all `docs/*.md`, configs, the OpenAPI schema (85 operations), the replay pack and the running server, the git state and remote, `.gitignore`, requirements. Contradictions found: README header/status and the "Real vs simulated" table were out of date (Stage 1 status line, sentiment v1, a UI description from before Stages 14-15); the clone command did `cd` into a folder that `git clone` would not create; `ARCHITECTURE.md` listed Stage-1 API/decisions as current; `SENTIMENT_MODEL.md` and `EVENT_MODEL.md` still said event/impact were placeholders; `DATA_LICENSES.md` said the same in its last caveat; the SignalForge-era PRD asked for FinBERT, XGBoost + SHAP, Streamlit, SQLite and DuckDB, none of which is what was built.

**Done.**
- `README.md` rewritten on the mandatory five-section template (plus API, ML, stress, evaluation, failure handling, limitations, security, reproducibility, future work), every number taken from a model card, the OpenAPI schema or the running server.
- `docs/ARCHITECTURE.md`: new authoritative sections 1-17 (system overview, components, data flow, API flow, storage, ML/training/evaluation, stress, dashboard, errors, configuration, deployment, security, reproducibility, trade-off table, PRD coverage table, production evolution, generated API reference); the Stage-1 text is kept as a labelled design record with its stale tables updated.
- `docs/architecture.png` (2400 × 1420) and `docs/architecture.svg`, generated by `scripts/make_architecture_diagram.py` (headless Chrome renders the PNG; the generator fails if text would overflow a box).
- `docs/SUBMISSION_CHECKLIST.md` with PASS / PARTIAL / TODO and a measured-numbers table; this *Journey at a glance* section; status notes on `SENTIMENT_MODEL.md`, `EVENT_MODEL.md`, `DATA_LICENSES.md`.
- `docs/interview/PROJECT_WALKTHROUGH.md` (git-ignored via `docs/interview/`).

**What broke / was found, and what was decided.**
1. **The repository is not public.** An unauthenticated request for the GitHub URL returned 404. Recorded as a TODO in the checklist; not something a documentation pass can fix.
2. **Two numbers for one event.** The Desk (and `POST /api/stress-test`) report **−$37.3M (−4.33 %)** for the Hormuz event under the catalog Geopolitical scenario, labelled "generated for this event"; `POST /api/signals/{id}/portfolio-stress` runs the propagation-generated scenario for the same event and reports **−$42.2M (−4.91 %)**. Both are right for their scenario; the Desk label is loose. Documented, not changed (no code or config was touched in this pass).
3. **Severity 8 vs trained impact 2 for the same text.** Expected by design (two different questions), but a jury will ask; the README and the interview notes now say so up front.
4. **FinBERT.** The research notes asked for FinBERT sentiment. It was only probed (93 % on a 30-pair polarity probe against 77 % for the shipped model) and used as frozen features; it is not served. The docs now say exactly that instead of implying either "used" or "never considered".
5. **My first diagram was unreadable** (text overflowing boxes, tangled arrows). The generator now measures text against box width and refuses to write a diagram that overflows; arrows were reduced to lane-to-lane flows with numbered steps.
6. **The suite is slow on a busy machine.** A second full `pytest` run (another process) was already in the repository while I started mine; the two doubled the load (server start-up 188 s in-process, 45 s as a server). I stopped my duplicate, ran the doc-related tests and `make freeze-check` separately, then started the full suite again, which finished with exit 0 (2,170 passed, 4 skipped, 0 failed; counted from the progress output). Timings in the checklist are labelled upper bounds.
7. **My own validation touched the developer's journal.** Starting the real server and calling `POST /api/analyze` appended pasted-text lines to `data/live/journal.jsonl` (git-ignored). Those lines were removed afterwards; tests are unaffected because `tests/conftest.py` redirects the journal.

**Not done / not verified.** `docs/presentation.pdf`, the demo video, the e-mail confirmation, making the repository public, committing anything. `make smoke` result and the full pytest result are in the checklist's validation log. The FinBERT head and human adjudication remain future work.

### Follow-up (2026-10-08): the rest of `docs/` brought to the Stage 15 state
After the first pass the question was whether every file under `docs/` was current. It was not. What was done:
- `FEATURES_AND_PAIN_POINTS.md` described the Stage 5 interface (Risk Feed, a left rail, "no per-event retrieval exists", impact as the headline). Corrected, and sections 10-15 added for Stages 6-15 (severity scorecard, analogues, Analyze, personal portfolios, heatmaps, propagation, contagion map, Today, Review, watchlists, brief, scenario lab, reverse stress, external markets, Live switch), each row naming a test or file that exists.
- `DEMO_SCRIPT.md`: "rail" wording fixed; a Stage 15 addendum (Live switch, Review, contagion map, heatmaps, Adjust) written after checking its steps against the running app (the Review page showed 75 of 400 events queued; the Live popover offered *News + SEC filings*, *GDELT news feed*, *SEC EDGAR 8-K filings* and *Simulated live*; the Hormuz event page shows the exposure chain and the run-scenario button).
- `PORTFOLIOS.md`, `PORTFOLIO_PROPAGATION.md`, `DECISION_INTELLIGENCE.md`: Stage 15 addenda (exposure heatmap, loss heatmap, contagion map, review queue).
- Checked and left unchanged because they are dated stage reports that already carry update notes: `IMPACT_MODEL.md`, `EVIDENCE_V2.md`, `MODELING_READINESS.md`, `FINAL_MODEL_REPORT.md`, `FINANCE_THEORY.md`, `ANALOGUES.md`, `RISK_ASSESSMENT.md`, `EVENT_INTELLIGENCE.md`, `EXTERNAL_MARKETS.md`, `GOLD_LABELING_GUIDE.md`. The check was mechanical (every `make` target and every path they name exists; no stale digest is presented as current) plus the existing number-pinning tests; their figures were not re-derived by hand.
- Found while checking: the Desk still tells the user to "start with make run-live" although the runtime Live switch exists (UI copy, not changed here); `configs/app.yaml` still comments `mode: LIVE (not implemented yet)`.
