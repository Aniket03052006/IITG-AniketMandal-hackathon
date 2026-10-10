# EventShock — final model report (frozen 2026-10-03)

Every number below is read from a committed model card (`models/*/*/model_card.json`) or `docs/evidence/*.json`; `tests/unit/test_final_report.py`
fails if a quoted figure stops matching its source. The final state is pinned by `docs/freeze_manifest.json` (`make freeze-check`).
Lifecycle words are the product's own, derived from the pre-registered rules in the cards, not chosen for this report. **Nothing is validated.**

## 1. The table

| Stage | Model (served) | Training data | Evaluation | Lifecycle | Main limitation |
|---|---|---|---|---|---|
| Sentiment | `tfidf-lr-v1`: TF-IDF (word 1-2gram + char 2-5gram) → logistic regression → temperature scaling | 9,355 human-labelled finance tweets (Twitter Financial News) | Same-source test (1,169): macro-F1 **0.778** [0.749, 0.805] vs 0.528 for the lexicon rule it replaced. Other sources: PhraseBank 0.466, gold 0.440 | experimental (no pre-registered bar was written) | Trained on tweets; on news headlines macro-F1 falls to 0.44 (AI-labelled gold, n=280) and calibration is poor (ECE 0.23) |
| Event type | `hybrid-event-v2`: TF-IDF ‖ 2×e5-large vector → 9-class logistic regression → temperature scaling → commit at P ≥ 0.5, else UNCERTAIN | 2,305 AI-annotated headlines/tweets (labels by `ai:claude`, not humans); 765 dev | Served macro-F1 (uncertain counts as wrong): gold v1 0.542 [0.418, 0.660], gold v2 0.596 [0.508, 0.670], replay check 0.779 [0.655, 0.831] | **experimental**: passes the 3 TF-IDF-bar checks, **fails** the one for an evaluation set that took no part in adopting it | All evaluation labels share the annotator family of the training labels; human adjudication was not done, so shared bias is unmeasured |
| Impact | `impact-v2` (two scopes: ISSUER, MARKET): additive gradient boosting on market state, timing, event calendar and TF-IDF event probabilities, rank-calibrated to 1-10 with an interval | 2015-2023 history: 14,378 issuer episodes, 1,577 market episodes | 2024-25 held-out (issuer 9,897 episodes): Spearman **+0.168** [+0.148, +0.187]; 2026 news +0.084 [+0.013, +0.156]. Placebo (pre-event window) +0.236 exceeds the real window | **experimental** (both scopes CALIBRATED, neither PRODUCTION): ISSUER fails C5, C7; MARKET fails C5, C10, C11, with C4, C8 not evaluable | Event-specific skill is not shown: the model predicts the volatile regime and the calendar, not the news itself |
| Stress engine | Deterministic revaluation: 8 scenario templates, shocks scaled by impact (0.5-1.5×), fires at impact ≥ 7 | none (rules); synthetic book of 103 positions ($860.1M: 41 bonds, 34 equities, 19 loans, 9 derivatives) | Unit, golden-replay and API tests; positions reconcile to the P&L; no data-based calibration | not a statistical model | Scenario magnitudes are illustrative assumptions, not forecasts; first-order revaluation only |

> **Stage 13 update (2026-10-07).** The served sentiment model is now `tfidf-lr-v2` (class-balanced; macro-F1 on PhraseBank 0.466 → 0.525, in-domain unchanged within noise; full table and caveats in `docs/notes/SENTIMENT_MODEL.md` "v2"). The sentiment row above and the section below describe `tfidf-lr-v1`, which remains the **reference** model: the impact models were trained on its output, so the impact stage still reads it. Event and impact were reviewed and are unchanged. The stress engine gained opt-in mechanics and a read-only Wholesale Book v2 (`docs/notes/PORTFOLIOS.md`); the numbers in the stress row are the default book's and are unchanged.

## 2. What each model does

### Sentiment (`tfidf-lr-v1`)
* **Predicts:** negative / neutral / positive probabilities for one text; the score in [−1, 1] is P(positive) − P(negative).
* **Can use:** the headline or tweet text only.
* **Cannot use:** prices, source, issuer, article body, anything after publication.
* **Protocol:** split by near-duplicate group on the TFN data; test scored once; bootstrap 95% intervals; compared with the earlier lexicon rule.
* **Limits:** domain shift (above); AI-annotated gold sets bound noise, not shared bias; the stress engine deliberately ignores the sentiment value (tested), so sentiment does not move any P&L number.

### Event type (`hybrid-event-v2`)
* **Predicts:** one of eight event classes, `NONE` ("not an event"), or `UNCERTAIN` (abstains below P 0.5 or when the class is flagged unreliable; none are flagged today).
* **Can use:** the text, as sparse n-grams plus a frozen e5-large sentence vector. In the replay pack the vectors are hash-pinned (`data/replay/embeddings/`), so the default run needs no torch; a new text needs the optional encoder (`requirements-embed.txt`).
* **Cannot use:** article body, prices, source, issuer.
* **Protocol:** representation chosen from five fixed designs by a pre-registered paired bootstrap on pooled held-out sets (`configs/evidence_v2.yaml`, `docs/notes/EVIDENCE_V2.md`). Acceptance bar from the TF-IDF model plus a fourth check added because the sets that chose this model cannot also validate it.
* **Result:** the three inherited checks pass (gold-v1 lower bound 0.418 vs best baseline 0.332; replay check 0.655 vs 0.251; event-vs-NONE F1 0.794 vs 0.488). The independent-set check **fails by construction** until a set that took no part in adoption is scored.
* **Limits:** labels are AI-annotated; five classes have only 56-81 training rows; ECE 0.08-0.16 off the training source.
* **Human adjudication:** the 20-row queue in `data/gold_v2/adjudication_v2.csv` (disagreements between two blind AI passes) and the 60-row v1 queue were **not adjudicated by decision**. Both files are frozen, unread by any code and unchanged. See `docs/notes/EVIDENCE_V2.md` §10 for the protocol and what must be built first.

