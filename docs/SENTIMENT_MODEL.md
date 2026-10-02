# Sentiment model (`tfidf-lr-v1`)

The first real NLP stage in EventShock. It replaces the placeholder sentiment lexicon; **event classification and impact are still
placeholder rules** (`placeholder-v0`) and are labelled as such everywhere. Every number below is read from
`models/sentiment/tfidf-lr-v1/model_card.json`, which `make train-sentiment` writes and the UI shows (Data pipeline page).

## What it does

`text → prepare → TF-IDF (word 1-2gram + char 2-5gram) → multinomial logistic regression → temperature scaling → P(neg), P(neu), P(pos)`
`score = P(positive) − P(negative)` in [−1, 1] (the existing `SentimentResult` contract, unchanged). Probabilities are rounded to 4 decimals.

Why this and not a transformer: the training set is 9.4k short texts, the target is a 3-way tone label, serving is CPU-only and must be
deterministic, and a linear model is trainable in two minutes and byte-reproducible. The evaluation below also shows *where* it falls short
(our own sources), which is the evidence a bigger model would have to beat. It is a finding for the next stage, not something to guess at now.

## Data and what may reach the model

| Use | Data | Rows |
|---|---|---|
| Train | Twitter Financial News sentiment (human labels, MIT), exact-deduplicated, split by near-duplicate group (`data/modeling/sentiment.jsonl`, built by `make audit`, committed) | 9,355 |
| Select + calibrate | same source, `valid` split | 1,170 |
| Final in-domain test | same source, `test` split, scored once | 1,169 |
| External test | Financial PhraseBank (non-commercial, evaluation only, never committed, never trained on) | 4,846 |
| Our own sources | gold set: 280 history rows (inclusion-weighted) + 119 TFN-style rows, **AI-annotated**, evaluation only | |

Rules the code enforces (each has a test): only `tfn-sent-*` rows with human labels; no `placeholder_*`, `ai_*`, `human_*`, `gold*` columns; no
gold ids; no near-duplicate group across splits; the only feature is the text itself (registered `sentiment_text` in `modeling/leakage.py`);
nothing but the text is available at event time. The placeholder lexicon is never a label. The AI-generated gold labels are never training data
and never used to choose the model.

## Selection (decided before looking at test data)

16 candidates (preprocessing {raw, normalised} × C {0.3, 1, 3, 10} × class weight {balanced, none}) are fitted on `train` and ranked on `valid` by
**log-loss after a one-parameter temperature fit**, because the product consumes calibrated probabilities rather than a hard label. Winner:
normalised text (URLs and handles dropped, `$TICKER` and numbers become tokens), C = 3, unweighted, T = 1.03. All 16 are listed in the card.

## Results

| Evaluation set | n | Accuracy | **Macro-F1** (95% CI) | Placeholder lexicon | Majority | Audit probe¹ | UI-rule macro-F1² | Rank corr.³ | ECE |
|---|---|---|---|---|---|---|---|---|---|
| TFN held-out test (in domain) | 1,169 | 0.844 | **0.778** (0.749–0.805) | 0.527 | 0.262 | 0.785 | 0.764 | 0.63 | 0.024 |
| Financial PhraseBank (external) | 4,846 | 0.650 | **0.466** (0.447–0.482) | 0.412 | 0.249 | 0.540 | 0.542 | 0.36 | 0.156 |
| Gold, our own sources (AI-labelled, weighted) | 280 | 0.544 | **0.440** (0.352–0.518) | 0.296 | 0.221 | 0.504 | 0.521 | 0.28 | 0.232 |
| Gold, TFN-style (AI-labelled; 1 near-duplicate of training removed) | 119 | 0.624 | **0.588** (0.437–0.708) | 0.446 | 0.199 | 0.608 | 0.653 | 0.50 | 0.261 |

¹ The Stage-3 audit probe (raw text, class-balanced, C = 3), re-fitted by `train-sentiment` rather than quoted; it reproduces the audit's 0.7855. 
² The label the UI actually shows: negative if score ≤ −0.15, positive if ≥ +0.15, else neutral. 
³ Spearman correlation between the score and the −1/0/+1 label; the mean score per true class rises monotonically (negative < neutral < positive) on every set.

Per class on the held-out TFN test (precision / recall / F1): negative 0.80 / 0.60 / 0.69, neutral 0.86 / 0.95 / 0.90, positive 0.81 / 0.69 / 0.75.

### What this says

- **It clearly beats what it replaces.** On every set it beats the lexicon and the majority class; on the held-out set and on our own sources the model's interval
  excludes the lexicon (0.296 vs 0.352–0.518 on gold). This met the acceptance bar set in `MODELING_READINESS.md`.
- **It is not better than the audit probe on arg-max macro-F1**, and we say so: 0.778 vs 0.785 in domain, 0.466 vs 0.540 on PhraseBank, 0.440 vs 0.504 on gold. The cause is
  class weighting, not features: the probe was trained class-balanced, so it calls minority classes more often; the selected model is unweighted, so its probabilities are
  calibrated to the real class mix (ECE 0.024 in domain) but it defaults to "neutral" under doubt. Using the score with the UI's own cut (column ²) closes the gap out of domain
  (0.542 vs 0.540 on PhraseBank, 0.521 vs 0.504 on gold; in domain it is 0.764 vs 0.785). We kept the pre-registered rule rather than switching to the probe's configuration after seeing out-of-domain results. A diagnostic
  comparison of four candidates showed the same ranking power for all of them (rank correlation within 0.015 on each set), so the choice moves where the labels fall, not how well the score orders texts.
