# Modeling readiness report (Stage 3 prep, 2026-10-02)

Scope: is the data ready to train the sentiment, event and impact models, what is not, and what we changed. No product model was
trained. Every number below comes from `python -m eventshock.modeling audit|probe|gold-score`
(`data/modeling/audit.json`, `probe.json`, `data/gold/gold_scores.json`); rebuild with `make audit probe gold-score`.

## 1. Verdict

| Model | Ready? | Why |
|---|---|---|
| Sentiment | **Yes, for news-style text; unproven for retail chatter** | 11.7k deduplicated human labels, a leak-free re-split, and a baseline (TF-IDF + logistic regression) at **0.79 macro-F1** vs 0.53 for the placeholder lexicon. It falls to **0.54 on PhraseBank**, so the domain gap is large. |
| Event class | **Partly.** Six of eight classes have silver data; two have none | GEOPOLITICAL and PRODUCT_OPERATIONS have no trainable topic. The crosswalk is wrong often enough that it cannot be the evaluation truth. The gold set can. 40% of real chatter is "not an event", which the taxonomy cannot express. |
| Impact | **Target and evaluation protocol: yes. Signal strength: unknown and probably modest** | A defensible, point-in-time target now exists for ~104k rows (10.5k ticker-sessions). Event-time tabular features alone already reach rho 0.23 to 0.34, so a text model must beat that, not zero. Held-out sets are small (167 / 184 ticker-sessions). |

## 2. What we discovered

**Placeholder labels cannot be used as targets.** 80.6% of history signals are `MARKET_VALUATION` (the no-keyword default) and
`impact.score` is a function of the class prior. Against the gold set the placeholder event class is right on 14% of history
documents (weighted), because it never says "not an event".

**Impact data**
- 136k signals reduce to **10.5k (ticker, session) price windows**. TSLA is 47% of rows (15% after episode weighting).
- Cluster-level evidence (`source_count`, `unique_domain_count`, `coverage_velocity`) includes reports up to 72 h *after* the first
  report; `recent_mention_count` is relative to the replay clock. Both are future information at event time. `novelty_score` is
  past-only and safe. These are now registered as banned.
- Raw returns are an issuer shortcut (idiosyncratic sigma: TSLA 3.1% vs KO 1.0%). Point-in-time normalisation removes it; full-sample sigma does
  not (2020: 1.3, 2021: 1.35 vs 0.9).
- The reaction lands in the report session or the next one (earnings: mean |z| 1.26 then 1.38 vs ~0.8 at baseline), hence the two-session window. Coverage is
  also partly a reaction to a move (session -1 is elevated), so the target is a coincident "market-response proxy", which matches the existing `ImpactAssessment` wording.
- Only earnings shows a clear lift in |z| (placeholder class EARNINGS: 1.43 vs 0.89 for MARKET_VALUATION). Other classes are indistinguishable.
- Timing quality differs by source: 35% of rows are off-hours (clean), 18% pre-open (mostly clean), 34% in-session (partly contaminated), 6% date-only (Reuters/Guardian) and 7% GDELT first-seen
  (mean |z| 0.59 vs 0.95 overall: a crawl lag, the reaction often precedes `s0`).
- Source and period are confounded (top-tweets 2015-19, headlines 2018-20, stock-tweets 2021-22, GKG 2026, nothing in 2023-25). Any time split is also a source split.
- Entity resolution agrees with the source dataset's own ticker tag 83% (stock-tweets) and 91.5% (top-tweets) of the time; the disagreements are tweets about other companies. 3,060 such rows are excluded.
  Gold: the resolved ticker is the text's main subject for 72% (weighted) of resolved history rows.

**Event data**
- TFN topic: 2,466 exact duplicates (12%), 27 label conflicts, and **23% of the published validation rows have a near-duplicate in train**.
  After a group-aware re-split the leakage is 0.1%.
- The crosswalk has two structural holes and several weak topics. Gold (6 rows per topic, noisy) and a corpus check:

