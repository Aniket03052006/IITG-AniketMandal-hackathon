# Event classification model (`tfidf-lr-event-v1`)

The second real NLP stage. It replaces the keyword placeholder for **event type** and, unlike the placeholder, can say "this is not a
market event" or "I am not sure". Sentiment (see [SENTIMENT_MODEL.md](SENTIMENT_MODEL.md)) is unchanged; **impact is still the
placeholder heuristic** and the stress engine is untouched. Every number below is in `models/event/tfidf-lr-event-v1/model_card.json`
(served at `GET /api/models/event`, shown on the Pipeline page) and is reproduced by `make train-event`.

## 1. Bottom line

| Question | Answer |
|---|---|
| Is it better than the placeholder? | **At telling events from non-events, yes**: F1 0.70 vs 0.49 on the gold set (our own sources), 0.73 vs 0.66 on fresh replay documents. **At naming the type, yes in aggregate but not on every class**: arg-max macro-F1 0.53 vs 0.33 (gold) and 0.62 vs 0.25 (replay check). The old rules scored 14% accuracy on the gold set because 80% of documents fell to the `MARKET_VALUATION` default. |
| Does it meet the bar we set in advance? | **No.** The pre-registered bar needs the *served* macro-F1 (every "uncertain" counts as wrong) to clear the best baseline with its whole 95% interval on both the gold set and the replay check set. It does on the replay check (0.51 [0.38, 0.55] vs 0.25) and not on the gold set (0.33 [0.26, 0.38] vs 0.33). The event-vs-not-event check passes. The card says so and the UI shows it. |
| Is it reliable per class? | No. Seven classes are asserted; `MA_CORPORATE_ACTION` is **never asserted** (dev F1 0.32 < 0.35 floor) and shows as "type uncertain". `GEOPOLITICAL` recall is 0.16 on gold; `MARKET_VALUATION` precision is 0.10 on gold history (0.67 on the replay check). Scores per class are in the card. |
| Can I trust a "Classified" label? | About 55–57% of the time on our own sources (weighted), 73% on the replay check set. The confidence shown is calibrated (ECE 0.04 on dev, 0.07 on gold), so a 60% label is wrong about 40% of the time. |
| Can I trust "not an event"? | About 88% of the time on dev; recall of real events on gold is 0.67. |

It is a weak-but-honest v1: real model, real evaluation, explicit abstention, and a documented list of what it cannot do.

## 2. What we found before building

- **The only event labels in the repo were Twitter Financial News topics**, mapped to our 8 classes by a crosswalk. A topic is not an event
  type. The audit's TF-IDF probe scored 0.89 macro-F1 on TFN's own test split and **0.16–0.30 on the gold set**. It cannot say "not an
  event", and `GEOPOLITICAL` / `PRODUCT_OPERATIONS` had **no** trainable rows at all (`docs/MODELING_READINESS.md`).
- **Most real text is not an event**: the gold set labels 55–90% of our sources' documents `NONE` (population estimate 68% for history).
  The taxonomy contract could not express that.
- **The gold set** (400 rows) is AI-annotated, frozen, evaluation-only. No human labels exist.
- ~170k unlabelled in-domain documents exist, so the missing ingredient was labels, not model capacity.

## 3. What we built and why

**Formulation.** One 9-way classifier (8 event classes + `NONE`), calibrated, plus **one decision rule on the calibrated posterior**:
commit to the arg-max only when its probability is at least 0.5 ("more likely than not", meaningful because the probabilities are
calibrated; fixed, not tuned). `NONE` → status `NO_EVENT`; an event class → `CLASSIFIED`; below 0.5, or an event class the model card
flags unreliable → `UNCERTAIN`. The taxonomy and the scenario mapping are unchanged: a non-event keeps its best-guess `category`
(the contract requires one) but the UI never presents it as a finding, and `GET /api/signals?category=` matches `CLASSIFIED` only.

**Non-events get no impact.** `NO_EVENT` and `UNCERTAIN` signals are `PARTIAL` with a stated reason and no impact score, so the
placeholder heuristic cannot turn chatter into a "severity" and the stress engine reports them `UNAVAILABLE`. Impact for events is the
unchanged placeholder (category prior + tone + corroboration), now fed the model's category.

**Model.** TF-IDF (word 1–2 grams + char 2–5 grams) → multinomial logistic regression → one-parameter temperature scaling, the same family
as sentiment. 12 candidates (preprocessing × C × class weight) are fitted on train and ranked on dev log-loss after calibration. Chosen:
normalised text, C = 10, balanced weights, T = 0.84. Reasons: ~2.3k labels do not justify a transformer, it is deterministic, byte-reproducible
and pinned to wheels that already exist for Python 3.14.

