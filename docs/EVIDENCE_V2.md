# Stage 4: a stronger evidence base, and what it says

Every number below is read from a committed evidence file: `docs/evidence/impact_study.json` (`make impact-study`), `docs/evidence/representation_bakeoff.json` (`make bakeoff`), the model cards in `models/`,
`data/gold_v2/agreement.json` and `data/events/manifest.json`. The rules that decided what was adopted are in `configs/evidence_v2.yaml`; its sha256 is stamped into the study, the dataset manifest and the
cards. The same material is served at `GET /api/evidence` and shown on the **Model evidence** page of the app.

## 1. The answer, in one paragraph

**Reading the news adds almost nothing; knowing the calendar adds something real; most of what the impact model predicts is still the volatility regime.** With about thirteen times the held-out data (4,636 issuer
episodes in 2025 alone, against 347 in impact-v1), a model that knows *whether an earnings release is expected or was just filed* (and a few other scheduled or published facts) predicts the size of the market's reaction
better than the same model without it: paired error difference **−0.0043 [−0.0065, −0.0021]** on the 2025 test, **−0.0065 [−0.0105, −0.0029]** on 2026 news, and the block helps in **10 of 10 calendar years**. The text-model outputs
(event type, sentiment) add **nothing measurable once the calendar is known** (−0.0001 [−0.0009, +0.0008] on test; shuffling them costs 0.0001 [−0.0002, +0.0005]). Independent of the news model, an earnings 8-K moves prices **+0.64 log-severity** more than a
matched quiet session of the same issuer in the same volatility regime (AUC 0.82, every year 2014-2026), while officer changes, deals and financings barely differ from a quiet day. But the model still predicts the window *before* an event better than the window
after it (check C7: real +0.170 vs placebo +0.254), so the product keeps calling it **experimental**; nothing is promoted. Separately, a **keyword + semantic hybrid** event classifier beat the TF-IDF one on every held-out set and was integrated; it too stays experimental
because no evaluation set remains that took no part in choosing it.

## 2. What was missing, and what was added

| | Before (impact-v1) | After |
|---|---|---|
| Issuer episodes held out, chronological | 347 (2022 Q2-Q3, tweets) | **5,261 (2024) + 4,636 (2025)** news episodes, plus 963 of 2026; legacy 2022 protocol kept and reproduced exactly |
| Market-wide sessions held out | 119 | 247 + 249 |
| News after 2022 | 2026 only | **2023-2025 added** (6,460 GKG files, deterministic six-a-day sample) |
| Event information | text only (AI-labelled) | + **SEC 8-K item codes with exact acceptance times** (9,772 filings, 34 issuers) + FOMC dates |
| Gold set | 400 rows, one AI annotator, EARNINGS 14 / CREDIT 10 rows | + **gold v2**: 300 rows from 2023-2025, two independent blind passes (agreement 93.3%, kappa 0.91, same family), 20 queued for human adjudication; v1 frozen |
| Feature availability | one class | **a** known before the event, **b** published at event time, **c** known only after (refused, registered `POST_EVENT`) |
| Evaluation of "does the text/event matter" | rank skill vs a placebo | paired increments by block, per year, event type, issuer group and timestamp quality; a regime-vs-event battery; a filing-anchored event study |

Limits of the added data, stated where they bite: the 2023-2025 news is **about 6% of GDELT's flow** (six fixed 15-minute files a day), **titles only**, and part of its timestamps are GDELT first-seen times rather than publisher times
(counting an episode only when every one of its documents has a publisher clock outside trading hours leaves 76 episodes in 2026, below the 100 the pre-registered check C8 needs, so in the study C8 is "not evaluable", never a pass; the served model scores documents individually, 743 episodes, see §8). The calendar's earnings date is *inferred from the issuer's own earlier 8-K 2.02 filings*, not an announced date; the realised
earnings **surprise** needs consensus estimates, which are not free data, so it is not used (registered as a banned feature).

## 3. What a model may see: three availability classes

