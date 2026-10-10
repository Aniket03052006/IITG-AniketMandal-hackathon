# EventShock: submission checklist

Checked against `1.Submission Guidelines_External.docx.md` (local copy, git-ignored on purpose) and the problem statement. First pass **2026-10-08**; refreshed
**2026-10-09** from commit `391ea7b` (Stage 16) plus this documentation pass. Rows that were re-checked on 2026-10-09 say so. A row is **PASS** only when something in the repository (or a command run in this
pass) shows it; **TODO** means it is not done; **PARTIAL** says what is missing. Nothing here was marked PASS on trust.

## Deliverables and repository

| Requirement | Repository location | Status | Evidence / notes |
|---|---|---|---|
| Repository is **public** | `github.com/Aniket03052006/IITG-AniketMandal-hackathon` | **TODO** | An unauthenticated `GET` of the repository URL returned **HTTP 404** on 2026-10-08 and again on 2026-10-09, i.e. it is private or not visible. Make it public, then open it in a private window. A private repository is a disqualification criterion |
| Naming `<college>-<candidate-name>-hackathon` | remote `IITG-AniketMandal-hackathon` | PASS | the local folder is `IITG-Aniket-Mandal-hackathon`; the README clone command uses the remote name |
| Root `README.md` in the mandatory template | `README.md` | **PARTIAL** | header fields and sections 1-5 are present and in order (Overview, Architecture & Tech Stack, Dataset Used, Quickstart, Key Results). The college e-mail is a **placeholder to confirm**, the demo-video link and the deck link are **TODO** |
| `requirements.txt` | `requirements.txt` (pinned; `requirements.in` is the source) | PASS | a **clean** venv built with `uv pip install -r requirements.txt` (exit 0) started the server with `python src/main.py` and served the same replay digest (`078a70ae…`, 2,330 signals) |
| `LICENSE` (MIT) | `LICENSE` | PASS | MIT, 2026 Aniket Mandal |
| `src/` application, pipelines, model code | `src/eventshock/`, entry `src/main.py` | PASS | 270 tracked files under `src/` (2026-10-09) |
| `data/` with the CSV/JSON used to run the prototype, sources and assumptions documented | `data/replay/` (frozen run pack), `data/fixtures/`, `data/events/`, `data/portfolio/`, `data/live/sample_capture.jsonl`; sources in README §3 and `docs/notes/DATA_LICENSES.md` | **PARTIAL** | everything needed to **run** is committed and hash-pinned. Retraining the event and impact models needs raw data that is git-ignored by design (size, licence); `make fetch-*` rebuilds it. `data/live/sample_capture.jsonl` is tracked (re-checked 2026-10-09), as is `data/rebalancer/{backtest,lab,risk_inputs}.json` |
| `docs/presentation.pdf` (5-7 slides) | `docs/presentation.pdf` | **TODO** | not created. Slide outline from the guidelines: title, problem and approach, system design (`architecture.png`), implementation highlights, key results, domain impact, limitations |
| `docs/architecture.png` (high resolution) | `docs/architecture.png` (2400 × 1600, 8-bit RGB) + generator `scripts/make_architecture_diagram.py` | PASS (regenerated 2026-10-09, not yet committed) | Stage 16: adds the Module A lane and the 93-operation API; viewed after rendering; every box names a real module; the generator refuses text that would overflow its box |
| Plain-language diagram (extra) | `docs/architecture_simple.png` (2400 × 1590) + generator `scripts/make_simple_diagram.py` | PASS (regenerated 2026-10-09, not yet committed) | seven steps for a non-technical reader, one real headline traced to the portfolio loss; step 7 now mentions the rebalancer page |
| Component-level diagram (extra) | `docs/architecture_detailed.png` (3600 × 2644) + generator `scripts/make_detailed_diagram.py` | PASS (regenerated 2026-10-09, not yet committed) | every module, model, store and route group by real name, now including `rebalancer/` and its router; the generator computes box heights from the text so nothing overflows |
| Exact run command stated in the README | README §4 | PASS | `python src/main.py` (after `pip install -r requirements.txt` and `npm run build`); verified on a clean venv |
| Demo video, YouTube **unlisted**, link in README | README header | **TODO** | script ready: `docs/notes/DEMO_SCRIPT.md` (3 min 40 s). The case study says ≤ 5 min live; the guidelines say 10 min: stay under 5 |
| Live jury pitch ready | prototype runs from a clone; `make smoke` | PARTIAL | the app starts and every documented endpoint answers (below). The demo path was not timed against a stopwatch in this pass |
| No real S&P Global / Crisil data | `docs/notes/DATA_LICENSES.md` | PASS | public sources and synthetic positions only |
| No secrets in the repository | `.gitignore`, `.env.example` | PASS | `.env` is ignored; a pattern scan (Groq, Anthropic, AWS, GitHub, Hugging Face token shapes, private keys) of the current tree **and of the full git history** found nothing; no `.env` or key file is tracked |
| Incremental commit history | `git log` | PASS | 100 commits, newest `391ea7b` on 2026-10-09 (Stage 16). Only this documentation pass (docs, three diagrams and their generators) is uncommitted |
| Repository hygiene (no large binary/data dumps) | `git ls-files` | PARTIAL | largest tracked files: `analogues.npz` 12 MB, `event-e5-large.npz` 4.3 MB, `analogues.jsonl` 3.4 MB (pinned run data, needed for the offline demo); 78 palette-quantised screenshots. `data/raw`, `data/history*`, large modelling tables are git-ignored |
| Untracked assistant/editor config files (re-checked 2026-10-09: still untracked) | `.cursor/ .cursorrules .gemini/ .kiro/ .opencode.json .qoder/ .vscode/ .windsurfrules .mcp.json .github/ AGENTS.md GEMINI.md QODER.md` | **TODO** | not ignored and not committed; a careless `git add .` would publish them. Decide: delete, or add to `.gitignore` |
| AI-usage honesty | README (§3 labels, §13) | PARTIAL | the guidelines allow AI assistance "with integrity". The repository states that event labels were **AI-annotated**; it has **no explicit statement about AI-assisted development**. Owner's decision whether to add one (the project's git rules currently forbid AI attribution in commits) |

