# Risk assessment

How EventShock turns a piece of unstructured text into a severity assessment, what is AI, what is data, what is deterministic, and exactly what is and is not claimed.

```
news text
  → UNDERSTANDING   event class + subtype, tone, entities, sectors, regions, asset classes, severity indicators, quotes   (AI, with rules as baseline and fallback)
  → RISK            four anchored answers (intensity, reach, certainty, direction) → fixed severity matrix → two bounded data adjustments → 1-10
  → SCENARIO        the default scenario for the assessed event class; configured shocks, labelled illustrative
  → PORTFOLIO       the deterministic stress engine: value before / after, contributions
  + evidence and a "what was known when" timeline
```

## What was wrong (severity-v1, the first version)

The first version computed severity as a **weighted average of seven bounded factors**. Measured on a 64-headline benchmark spanning routine to systemic events
(`docs/evidence/severity_baseline_v1.json`), it compressed the scale in both modes: with the language model, 30 of 64 items landed in the moderate band, nothing scored above 8,
and no item was ever extreme; in rule mode, rank agreement with the expected bands was 0.22. The causes were structural, not a tuning problem:

| cause | evidence |
|---|---|
| **Averaging bounded factors regresses to the middle.** A score of 9 needed every factor near 1. | the maximum reachable score on the benchmark was 8 (LLM) and 7 (rules) |
| **Only one factor measured the event's scale.** Event class (range 0.40-0.75) and breadth (0.25-0.85) swung under 1 point each. | per-factor swing: indicators 3.3 points, class prior 0.8, breadth 0.8 |
| **A constant factor.** Source credibility was 0.42 for every single-source report: it swung 0.0 points and only shifted the whole distribution. | min = max = 0.42 |
| **Tone counted as severity.** The score partly measured how negative the wording sounded. | tone swing 1.2 points |
| **An uncertainty discount (x0.9) shrank every score,** making the model's confidence part of how severe an event is. | design |
| **No notion of systemic scale at all.** | the top of the scale was unreachable by construction |

## What it is now: a scorecard

Severity is a **deterministic function of four anchored ordinal answers and two bounded data adjustments**. No fitted parameters, no outcome labels.

1. **Four answers describe the event** (`configs/severity.yaml`):
   * *intensity* (0-4): how severe the development is for those directly affected (routine, minor, significant, severe, critical). Breadth is *not* counted here;
   * *reach*: one issuer, a sector, a market, global;
   * *certainty*: confirmed, proposed, speculative;
   * *direction*: adverse, mixed, neutral, favourable.
2. **A fixed severity matrix.** `raw = anchor[intensity] + offset[reach]`. The five intensity anchors are the *middles of the five semantic bands* (1-2 negligible, 3-4 low, 5-6 moderate, 7-8 high,
   9-10 extreme), so every band is reachable by construction (a test asserts all ten scores are reachable) and reach moves the score within a band.
3. **Certainty and direction scale** the distance above 1: `1 + (raw - 1) x certainty x direction`. A proposal is worth less than a decision; a favourable surprise carries less downside.
4. **Two data adjustments**, each bounded and each *omitted with its reason* when its input is missing or stale: the volatility regime at the report's time (VIX, within about +-1 point), and novelty
   against earlier reports of the same issuer (+-0.4).
5. Round, clamp to 1-10.

**What is deliberately not an input:** tone, the model's confidence, the number of outlets, source reliability. They say how far to trust the report or the reading, not how big the event is. Reliability
is shown next to the score (never inside it); uncertainty widens the range but never lowers the score. Portfolio exposure is also not an input: severity is a property of the event; the relevance and the
stress engine say what it means for the book.

### How the AI contributes (and why it cannot dictate the score)

Each of the four answers is first derived by **deterministic rules** from the text (`assessment/rubric.py`): indicator levels, a monetary-amount floor, escalating and de-escalating words, the sector
vocabulary, hedge and proposal cues, indicator polarity. This *baseline* is crude but reproducible and needs no model. If a language model read the text it then answers the same four questions, and:

* an answer needs a **stated reason**, or it is ignored;
* it may move **one step** from the baseline, never more where the rules have evidence: a larger move is clamped and shown as clamped;
* one exception: where the rules found **no evidence at all** for an answer (their baseline is only a default: an unseen phrasing, no hedge word to find), the bound would cap a correct answer at a guess, so a **verbatim quote** lets the AI's answer stand there. Each field says whether its baseline was informed.

