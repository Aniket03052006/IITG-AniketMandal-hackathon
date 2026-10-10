# Impact model (`impact-v1`): can event-time information predict the size of the market's reaction?

Stage 3c, 2026-10-03. Every number below is read from `models/impact/impact-v1/model_card.json` (written by `make train-impact`), from
`docs/evidence/embedding_experiment.json` (the representation experiment), or from `data/modeling/impact_dataset.json` (the table's manifest).

> **Stage 4 update (2026-10-03): the product now serves `impact-v2`.** This document describes impact-v1 (trained on 2015-2022, 347 held-out issuer episodes), which remains in the repository as the reference and the fallback.
> impact-v2 (`models/impact/impact-v2/`, `docs/notes/EVIDENCE_V2.md` section 8) adds the event calendar (earnings timing known in advance, filings published at event time), is trained on 2015-2023 and tested on 2024-2025
> (9,897 held-out issuer episodes), beats v1 on the issuer scope by a paired interval (error −0.0036 [−0.0052, −0.0018]; 2026 news −0.0047 [−0.0080, −0.0016]) and is slightly *worse* in error on the market scope (+0.0042 [+0.0013, +0.0070], rank skill unchanged).
> It is still **experimental**: C5 (interval coverage) and C7 (placebo) fail for issuers, and the main finding of v1 stands: most of the skill is volatility regime. What is new and measured is that the calendar is a real event-specific signal and the text-model outputs add nothing once it is known.
> The v1 sections below are unchanged and still describe how the model class is built, calibrated and evaluated.

> **Final state (2026-10-03):** the lifecycle verdicts, evidence and frozen hashes for all stages are in [FINAL_MODEL_REPORT.md](FINAL_MODEL_REPORT.md); nothing here has been promoted.

## 1. The answer, in one paragraph

**Partly, and not yet well enough to call it validated.** Information available when a report appears does predict how *large* the market's
reaction is, better than guessing the average: the issuer-scope model reaches a rank correlation of **+0.12 (95% interval +0.01 to +0.22)** on
347 held-out ticker-sessions from 2022 and **+0.08 to +0.11** on 2026 news, and the market-wide scope **+0.25 (+0.07 to +0.41)**. But three
things stop it being validated. (1) **Almost all of that skill is market state, not the event**: the same models rank the window *before* the report
as well as, or better than, the window after it (placebo +0.23 vs real +0.12 for issuers; +0.34 vs +0.25 for the market). Volatility clusters, so a model that knows
"this stock is in a volatile stretch" predicts that a report published now will be followed by a large move, whatever the report says. (2) **Reading the text adds
nothing measurable**: adding the event-model and sentiment outputs, TF-IDF n-grams or sentence embeddings never improved held-out error with an interval that excludes zero.
(3) **Within an issuer the model has no ranking skill** (macro-averaged over issuers with enough held-out episodes: +0.0004). It knows *who and when is volatile*, not *which of their reports matters*.

So the product ships it as **experimental**: a calibrated, uncertainty-aware, explained, market-state-conditioned severity prior, labelled as such on every screen. Four of the eight pre-registered
acceptance checks fail on the issuer scope, and one cannot be evaluated; nothing is promoted to PRODUCTION.

## 2. What the repository could support

| Question | Answer from the data |
|---|---|
| Historical market data? | Yes: 34 issuers + `^GSPC` `^VIX` `^TNX`, daily adjusted prices 2014 to 2026-10-01 (Yahoo chart endpoint; git-ignored, not redistributed). Adjusted closes carry splits and dividends. |
| Events with timestamps? | 174k history documents (tweets 2015-19 and 2021-22, headlines 2017-20, GDELT 2026). Timestamps differ in quality: publisher time, date only, or GDELT first-seen. |
| Event to entity? | Dictionary resolver (cashtag, legal name, alias). 130k documents resolve; 31k name several issuers (excluded); 5.9k name none (market scope). |
| What is knowable at event time? | Prices up to the previous close, the report's own words and timestamp, past-only novelty. Not: later reports of the same story (outlet counts, coverage velocity), anything from the reaction session. |
| Effective sample size | The **ticker-session**, not the row: 104k rows are 10.5k issuer episodes. Held-out: 166 (val) + 181 (test) issuer episodes, 57 + 62 market sessions. Spearman standard error is about 0.07. |
| What was missing | News for 2023 to 2025 (none), and anything but 34 large caps. Not fabricated; stated as a limit. |

## 3. Target (decided, not assumed)

`docs/notes/MODELING_READINESS.md` has the evidence; the decisions, restated:

* **Event time `s0`** is the first session whose close is after publication (America/New_York, DST-aware). Weekends, holidays and after-close reports go to the next session; date-only stamps use that date;
  GDELT first-seen stamps are flagged. `pipeline/market_context.py::anchor_session` is the single implementation, used by training and serving (a test pins them equal).
* **Horizon: two sessions** (report session and the next), because earnings-type reactions land in either. Windows of 1 and 3 sessions are scored as a sensitivity check (card, "Horizon check"); the conclusion does not depend on it.
* **Unsigned severity**, `|z|`, where `z = CAR / (sigma * sqrt(2))`: `CAR` is the abnormal return against the S&P 500 and an equal-weight sector-peer average (coefficients from the 250 sessions before `s0`), `sigma` the RMS residual of the 60 sessions before `s0`
  (point-in-time normalisation removes the issuer shortcut "TSLA moves a lot"). Direction is not modelled: the scenario templates are adverse by construction, and confident sentiment matched the sign of the realised move only 53% of the time (95%: 45% to 59%): a coin flip, reported on the card, never used.
* **Market scope** (no listed issuer named): the same construction for the S&P 500's own move, `(r - mu) / sigma_trailing`.
* **Missing data**: a window with a missing return, fewer than 120 prior sessions, or beyond the price calendar is dropped with a named reason (`CENSORED`, `INSUFFICIENT_HISTORY`, `MISSING_RETURN`), never filled.
* **Corporate actions**: adjusted closes. **Benchmark**: the S&P 500 plus sector peers.

## 4. Data and reproducibility

`make impact-table` builds `data/modeling/impact_table.jsonl` (106,951 rows) and `data/modeling/impact_dataset.json`: input hashes (history signals, every price file, both text-model artifacts, both configs), split boundaries, per-scope per-split row and episode counts,
**every exclusion by reason** (issuer scope: multi-entity 19,310, no issuer 5,908 (market scope input), low link confidence 4,023, source-ticker mismatch 3,060, embargo 1,142, censored 54, unscorable or seen-by-a-text-model 1,489; market scope: embargo 53, censored 7, text stage 125),
seeds and the leakage findings. A test rebuilds nothing but verifies the manifest pins the table byte for byte; the table is deterministic (sorted, quantised, fixed seeds).
Documents that the sentiment or event model *trained on* (1,553) are excluded: their text-model output would be in-sample, unlike at serving.

Serving needs the same features without raw prices (which are not redistributable). `make market-context` freezes **derived statistics only** (trailing volatility, betas, returns, VIX and yield context; no prices, no volumes) for the replay window into
`data/replay/market/context.json`, built by the same `PriceStore` functions as the training table, rounded identically, and hash-pinned in the replay manifest.

## 5. Features (all registered `AT_EVENT_TIME`; anything else aborts training)

Issuer scope (34): 13 price-state features (trailing sigma, betas, 1/5/20-session returns, market and sector 5-session returns, volume ratio, recent-vs-usual abnormal volatility at 5 and 20 sessions, VIX level and 5-session change),
timestamp (hour, weekday, source type, four timing flags), link confidence, novelty, and the text-model outputs (9 event-class probabilities incl. `NONE`, sentiment positive/negative/magnitude). Market scope (31): 11 market-state features plus timing, novelty and the text-model outputs.
Banned and enforced: `unique_domains`, `source_count`, `coverage_velocity`, `recent_mention_count` (all measured on later reports), `episode_size`, `ticker`, `adapter`, `year`, the placeholder class (circular), and the target itself.
The old placeholder impact used `unique_domains`; the model cannot.

## 6. Evaluation (chronological only)

* **Rolling-origin folds** over the training period (2017-2022Q1, 21 quarterly folds): a fold's model sees only sessions at least five sessions before the fold starts; no episode straddles. These give the model selection and the out-of-fold predictions that define the score calibration.
* **val** (2022 Q2) is a checkpoint; **test** (2022 Q3) is scored once; **live** (2026 news, 963 issuer episodes) is scored once. All metrics are episode-level with a cluster bootstrap (episodes are resampled, never rows).
* **Ladder**, tried in order, each step adopted only if its paired out-of-fold improvement over the current choice has a bootstrap interval entirely below zero: R0 constant, R1 metadata (issuer/source/month; diagnostic only, uses a banned shortcut), R2 market-state ridge / additive boosting / full boosting,
  R3 the same plus text-model outputs, R4 R3 plus TF-IDF n-grams (diagnostic only, needs raw text at serving time).

### Issuer scope, out of fold (6,786 episodes, 2017-2022Q1) and held out

| Model | OOF error | OOF rank corr. | val+test error (347 ep.) | val+test rank corr. [95%] | placebo rank corr. | live news rank corr. (963 ep.) |
|---|---|---|---|---|---|---|
| R0 constant | 0.3060 | −0.01 | 0.2841 | n/a | n/a | n/a |
| R1 metadata | 0.3197 | +0.03 | 0.2946 | −0.10 [−0.20, −0.00] | −0.16 | +0.07 |
| R2 ridge (market state) | 0.3040 | +0.18 | 0.2834 | **+0.20 [+0.09, +0.30]** | +0.23 | +0.07 |
| R2 additive boosting | 0.3009 | +0.19 | 0.2824 | +0.10 [−0.01, +0.21] | +0.25 | +0.10 |
| **R3 full boosting (selected)** | **0.2968** | **+0.23** | 0.2842 | +0.12 [+0.01, +0.22] | +0.23 | +0.08 |
| R4 + TF-IDF (diagnostic) | 0.2989 | +0.22 | 0.2887 | +0.18 [+0.07, +0.28] | +0.16 | +0.11 |

Error is the mean absolute error of `ln(1+|z|)`; lower is better. Out of fold, the learned models beat the constant (R3-full: −0.009 [−0.011, −0.007] paired), and each rung up the ladder earned its place: the cumulative gain is small but its interval excludes zero.
On the held-out 2022 quarters the paired error difference to the constant is **+0.000 [−0.007, +0.007]**: no measurable improvement. The simple market-state ridge (R2) is as good as anything on 2022 and is the model with the best 2022 rank correlation; the selection rule (out-of-fold, pre-registered) picked R3-full instead.
Interpretation: the rank skill is real but small, comes from market state, and does not survive as lower error on a 2022 sample of this size. The held-out column carries the evidence level; the headline is the interval, not the point.

### Market scope (no listed issuer): 1,204 training sessions, 119 held-out sessions, 36 live sessions

R2 additive boosting (market state only) was selected: out-of-fold error 0.2752 vs 0.3069 for the constant; held-out rank correlation +0.25 [+0.07, +0.41], paired error difference −0.009 [−0.032, +0.013]. Its placebo rank correlation is **+0.34**: it predicts the window *before* the report better than the window after.
It is a volatility-regime meter for the S&P 500 on that date. The 36 live sessions are too few for the news check (C8 not evaluable).

### Does reading the event add anything beyond market state? (the direct test)

R3 minus R2 (same learner): out-of-fold error 0.2989 vs 0.3009 (additive) and 0.2968 vs 0.3004 (full): a gain of 0.002 to 0.004 whose paired interval excludes zero out of fold but which is absent on 2022 and on 2026 news. By event type (held-out, issuer scope) rank correlation is +0.12 to +0.20 for
every type, i.e. the same as the overall figure: the model does not rank *earnings* reports above *product* reports. The event model's types are not what the market reacts to in these data (earnings is the one class that showed a clear raw lift in the audit, and it has 12 labelled history rows).

## 7. Calibration to the 1 to 10 EventShock score (no hand-set thresholds)

The continuous prediction is kept (`predicted_severity`, in sigma units). The integer score is: prediction → its percentile among the **out-of-fold training predictions** → the `|z|` at that percentile of the realised severity distribution → the target's own fixed cut points
(0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7 sigma, `configs/modeling.yaml`). "Score 7" therefore means "predicted severity ranks in the top few percent of historical events"; it does not mean a 7-sigma move is expected.
`raw = continuous/10` so `ceil(raw*10)` reproduces the score. The uncertainty shown is empirical: what comparable out-of-fold events *actually realised* (10th to 90th percentile of their score, their median `|z|`, and the share that realised an extreme move, score ≥ 7).

What the table says (issuer scope, out of fold, 6,786 episodes): predicted score 1: median realised `|z|` 0.50, 1.5% extreme; score 3: 0.73, 4.6%; score 5: 0.87, 10.4%; score 7: 1.06, 17.6%; scores 8 to 10: 1.85, 28.5%. The base rate is 3.9%. So the ordering is clear in the training period (a score-8+ event was extreme 7 times as often as average).
On the 2022 hold-out the buckets are too sparse to confirm it (episodes concentrate in scores 1 to 3 because 2022 predictions are low; only 2 episodes score 7), the 10-90% interval over-covers (94% vs 80% nominal, a consequence of integer scores and wide buckets), and bucket order could not be assessed. Those are checks C4 and C5; both are in the card.

## 8. Explanations

The drivers are the model's own. For an additive model, baseline + the per-feature contributions equal the prediction exactly (a test pins it to 1e-9). The selected model allows interactions, so the card labels its attributions **sensitivity** (each feature moved alone from its typical value;
worst gap to the prediction 0.045 in log-severity) and the UI says so under the bars. No SHAP, no after-the-fact story: nothing is displayed that the model did not use.

