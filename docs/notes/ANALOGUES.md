# Historical analogues (Stage 8)

"Find past reports that look like this one, and show what the market did after them." A retrieval layer for *context and explanation*. It is **not** a score input: the pre-registered test found that it does not improve the prediction of the realised move (section 5), so it is display evidence and is labelled `RETRIEVED` / hindsight everywhere. Theory and method choices: `docs/notes/FINANCE_THEORY.md`. Pre-registration: `configs/evidence_v3.yaml`.

## 1. What is indexed

`make analogue-corpus analogue-embed analogue-index`

| item | value |
|---|---|
| source | the v2 impact table (documents, clocks, splits) + local prices (outcomes); git-ignored inputs, rebuilt by the commands above |
| corpus | 25,689 past **news** reports: 19,638 company episodes (one per ticker-session, the earliest report) and 6,051 market-scope documents (they name no listed company; they share a session outcome). Tweets are excluded (5-6 tickers, TSLA is 37% of all documents) |
| served index | **6,531 TRUSTED** rows: an exact publisher timestamp before the open or after the close, so the whole reaction window follows the report (4,811 company episodes + 1,720 market documents). The other clocks carried no more outcome signal than the placebo window (`outcome_audit.json`) |
| text | headlines only (median 93 characters): no body text is held |
| encoder | `intfloat/multilingual-e5-large`, 1024-d, `query:` prefix, 128 tokens, L2-normalised, float16 precision (the encoder already adopted for the event model; no new dependency) |
| index | brute-force cosine in NumPy (6.5k vectors; FAISS would add a dependency for nothing) |
| pack | `data/replay/analogues/`: vectors (12.3 MB) + rows (3.5 MB) + manifest with both sha256 (a modified pack stops start-up). Derived only: headline, reaction session, outcome, VIX; **no prices** |
| outcome shown | company: `outcome-v3` abnormal return (CAR in percent) and its size in own-volatility units; market-wide: the S&P 500's excess move over the reaction window |

Licences: the headlines are GDELT titles and CC0/MIT datasets (`docs/notes/DATA_LICENSES.md`); the non-commercial PhraseBank derivative is never used.

## 2. How search works (`retrieval/search.py`; every rule has a test)