So the AI's contribution is structured (four ordinal answers), bounded, inspectable (the rules' answer, the AI's answer, its reason and quote, and the outcome are all shown), reproducible (answers are cached;
the rest is arithmetic) and labelled (**Hybrid**). The assessment also reports the rules-only score and **what the AI changed** (`ai_effect`). The model never outputs a score and never touches the stress
arithmetic.

### Evidence classes: a quote is never an inference

Every severity indicator is one of `QUOTED` (the AI's quote is a verbatim phrase of the report), `KEYWORD` (a configured cue phrase for it appears in the report) or `INFERRED` (the AI judges it present with
**no matching phrase**). An inference is kept, because a model can understand what a phrase list cannot, but it carries the AI's reason, is labelled "inferred", is never highlighted and is never shown as a
quote. (This is the fix for "inflation pressure builds" having become "persistent inflation" with no matching phrase.) Entities must appear in the text and can never become the issuer (only the entity master
can); evidence quotes must be verbatim; a quote that covers nearly the whole text is dropped; every id must be in the closed vocabulary.

### Provenance

Each part of the result carries an origin: **AI** (a language model's or trained classifier's reading), **Data** (market data, timestamps, source metadata), **Rules** (deterministic logic), **Hybrid**
(a rules baseline moved by a bounded AI adjustment) or **Assumption** (a configured judgement: matrix anchors, multipliers, scenario shocks). `RiskAssessment.provenance` lists them; the UI shows them as
small chips and a "Where each part comes from" list. Nothing is labelled "AI-generated" as a whole.

## Market data freshness

