# EventShock — common tasks. Requires: Python >= 3.12, uv (or pip), Node >= 20.
PY := .venv/bin/python
GDELT_START ?= 20260917000000
GDELT_END ?= 20260930235959
# seconds between GDELT requests; raise it when GDELT answers 429
GDELT_THROTTLE ?= 20
PRICES_START ?= 2014-01-01
PRICES_END ?= 2026-10-02

.PHONY: book-v2 train-sentiment-v2 run-llm market-context impact-table train-impact audit probe gold-sample gold-validate gold-score train-sentiment train-event event-pools event-merge event-table fetch-kaggle fetch-tfn-topic fetch-prices fetch-gkg fetch-gkg-list fetch-gdelt fetch-tfn replay-pack ingest setup setup-api setup-web run dev build test test-api test-web lint fixtures types logo

setup: setup-api setup-web  ## install everything

setup-api:
	uv venv --python 3.14 || uv venv
	uv pip install -r requirements-dev.txt
	uv pip install -e . --no-deps

setup-web:
	cd web && npm ci

build:  ## build the web UI into web/dist (served by the API)
	cd web && npm run build

run: build  ## single process: API + built UI on http://127.0.0.1:8000
	$(PY) -m eventshock

run-llm: build  ## like `run`, with a language model reading new text (needs GROQ_API_KEY (default) or ANTHROPIC_API_KEY in .env or the environment; sends pasted text to the provider). Falls back to rules, labelled, if it fails
	EVENTSHOCK_LLM=1 $(PY) -m eventshock

run-live: build  ## like `run`, with the live feed on: polls GDELT DOC 2.0 every 5 min (network). Replay data keeps serving if it fails
	EVENTSHOCK_LIVE=1 $(PY) -m eventshock

run-capture: build  ## like `run-live`, but replays a captured GDELT file as if live (offline, labelled "simulated")
	EVENTSHOCK_LIVE=1 EVENTSHOCK_LIVE_SOURCE=capture $(PY) -m eventshock

capture-from-replay:  ## rebuild the committed offline stream data/live/sample_capture.jsonl from the replay pack (no network)
	$(PY) scripts/build_sample_capture.py

capture-gdelt:  ## capture what GDELT saw recently into data/live/sample_capture.jsonl for `make run-capture` (network, ~2 min, throttled)
	$(PY) scripts/capture_gdelt.py

scope-eval:  ## measure the sector vocabulary on replay documents whose company resolved -> docs/evidence/scope_eval.json
	PYTHONPATH=src $(PY) -m eventshock.modeling.scope_eval

dev:  ## API with reload on :8000 and Vite on :5173 (open http://localhost:5173)
	./scripts/dev.sh

test: test-api test-web

test-api:
	$(PY) -m pytest

test-web:
	cd web && npm test

lint:
	$(PY) -m ruff check src tests scripts
	cd web && npm run typecheck

fetch-gdelt:  ## download GDELT articles into data/raw (network; 12 throttled requests, resumable)
	PYTHONPATH=src $(PY) -c "import json,sys; sys.path.insert(0,'scripts'); from replay_universe import gdelt_queries; json.dump(gdelt_queries(), open('data/raw/gdelt/queries.json','w'), indent=1)"
	PYTHONPATH=src $(PY) -m eventshock.ingestion.fetch gdelt --queries-file data/raw/gdelt/queries.json \
		--start $(GDELT_START) --end $(GDELT_END) --throttle $(GDELT_THROTTLE) --out data/raw/gdelt/articles.jsonl

fetch-gkg-list:  ## download GDELT's master file list (128 MB) into data/raw/gdelt_gkg
	mkdir -p data/raw/gdelt_gkg
	curl -fL -o data/raw/gdelt_gkg/masterfilelist.txt https://data.gdeltproject.org/gdeltv2/masterfilelist.txt

