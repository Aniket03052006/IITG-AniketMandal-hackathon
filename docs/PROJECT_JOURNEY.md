# EventShock — Project Journey

Chronological log: **what we did · what broke · how we fixed it**. Updated after every task and at the end of every stage.

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