The market state is the close of a trading session. For a report, the relevant session is the **last completed session before it** (weekday calendar; exchange holidays are not modelled, which errs towards
excluding data). The state may lag that session by **at most one session**; beyond that it is **excluded and the reason is shown**, and a state dated after the report's last completed session is excluded as
something that could not have been known. Every use shows the date and the lag ("VIX 16.4 from the 2026-10-01 close, 1 session behind"). For replayed reports the state is the weekday before the reaction
session (the pipeline's features are strictly before it): the first version took the reaction date itself, overstating freshness by a session.

## Temporal integrity

The score reads only the report, the extraction of its text, the novelty and corroboration that existed at its time, and market state before it. It does not read later coverage, later filings, future
outlet counts or realised returns (`tests/unit/test_assessment_temporal.py`: six later reports change no step, no factor and not even the reliability line). `GET /signals/{id}/timeline` lists everything
(before, at and after the report) with a *used in the severity score* / *read by the reference model only* / *not used* tag on each item.

## The trained market-reaction model (reference only)

The repository does contain real outcome labels and a trained model, `impact-v2` (`HistGradientBoosting` / Ridge; there is **no** XGBoost anywhere). It fails its own pre-registered acceptance bar: a placebo
window before the news scores at least as well as the real window, so its skill is the volatility regime, not the event. It is shown in a collapsed, labelled *Reference* panel and never drives the trigger. No
labels were created and none was inferred; no supervised severity model is claimed.

## The language model

Off by default (`EVENTSHOCK_LLM=1` plus the provider's key). Groq (`openai/gpt-oss-120b` by default) or Anthropic, both over `urllib`, forced tool call, closed enums; the report text (at most 2,000
characters) is sent to the provider, the UI says so, and answers are cached by text, model and prompt version. **No key, a timeout, a rate limit, a daily quota, an outage, a refused request, a malformed answer
or a local call cap all fall back to the rule extractor, labelled** (`extraction.fallback_reason`; the UI shows "Rules (model unavailable)" and the provider's own words). A daily-quota 429 fails fast (waiting cannot
help); after any provider failure a 60 s circuit breaker sends new text straight to the rules instead of making each paste wait; a call has a 30 s total budget.

## API

`POST /api/analyze` (adds `assessment`, optional `source`), `GET /api/signals/{id}/assessment[?refine=true]`, `/evidence` (source evidence, model inference, scenario assumptions: never blended), `/timeline`,
`GET /api/stress-runs?signal_id=`, `POST /api/stress-test`, `GET /api/stress-runs/{id}`. `GET /api/meta` reports which mode is running. Feed rows carry `severity_*` (score, band, AI effect).

## Evidence: what was measured, and what was not

Benchmark: `data/benchmarks/` (pre-registered expected bands and pass criteria in its README; 64 development items, 32 held-out items, eight groups (A-H) from routine to systemic).
Results are regenerated by `python scripts/severity_benchmark.py evaluate` into `docs/evidence/severity_benchmark.json` and pinned by a test.

| run | n | min..max | spearman | within 1 band | bands (negl / low / mod / high / extreme) |
|---|---|---|---|---|---|
| severity-v1, rules (the compressed formula) | 64 | 1..7 | 0.22 | | see `severity_baseline_v1.json` |
| severity-v2, rules, **dev** | 64 | 1..10 | 0.923 | 0.984 | 16 / 15 / 17 / 7 / 9 |
| severity-v2, recorded real-model answers, **dev** (prompt v4, `gpt-oss-20b`) | 64 | 1..8 | 0.899 | 0.984 | 9 / 21 / 19 / 15 / 0 |
| severity-v2, rules, **held-out** | 32 | 1..7 | 0.391 | 0.594 | 17 / 8 / 4 / 3 / 0 |

How to read it, honestly:

* **The compression is fixed by structure.** All ten scores are reachable by construction, and the rules reach 1 and 10 on the development set with no band holding half the items.
* **The development rules numbers are optimistic.** The rule vocabulary was written by an author who had seen the development items. The held-out set was not used to write or tune a single cue, and
  there the rules fallback **does not generalise**: it under-scores unseen wording (17 of 32 read as negligible) and ranks the bands weakly (0.39). The rules are a labelled fallback, not the product;
  this is exactly why the language model exists. It was deliberately **not** tuned against the held-out set, which would end its independence.
* **The language-model result is from an earlier prompt.** The recorded answers are from prompt v4, whose level 3 / 4 definitions contradicted each other (the model never answered "critical", hence 0 extreme).
  The prompt was rewritten (v6) afterwards, but the Groq daily token quota was exhausted before a re-recording could be made, so **there is no live-model result for the shipped prompt, and the held-out set
  has never been run with a model**. The test that would guard it is written and skips until a recording for the current prompt exists. To produce it (about 90k tokens, so a fresh daily quota):
  `EVENTSHOCK_LLM_MODEL=openai/gpt-oss-120b python scripts/severity_benchmark.py record dev --fresh && ... record heldout && python scripts/severity_benchmark.py evaluate`.
* **The AI bound is chosen by evidence, on the dev set only** (`docs/evidence/severity_ai_bound_ablation.json`): on the recorded answers, a one-step bound scored 0.905 against 0.849 for two steps and 0.833 unbounded.
  The shipped variant (quote lifts the bound only where the rules have no evidence) scores 0.899 there.
* **No claim of calibration or predictive accuracy.** The benchmark expected bands are the author's judgement of how severe each headline is for the financial system (not realised outcomes); agreement with them
  measures whether the score is semantically meaningful, not whether it predicts anything.


## Stage 8 addendum: what the 1-10 score means, now tested against outcomes

The score is, and remains, a **transparent ordinal consequence scale**: four anchored answers (intensity, reach, certainty, direction) through a fixed matrix, two bounded data adjustments. It is not a price forecast, and Stage 8 tested it against realised market moves for the first time.

- **Test** (`docs/evidence/severity_validity.json`, pre-registered in `configs/evidence_v3.yaml` before any result): the text-only scorecard (rules, no VIX, no novelty, no model; unchanged) scored the headline of 19,638 past news episodes about 34 large caps; compared with the realised `outcome-v3` move (an abnormal return in own-volatility units) by rank correlation, within volatility regimes, against a placebo window before the report, and beyond a regime baseline; intervals are clustered bootstrap over reaction dates.
- **Result: `HEURISTIC_UNCALIBRATED`.** 2025 test +0.007 [-0.025, +0.039]; 2026 live -0.021 [-0.086, +0.040]; band monotonicity fails; 73-82% of these headlines are read as "no market event". A small positive correlation on 2018-2024 dev data (+0.054 [+0.036, +0.072]) does not replicate. A post-hoc market-scope extension (disclosed as such) flips sign across periods.
- **Why the data cannot settle it:** around ordinary company headlines the market behaves like an ordinary day (stratified AUC 0.523 [0.512, 0.532]; 0.508 without earnings), earnings being the one clear exception (about 0.80). A realised move is therefore not a usable label for "how serious is this headline", and a fitted severity model on these labels would learn the regime and the earnings calendar.
- **What changed in the product:** the UI states the label (Evidence page, "Outcome check" tab), nothing in `severity.yaml` or `semantics.yaml` was edited, the benchmark sets are untouched, and **historical analogues do not feed the score** (`docs/notes/ANALOGUES.md` section 5: retrieval did not improve prediction of the realised move).
- **Pending, unchanged:** no live-model recording exists for prompt `extract-v6` (provider quota); until one exists no LLM score distribution is claimed.
