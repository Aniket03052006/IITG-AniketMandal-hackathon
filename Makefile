# EventShock — common tasks. Requires: Python >= 3.12, uv (or pip), Node >= 20.
PY := .venv/bin/python
GDELT_START ?= 20260917000000
GDELT_END ?= 20260930235959
# seconds between GDELT requests; raise it when GDELT answers 429
GDELT_THROTTLE ?= 20
PRICES_START ?= 2014-01-01
PRICES_END ?= 2026-10-02

.PHONY: audit probe gold-sample gold-validate gold-score train-sentiment train-event event-pools event-merge event-table fetch-kaggle fetch-tfn-topic fetch-prices fetch-gkg fetch-gkg-list fetch-gdelt fetch-tfn replay-pack ingest setup setup-api setup-web run dev build test test-api test-web lint fixtures types logo

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

train-sentiment:  ## train + select + calibrate + evaluate the sentiment model -> models/sentiment/ (needs data/modeling/sentiment.jsonl; ~1 min)
	$(PY) -m eventshock.modeling train-sentiment

event-pools:  ## draw the blind event-labelling batches into data/event_labels/batches (refuses to overwrite labels)
	$(PY) -m eventshock.modeling event-pools

event-merge:  ## validate the annotator's answers (data/event_labels/answers/*.jsonl) and merge them into event_labels.csv
	$(PY) -m eventshock.modeling event-merge

event-table:  ## build data/modeling/event_train.jsonl (annotated rows + capped TFN silver) and verify it is disjoint from gold/replay-check
	$(PY) -m eventshock.modeling event-table

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