1. **Routing by scope.** Company report -> company analogues. Sector report -> company analogues of that sector. Market-wide report -> market analogues. **Unresolved report -> refused** with the reason: the market-wide corpus pairs documents that name no listed company with the S&P's move, which is meaningless for a report tied to nothing.
2. **Point-in-time eligibility.** A past episode is usable only if its reaction window plus a 5-session embargo had closed before the query date (`available_from <= query date`). A future-invariance test adds later episodes (even identical to the query) and asserts the answer is unchanged.
3. **One analogue per outcome**, then **story collapse** (same ticker, within 10 sessions, cosine >= 0.92): the effective sample is distinct stories, not articles.
4. **Diversity caps:** at most 3 per company and 2 per company-month (market-wide: spread over months).
5. **Reliability bar:** at least 5 distinct episodes and 3 distinct stories above the similarity floor, else `NO_RELIABLE_ANALOGUE`. Nothing is padded; the three nearest matches are listed separately as "below the bar, not precedent". No index or no encoder for new text is `UNAVAILABLE` with the reason, never an empty answer.
6. **The yardstick.** The summary reports the share of analogues with a move of 2 sigma or more next to the same share on an ordinary day (4.9% for companies; the audit's quiet-day null excluding earnings), and says "not distinguishable from an ordinary day" unless the interval lies entirely above it.

Replay signals use the already-pinned replay vectors (no torch needed). New pasted text needs the optional encoder (`requirements-embed.txt`); without it the answer is `UNAVAILABLE`, labelled.

## 3. The similarity floor

Pre-registered rule, dev data only: the smallest grid value with event-type precision lift >= 1.3 and >= 30% of dev episodes answerable. **Chosen: 0.78** (`docs/evidence/analogue_floor.json`). Honest note: precision lift is about 5x chance at every floor (4.97 at 0.78, 5.5 at 0.86, 9.0 at 0.90), so the lift condition never binds and the rule picks the most permissive floor (97% of dev episodes answerable at 0.78, 37% at 0.84, 0.4% at 0.90). A stricter floor trades coverage for precision; e5 similarities are compressed (unrelated headlines typically score 0.70-0.80), so the similarity is shown on every row. The served floor is read from that evidence file (`similarity_floor: rule`), never typed into a config.

## 4. Retrieval quality (no invented labels) `docs/evidence/analogue_relevance.json`

Queries: the 280 doubly annotated gold-v2 titles where both blind annotators agree (unseen wording: other period and source mix). Corpus: 3,270 AI-annotated event texts. Relevant = same event-type label. Baseline: TF-IDF cosine (1-2-grams).

| queries | by chance | P@5 TF-IDF | P@5 e5-large | difference (95% bootstrap) |
|---|---|---|---|---|
| all 280 | 0.307 | 0.443 | 0.504 | +0.061 [+0.026, +0.093] |
| 149 event queries | 0.071 | 0.255 | 0.389 | +0.134 [+0.094, +0.179] |
| 267 without a corpus near-duplicate | 0.310 | 0.443 | 0.503 | +0.059 [+0.027, +0.094] |

Pre-registered rule met: e5-large is the served retriever. Caveat: "relevant" means the same kind of event under AI labels, not the same market outcome. Other measures: temporal-validity violations are 0 by test; duplicate contamination is handled by story collapse (3.8% of episodes have a same-ticker near-duplicate story within 10 sessions; 5 such pairs straddle splits).

## 5. Does retrieval add information about the realised move? **No.** `docs/evidence/analogue_outcome_value.json`

Baseline B0: ridge on market state + timing + structured calendar (the `R2s` feature set), target `log1p |z|` (outcome-v3), 19,638 company episodes, neighbour features computed strictly point-in-time. Paired MAE difference, 2,000 resamples clustered by reaction date.

| candidate vs B0 | 2025 test | 2026 live | real-minus-placebo improves |
|---|---|---|---|
| neighbour outcomes (similarity-weighted mean, n_eff, max similarity) | +0.0005 [+0.0001, +0.0009] (worse) | +0.0012 [+0.0004, +0.0019] (worse) | no |
| event-class x VIX-tercile reference class | -0.0006 [-0.0012, -0.0001] | +0.0002 [-0.0009, +0.0013] | no |

Pre-registered rule (both periods must improve and the real-minus-placebo gap must widen): **not met. No analogue-derived quantity enters the severity score.** This is reported as a failed experiment, consistent with Stage 4 (embeddings never lowered held-out impact error). The scorecard and its pre-registered benchmark are untouched.

## 6. What the severity score is, now that this is known

`docs/evidence/severity_validity.json`: the text-only scorecard does not rank realised moves out of sample (2025 +0.007 [-0.025, +0.039]; 2026 -0.021 [-0.086, +0.040]); label `HEURISTIC_UNCALIBRATED`. Both findings have the same root, shown by `outcome_audit.json`: around ordinary company headlines the market does what it does on an ordinary day (AUC 0.523 [0.512, 0.532]; 0.508 without earnings), with earnings the one clear exception (AUC about 0.80). So "what happened after similar headlines" mostly reads "an ordinary move", and the panel says exactly that.

## 7. Limitations

Headline-only text; 34 current large caps (survivorship); a 6% GDELT sample for 2023-2025 and almost no news for 2021-2022; only 6.5k trusted-clock episodes, so rare event types have few analogues (the "no reliable analogue" state is common for them); the outcome is coincident with coverage (a response proxy, not a forecast); market-wide analogues pair a session outcome with several reports; the floor rule is permissive (section 3); relevance is measured by event-type agreement with AI labels, not by market behaviour; the pack is 15.8 MB.

## 8. Reproduce

```bash
make outcome-audit severity-validity          # needs impact-table-v2 and data/raw/prices (git-ignored)
make analogue-corpus                          # corpus + texts
make analogue-embed                           # (.venv-emb) about 45 minutes on CPU, cached and resumable
make analogue-index analogue-relevance analogue-floor analogue-value
make shock-history                            # scenario reality check
make freeze-check smoke
```