`modeling/leakage.FEATURE_REGISTRY` carries one class per feature; `check_features` refuses anything else.

| Class | Meaning | Examples |
|---|---|---|
| **a** known before the event | scheduled, announced ahead, or a pure function of strictly *earlier* filings | `earn_days_to_expected`, `earn_window`, `earn_days_since_last`, `fomc_s0`, `fomc_s1` |
| **b** published at event time | an accepted filing, strictly before the report's own timestamp | `f8k_earnings_24h`, `f8k_deal_24h`, `f8k_count_24h`, `f8k_hours_since_last`; on filing events, the filing's own `item_*` codes |
| **c** known only after | refused; registered `POST_EVENT` | realised EPS surprise, any filing accepted at or after the report, later 10-Q/10-K, the item codes of the 8-K the report is about when read afterwards |

Enforced by: the registry (a test asks for each banned name and requires an error), `calendar_future_invariance` (replace every filing at or after the report by decoys and require bit-identical features, fatal in the dataset build, run over 80 events),
the existing price future-invariance, group-straddle and time-order checks per protocol, and a regression gate (every impact-v1 row is reproduced exactly in the v2 table: 106,951 rows, 0 differences).

## 4. Pre-registration, and exactly what is not clean about it

`configs/evidence_v2.yaml` fixed the protocols (P1 legacy = impact-v1's split; P2 extended = train through 2023, val 2024, test 2025 scored once, live 2026 news scored once, five-session embargo), the nested chain (R0 → market state → + calendar → + text-model outputs;
ridge, additive boosting, full boosting; a rung is adopted only if its paired out-of-fold interval is entirely below zero), the representation adoption rule and the added checks C9-C11, **before any 2023-2025 episode, calendar feature, gold v2 label or v2 held-out number existed.**
Disclosures:

* `impact.fit`, `impact.folds` and `impact.chain` (a narrower hyper-parameter grid and half-yearly folds, for run time) were written into the file before the first study run but after the dataset existed. No held-out impact number had been produced.
* **A dry run of the representation comparison** on gold v1 and the replay check (before gold v2 existed, to debug the code) already showed a large early-fusion gain. After seeing it we **added** two guards (a decontaminated evaluation, a cost rule). Both only make adoption harder or cheaper and are marked as added-after in the file; the dry run's numbers were not used for any choice.
* The study was run once for the committed result. The synthetic end-to-end tests (`tests/e2e/test_impact_study_synthetic.py`) show it adopts and certifies a planted effect and refuses to certify the same data without it.
* All labels are AI-annotated by one model family. Agreement between two passes bounds noise, not shared bias.

## 5. Representation study: keywords, semantics or both

Eight frozen encoders (five dense: e5 small/base/large, bge-base, gte-base; three affect: finance tone, FinBERT, a general emotion model), a finance lexicon written for this project, and three fixed fusion designs, all trained on the same annotated rows with
hyper-parameters and temperature chosen on dev log-loss by the production rule, scored on pooled held-out sets (gold v1 history, gold v2 agreed rows, replay check: 759 rows) with a paired weighted bootstrap.

| Candidate (pooled served macro-F1 difference to TF-IDF, 95%) | Δ | decontaminated Δ | Adopt on evidence |
|---|---|---|---|
| e5-large alone | +0.043 [−0.023, +0.101] | +0.044 [−0.019, +0.104] | no |
| bge-base alone | +0.073 [+0.003, +0.134] | +0.062 [−0.013, +0.125] | no (fails the decontaminated check) |
| e5-base alone / e5-small alone / gte-base alone | −0.034 / −0.059 / −0.032 | | no |
| late fusion (e5-large) | +0.017 [−0.024, +0.059] | +0.016 [−0.032, +0.062] | no |
| late fusion (e5-base) | +0.059 [+0.013, +0.102] | +0.049 [+0.000, +0.094] | yes, weakly |
| **early fusion `[TF-IDF ‖ 2·dense]` (e5-large)** | **+0.219 [+0.175, +0.270]** | **+0.215 [+0.167, +0.269]** | **yes** |
| early fusion (e5-base) | +0.185 [+0.140, +0.231] | +0.190 [+0.136, +0.240] | yes |
| early fusion + lexicon + affect block (e5-large / e5-base) | +0.213 / +0.188 | +0.211 / +0.191 | yes (no better than early fusion alone) |