fetch-gkg: data/raw/gdelt_gkg/masterfilelist.txt  ## bulk GKG files for GDELT_START..END, filtered on the fly; zips are discarded
	PYTHONPATH=src $(PY) -c "import json,sys; sys.path.insert(0,'scripts'); from replay_universe import gkg_filter; json.dump(gkg_filter(), open('data/raw/gdelt_gkg/filter.json','w'), indent=1)"
	PYTHONPATH=src $(PY) -m eventshock.ingestion.gkg_fetch --master data/raw/gdelt_gkg/masterfilelist.txt \
		--start $(GDELT_START) --end $(GDELT_END) --filter data/raw/gdelt_gkg/filter.json \
		--out data/raw/gdelt_gkg/filtered.jsonl --workers 4

data/raw/gdelt_gkg/masterfilelist.txt:
	$(MAKE) fetch-gkg-list

fetch-prices:  ## daily prices (Yahoo chart endpoint, no key) for all issuers + ^GSPC ^VIX ^TNX into data/raw/prices
	mkdir -p data/raw/prices
	PYTHONPATH=src $(PY) -c "import json,sys; sys.path.insert(0,'scripts'); from replay_universe import price_symbols; json.dump(price_symbols(), open('data/raw/prices/symbols.json','w'))"
	PYTHONPATH=src $(PY) -m eventshock.ingestion.prices --symbols-file data/raw/prices/symbols.json --start $(PRICES_START) --end $(PRICES_END) --out data/raw/prices

market-fixtures:  ## regenerate the SYNTHETIC external-market fixtures (deterministic; tests and the offline demo)
	$(PY) scripts/make_market_fixtures.py

kalshi-snapshot:  ## capture a small hash-pinned snapshot of Kalshi's public market data for the curated themes -> data/external/kalshi_snapshot.json (network, no key; replay and the demo read it)
	$(PY) scripts/kalshi_snapshot.py

fetch-tfn:  ## download the Twitter Financial News dataset into data/raw (network)
	PYTHONPATH=src $(PY) -m eventshock.ingestion.fetch tfn --split train --out data/raw/tfn/train.jsonl
	PYTHONPATH=src $(PY) -m eventshock.ingestion.fetch tfn --split valid --out data/raw/tfn/valid.jsonl

fetch-kaggle:  ## Kaggle datasets from configs/external_datasets.yaml (needs KAGGLE_API_TOKEN or ~/.kaggle/access_token)
	PYTHONPATH=src $(PY) -m eventshock.ingestion.kaggle

fetch-tfn-topic:  ## Twitter Financial News topic dataset (20 labels) into data/raw/tfn (event-class labels)
	PYTHONPATH=src $(PY) -m eventshock.ingestion.fetch tfn --kind topic --split train --out data/raw/tfn/topic_train.jsonl
	PYTHONPATH=src $(PY) -m eventshock.ingestion.fetch tfn --kind topic --split valid --out data/raw/tfn/topic_valid.jsonl

replay-pack:  ## freeze data/raw into the committed, hash-pinned data/replay pack
	$(PY) scripts/build_replay_pack.py

ingest:  ## run the pipeline over data/replay and export signals/quarantine/report to data/processed
	$(PY) -m eventshock.pipeline --export data/processed

audit:  ## modeling tables + every leakage check -> data/modeling/ (needs data/raw and data/processed/history; ~2 min)
	$(PY) -m eventshock.modeling audit

probe:  ## seconds-long classical baselines on the audit tables (needs `uv pip install -r requirements-ml.txt`)
	$(PY) -m eventshock.modeling probe

book-v2:  ## Wholesale Book v2 (Stage 13 mechanics on the replay default book) -> data/portfolio/book_v2_replay.json
	$(PY) scripts/build_book_v2.py

train-sentiment-v2:  ## sentiment v2 (class-balanced candidates, selected on valid macro-F1) -> models/sentiment/tfidf-lr-v2/
	$(PY) -m eventshock.modeling train-sentiment --config sentiment_model_v2.yaml

train-sentiment:  ## train + select + calibrate + evaluate the sentiment model -> models/sentiment/ (needs data/modeling/sentiment.jsonl; ~1 min)
	$(PY) -m eventshock.modeling train-sentiment

