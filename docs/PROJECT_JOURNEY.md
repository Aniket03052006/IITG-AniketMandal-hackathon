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