Baseline pooled served macro-F1 is 0.434; the adopted model's is 0.653. Per set, early fusion on e5-large improves gold history (+0.230 [+0.110, +0.360]), gold TFN-style (+0.144 [+0.046, +0.254]), gold v2 (+0.191 [+0.134, +0.253]) and the replay check (+0.264 [+0.167, +0.373]);
log-loss falls by 0.237, pooled ECE rises 0.036 → 0.055 (+0.019, inside the pre-registered tolerance of 0.02; it is lower on gold history and gold-TFN and higher on gold v2 and the replay check), abstention precision at equal coverage rises by 0.085.

* **Only the combination works.** Dense vectors alone, even the best, do not clear the bar; adding them to the keyword features does by a wide margin. This matches the finance-embedding literature (FinMTEB: general-benchmark rank is a poor predictor of finance performance; bag-of-words still wins some finance similarity tasks).
* **Contamination was checked, not assumed.** Dense encoders can exploit semantic near-duplicates that a token-overlap check cannot see: 31% of gold-history rows sit within cosine 0.90 of a training text. Removing them, for both models, leaves the gain unchanged.
* **Cost decided the encoder.** The rule builds hybrids on the best-dev-log-loss encoder and on the best one under a 100 ms CPU cap (e5-large costs about 105 ms per text at batch 32, 560M parameters, 2.7 GB resident; e5-base about 36 ms), then adopts the cheapest candidate that passes every check and is within 0.02 of the best pooled score. e5-base early fusion is 0.034 lower, outside the margin, so e5-large was chosen despite exceeding the cap. The frozen replay pack needs none of it at run time: its 2,324 scored strings have hash-pinned float16 vectors (4.4 MB).
* **Affect and lexicon channels did not earn their place.** The lexicon and the three affect classifiers added no measurable improvement on top of early fusion. On a 30-pair probe of finance-in-context polarity ("crushing earnings" against "a crushing debt load") the finance tone and FinBERT models get 93% right, the emotion model 90%, the shipped sentiment model 77% and the lexicon 60% (a diagnostic, never used to choose).
* **Late fusion is weaker than early fusion**, and the strongest dense-only model (bge-base, +0.073) does not generalise across every set.

**Integrated** as `hybrid-event-v2` (see `docs/EVENT_MODEL.md`): same temperature, same fixed 0.5 commit rule, same unreliable-class routing; torch is an optional dependency; impact-v1 keeps reading the TF-IDF event model's probabilities (it was trained on them) and the notices say so.
On the replay pack it classifies 41% of signals (TF-IDF: 32%), says "not an event" for 45% and abstains on 14% (29%). **It stays experimental:** gold v1, gold v2 and the replay check all fed the adoption statistic, so passing the TF-IDF model's old bar (gold history lower bound 0.417 against 0.332; replay check 0.655 against 0.251) is not independent evidence, and its card carries an explicit failing check for that.

## 6. The incremental-value study (impact)

Protocols and sizes (episodes): **P1 legacy** train 9,133 / val 166 / test 181 / live 963; **P2 extended** train 14,378 / val 5,261 / test 4,636 / live 963 (issuer); market-wide P2 1,577 / 247 / 249 / 36.

### Issuer events, extended protocol (selected by the pre-registered rule: R3s-full)