| Topic -> class | Gold precision | Finding |
|---|---|---|
| Earnings -> EARNINGS | 0/6 | ~70% of the topic (683/987) are scheduling notices, previews and call transcripts, not results. Results are in *Financials* (5/6) |
| Stock Movement -> MARKET_VALUATION | 2/6 | the text names the cause (earnings, recall, ruling), which is the event |
| Company / Product News -> PRODUCT_OPERATIONS | 2/6 | grab-bag (credit, M&A, filings, strikes) |
| Politics -> GEOPOLITICAL | 2/6 | mostly domestic politics, 4/6 "not an event" |
| Stock Commentary -> MARKET_VALUATION | 2/6 | opinion and promotion, 4/6 "not an event" |
| Treasuries / Corp Debt -> CREDIT | 3/6 | sovereign yields and rates mixed in |
| M&A -> MA | 4/6 | an executive hire, a regulatory review |
| Fed, Macro, Currencies, Legal, Markets, Analyst Update, IPO, Dividend | 4/6 to 6/6 | usable |

- Result: tiers revised (`topic_mapping.yaml` v3). Trainable (strong + medium) rows: MACROECONOMIC 2,697, EARNINGS 1,199, MARKET_VALUATION 885, MA 618, REGULATORY 546,
  CREDIT 294, **GEOPOLITICAL 0, PRODUCT_OPERATIONS 0**.
- **Most real text is not an event.** Gold, exact random strata (20 rows each, Wilson 95%): NONE = 90% of top-tweets (70-97%), 75% of stock-tweets (53-89%), 55% of GDELT titles (34-74%), 0% of the
  (Cramer-heavy) timestamped headlines. The 8-class taxonomy has no way to say so. We did not change the contract; the gold set carries `NONE` so abstention can be measured.

**Sentiment data**
- TFN sentiment: 11,931 rows, 206 duplicates and 15 conflicts removed, 65% neutral. Published split has 8% near-duplicates; the re-split has none.
- Representativeness: OOV against the TFN vocabulary is 7% for headlines, 13-17% for tweets and 12% for GDELT titles; our tweets are longer (128-162 vs 73 characters)
  and almost all cashtagged (83-99% vs 24%).
- Gold sentiment (history, weighted): 25% negative, 50% neutral, 25% positive; the placeholder lexicon gets 47% accuracy, i.e. below the neutral majority.
- PhraseBank (NC licence, evaluation only): the TFN-trained baseline gets 0.54 macro-F1, the lexicon 0.41.

## 3. What we changed

- New package `src/eventshock/modeling/` (config, text identity, corpora loaders, market/impact target, splits, leakage checks, gold set, probes, CLI); `configs/modeling.yaml`.
- `configs/topic_mapping.yaml` v3 and `pipeline/topics.py`: per-topic `tier` and `rationale`, `trainable()`; tiers demoted after the gold review.
- Prices refetched from 2014-01-01 (`Makefile`: `PRICES_START`). `Makefile`: `audit`, `probe`, `gold-sample`, `gold-validate`, `gold-score`.
- `requirements-ml.in/.txt` and an `ml` extra (numpy, scikit-learn; probes only). `pyproject.toml`: ruff E501 relaxed for `modeling/`.
- Gold set in `data/gold/` (400 rows, blind, deterministic, labelled; adjudication and consistency sheets), `docs/GOLD_LABELING_GUIDE.md`.
- Docs: `DATA_LICENSES.md` (derived data), `PROJECT_JOURNEY.md`, this report, `CLAUDE.md` repo state.
- Not changed: the pipeline, the `RiskSignal` contract, the API, the UI.

## 4. What data is actually usable