## 9. Pre-registered acceptance bar (`configs/impact_model.yaml`, fixed before the first held-out run)

| | Check | Issuer | Market |
|---|---|---|---|
| C1 | held-out rank skill, 95% interval lower bound > 0 | pass (+0.014) | pass (+0.073) |
| C2 | paired error below the constant, upper bound < 0 | **fail** (+0.007) | **fail** (+0.013) |
| C3 | not worse than the market-state linear model on val and on test | pass | pass |
| C4 | score buckets ordered by realised severity | not evaluable | not evaluable |
| C5 | interval coverage within ±0.10 of nominal | **fail** (0.94) | **fail** (0.93) |
| C6 | leakage suite clean | pass | pass |
| C7 | more skill on the real window than on the placebo window | **fail** (−0.11) | **fail** (−0.09) |
| C8 | skill on 2026 publisher-timestamped news | **fail** (lower bound −0.008) | not evaluable (36 sessions) |

Neither scope meets the bar, so both are `CALIBRATED` (UI: *experimental*). One honest procedural note: the market scope was run once end to end as a smoke test before the full run and its held-out numbers were seen; no threshold, rung or rule was changed afterwards (the config's git history shows it).

## 10. Leakage controls (and the tests that exercise them)

* Feature registry: every model input must be `AT_EVENT_TIME`; unknown names are errors (`test_impact_features.py`: banned names, unregistered names, rung nesting).
* **Future invariance, three ways**: replacing every price from `s0` on with noise leaves (a) the training-table features (`future_invariance`, run over 40 events during `make impact-table`, fatal), (b) the market-scope features, and (c) the *served estimate* of a signal, bit-identical (`test_market_context.py`, `test_impact_model_loading.py`).
* **Chronology**: splits are time-ordered with a five-session embargo; rolling folds assert that training ends at least five sessions before each fold and that no episode straddles (`check_rolling_folds`, with an injected-overlap test).
* **Fit invariance**: the whole training run refits the selected model with every held-out label scrambled and requires bit-identical predictions; the calibration reference is a pure function of the out-of-fold predictions it is handed.
* `fit_step` refuses any row outside the train split.
* **Entity statistics**: no target encoding exists; `ticker` is a banned feature; issuer weight is capped at 15% of the training mass (water-filling) so the model cannot become "TSLA moves a lot".
* **Text-model leakage**: documents the sentiment or event model was trained on are excluded from impact data; a placebo-window score is reported for every model; the **hand-set** circular placeholder class never enters.
* **Train/serve parity**: the anchor, the quantised features, the text features and the calibration are the same functions in both paths; the e2e test pins the served output digest and that the impact stage changes only impact fields.

## 11. Representation experiment (embeddings, FinBERT)

Question: would richer language representations materially improve the relevant metrics? `experiments/embeddings/` (run in a throwaway `.venv-emb` with torch and transformers, which are **not** product dependencies; encoders are frozen, no fine-tuning) tested three
encoders on the same protocols: the cached `multilingual-e5-small` and `-base`, and `ProsusAI/finbert` (a financial BERT, downloaded for this experiment). The rules were written into the script before any number was seen. Results are in `docs/evidence/embedding_experiment.json`.

**Event classification** (same train rows, dev rows and gold history rows as `tfidf-lr-event-v1`; C and temperature chosen on dev log-loss; the shipped TF-IDF model scored on the very same rows; gold read once, never selected on):

| | dev log-loss (lower is better) | gold served macro-F1 | difference to TF-IDF, 95% interval | adopt? |
|---|---|---|---|---|
| TF-IDF + LR (shipped) | 0.872 | 0.388 | | |
| e5-small + LR | 0.799 | 0.337 | −0.16 to +0.08 | no |
| **e5-base + LR** | **0.719** | **0.438** | −0.09 to +0.19 | **no (interval includes 0)** |
| FinBERT + LR | 0.753 | 0.357 | −0.16 to +0.12 | no |

(The gold macro-F1 here is a re-implementation over the truth-present classes with UNCERTAIN counted wrong, so its level differs from the card's 0.325; only the paired differences are meaningful.)
All three encoders beat TF-IDF on the selection metric, e5-base clearly (−0.15 log-loss), and its gold point estimate is higher; but the pre-registered adoption rule required the paired interval on gold to exclude zero, and 280 weighted rows cannot show that. **Not integrated.**
**Second look before deciding (`experiments/embeddings/confirm_event.py`).** The e5-base model was scored against TF-IDF on every held-out event set, not only gold history (served macro-F1 of each, paired 95% interval of the difference; log-loss):
replay-pack check set (199 fresh documents) 0.549 vs 0.529 [−0.16, +0.10], log-loss 0.991 vs 0.855; gold TFN-style tweets (120) 0.476 vs 0.452 [−0.12, +0.07], 1.376 vs 1.301; gold history (280) 0.388 vs 0.438 [−0.09, +0.19], 1.122 vs 1.005; dev history, which was selected on (522) 0.434 vs 0.349 [−0.19, +0.03], 0.815 vs 0.629.
So e5-base gives consistently better *probabilities* (lower log-loss on all four sets), but the *decision* metric the product serves (committed class, abstentions counted wrong) is better on one set and worse on three, with every interval spanning zero. It does not score better where it counts, so production keeps TF-IDF: no torch dependency, no change to the event stage or to the impact features that read it.
A general multilingual sentence encoder did better than the finance-specific one. This is the most promising lead for the event classifier; confirming it needs a larger or human-adjudicated gold set (and a ~1 GB torch runtime dependency that is not worth carrying on this evidence).

**Impact** (episode-level ridge on market state + text representation vs market state alone; alpha chosen on the last fifth of the *training* period; scored on 2022 val+test, 347 issuer episodes, and 2026 live news, 963):

| Issuer scope | val+test error vs state-only (paired, 95%) | val+test rank corr. | placebo rank corr. | live news rank corr. |
|---|---|---|---|---|
| state only | | +0.19 | +0.23 | +0.08 |
| + TF-IDF | +0.005 (−0.001, +0.012) | +0.18 | +0.13 | +0.13 |
| + e5-small | +0.006 (+0.001, +0.012) | +0.14 | +0.18 | +0.12 |
| + e5-base | +0.003 (−0.002, +0.008) | +0.17 | +0.16 | +0.13 |
| + FinBERT | +0.008 (+0.002, +0.013) | +0.10 | +0.19 | +0.10 |

No representation lowers held-out error (every difference is positive: worse or no better), and none raises 2022 rank skill. On 2026 news the text variants rank slightly higher (+0.10 to +0.13 against +0.08) while error is no lower: a hint that text carries a little rank information in the served domain, too small to act on.
In the market scope the text changes nothing at all (the model selects a strong penalty and falls back to market state). **Embeddings do not belong in the impact model.**


## 12. Limits, stated plainly

* Held-out evidence is small (347 issuer and 119 market episodes) and 2022-only; live news is the served domain but a substantial share of its timestamps are first-seen crawl times.
* The target is a coincident proxy: coverage is partly a *reaction* to a move, so the model measures how large the move around a report tends to be, not a forecast made before anyone knew.
* 34 current large caps; severity does not transfer to small or distressed issuers (survivorship).
* Within-issuer ranking skill is nil; the model cannot tell an important report from a trivial one by the same company.
* Market-wide documents are mostly not market news ("Fujitsu laptop review"); the event model says so for most (they stay without impact), and the market scope's score is the same for every document on a session.
* No 2023 to 2025 news, so no out-of-sample evaluation of the news domain beyond the 2026 window.

## 12b. What the product shows

Per signal: the raw prediction (sigma units), the calibrated 1 to 10 score with the realised range of comparable events, the share of them that realised an extreme move, the lifecycle in words (placeholder rule / experimental model / validated model),
the model's own drivers, the inputs it saw, the timestamp-quality caveat, model id, artifact hash, feature schema and market-data date. Signals the model cannot score (several issuers, a weak entity link, a replay-assigned clock, no market data for that session) keep the placeholder rule, visibly, with the reason.
On the replay pack: 309 issuer and 273 market signals are model-scored, 174 keep the placeholder rule (113 not a single resolved issuer, 61 with no real timestamp), 1,574 are non-events or uncertain and get no impact. Of the 12 signals at score 7 or more, 3 come from the model and 9 from the placeholder rule
(the placeholder over-scores: the model's calibration puts 7+ at the top few percent).

## 13. Next stage

See the final engineering report: the highest-value step is not a better model class but better *labels of what matters*: earnings-calendar and surprise features (known in advance, the one class with a clear lift) and 2023 to 2025 news, so that the text can be tested against an event-specific target on enough episodes.