**Labels: an AI annotator, committed and disclosed.** There is no cheaper path to in-domain event labels. A Claude annotator (`ai:claude`,
blind subagents, one batch of ≤ 200 rows each) labelled 3,270 documents by the project's `docs/GOLD_LABELING_GUIDE.md` rules (including
"when unsure between a class and NONE choose NONE"). The labels, the batches' blind input and the answer files are committed
(`data/event_labels/`); the model at runtime is purely classical, so replay stays offline and deterministic. **An LLM is not called by the
product.** A second blind pass over 200 rows gives self-agreement 92% (κ 0.88): a bound on label *noise*, not on shared bias with the gold set
(same annotator family) and not an independent inter-annotator κ.

| Pool (all disjoint from gold by id **and** near-duplicate text) | Rows | Why |
|---|---|---|
| Random samples of our four history sources (top-tweets 400, stock-tweets 400, headlines 400, GDELT GKG titles 500) | 1,700 | Unbiased NONE rate; inclusion weights `N/n` give population estimates |
| Keyword-hit candidates per rare class (60 × 7) | 420 | Find rare events. The keyword class is only a search aid, never a label |
| TFN topic rows from nine weakly-mapped topics, **relabelled by the annotator** (not the crosswalk) | 950 | Where `GEOPOLITICAL`, `PRODUCT_OPERATIONS` and extra `NONE` come from |
| **Replay check set**: fresh documents of the served pack (GDELT DOC 100, GKG 60, TFN 40) | 200 | Never trained on; the closest test of what the product shows |
| Consistency re-label | 200 | Self-agreement |

Class counts (first-pass labels): NONE 1,879 · PRODUCT_OPERATIONS 534 · MARKET_VALUATION 212 · REGULATORY_LEGAL 181 · GEOPOLITICAL 113 ·
MA_CORPORATE_ACTION 113 · EARNINGS 83 · CREDIT_FUNDING 78 · MACROECONOMIC 77. Targeted pools over-represent rare classes, so dev metrics
use inclusion weights and no prior correction is applied (a known limitation).

**The TFN crosswalk silver rows were tested and not used**: adding them *raised* dev log-loss (0.896 vs 0.871). That is the audit's finding
re-measured: topic labels teach "everything is an event".

## 4. Evaluation protocol

- **Train**: 2,305 annotated rows (group-aware split by near-duplicate text). **Dev**: 765 rows (25%, weighted per stratum): selects the model,
  fits the temperature and decides which classes are flagged unreliable. Dev numbers are optimistic.
- **Held-out sets that no training or model-selection choice used**: the gold set (history 280 rows, inclusion-weighted; TFN-style 120), the
  replay check set (199 scorable of 200), and the old TFN topic test split (secondary, crosswalk labels).