| Use | Data | Rows | Caveat |
|---|---|---|---|
| Sentiment train / valid / test | TFN sentiment, re-split by near-duplicate group | 9,355 / 1,170 / 1,169 | tweets from news accounts; neutral-heavy |
| Sentiment out-of-domain | gold sentiment (400, AI-annotated), PhraseBank (4,846, eval only) | | gold is the only check on our own sources |
| Event silver (train) | TFN topic, strong + medium tiers, 6 classes | 4,963 train rows (strong + medium, after the tier change) | no GEOPOLITICAL / PRODUCT_OPERATIONS; topic is not event type |
| Event truth | gold set (400; 280 history + 120 TFN) | | AI-annotated; 60 rows queued for human adjudication |
| Impact train / val / test | history signals with the target | 69,647 / 8,612 / 7,380 rows (9,153 / 167 / 184 ticker-sessions) | the **effective** size is the ticker-session; val and test are tweets only |
| Impact live-like test | GDELT GKG, Feb-Sep 2026 | 17,079 rows (965 ticker-sessions) | news only, first-seen clocks, noisier target; evaluate once |
| Not usable as labels | placeholder event / impact / sentiment of the history signals | 136k | circular |
| Dropped from impact | multi-entity 19,310, no issuer 5,908, link < 0.8 4,023, dataset-ticker mismatch 3,060, censored 54, embargo 1,142 | | |

## 5. Major risks and limitations

1. **Small held-out sets.** 167 and 184 ticker-sessions give a Spearman standard error near 0.07. Use rolling-origin pooling and report intervals.
2. **Volatility clustering, not leakage, explains most tabular skill.** The tabular probe predicts the placebo window nearly as well as the real one (section 6). The text model must add skill over it *and* show none on the placebo.
3. **Domain shift.** Train on 2015-2022 tweets and headlines; the only recent test is GDELT titles, whose timestamps and entity resolution are weaker. Live-like skill is measured on a different target quality.
4. **Survivorship.** The universe is 34 current mega-caps; severity is calibrated for them and does not transfer to small or distressed issuers.
5. **AI-annotated gold.** Self-consistency is high (event 97.5% agreement, kappa 0.97; sentiment 90%, kappa 0.85), but it is the same annotator, so it bounds noise and says nothing about shared bias. Calendar notices and previews are labelled NONE; a different convention would change the EARNINGS numbers.
6. **Gold is small per cell.** 6 rows per topic; the tier demotions are directional. Rare classes in the history sample come from keyword hits, so they measure the placeholder's precision, not class prevalence.
7. **The sample is frozen** against mapping v2; re-sampling would pick different disagreement rows.
8. **Event time vs serving.** At serving time `source_count` is 1; any corroboration feature has to be recomputed point-in-time by a streaming job.
9. **Date-only and first-seen timestamps** make roughly 13% of impact rows timing-ambiguous; they carry a `timing` flag and should be reported separately.

## 6. Baseline numbers the models must beat (audit probes, not product models)

Sentiment, re-split test (macro-F1 / accuracy): majority 0.26 / 0.65; placeholder lexicon 0.53 / 0.68; **TF-IDF + logistic regression 0.79 / 0.84**. PhraseBank (out of domain): 0.54 / 0.66.
The published TFN split scores 0.77, so near-duplicate leakage did not inflate sentiment.

Event, re-split TFN test on the trainable tiers (6 classes, macro-F1 / accuracy): majority 0.10 / 0.41; placeholder keywords 0.55 / 0.50; **TF-IDF + logistic regression 0.89 / 0.92**
(published validation split: 0.92; near-duplicate leakage adds about 3 points). On the **gold set** the same classifier scores **0.30 macro-F1 / 40% accuracy on the TFN rows and 0.16 / 10% on our own sources**
(weighted): it learned TFN's topics, not event types, and it cannot say NONE or predict two of the classes. This gap is the main reason TFN numbers must never be reported as event-classification accuracy.

Impact (episode-weighted, tabular event-time features only, no text), Spearman and top-decile lift:

| Split | Real target (abs z) | Placebo window |
|---|---|---|
| val (167 ticker-sessions) | +0.23, lift 1.45 | +0.17, lift 1.39 |
| test (184) | +0.34, lift 1.96 | +0.15, lift 1.30 |
| live (965) | +0.07, lift 1.35 | +0.24, lift 2.18 |

Metadata only (issuer, source, calendar month; no text, no prices): +0.09 on test and +0.20 on live for the target; +0.05 and +0.08 on the placebo. The live row is the warning: first-seen
timestamps misalign the target, so a model there looks worse on the real window than on the placebo.