| Check | Result | Reading |
|---|---|---|
| C1 rank skill on held-out episodes | **pass**, +0.170 [+0.150, +0.191] | |
| C2 error below the constant | **pass**, −0.008 [−0.010, −0.006] | impact-v1 failed this on 347 episodes; with 9,897 it passes |
| C3 not worse than the market-state linear model | **pass** on val and on test | |
| C6 leakage suite | pass | |
| C7 more skill on the real window than on the placebo window | **FAIL**, real +0.170, placebo +0.254 | the regime still explains most of the skill |
| C8 skill on publisher-timestamped 2026 news | **not evaluable in the study** (76 episodes; an episode counts only if *every* document in it has a reliable clock); **pass on the served model**: +0.084 [+0.013, +0.156], 743 episodes with reliable documents | two units, one rule: see §8 |
| C9 regime-neutral rank skill | pass, +0.174 [+0.143, +0.202] | removes the issuer and its own volatility bucket; **not** the market-wide regime (VIX), so read with C10 |
| C10 block increment over market state | **pass**: test −0.0043 [−0.0065, −0.0021], live −0.0065 [−0.0105, −0.0029] | |
| C11 the block helps in most years | pass, 10 of 10 years | |
| C4, C5 | not part of the study; evaluated on the artifact (§8) | |

**Which block.** Calendar alone (full learner): oof −0.0063, test −0.0043, live −0.0069, all intervals below zero. Text-model outputs given the calendar: oof −0.0011 [−0.0019, −0.0004], test −0.0001 [−0.0009, +0.0008], live +0.0003 [−0.0007, +0.0015]: nothing once the calendar is known.
Without the calendar the text looks helpful out of fold (−0.0033), which is the calendar's information arriving through the event-type probabilities (mostly "earnings"). Shuffling the calendar block among episodes of the same issuer and month at prediction time costs rank skill 0.036 and error 0.0059 [0.0050, 0.0069]; shuffling the text block costs no rank skill (−0.0007) and 0.0001 [−0.0002, 0.0005] of error.
**Where.** By event type of the news episode the increment is largest for earnings (−0.041 [−0.075, −0.012], 231 episodes) and small for product/operations (−0.0039 [−0.0057, −0.0021]); by sector it is similar everywhere (−0.0016 to −0.0048), and by timestamp quality it is largest for reports published outside trading hours (off hours −0.0096 [−0.0151, −0.0048]) and smallest for GDELT first-seen stamps (−0.0027 [−0.0043, −0.0009]).

### Filing-anchored event study (Track F: 8-K filings with exact SEC acceptance times, 4,713 matched pairs)

Each filing is paired with a quiet session of the same issuer in the same volatility bucket with no filing within three sessions.

| Filing type | pairs | lift in log-severity (event − quiet) | AUC |
|---|---|---|---|
| all, excluding in-session filings | 3,636 | +0.226 [+0.208, +0.245] | 0.62 |
| **earnings (item 2.02)** | 1,084 | **+0.638 [+0.596, +0.675]** | **0.82** |
| deals (1.01, 1.02, 2.01, 5.01) | 207 | +0.064 [+0.001, +0.127] | 0.54 |
| financing (2.03, 3.02) | 119 | +0.099 [+0.013, +0.190] | 0.56 |
| officer changes (5.02) | 813 | +0.038 [+0.005, +0.072] | 0.51 |
| other (7.01, 8.01, 5.07, ...) | 2,085 | +0.126 [+0.104, +0.150] | 0.57 |

Earnings lift by year: 0.79, 0.62, 0.73, 0.69, 0.73, 0.68, 0.51, 0.62, 0.70, 0.58, 0.67, 0.50, 0.51 (2014-2026); every other type combined stays between 0.00 and 0.12 in every year.
Given state, the calendar block predicts the reaction to a filing (P2 test: −0.0233 [−0.0406, −0.0066] additive, −0.0272 [−0.0464, −0.0090] ridge); the filing's own item codes add little beyond it (−0.0035 [−0.0092, +0.0022]).

### Market-wide scope

