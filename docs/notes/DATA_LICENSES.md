# Data sources, licences and what is committed

EventShock uses only free, public data. Nothing here is S&P Global or Crisil data.

| Source | What we take | Licence / terms | Committed? |
|---|---|---|---|
| **GDELT DOC 2.0 API** (`api.gdeltproject.org/api/v2/doc/doc`, mode `artlist`) | article metadata only: URL, title, first-seen time, domain, language, country | GDELT states its datasets are free for unrestricted academic, commercial and governmental use, with citation and a link back ([gdeltproject.org/about.html](https://www.gdeltproject.org/about.html)). Courtesy rate limit: 1 request / 5 s (we throttle to 5.5 s). | **Yes, metadata only**, ~1.5k records (1,479 unique articles) in `data/replay/gdelt/`. No publisher text is stored or redistributed. |
| **GDELT DOC 2.0, live polling** (Stage 6; same endpoint, opt-in via `EVENTSHOCK_LIVE=1`) | the same article metadata, for the trailing 90 minutes, a few times an hour, 8 queries with a ≥ 6 s gap (GDELT asks for one request per 5 s) | same GDELT terms | **Nothing is shipped.** `make capture-gdelt` writes a metadata-only capture (`data/live/sample_capture.jsonl`) for the offline *simulated live* mode. The running journal (`data/live/journal.jsonl`: live and **pasted** text) is git-ignored and local. |
| **GDELT GKG 2.1 bulk files** (`data.gdeltproject.org/gdeltv2/*.gkg.csv.zip`, listed in `masterfilelist.txt`) | per article: page title, URL, domain, publisher timestamp, machine tone, NER organisations, themes. Filtered on the fly to our issuers + market themes. | Same GDELT terms (free reuse with citation). | **A 1,308-record slice only** (`data/replay/gdelt/gkg_articles.jsonl`). The full filtered download (127,592 rows, 84 MB) stays in `data/raw/gdelt_gkg/` (ignored); the 1,344 zips (≈5.8 GB) are discarded after filtering. |
| **Twitter Financial News — sentiment** (`zeroshot/twitter-financial-news-sentiment`, Hugging Face) | tweet text + human sentiment label (bearish / bullish / neutral) | Dataset card declares **MIT**. The tweets originate on X; the dataset publisher's licence does not transfer rights the publisher may not hold. | **Small sample only** (300 rows) in `data/replay/social/`, with attribution in `manifest.json`. The full dataset (≈11.9k rows) is downloaded to `data/raw/` (git-ignored). **Removal:** delete `data/replay/social/` and rebuild the pack if a rights holder objects. |
| **Entity master** (`data/replay/entities.json`) | 34 listed issuers: legal name, ticker, sector, country, aliases | Public facts, hand-curated. | Yes |
| **Portfolio** (`data/replay/portfolio.json`) | synthetic equities / bonds / loans / derivatives on those issuers | Generated with a fixed seed. **Not real positions.** | Yes |

## Modelling and history data (all git-ignored under `data/raw/` unless stated)

| Source | What we take | Licence | Committed? |
|---|---|---|---|
| **Yahoo Finance chart endpoint** (`query1.finance.yahoo.com/v8/finance/chart`) via our own fetcher (not the `yfinance` package, same source) | daily OHLCV + adjusted close, 2015-01-02..2026-10-01, for the 34 issuers and `^GSPC`, `^VIX`, `^TNX` (37 CSVs, 5.7 MB) | Unofficial endpoint; Yahoo Finance terms apply (personal / research use). Not redistributed. | No |
| **Twitter Financial News — topic** (`zeroshot/twitter-financial-news-topic`, HF) | 21,107 tweets, 20 topic labels (event-class labels via `configs/topic_mapping.yaml`; 17,855 map to our 8 classes) | MIT per dataset card; tweets originate on X | No |
| **Kaggle `equinxx/stock-tweets-for-sentiment-analysis-and-prediction`** | 80,793 timestamped tweets about 25 tickers, 2021-09..2022-09 | CC0 | No |
| **Kaggle `notlucasp/financial-news-headlines`** | 53,650 Reuters / CNBC / Guardian headlines 2017-2020 (dates, no tickers) | CC0 | No |
| **Kaggle `omermetinn/tweets-about-the-top-companies-from-2015-to-2020`** | 3.7M tweets about 6 large caps; a 155k hash-sample is used | CC0 | No |
| **Kaggle `computingvictor/transactions-fraud-datasets`** | 13.3M retail card transactions; **only the merchant-category spend mix** is derived | Apache-2.0 | **Aggregate only** (`data/replay/sector_mix.json`, 11 KB) |
| **Kaggle `ankurzing/sentiment-analysis-for-financial-news`** (Financial PhraseBank derivative) | labelled sentences, for local evaluation only | **CC BY-NC-SA 4.0 (non-commercial, share-alike)** | **Never** |

Datasets are listed with their licence and commit policy in `configs/external_datasets.yaml` (`make fetch-kaggle`, needs a Kaggle token
in `KAGGLE_API_TOKEN` or `~/.kaggle/access_token`; the token is never stored in the repo).

Not obtained: **NewsAPI** and **Alpha Vantage** need personal API keys (Yahoo covers prices), and **Salad Money Open Banking** is not an open
download (research access is by application). The Kaggle card-transaction dataset stands in for "sample transaction data".

## Derived modeling data (Stage 3 prep)

| Artefact | Built from | Committed? |
|---|---|---|
| `data/gold/gold_sample.csv`, `gold_manifest.json`, `adjudication.csv`, `consistency_sheet.csv`, `gold_scores.json` | ~400 texts sampled from the history snapshot (CC0 Kaggle tweets and headlines, GDELT GKG titles) and 120 Twitter-Financial-News topic tweets (MIT per dataset card; tweet content originates on X) plus our labels (annotator `ai:claude`; a human may override in `adjudication.csv`) | **Yes** (about 320 KB, incl. `gold_scores.json`). Removal for the TFN rows: delete them from the sheet and manifest, re-run `gold-sample` |
| `data/modeling/sentiment.jsonl` | TFN sentiment (MIT, attribution above) exact-deduplicated and re-split; the training table of the sentiment model | **Yes** (2 MB) so `make train-sentiment` works from a clone |
| `models/sentiment/tfidf-lr-v1/` | a TF-IDF + logistic-regression model trained on that table (its weights derive from MIT data). PhraseBank (CC BY-NC-SA) and the AI-annotated gold set were used for evaluation only, never for training or selection; the card quotes aggregate scores and no PhraseBank text | **Yes** (1.7 MB) |
| `data/event_labels/` (`event_labels.csv`, `manifest.json`, `answers/*.jsonl`, `consistency.json`) and `data/modeling/event_train.jsonl` | ~3,270 texts from the history snapshot (CC0 Kaggle tweets and headlines, GDELT GKG titles), TFN topic tweets (MIT per dataset card; tweet content originates on X) and 200 titles/posts of the replay pack (GDELT metadata, TFN sample), plus the AI annotator's labels (`ai:claude`, blind; see EVENT_MODEL.md). No publisher text. The blind input batches are regenerable and git-ignored | **Yes** (about 2 MB + 0.6 MB + 0.4 MB). Removal for the TFN rows: delete them from the label CSV/manifest and re-run `make event-table train-event` |
| `models/event/tfidf-lr-event-v1/` | a TF-IDF + logistic-regression model trained on that table (weights derive from CC0 / MIT texts and our labels). The gold set was used for evaluation only | **Yes** (2.7 MB: artifact + model card) |
| `docs/evidence/event_first_run_two_threshold_card.json` | the event model card of the first full run, kept so a design change made after it stays auditable | **Yes** |
| `data/modeling/*` (the rest: `impact_events.jsonl`, `event_silver.jsonl`, `phrasebank_eval.jsonl`, `audit.json`, `probe*.json`) | the raw datasets above, re-split, deduplicated and joined to prices | **No** (git-ignored; rebuild with `make audit`). `phrasebank_eval.jsonl` is CC BY-NC-SA and must never be committed or trained on |
| `data/replay/market/context.json` | per-issuer and market statistics derived from the Yahoo prices (trailing volatility, betas, 1/5/20-session returns, volume ratio, VIX and yield context) for the replay window's sessions: **no prices, no volumes, no OHLCV**; `make market-context` | **Yes** (derived statistics only; the raw prices stay git-ignored). If a rights holder objects, the impact model falls back to the labelled placeholder rule |
| `data/modeling/impact_table.jsonl`, `impact_dataset.json` | the impact training table (features, outcomes, text) and its manifest; `make impact-table` | **No** (git-ignored, ~140 MB; the manifest pins it by sha256) |
| `models/impact/impact-v1/` | the fitted impact model (a 0.1 MB scikit-learn artifact) and its card | Yes |
| Yahoo prices | refetched from 2014-01-01 (`make fetch-prices`) so H1 2015 has a 250-session history | No |

## Stage 4 evidence sources (structured events, 2023-2025 news, representation study)

| Source | What we take | Licence / terms | Committed? |
|---|---|---|---|
| **SEC EDGAR submissions index** (`data.sec.gov/submissions/`, `www.sec.gov/files/company_tickers.json`) | per filing of the 34 issuers (and predecessor registrants of GOOGL and XOM): form, exact acceptance time (UTC), 8-K item codes, accession, primary document name | US government work, public domain. SEC fair-access policy: declared contact in the User-Agent (`EVENTSHOCK_SEC_CONTACT`, kept in the git-ignored `.env`, never committed), at most 10 requests per second (we send about 4) | **Derived table only** (`data/events/sec_filings.jsonl`, 9,772 rows, 2 MB). Raw index pages: `data/raw/edgar/`, git-ignored |
| **SEC EDGAR "current filings" Atom feed** (`www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom`), live source only, opt-in from the Live switch | per new 8-K: filer name, CIK, form, accession, exact acceptance time, item titles, filing index URL. The headline shown is composed from those fields and marked `synthesized_headline`; no filing text is read | US government work, public domain. Same fair-access policy and the same `EVENTSHOCK_SEC_CONTACT`; one request per poll (default every 5 minutes) | **Nothing stored in the repo.** Documents live in the git-ignored overlay and journal (`data/live/`) |
| **FOMC calendars** (`federalreserve.gov/monetarypolicy/fomccalendars.htm`, `fomchistorical<year>.htm`) | decision dates (scheduled flag; cancelled meetings and notation votes dropped) | US government work, public domain | Derived (`data/events/fomc.json`). Raw pages git-ignored |
| **GDELT GKG 2.1, 2023-2025 sample** | six fixed 15-minute files per UTC day, filtered on the fly to the entity master (same filter and fields as the 2026 slice): title, URL, domain, publisher timestamp where valid, machine tone, organisations | GDELT terms: free reuse with citation | **No** (raw filter output and the curated `data/history_v2/` are git-ignored; `make fetch-gkg-2023 history-v2` rebuilds them). No publisher text is stored |
| **Gold v2** (`data/gold_v2/`) | about 300 titles from that sample, two independent blind AI passes, agreement report, human adjudication queue | titles are GDELT metadata (as above); labels are ours (`ai:claude`) | **Yes** (small) |
| **Finance polarity probe** (`data/probes/`) | 60 sentences written for this project | ours (MIT with the repository) | Yes |
| **Finance lexicon** (`configs/lexicons.yaml`) | word lists written for this project, not copied from any dictionary | ours | Yes. The Loughran-McDonald dictionary is academic-licence and is deliberately **not** used or redistributed |
| **Frozen encoders** (`intfloat/multilingual-e5-*`, `BAAI/bge-base-en-v1.5`, `thenlper/gte-base`, `yiyanghkust/finbert-tone`, `ProsusAI/finbert`, `j-hartmann/emotion-english-distilroberta-base`) | frozen weights used only to embed text; no fine-tuning, no redistribution | each model's own licence on Hugging Face (MIT / Apache-2.0 for these); downloaded anonymously into the user's cache | Weights: no. Embedding cache `data/modeling/embeddings/`: git-ignored. They run only in the optional `.venv-emb`; the product never imports them |

Not obtained, and said so: consensus earnings estimates (so no realised earnings surprise), BLS jobs and CPI release calendars, and any GDELT coverage outside the six sampled slots.

## What goes where

| Location | Content | Tracked |
|---|---|---|
| `data/replay/` | frozen, small, hash-pinned snapshot (`manifest.json` lists sha256 + record counts) | yes |
| `data/raw/` | bulk / fresh downloads (`make fetch-gdelt`, `make fetch-gkg`, `make fetch-tfn`, `make fetch-kaggle`, `make fetch-prices`) | no |
| `data/history/` | curated modelling snapshot (2015-2026; `scripts/build_history_pack.py`) read by the same pipeline | no |
| `data/processed/` | pipeline exports (`make ingest`) | no |
| `data/modeling/` | modeling tables and audit output (`make audit`); only `sentiment.jsonl` and `event_train.jsonl` (the training tables) are tracked | partly |
| `models/sentiment/`, `models/event/` | the trained artifacts and their model cards (`make train-sentiment`, `make train-event`) | yes |
| `data/event_labels/` | the annotator's event labels, blind-pool manifest and answer files (`make event-pools`, `make event-merge`) | yes |
| `data/events/` | SEC filing acceptance times and 8-K item codes, FOMC decisions, manifest with hashes and known gaps (`make fetch-edgar fetch-fomc events-calendar`) | yes |
| `data/outcomes/` | realised two-session moves after the replay reports (derived statistics from our own impact table: scope, issuer, session, |z|, score; no prices, no text), read only by the per-signal context endpoint (`make outcomes`) | yes |
| `data/rebalancer/` | the tactical rebalancer's derived outputs: `backtest.json` (daily returns, cumulative curves, turnover, a placebo summary), `lab.json` (every strategy on the same window, sensitivity grid, cost sensitivity) and `risk_inputs.json` (one volatility and one average dollar volume per stock at the window start), each with the sha256 of the (git-ignored, not redistributed) price files it read; no prices, no text (`make rebalancer-backtest rebalancer-risk-inputs rebalancer-lab`) | yes |
| `data/gold_v2/`, `data/probes/` | the 2023-2025 doubly annotated evaluation set; the polarity probe | yes |
| `data/history_v2/`, `data/processed/history_v2/` | history v1 plus the 2023-2025 GKG sample, and its pipeline output | no |
| `data/gold/` | the gold set: blind sheet, manifest, adjudication, consistency | yes |
| `data/fixtures/` | Stage-1 fictional demo data (`EVENTSHOCK_PROFILE=demo`) | yes |

## Known data caveats (also shown in the UI)

- GDELT `seendate` is when GDELT first saw the page, not the publication time (`timestamp_origin = GDELT_FIRST_SEEN`).
- The Twitter Financial News dataset has **no timestamps**. Replay assigns deterministic times inside the snapshot
  window (`SYNTHETIC_REPLAY_CLOCK`); such documents are never correlated with others by time.
- GDELT relevance ranking returns off-topic articles for some queries (e.g. a bank query returning an unrelated
  filing). That noise is kept deliberately: the pipeline must cope with it, and entity resolution decides from the
  text, never from the query that fetched the article.
- Sentiment, event type and impact are **trained, experimental models** (see `SENTIMENT_MODEL.md`, `EVENT_MODEL.md`, `IMPACT_MODEL.md`); the placeholder
  rule (`placeholder-v0`) only remains for signals the impact model cannot score, labelled per signal. The TFN tweets in the replay pack are part of the
  sentiment model's training data and are flagged in-sample.