Gold (history, weighted): placeholder / naive-Bayes event accuracy 14% / 9%; sentiment accuracy 47% / 56%; the TF-IDF probe 10% (event) and 56% (sentiment, macro-F1 0.50). The number to beat for event is not accuracy
but macro-F1 on non-NONE classes plus abstention quality.

## 7. Approach per model

**Sentiment.** Train on TFN (re-split); calibrated TF-IDF (word 1-2 + char 2-5) logistic regression as the baseline, `score = p_pos - p_neg`.
Select on TFN valid; report TFN test, PhraseBank, and the gold set (history rows) separately. If gold shows a large gap on retail chatter, add a small
financial-domain transformer fine-tune (check py3.14 wheels first) and consider self-training on in-domain pseudo-labels; PhraseBank stays evaluation-only.
Acceptance: beats the lexicon and majority on gold with a non-overlapping interval, and ECE is reported.

**Event.** Two-stage: (1) an "is this an event" abstention head, trained from gold-adjacent supervision and keyword-seeded positives; (2) the 8-class head. Train on strong + medium tiers
plus keyword-gated candidates for GEOPOLITICAL (Politics topic + conflict/sanction/tariff terms) and PRODUCT_OPERATIONS (Company/Product News + launch/recall/outage/strike terms),
whose precision is then measured on gold before use. Evaluation truth is the gold set only; TFN numbers are secondary. Report per-class precision/recall, abstention rate, and the confusion
matrix. Expect the TFN score (0.9) to be far above the gold score; the gap is the finding.

**Impact.** Target `|z|` and score as defined in `configs/modeling.yaml` (two-session CAR, point-in-time two-factor model, fixed cut points; `ImpactAssessment.raw` is a monotone rescale
of the continuous severity so `ceil(raw * 10)` reproduces the score). Ladder of models, each evaluated by rolling-origin monthly folds with a 5-session embargo, then the locked test and live sets:
(0) constant, (1) metadata-only, (2) event-time tabular (the probe), (3) tabular + event-class probabilities (out-of-fold) + sentiment magnitude, (4) + text embedding.
Gradient boosting with episode weights, issuer share capped, metrics macro-averaged by issuer, bootstrap by ticker-session. A model is "better" only if it beats (2) on val, test **and** has no extra skill on the placebo.
Report timing strata (off-hours, in-session, date-only, first-seen) separately.

## 8. What should happen next

1. Human adjudication of `data/gold/adjudication.csv` (60 rows; overrule in `human_*`), then `make gold-score`; expand to 600 if the crosswalk numbers move.
2. Add GEOPOLITICAL / PRODUCT_OPERATIONS silver data via keyword-gated topic rows; measure the gate on gold.
3. Train the sentiment baseline properly (calibration, ECE) and score it on gold and PhraseBank; decide on a transformer.
4. Build the earnings-calendar feature (earnings is the only class with a clear impact lift, and its dates are known in advance): derive it from the scheduling notices, which the audit showed are ~70% of the TFN "Earnings" topic.
5. Impact ladder (0-4) with rolling-origin evaluation; keep the live GKG test for last.
6. Replace the placeholder enricher behind the existing `Enricher` protocol only after each stage clears its acceptance bar.

## Appendix: impact target (one paragraph)

`AR_k = r_k - a - b*m_k - c*p_k` (market `^GSPC`, equal-weight sector peers ex-self; `a, b, c` from the 250 sessions before `s0`), `CAR` over sessions `s0..s0+1`,
`z = CAR / (sigma * sqrt(2))` with `sigma` the RMS residual of the 60 sessions before `s0`; severity `|z|`; score `= 1 + #{cut points <= |z|}` with cut points 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7.
`s0` is the first session whose close is after publication (America/New_York, DST-aware; weekends and after-hours go to the next session). Score 7 or more is a 3-sigma idiosyncratic move:
3.2% of ticker-sessions (4.3% of rows), which fits "impact above 7 triggers a stress test". Eligibility: one resolved issuer, link confidence at least 0.8, the source's own ticker tag (if any) agrees,
at least 120 prior sessions, a complete window.