Skill is real and larger (C1 +0.359 [+0.275, +0.439]; C2 and C3 pass; **C7 passes**, +0.058), but the calendar and text blocks do not help here (C10 fails: live +0.0127 [+0.0051, +0.0202], i.e. worse; C11 4 of 6 years): a market-wide score is a volatility-regime meter, as impact-v1 said.

### Legacy protocol

Reproduces impact-v1: C1 +0.114 [+0.008, +0.216] (v1: +0.119), C2 and C3 and C7 fail, C8 not evaluable. Nothing in the 347-episode result was a fluke of the model; what changed is the sample size.

## 7. What improved, what did not

**Improved.** The held-out sample (13×), the period covered (2023-2026), the label quality evidence (second independent pass), a model that beats the constant on a large sample (C2), a measurable and consistent gain from the structured calendar, an event classifier that beats the old one on every held-out set,
and the clarity of the evidence in the product.
**Did not improve.** Text and event-type probabilities do not help the impact model once the calendar is known; the market-wide scope gains nothing from either block; C7 still fails (the model is mostly a regime meter); affect and lexicon channels add nothing to event classification; the replay pack's live-news check still cannot be evaluated (76 reliable episodes).

## 8. impact-v2: the artifact that serves

`make train-impact-v2` fits the study's chosen design at document level (the unit the product scores) on the extended history: 145,421 document rows, 27,347 episodes, features `impact-features-v2` (v1's state, document and text-output features plus the calendar block),
the same ladder, selection rule, calibration and acceptance machinery as v1 (it runs through the same code, parameterised), with C9-C11 imported from the study. The artifact (`models/impact/impact-v2/`, 0.11 MB) pins the calendar's hashes, the
dataset's and the pre-registration's; loading it with a modified calendar is a `ConfigError`.

| | ISSUER | MARKET |
|---|---|---|
| Selected out of fold | R3s-additive (exact additive attributions) | R2-additive |
| Lifecycle | **CALIBRATED** (experimental) | **CALIBRATED** (experimental) |
| C1 rank skill (val+test) | +0.168 [+0.148, +0.187] | +0.351 [+0.266, +0.434] |
| C2 error below the constant | pass, −0.008 [−0.010, −0.006] | pass, −0.023 [−0.033, −0.014] |
| C3 not worse than market-state linear | pass | pass |
| C4 buckets ordered by realised severity | pass, +1.00 | n/a (too few buckets) |
| C5 interval coverage within 0.1 of 0.80 | **fail**, 0.93 (the intervals are too wide, i.e. conservative) | **fail**, 0.95 |
| C7 real window beats placebo | **fail**, real +0.168 vs placebo +0.236 | pass, +0.047 |
| C8 publisher-timestamped 2026 news | **pass**, +0.084 [+0.013, +0.156] (v1: +0.060 [−0.008, +0.135], fail) | n/a, 35 episodes |
| C9 / C10 / C11 | pass / pass / pass (10 of 10 years) | pass / **fail** / **fail** |

Both scopes miss at least one pre-registered check, so neither is PRODUCTION and the product keeps calling the stage *experimental*.

**Paired comparison with impact-v1** (same episodes, same targets, difference in log-severity error; negative = v2 better):

| Scope | Set | episodes | Δ error | rank skill v2 vs v1 |
|---|---|---|---|---|
| ISSUER | val+test (2024-2025) | 9,897 | **−0.0036 [−0.0052, −0.0018]** | +0.168 vs +0.141 |
| ISSUER | live (2026 news) | 963 | **−0.0047 [−0.0080, −0.0016]** | +0.100 vs +0.084 |
| MARKET | val+test | 496 | **+0.0042 [+0.0013, +0.0070]** | +0.351 vs +0.358 |
| MARKET | live | 36 | −0.0010 [−0.0130, +0.0105] | −0.017 vs +0.040 |