- A text with no words (only links, handles, tickers) is quarantined by the pipeline, never scored; the same rule is applied in evaluation.
- Metrics: 9-class macro-F1 of the arg-max; **"as served" macro-F1** where UNCERTAIN is always wrong; event-vs-not-event F1; per-class P/R/F1,
  confusion matrix, ECE, log-loss; bootstrap 95% intervals (1,000 resamples); baselines (majority, the old keyword rules, the audit's TFN probe re-fitted).
- Pre-registered bar (in `event_train._acceptance`): served macro-F1 CI lower bound above every baseline on `gold_history` and `replay_check`,
  and event-vs-not F1 on `gold_history` not below the best baseline.

## 5. Results

Macro-F1 over nine classes (CI in brackets where shown). "As served" counts every UNCERTAIN as wrong, which is harsh by design.

| Set | n | Model, arg-max | **As served** | Old keywords | Majority | Event-vs-not F1 (model / keywords) | Committed |
|---|---|---|---|---|---|---|---|
| Dev, our sources (selected on) | 522 | 0.506 | 0.402 [0.27, 0.48] | 0.294 | 0.094 | 0.649 / 0.420 | 88% |
| Dev, TFN topic tweets | 242 | 0.507 | 0.426 [0.35, 0.51] | 0.302 | 0.071 | 0.726 / 0.695 | 77% |
| **Gold, our sources** | 280 | 0.527 [0.37, 0.60] | **0.325 [0.26, 0.38]** | 0.332 | 0.090 | **0.696 / 0.488** | 86% |
| Gold, TFN-style tweets | 120 | 0.548 | 0.442 [0.30, 0.53] | 0.356 | 0.050 | 0.774 / 0.831 | 83% |
| **Replay check (fresh pack documents)** | 199 | 0.616 [0.46, 0.69] | **0.508 [0.38, 0.55]** | 0.251 | 0.075 | **0.730 / 0.661** | 71% |
| TFN topic test (crosswalk labels, secondary) | 585 | 0.319 | 0.228 | 0.416 | 0.000 | 0.867 / 1.000 | 60% |

Reading it honestly:
- Against the old keyword rules, the model is clearly better on the replay check and on detection; on **gold-history as served** the two are
  indistinguishable (0.325 vs 0.332). The weighted gold-history estimate rests on very few rare-class rows with large weights (e.g. 4 earnings
  rows), so its intervals are wide; "not met" is the correct verdict, not "worse".
- The old TFN-trained probe scores 0.88 on its own benchmark and 0.14 on gold; this model scores 0.32 on the TFN benchmark (it disagrees with
  the crosswalk by design: a scheduling notice is "earnings" there and "not an event" here) and 0.53 on gold. **TFN numbers are not event-classification accuracy.**
- Calibration: ECE 0.06 → 0.04 on dev; 0.07 gold-history, 0.05 replay check, but 0.19 on gold-TFN and 0.25 on the TFN topic test (the TFN text
  is over-confident because the model is trained on our sources).
- On the real served pack the model commits to a type for 756 of 2,330 signals (32%), says "not an event" for 890 (38%) and "uncertain" for 684 (29%);
  the old rules gave 80% of history `MARKET_VALUATION`.

Per-class (gold history, weighted, arg-max): `MACROECONOMIC` F1 0.87, `CREDIT_FUNDING` 0.84, `REGULATORY_LEGAL` 0.84, `NONE` 0.86, `MA_CORPORATE_ACTION` 0.53,
`PRODUCT_OPERATIONS` 0.47, `GEOPOLITICAL` 0.28 (recall 0.16), `MARKET_VALUATION` 0.06, `EARNINGS` 0.00 (4 gold rows). Replay check: `CREDIT_FUNDING` 1.00 (10 rows),
`MACROECONOMIC` 0.86, `MARKET_VALUATION` 0.72, `PRODUCT_OPERATIONS` 0.56, `REGULATORY_LEGAL` 0.55, `MA_CORPORATE_ACTION` 0.50, `EARNINGS` 0.31, `GEOPOLITICAL` 0.31.

## 6. Error analysis

Replay check set (199 documents), what the product would have shown:

- **Classified correctly (examples)**: "CarMax Price Target Raised to $70.00" (market valuation 0.89), "Gujarat Themis secures $58 million private credit
  for Japanese acquisition" (credit/funding 0.95), "Bond yields rise as inflation risks fuel BSP rate hike bets" (macro 0.99), "Fox must hand over
  documents in shareholder case, judge says" (regulatory 0.78).
- **Classified wrongly (19 documents, of which 15 were annotated as non-events)**: valuation-style or corporate-news headlines get a product/operations or
  valuation label: "Boeing Demand Is Strong. Can Production Finally Catch Up?" (product 0.94), "TFI International to add investment executive to board"
  (product 0.87), "Is Meta Stock Still Cheap After Its AI-Fueled Rally?" (valuation 0.67), "Apple SVP Sells 2,399 Shares" (valuation 0.68), and
  dividend declarations, which the guide labels earnings but the model files under valuation ("JPMorgan declares $0.90 dividend"). Product/operations is the
  catch-all of the data (the annotator labelled 534 rows with it), so the model over-uses it.
- **"Not an event" for something that is one**: "Pfizer to Pay $44M to Resolve Contaminated Chantix Litigation" (regulatory/legal, called not an event at 0.52),
  "September series selloff broadens beyond largecaps" (valuation, 0.73), "Why is Meta stock surging after Muse AI launch?" (product, 0.92). Some of these
  are plausibly annotator judgement calls (valuation vs product news): the label noise bound (92% self-agreement) says roughly 1 in 12 labels is unstable.
- **Uncertain**: 29% of the pack, including every `MA_CORPORATE_ACTION` document (the class is never asserted), e.g. "Brazil broker XP surges in debut after
  $1.96 billion U.S. IPO". The UI shows the model's lean but never a type.
- **By source**: GDELT DOC titles 43% classified / 29% not an event / 28% uncertain; GKG 20 / 23 / 17 of 60; TFN tweets mostly "not an event" or uncertain.
  Tweets are the weakest, because 70–90% of them genuinely are not events and many are fragments.
- **Class confusion on gold** (the Pipeline page shows the full matrix): `GEOPOLITICAL` → `MA_CORPORATE_ACTION` (43%) or `NONE` (32%); `EARNINGS` → `NONE` (71%)
  (previews and scheduling notices are `NONE` by the guide, but results are also often missed); `PRODUCT_OPERATIONS` → `NONE` 42%.

## 7. Decisions, alternatives, and one change after seeing results

- **Rejected: a runtime LLM.** Cost and nondeterminism, breaks offline replay, and the project rule is no LLM where a classical method suffices.
  The LLM boundary is annotation only.
- **Rejected for v1: embeddings / a fine-tuned transformer.** `torch` has wheels for Python 3.14, but it would add ~200 MB of runtime dependencies, a slow
  start-up, float-level nondeterminism in a pinned replay digest, and 2.3k labels do not obviously justify it. It is the first thing to try next (section 9).
- **Also compared on dev only (a throw-away script, not shipped)**: logistic regression with C = 10/30/100, word-only features, raw text, and a linear SVM. All landed at
  dev macro-F1 0.53–0.59 (within noise of each other); we kept the pre-set grid rather than chase noise.
- **Rejected: a two-stage "is it an event?" head.** One calibrated 9-way model gives the same abstention with one calibration and one threshold.
- **A serving-policy change after the first full run (disclosed).** The first run used two thresholds tuned on dev (NO_EVENT when P(NONE) ≥ 0.64, UNCERTAIN when
  P(top | event) < 0.91). Its gold-history numbers were: as-served macro-F1 0.236 [0.17, 0.30] and coverage 0.69 — far below the baseline — because the
  precision target was unreachable and the fallback committed to only 11% of dev rows. We replaced it by the single, untuned 0.5 commit threshold, which a dev-only
  look showed has a better frontier (dev served macro-F1 0.40 vs 0.34, coverage 0.88 vs 0.71). The card from that first run is kept in
  `docs/evidence/event_first_run_two_threshold_card.json`. The gold and replay-check sets therefore did not choose the model or its training data, but they did
  see one policy iteration, and the headline numbers should be read with that in mind. The acceptance bar was not edited to pass.
- **Gold labels and replay-check labels are the same annotator family as the training labels.** The disagreement we would expect from a human is not measured.
  Human adjudication of `data/gold/adjudication.csv` (60 rows) is still outstanding and is the largest external uncertainty.

## 8. How to reproduce

```bash
make audit                 # (needs data/raw) builds data/modeling/event_silver.jsonl; skip if you only retrain
python scripts/build_history_pack.py && python -m eventshock.pipeline --replay-dir data/history --export data/processed/history   # history signals (see the script's docstring)
make ingest                # the replay signals the replay check set is drawn from -> data/processed
python -m eventshock.modeling event-pools      # blind batches -> data/event_labels/batches (refuses once labels exist)
#  ...annotate each batch into data/event_labels/answers/<batch>.jsonl:  {"label_id","event_class","secondary_class","notes"}
make event-merge           # validate vocabulary/ids, merge, self-consistency -> data/event_labels/event_labels.csv
make event-table           # data/modeling/event_train.jsonl, with a disjointness check against gold and the replay check set
python -m eventshock.modeling train-event --dev-only /tmp/dev_model   # iterate on dev alone; never scores held-out sets
make train-event           # ~2 min; the artifact and card are byte-identical on a re-run
make test                  # pytest + vitest
```

A clone can run `make train-event` and the app without the raw datasets: the label CSV, the manifest, the answers and the training table are committed.
The server refuses to start if the artifact is missing, modified (sha256 vs card) or built with another scikit-learn. There is no keyword fall-back.
Start-up is ~16 s (the pipeline re-runs over 3,455 records with two models).

Files: `configs/event_model.yaml` · `src/eventshock/pipeline/{event_model,event_card}.py` (serving, card) · `src/eventshock/modeling/{event_labels,event_cli,event_train,event_eval}.py` ·
`models/event/tfidf-lr-event-v1/` · `data/event_labels/` · `data/modeling/event_train.jsonl` · `tests/unit/test_event_{labels,train,model}.py`.

## 9. What remains

1. **Human adjudication** of the gold rows and a human second annotator on a slice of the training labels (the biggest threat to validity).
2. **More labels where the model is weak**: `EARNINGS` (56 train rows), `MACROECONOMIC` (56), `CREDIT_FUNDING` (58), `MA_CORPORATE_ACTION` (flagged), `GEOPOLITICAL` (recall 0.16).
   Active learning from the replay pack's uncertain signals is the cheapest source.
3. **A frozen sentence encoder + logistic regression** (e.g. the locally cached `multilingual-e5-small`) as an experiment, judged by the same protocol; the
   pinned-digest and start-up cost must be solved first.
4. **Prior correction** for the over-sampled rare classes, and per-source calibration (tweets vs headlines).
5. **Impact** is still a placeholder; it is the next stage and should use the event model's calibrated probabilities as input (and the market-response target in `MODELING_READINESS.md`).
6. A second label per document for multi-event headlines.