### Impact (`impact-v2`)
* **Predicts:** the *size* (not direction) of the two-session market response, log1p(|z|), z = abnormal return ÷ trailing volatility, as an EventShock score 1-10 with an empirical 10-90% interval. ISSUER scope: one resolved company's abnormal return. MARKET scope: the S&P 500's own move, for documents naming no company.
* **Can use (event-time only):** market state, timing, an `EventCalendar` (FOMC dates, SEC 8-K schedule: availability classes a/b), and the TF-IDF event model's probabilities.
* **Cannot use:** anything known only after the event (class c, refused as `POST_EVENT`), source counts, tickers, and any feature not registered `AT_EVENT_TIME` in `modeling/leakage.py`.
* **Protocol:** chronological, 5-session embargo, rolling-origin folds for selection and calibration, 2024 validation, 2025 test and 2026 news scored once; acceptance C1-C8 (`configs/impact_model.yaml`) plus C9-C11 (`configs/evidence_v2.yaml`), never edited after results.
* **Result:** ISSUER passes 9 of 11 checks, MARKET passes 6 of 11 with 2 not evaluable (35 live episodes, 100 needed). The failures that matter: realised-score intervals over-cover (0.93 vs nominal 0.80, C5) and the placebo window scores higher than the real one (C7), so the model cannot be said to read the event. The incremental-value study (`docs/notes/EVIDENCE_V2.md` §6) attributes the skill to the calendar and the volatility regime; text-model outputs add none.
* **Limits:** score 7+ is "a move that large happened about this often in similar regimes", not a forecast about this headline. Signals it cannot score (several issuers, weak entity link, replay-assigned clock) keep the labelled placeholder rule.

### Stress engine
* **Computes:** for an impact ≥ 7 signal, the scenario for its event class is scaled by impact (clamped 0.5-1.5×); per position, the most specific applicable shock wins (issuer > sector > market); equity, bond (duration × Δrates+Δspread), loan (PD/LGD expected loss) and derivative (first-order delta) revaluation; attribution sums exactly to the position change.
* **Uses:** event class, impact score, entity link, and the synthetic portfolio. **Not** the sentiment value.
* **Evidence:** deterministic (`run_id` is a hash of its inputs; two server starts produce identical results); positions reconcile to the P&L in the API smoke test and tests.
* **Limits:** shock sizes are assumptions; unresolved entities get market-wide shocks only; positions without a shock are reported uncovered, never safe.

## 3. Train/serve interaction (intentional)

The user-facing event stage serves the **hybrid**, but both impact models were fitted on the **TF-IDF** event model's probabilities. The impact stage therefore re-reads the TF-IDF model (`ImpactModelEnricher`, `impact_event_model`); feeding it the hybrid's probabilities would be a train/serve mismatch. This is visible per signal (event audit names `hybrid-event-v2`, impact audit names `impact-v2`), in `/api/meta`, and pinned by `tests/e2e/test_replay_served.py`, which also pins the whole served configuration (digest, status mix, impact mix, artifact hashes on every signal).

## 4. Lifecycle decision and what is open

| Question | Outcome | Basis |
|---|---|---|
| Event model EXPERIMENTAL → VALIDATED? | **No** | `acceptance.met = false`: the independent-set check cannot pass without a set that took no part in adoption |
| impact-v2 promoted? | **No** | no scope has every check passed (`ImpactLifecycle.PRODUCTION` not reached) |
| Sentiment | experimental | no bar existed |
| Acceptance thresholds changed? | **No** | `configs/evidence_v2.yaml` hash is pinned in impact-v2's card and checked by `make freeze-check` |

Not done, by decision: human adjudication of the gold queues, hence no independent event evaluation. Closing it needs a loader for human labels with who/when fields, a scorer that treats them as a separate set, and an honest note that 20 hard rows give a very wide interval.

Known gap: `configs/impact_model.yaml` changed after impact-v1 was trained (it gained `served_model_dir`), so its hash no longer equals the one stamped in impact-v1's card; impact-v2 pins the pre-registration file instead, which is unchanged.

## 5. Reproduce

```bash
make freeze-check     # model, config, gold, calendar, replay and evidence hashes
make test lint        # pytest + vitest, ruff + tsc
make smoke            # real server: API, model ids/hashes, evidence, stress, UI
make run              # http://127.0.0.1:8000
```


## Stage 8 addendum (2026-10-05): outcome checks that do not change any frozen model

No trained artifact, threshold or pinned digest changed. New, additive evidence: `outcome_audit.json` (the realised-outcome target audited on 60,000 quiet-day pairs; EWMA sigma adopted as `outcome-v3` for side-car layers by a pre-registered rule), `severity_validity.json` (the severity scorecard is `HEURISTIC_UNCALIBRATED` against realised moves), `analogue_relevance.json` / `analogue_floor.json` / `analogue_outcome_value.json` (e5 retrieves same-event precedent better than TF-IDF; retrieval adds no information about the realised move and so stays display evidence). Under the regime-neutral outcome-v3 the regime-plus-calendar baseline's rank skill is event-specific (+0.149 real vs -0.007 placebo, 2025 test), i.e. calendar-driven; `impact-v2` itself is unchanged and remains experimental. Details: `docs/notes/FINANCE_THEORY.md`, `docs/notes/ANALOGUES.md`.