**What serves, and the decision.** impact-v2 replaces impact-v1 in the product (`configs/impact_model.yaml: served_model_dir`; v1 stays in the repository as the reference and as the fallback if the v2 artifact is missing). On the issuer scope (every document that names a single company) v2 is better by a paired interval on both held-out sets.
On the market scope v2 is **statistically worse in error (+0.0042) with the same rank skill**. Our own plan said v2 would serve only if at least as good; for the market scope it is not. We served the single artifact anyway because a second model per scope would need two cards, two lifecycles and two sets of attributions in
every API response and screen, and the scope's output is a rank-calibrated 1-10 score whose ordering (+0.351 vs +0.358) is unchanged; the difference is the level of the unsigned error, which the score does not show. This is a judgement call, disclosed here, on the card (`vs_previous`) and on the Model-evidence page. If it matters to you, serving v1 for market-wide signals only is a small change: the two models already
share every input.

**Two units, one C8.** The study counts an episode as publisher-timestamped only if every document in it is (76 episodes: not evaluable). The served model scores each document against its own clock, so the same pre-registered rule, applied to the 6,214 documents with reliable clocks (743 episodes), is evaluable and passes. Both are reported; neither changes the verdict, since C5 and C7 still fail.
## 9. What should happen next

1. **Human adjudication** of `data/gold_v2/adjudication_v2.csv` (20 rows) and of the 60 gold v1 rows, then a fresh blind sample scored once: the missing independent set that would let the hybrid event model and any impact model be called validated.
2. **Publisher-timestamped news for 2024-2026** (the strict episode-level reliable-clock set is 76 episodes): a full GKG pull for the reliable-timestamp fraction, or a licensed news archive, so C8 can be evaluated.
3. **Announced earnings dates** (a free calendar) in place of the inferred ones, and consensus estimates if a licence is found, to test the surprise (class c) as a *label*.
4. **A within-regime event target**: the question the data keeps pointing at is not "how big" but "bigger than this regime would give anyway", for which earnings-day residuals are the clean test.
5. Distilling the hybrid's encoder (e5-base is within 0.034 at a third of the cost) if live inference matters.

## 10. Human adjudication: protocol, state and what is missing (2026-10-03)

**State: not adjudicated, by decision.** At the final freeze, `data/gold_v2/adjudication_v2.csv` holds 20 rows with every `human_event_class` and `human_notes` cell blank, and `data/gold/adjudication.csv` holds 60 blank v1 rows. Nothing was filled, nothing was AI-substituted and labelled human, and the blind labels (`label_a`, `label_b`), their notes and the agreement report are byte-identical to the freeze (`docs/freeze_manifest.json`). Consequently the independent-set check on the hybrid event model's card still fails and the model stays *experimental*.

**The 20 queued rows** (two blind AI passes gave different classes; strata: 12 random, 5 geopolitical-keyword, 1 each credit-keyword, earnings-keyword, filing): V0007, V0029, V0032, V0048, V0065, V0077, V0096, V0100, V0102, V0175, V0182, V0184, V0198, V0203, V0214, V0218, V0229, V0234, V0252, V0275. The other 280 agreed rows fed the adoption statistic; only these 20 took no part in it, and they are hard by construction.

**Rule a human adjudicator follows** (`docs/GOLD_LABELING_GUIDE.md` applies unchanged): see only the text, not `label_a`/`label_b` or the model output when possible; label the *event the text reports*, not the price reaction; fill `human_event_class` with one of the eight classes or `NONE`; leave a row blank if undecidable, and say why in `human_notes`. A human label never overwrites `label_a`/`label_b`; the effective label is derived at scoring time and both originals stay in the file. Human labels are evaluation-only and must never enter training.

**What would still have to be built before filling the file has any effect** (no code reads `adjudication_v2.csv` today):
1. a loader that validates the vocabulary and records who labelled and when (the v2 queue has no such columns yet);
2. a scorer that evaluates the frozen artifact on the adjudicated rows as their own set, with bootstrap intervals, without refitting or changing any threshold;
3. a replacement of the hard-coded failing check in `hybrid_train.py` by a computed one. Twenty hard rows give a very wide interval, so a pass is unlikely: a fresh blind sample scored once is the stronger route.