event-pools:  ## draw the blind event-labelling batches into data/event_labels/batches (refuses to overwrite labels)
	$(PY) -m eventshock.modeling event-pools

event-merge:  ## validate the annotator's answers (data/event_labels/answers/*.jsonl) and merge them into event_labels.csv
	$(PY) -m eventshock.modeling event-merge

event-table:  ## build data/modeling/event_train.jsonl (annotated rows + capped TFN silver) and verify it is disjoint from gold/replay-check
	$(PY) -m eventshock.modeling event-table

market-context:  ## freeze the event-time market features of the replay window into data/replay/market/context.json (needs data/raw/prices)
	$(PY) scripts/build_market_context.py

impact-table:  ## build data/modeling/impact_table.jsonl + manifest (needs `make ingest-history`-style signals, data/raw/prices, both text models)
	PYTHONPATH=src $(PY) -m eventshock.modeling impact-table

train-impact:  ## select, fit, calibrate and evaluate the impact model -> models/impact/ (--dev-only OUT iterates without scoring test/live)
	PYTHONPATH=src $(PY) -m eventshock.modeling train-impact

train-event:  ## train + tune + calibrate + evaluate the event model -> models/event/ (needs data/modeling/event_train.jsonl)
	$(PY) -m eventshock.modeling train-event

gold-sample:  ## draw the blind gold sample into data/gold (refuses to overwrite labels)
	$(PY) -m eventshock.modeling gold-sample

gold-validate:  ## check the gold sheet vocabulary and completeness
	$(PY) -m eventshock.modeling gold-validate

gold-score:  ## weighted scores, crosswalk precision and agreement from the labelled gold sheet
	$(PY) -m eventshock.modeling gold-score --out data/gold/gold_scores.json

fixtures:  ## regenerate deterministic demo fixtures
	$(PY) scripts/generate_fixtures.py

types:  ## regenerate frontend API types from the FastAPI schema
	$(PY) scripts/export_openapi.py
	cd web && npm run gen:api

logo:  ## rebuild SVG logos (needs fonttools + brotli via uv)
	uv run --with fonttools --with brotli python scripts/build_logo.py

# ---- Stage 4: structured events, 2023-25 news, representation study (see docs/notes/EVIDENCE_V2.md)
.PHONY: fetch-edgar fetch-fomc events-calendar fetch-gkg-2023 bakeoff-texts bakeoff-embed bakeoff
fetch-edgar:  ## SEC filing index for the 34 issuers (needs EVENTSHOCK_SEC_CONTACT in .env) -> data/raw/edgar
	PYTHONPATH=src $(PY) -m eventshock.ingestion.edgar --symbols-file data/raw/prices/symbols.json --out data/raw/edgar

fetch-fomc:  ## FOMC decision dates (federalreserve.gov) -> data/raw/fomc
	PYTHONPATH=src $(PY) -m eventshock.ingestion.fomc --out data/raw/fomc

events-calendar:  ## offline: build the committed data/events/ tables from data/raw/edgar + data/raw/fomc
	$(PY) scripts/build_event_calendar.py

fetch-gkg-2023:  ## GKG 2023-01..2025-12, six 15-minute files per UTC day (configs/evidence_v2.yaml), resumable, zips discarded (~3 h)
	PYTHONPATH=src $(PY) -m eventshock.ingestion.gkg_fetch --master data/raw/gdelt_gkg/masterfilelist.txt --start 20230101000000 --end 20251231235959 \
		--slots 0000,0400,0800,1200,1600,2000 --filter data/raw/gdelt_gkg/filter.json --out data/raw/gdelt_gkg/filtered_2023_25.jsonl --workers 6

bakeoff-texts:  ## every labelled text the representation study encodes -> data/modeling/bakeoff_texts.jsonl
	PYTHONPATH=src $(PY) -c "from pathlib import Path; from eventshock.modeling.representations.corpus import write_texts; print(write_texts(Path('.'), Path('data/modeling/bakeoff_texts.jsonl')), 'texts')"