- **There is a large domain gap.** Macro-F1 falls from 0.78 (TFN) to 0.47 (PhraseBank, formal corporate news) and 0.44 (our own tweets and headlines). Rank correlation falls from 0.63 to 0.28 on gold.
  Whoever reads a sentiment score from a GDELT headline or a retail tweet should treat it as indicative.
- **Out-of-domain probabilities are over-confident.** ECE is 0.02 in domain but 0.16 to 0.26 elsewhere: the temperature was fitted on TFN. The UI's "confidence" is a statement about the model, not the text.
- **Where it fails.** Its most confident mistakes (`confident_errors` in the card, 98–99% confidence) are almost all *implicit* sentiment called neutral: "How to protect your assets ahead of Fed interest rate hikes" (annotated negative),
  "Google acquires Orbitera" (positive), "Meta to restrict children's use of Instagram … in $18bn settlement" (negative). Negative recall is the weakest (0.60 in domain, 0.19 on gold).
  Bag-of-words cannot read event consequences; that is what the event and impact stages are for, and a reason a domain-adapted model is the next sentiment step.
- **Calibration.** Temperature scaling was fitted on `valid`; on the held-out test ECE moved 0.018 → 0.024, i.e. the fit is within noise (T = 1.03 is almost the identity), so we do not claim the calibration step improved anything in domain.
  It is kept because it is cheap, honest and it made the selection criterion well defined.

## In the product

- `ModelSentimentEnricher` (`pipeline/enrich.py`) takes sentiment from the model. Event and impact are the unchanged placeholder rules, and `RiskSignal.provenance.stage_origins` records
  `{"sentiment": "MODEL", "event": "PLACEHOLDER_RULES", "impact": "PLACEHOLDER_RULES"}`; `data_origin` is `REAL_SOURCE_MIXED_NLP`. A `source_label` shipped with a document (TFN's human label)
  is never an input.
- Provenance (`SignalProvenance.sentiment`): model id/version, sha256 of the artifact, top-class confidence, `calibrated`, and **`seen_in_training`**. The 300 replay tweets come from the very dataset the model learned from, so
  most of them (261 of 290 after quarantine) are flagged in-sample; the UI says so. GDELT headlines are never in-sample. The check is exact-text only (case, punctuation, links ignored).
- **When inference cannot be done:** a document that passes validation but has no scorable words (a link, a handle, `$SPY $IWM`) is quarantined with `UNSCORABLE_TEXT` (4 of the 3,087 records in the pack) and
  appears in the pipeline report; no neutral score is invented. A missing, modified (sha256 mismatch) or version-mismatched artifact stops the server at startup with the command that fixes it.
  There is deliberately no fall-back to the lexicon.
- Impact still reads `0.2 × |sentiment|`, so impact scores of real signals moved when sentiment became real (mean |score| 0.11 → 0.19; real signals at impact ≥ 7 on a known issuer 12 → 21; all signals 33 → 44).
  The stress engine itself never reads sentiment and is unchanged (a test shows two signals differing only in sentiment give the same stress result).
- API: `GET /api/models/sentiment` returns the card (404 in the demo profile). UI: Risk Feed stage strip, Event sentiment card / provenance / audit, Data pipeline "Sentiment model" panel.

## Reproduce

```bash
make setup                 # installs numpy / scikit-learn / joblib (now runtime dependencies, pinned in requirements.txt)
make train-sentiment       # ~2 min: trains 16 candidates, selects, calibrates, evaluates, writes models/sentiment/tfidf-lr-v1/
make test                  # includes artifact integrity, determinism and the golden replay digest
```

Needs `data/modeling/sentiment.jsonl` (committed; `make audit` regenerates it byte-identically from `data/raw`). PhraseBank is only used if `data/raw/kaggle/sentiment-analysis-for-financial-news/all-data.csv` exists
(`make fetch-kaggle`); otherwise that row of the card says it was not run. Retraining reproduces the artifact and the card byte for byte (two consecutive runs compared; a test does the same on a toy corpus).
`model.joblib` is only loaded after its sha256 matches the card and the installed scikit-learn equals the version it was built with.

## Limitations

1. Trained on TFN (English tweets and headlines from financial news accounts, 65% neutral). Out of domain it is much weaker, see above.
2. The gold labels are AI-annotated and not yet human-adjudicated (60 rows are queued in `data/gold/adjudication.csv`); the gold rows measure agreement with one annotator.
3. Bag-of-words: no negation scope, sarcasm, or numeric magnitude; implicit sentiment is read as neutral.
4. Tone is not market impact. A negative headline about a competitor, or a neutral regulatory notice, can matter more than the sign suggests.
5. `seen_in_training` catches exact texts only.
6. Calibration is fitted on one domain.
7. Gold-set and PhraseBank numbers inform *whether* the model works, but one non-selection diagnostic (comparing four candidate families on them) informed the write-up; the selection itself used `valid` only.

## What stays placeholder

| Stage | Status |
|---|---|
| Sentiment | **Trained model** (this document) |
| Event classification | Placeholder keyword rules (`placeholder-v0-keywords`) |
| Impact score | Placeholder heuristic (`placeholder-v0-heuristic`), which now reads the model's tone magnitude |
| Stress engine | Real, deterministic |
