# Data sources, licences and what is committed

EventShock uses only free, public data. Nothing here is S&P Global or Crisil data.

| Source | What we take | Licence / terms | Committed? |
|---|---|---|---|
| **GDELT DOC 2.0 API** (`api.gdeltproject.org/api/v2/doc/doc`, mode `artlist`) | article metadata only: URL, title, first-seen time, domain, language, country | GDELT states its datasets are free for unrestricted academic, commercial and governmental use, with citation and a link back ([gdeltproject.org/about.html](https://www.gdeltproject.org/about.html)). Courtesy rate limit: 1 request / 5 s (we throttle to 5.5 s). | **Yes, metadata only**, ~1.5k records (1,479 unique articles) in `data/replay/gdelt/`. No publisher text is stored or redistributed. |
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
| Yahoo prices | refetched from 2014-01-01 (`make fetch-prices`) so H1 2015 has a 250-session history | No |

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
| `data/gold/` | the gold set: blind sheet, manifest, adjudication, consistency | yes |
| `data/fixtures/` | Stage-1 fictional demo data (`EVENTSHOCK_PROFILE=demo`) | yes |

## Known data caveats (also shown in the UI)

- GDELT `seendate` is when GDELT first saw the page, not the publication time (`timestamp_origin = GDELT_FIRST_SEEN`).
- The Twitter Financial News dataset has **no timestamps**. Replay assigns deterministic times inside the snapshot
  window (`SYNTHETIC_REPLAY_CLOCK`); such documents are never correlated with others by time.
- GDELT relevance ranking returns off-topic articles for some queries (e.g. a bank query returning an unrelated
  filing). That noise is kept deliberately: the pipeline must cope with it, and entity resolution decides from the
  text, never from the query that fetched the article.
- Event type and impact are **placeholder rules** (`placeholder-v0`). Sentiment comes from a trained model (see
  `SENTIMENT_MODEL.md`); the TFN tweets in the replay pack are part of its training data and are flagged in-sample.