bakeoff-embed:  ## frozen encoders (needs the optional .venv-emb: torch + transformers) -> data/modeling/embeddings (cached, resumable)
	PYTHONPATH=src .venv-emb/bin/python -m eventshock.modeling.representations.encoders --texts data/modeling/bakeoff_texts.jsonl

bakeoff:  ## the pre-registered representation comparison -> docs/evidence/representation_bakeoff.json (main venv; needs bakeoff-embed first)
	PYTHONPATH=src $(PY) -m eventshock.modeling.representations.bakeoff

.PHONY: history-v2 ingest-history-v2 impact-table-v2 impact-study
history-v2:  ## v1 history + GKG 2023-25 -> data/history_v2 (needs `make fetch-gkg-2023`)
	$(PY) scripts/build_history_v2.py

ingest-history-v2:  ## run the pipeline over history v2 -> data/processed/history_v2/signals.jsonl
	PYTHONPATH=src $(PY) -m eventshock.pipeline --replay-dir data/history_v2 --export data/processed/history_v2

impact-table-v2:  ## the v2 impact table: protocol splits + calendar features (needs ingest-history-v2, events-calendar, prices)
	PYTHONPATH=src $(PY) -m eventshock.modeling impact-table-v2

impact-study:  ## Stage 4 study -> docs/evidence/impact_study.json (long: use `--dev-only` through python -m eventshock.modeling impact-study)
	PYTHONPATH=src $(PY) -m eventshock.modeling impact-study

.PHONY: outcome-audit
outcome-audit:  ## Stage 8 Phase 2: audit the outcome construction on a quiet-day null sample -> docs/evidence/outcome_audit.json (needs impact-table-v2, prices)
	PYTHONPATH=src $(PY) -m eventshock.modeling outcome-audit

.PHONY: severity-validity
severity-validity:  ## Stage 8 Phase 3: text-only severity scorecard vs realised outcome-v3 moves -> docs/evidence/severity_validity.json (needs impact-table-v2, prices)
	PYTHONPATH=src $(PY) -m eventshock.modeling severity-validity

.PHONY: analogue-corpus analogue-embed
analogue-corpus:  ## Stage 8 Phase 4: past news reports + realised outcome-v3 -> data/modeling/analogue_corpus.jsonl (+ texts to embed); needs impact-table-v2, prices
	PYTHONPATH=src $(PY) -m eventshock.modeling analogue-corpus

analogue-embed:  ## (.venv-emb) encode the analogue texts with e5-large -> data/modeling/embeddings (cached, resumable; ~1 h on CPU)
	PYTHONPATH=src .venv-emb/bin/python -m eventshock.modeling.representations.encoders --texts data/modeling/analogue_texts.jsonl --models intfloat/multilingual-e5-large

.PHONY: analogue-index analogue-relevance analogue-floor analogue-value analogue-eval
analogue-index:  ## Stage 8: pack the trusted analogue episodes -> data/replay/analogues/ (needs analogue-corpus + analogue-embed)
	PYTHONPATH=src $(PY) -m eventshock.modeling analogue-index

analogue-relevance:  ## Stage 8: retrieval relevance, e5 vs TF-IDF on gold-v2 -> docs/evidence/analogue_relevance.json
	PYTHONPATH=src $(PY) -m eventshock.modeling analogue-relevance

analogue-floor:  ## Stage 8: the pre-registered similarity-floor rule (dev data only) -> docs/evidence/analogue_floor.json
	PYTHONPATH=src $(PY) -m eventshock.modeling analogue-floor

analogue-value:  ## Stage 8: outcome value of retrieval vs the regime+calendar baseline -> docs/evidence/analogue_outcome_value.json (needs analogue-floor)
	PYTHONPATH=src $(PY) -m eventshock.modeling analogue-value

analogue-eval: analogue-relevance analogue-floor analogue-value  ## Stage 8: the whole retrieval evaluation