## Case-study requirements

| Requirement | Where | Status | Evidence / notes |
|---|---|---|---|
| ≥ 2 text sources | GDELT news metadata + Twitter Financial News posts in the replay; SEC 8-K as an optional live source | PASS | per-source counts in `GET /api/pipeline/report` and README §3 |
| Sentiment score in [−1, 1] | `pipeline/sentiment_model.py` | PASS (experimental) | `tfidf-lr-v2`; metrics in README §11 |
| Event classification | `pipeline/event_model.py` | PASS (experimental) | 8 classes + not-an-event + uncertain; fails the independent-set check, disclosed |
| Impact score 1-10 | `pipeline/impact_model.py`, `assessment/severity.py` | PASS (experimental) | trained `impact-v2` plus the transparent `severity-v2` scorecard (headline and trigger); neither validated, both labelled |
| Signals exposed by API or file | `/api/signals…`, `make ingest` | PASS | |
| Module A: tactical index rebalancer (10-20 stocks, sentiment up → weight up, dashboard of weights over time) | `src/eventshock/rebalancer/`, `configs/rebalancer.yaml`, `/rebalancer` page | PASS | 15 stocks, weights follow `sentiment.score`; back-test is within chance of a placebo (+0.19 %, 82nd percentile, 10 sessions), documented in `docs/notes/REBALANCER.md`; tests `tests/unit/test_rebalancer_*.py`, `tests/integration/test_rebalancer_api.py`, `tests/e2e/test_rebalancer_replay.py` |
| Module B: synthetic wholesale portfolio (loans, bonds, derivatives) | `data/replay/portfolio.json`, `portfolio/`, `stress/` | PASS | 103 positions: 34 equities, 41 bonds, 19 loans, 9 derivatives, USD 860.1M |
| High-impact event triggers shocks (e.g. Geopolitical & impact > 7) | `services/stress_service.py`, `configs/app.yaml: trigger_threshold: 7` | PASS | trigger is `severity ≥ 7`; a product rule, documented as such |
| Portfolio value before vs after dashboard | web `Desk`, `Stress Lab` | PASS | `POST /api/stress-test` for the Hormuz event: $860,085,066 → $822,816,166 (−$37.27M, −4.33 %) |

## Measured in this repository

Measured on 2026-10-08 on an Apple-silicon Mac under **heavy background load** (load average 8-18: other test runs and editors were active), so timings are
upper bounds. Nothing else is claimed.

| Metric | Value | How |
|---|---|---|
| Server start-up to first answered request | 45 s (loaded machine) | `python src/main.py`, polled `/api/health` |
| `GET /api/signals` (all 2,331 signals, no paging) | 2.4 s warm (first call 16.7 s), 2.65 MB | `curl` |
| `POST /api/stress-test` (one signal) | 9-11 ms | `curl` |
| `POST /api/signals/{id}/portfolio-stress` | 16 ms | local client |
| `POST /api/analyze` (rules mode, short headline) | ≈ 0.4 s | `curl` |
| Backend tests | 2,368 collected in 152 files (116 unit, 20 integration, 16 e2e) (2026-10-09) | `pytest --collect-only`; result below |
| Frontend tests | **782 passed** in 42 files (2026-10-09) | `npx vitest run` |
| Frozen state | `make freeze-check` passed: 88 files, 6 models, snapshot `replay-2026-09-30-v1` (2026-10-09) | `scripts/freeze_manifest.py --check` |
| Documented endpoints | (2026-10-08, 85 operations; the API has 93 operations since the 8 rebalancer routes were added in Stage 16 and was not re-swept) 48 GET requests (health, meta, signals, every per-signal side-car, scenarios, portfolio, portfolios, evidence, models, live, monitor, review, scope, concentration, watchlists, adjustments, feedback, lab, events/{id}/…) answered **200**; `GET /api/stress-runs` without `signal_id` answered 422 and an unknown signal id 404, as documented. POST `stress-test` (default scenario, a multi-factor scenario, the Wholesale Book v2 preset), `signals/{id}/portfolio-stress`, `analyze` and `portfolios/parse` answered 200; an empty stress body and an empty analyze text answered 422 | scripted client against the real server |
| Replay | 3,455 records → 244 quarantined, 184 exact duplicates folded → 2,330 signals (1,082 market events, 1,248 not events, 27 at severity ≥ 7) | `GET /api/pipeline/report`, Desk |

Test results for this pass: see the *Validation log* at the bottom of this file.

## Known open items (be honest in the pitch)

1. Repository is not public (above); presentation, video and e-mail are not final.
2. The uncommitted tree is large (Stage 14-15, UI re-skin, screenshots, docs): commit in small steps before submission.
3. The Desk labels its scenario *generated for this event* but shows the **catalog** Geopolitical scenario's loss (−$37.3M); `POST /api/signals/{id}/portfolio-stress` runs the **propagation-generated** scenario for the same event and returns −$42.2M. Both are real and labelled in their own screens; they are not the same scenario. Decide which the pitch quotes.
4. UI copy still says *Start with make run-live to poll GDELT* although the Stage 15 Live switch can do it at runtime; `configs/app.yaml` still comments `mode: LIVE (not implemented yet)`. Config text is covered by the freeze manifest, so it is left unchanged here.
5. No stress-formula, model or threshold has independent validation: all are labelled experimental, unvalidated priors or assumptions.
6. Live GDELT is rate-limited from this machine; a real end-to-end live poll with the SEC and GDELT sources together was not observed.
7. `GET /api/signals` returns every signal in one 2.6 MB response; fine for the demo, not for scale.

## Validation log

The 2026-10-08 rows below are the first pass. The block **Refresh 2026-10-09** lists what was re-run after Stage 16 and the documentation pass; where a row appears in both, the later one is current.

All first-pass rows were run on 2026-10-08 against the working tree described at the top (no source, config or model file was changed by this documentation pass; `make freeze-check` agrees).

| Check | Result |
|---|---|
| `make smoke` (starts the real server, checks API, served model ids and artifact hashes, evidence, stress, feedback, UI) | **passed** (exit 0) |
| `make freeze-check` | **passed**: 87 files, 6 models, snapshot `replay-2026-09-30-v1` (re-run after the last documentation edit) |
| Frontend: `npx vitest run` | **668 passed** (38 files) |
| Documentation-linked tests (`test_final_report`, `test_final_lifecycle`, `test_freeze`, `test_stage8_evidence`) re-run after all documentation edits | **25 passed** |
| Clean-environment quickstart: fresh venv, `uv pip install -r requirements.txt`, `python src/main.py` | server up, digest `078a70ae…`, 2,330 signals |
| Full backend suite (2,174 tests), run by this task | **exit 0**: 2,170 passed, 4 skipped (the progress dots; no summary line was printed), 0 failed. A separate full run started outside this task at 19:29 also exited 0 |
| Link/anchor audit of README and `docs/*.md` | no broken relative link or anchor |
| Secrets scan (tree + full history) | nothing found |
| `git check-ignore -v docs/interview/PROJECT_WALKTHROUGH.md` | ignored by `.gitignore:53 docs/interview/` |
| `docs/architecture.png` | exists, opens, 2400 × 1420, text checked by eye and by the generator's fit test |

### Refresh 2026-10-09 (Stage 16 and the documentation pass; no source, config, model or data file was changed by this pass)

| Check | Result |
|---|---|
| `make smoke` (real server, 93 operations incl. the rebalancer routes, served hashes, stress, ledger, UI) | **passed** |
| `make freeze-check` | **passed**: 88 files, 6 models, snapshot `replay-2026-09-30-v1` |
| Frontend: `npx vitest run` | **782 passed** (42 files) |
| Documentation-linked and boundary tests (`test_final_report`, `test_freeze`, `test_rebalancer_architecture`) re-run after the edits | **passed** |
| Link audit of README and `docs/*.md` (relative links) | no broken relative link |
| Diagrams | `docs/architecture.png` 2400 × 1600, `architecture_detailed.png` 3600 × 2644, `architecture_simple.png` 2400 × 1590, regenerated from their generators and viewed |
| Public repository | `GET https://github.com/Aniket03052006/IITG-AniketMandal-hackathon` still answers **HTTP 404**: still the first thing to fix |
| Full backend suite (2,368 collected), `pytest -q -x` | **exit 0**: 2,364 passed, 4 skipped, 0 failed (counted from the progress marks; no summary line was printed because of `-q -q`). It took about 50 minutes on a loaded machine |