.PHONY: shock-history
shock-history:  ## Stage 8 Phase 7: empirical 1/5/21-session move distributions (quantiles only) -> data/replay/market/shock_history.json (needs prices)
	PYTHONPATH=src $(PY) -m eventshock.modeling shock-history

.PHONY: filing-events
filing-events:  ## Track F: 8-K events (exact SEC timestamps, item codes) + matched quiet-session controls -> data/modeling/filing_events.jsonl
	PYTHONPATH=src $(PY) -m eventshock.modeling filing-events

.PHONY: replay-embeddings-texts bakeoff-embed-replay replay-embeddings train-event-hybrid
replay-embeddings-texts:  ## record the exact strings the replay pipeline scores -> data/modeling/replay_event_texts.jsonl
	PYTHONPATH=src $(PY) scripts/build_replay_embeddings.py texts

bakeoff-embed-replay:  ## (.venv-emb) encode those strings with the hybrid model's encoder
	PYTHONPATH=src .venv-emb/bin/python -m eventshock.modeling.representations.encoders --texts data/modeling/replay_event_texts.jsonl --models intfloat/multilingual-e5-large

replay-embeddings:  ## pin the vectors (float16) in data/replay/embeddings/ and in the replay manifest
	PYTHONPATH=src $(PY) scripts/build_replay_embeddings.py pack

train-event-hybrid:  ## fit, calibrate, evaluate the adopted hybrid event model -> models/event/hybrid-event-v2/ (needs bakeoff evidence + embeddings)
	PYTHONPATH=src $(PY) -m eventshock.modeling.hybrid_train

.PHONY: train-impact-v2
train-impact-v2:  ## fit, calibrate, evaluate impact-v2 (document level, Stage 4 protocol) -> models/impact/impact-v2/ (long; needs impact-table-v2 and impact-study)
	PYTHONPATH=src $(PY) -u -m eventshock.modeling.impact_train_v2

.PHONY: outcomes
outcomes:  ## export the realised moves after the replay reports -> data/outcomes/replay_outcomes.json (needs impact-table-v2; read by the per-signal context endpoint only)
	$(PY) scripts/export_outcomes.py

.PHONY: rebalancer-backtest
rebalancer-backtest:  ## Module A: back-test the mock index against its equal-weight benchmark (reads git-ignored prices; writes derived data/rebalancer/backtest.json only)
	PYTHONPATH=src $(PY) scripts/build_rebalancer_backtest.py

.PHONY: freeze-check freeze-write smoke run-live run-capture capture-gdelt capture-from-replay scope-eval
freeze-check:  ## verify the final model state against docs/freeze_manifest.json (models, configs, gold, calendar, replay, evidence)
	$(PY) scripts/freeze_manifest.py --check

freeze-write:  ## rewrite docs/freeze_manifest.json: only after a deliberate, journaled change
	$(PY) scripts/freeze_manifest.py --write

smoke:  ## start the real server (replay profile), check API, model ids/hashes, evidence, stress and the UI (~2 min)
	$(PY) scripts/smoke_e2e.py

.PHONY: portfolio-betas
portfolio-betas:  ## personal portfolios: single-factor trailing beta of each issuer (Blume-adjusted, derived stats only) -> data/replay/market/betas.json (needs prices; then `make freeze-write`)
	PYTHONPATH=src $(PY) -m eventshock.modeling portfolio-betas

.PHONY: rebalancer-risk-inputs
rebalancer-risk-inputs:  ## Module A: volatility and dollar volume per stock at the window start (reads git-ignored prices; writes derived data/rebalancer/risk_inputs.json only)
	PYTHONPATH=src $(PY) scripts/build_rebalancer_risk_inputs.py

.PHONY: rebalancer-lab
rebalancer-lab:  ## Module A: compare every strategy on the replay window (reads git-ignored prices; needs rebalancer-risk-inputs; writes derived data/rebalancer/lab.json only)
	PYTHONPATH=src $(PY) scripts/build_rebalancer_lab.py
