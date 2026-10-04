# Risk assessment (Stage 7)

What EventShock does with a piece of unstructured text, how it decides how serious it is, and exactly what is and is not claimed.

```
news text
  → AI understanding   (event class + subtype, tone, entities, sectors, regions, asset classes, severity indicators, verbatim evidence quotes)
  → risk signal        (a transparent severity score 1-10 from explicit, configurable weights; a sensitivity range; the factors that built it)
  → scenario           (the default scenario for the ASSESSED event class; configured shocks, labelled illustrative)
  → portfolio impact   (the deterministic stress engine: value before / after, contributions)
  + evidence and a "what was known when" timeline
```

## Why the headline score changed

The repository does contain real outcome labels (two-session abnormal returns), and a real trained model, `impact-v2` (`HistGradientBoosting` / Ridge; there is **no** XGBoost anywhere). But the
model fails its own pre-registered acceptance bar: a placebo window *before* the news scores at least as well as the real window, so its skill is the volatility regime, not the event
(`docs/FINAL_MODEL_REPORT.md`, `models/impact/impact-v2/model_card.json`). It cannot defensibly be the number that triggers a stress test, and no further labels can legitimately be
created. So the headline is now a **transparent hybrid severity score**, and the trained model is shown next to it as a labelled *reference* (experimental, "mostly the volatility regime"),
never as the trigger. The trained models, the frozen replay pack and their digests are untouched.

| | what it is | supervised? | validated? |
|---|---|---|---|
| **Severity score** (headline, drives the trigger) | `1 + 9 · Σ wᵢ'·fᵢ · (1 − λ·uncertainty)`, explicit factors and weights, in `configs/impact_hybrid.yaml` | no, no labels used | **no**: weights are documented judgements |
| Reference market-reaction model | the trained `impact-v2` (or the labelled placeholder rule where it cannot score) | yes (real labels) | no: experimental, acceptance bar not met |
| Scenario shocks | configured assumptions (`configs/scenarios.yaml`), labelled illustrative | n/a | n/a |
| Portfolio arithmetic | deterministic code | n/a | tested |

## The LLM's job, and its limits

The language model **reads**; it does not score. It fills a closed schema through a forced tool call (`llm/schema.py`): event class (the 8 taxonomy ids, or `NO_EVENT`), subtype,
confidence, tone and intensity, entities, sectors, regions, asset classes, severity indicators, uncertainty and verbatim quotes. Everything it returns is then checked (`assessment/grounding.py`):

* an **entity** survives only if its name appears in the text; it is `resolved` only if the entity master matched it; it can never become the signal's issuer (that comes from the master alone);
* an **evidence quote** survives only if it is a verbatim excerpt (found by position, so the UI highlights it);
* every id (event class, subtype, sector, region, asset class, indicator) must be in the closed vocabulary (`configs/semantics.yaml`), or it is dropped, and what was dropped is shown;
* an invalid event class is a malformed answer and falls back to the rules.

It never outputs an impact number, never decides the trigger, never does portfolio arithmetic. **Off by default.** `EVENTSHOCK_LLM=1` plus the provider's key (`GROQ_API_KEY`, or `ANTHROPIC_API_KEY`) turn it on (`make run-llm`); then the report
text (capped at 2,000 characters) is sent to the provider, the UI says so, and answers are cached by text + model + prompt version so the same text is never sent twice (also across restarts,
because the journal re-ingest hits the cache). Providers (`configs/llm.yaml`, `EVENTSHOCK_LLM_PROVIDER`): **Groq** (default; OpenAI-compatible chat completions with a forced function call, `openai/gpt-oss-120b`, `reasoning_effort: low`) and the Anthropic Messages API (`claude-haiku-4-5-20251001`), both over the standard library (`urllib`, no new dependency). Which models a key may use differs per account (`llama-3.3-70b-versatile` was refused for ours), so a refused request is reported with the provider's own words. Bounds: 15 s per attempt, 2 retries, **30 s total** including retries, and a local cap of 30 provider calls per minute; past any of them the rules answer, labelled.

**Fallback, never a crash.** No key, a timeout, a rate limit (429, retried with back-off and `Retry-After`), a 5xx, a rejected key, a refused request (unknown model) or a malformed answer all end in the deterministic **rule extractor**
(`assessment/rules.py`): cue phrases from the same vocabulary, anchored to the trained models' readings (the trained event model keeps authority unless cues of weight ≥ 2 disagree; tone is the trained
model's, unchanged). The result says `mode: RULES`, with the reason in `extraction.fallback_reason`, and the UI shows "Rule-based reading" or "Rules (model unavailable)".

## The severity factors

All inputs are available at the report's own time. A factor that cannot be computed from them is **left out and listed**, and the remaining weights are renormalised; nothing is guessed.

| factor | reads | notes |
|---|---|---|
| Event class | the assessed class | a configured prior per class (credit/funding highest) |
| Severity indicators | indicators found in the text (default, sanctions, guidance cut, capital requirement…) | noisy-OR of their weights; the strongest factor |
| Tone | −sentiment (adverse counts fully, favourable half) × confidence | a downside-risk tool |
| Novelty | the report's novelty against earlier reports of the same issuer | only when an issuer was resolved |
| Breadth | what the text is about: company < sector < market-wide, plus extra sectors / regions / asset classes | |
| Source credibility | news vs social prior + independent reports **that existed at the time** | later coverage is excluded |
| Market regime | VIX level recorded at event time | only if the market data is ≤ 5 days old at the report's time |

`severity = 1 + 9 · (Σ w'ᵢ fᵢ) · (1 − 0.2 · uncertainty)`, rounded for the trigger. The score is accompanied by an **assumption-sensitivity range** (each weight ±30% in turn): that is a statement about
how much the weights matter, *not* a statistical interval. Every weight has a one-line rationale in the YAML. The Risk-drivers list is generated from the factors' computed values by rule
(`hybrid._driver_text`), so it never says more than the numbers do.

## Temporal integrity

The score reads only the report, the extraction of its text, the novelty/corroboration that existed at its time and market state before it. It does **not** read later coverage, later filings,
future outlet counts or any realised return. `tests/unit/test_assessment_temporal.py` pins that: adding six later reports does not change a single factor. `GET /api/signals/{id}/timeline` lists everything
(before / at / after the report) with a *used in the severity score* / *read by the reference model only* / *not used* tag on each item; items dated after the report are shown for audit and flagged as never used.

## Stress engine hook

`StressService` takes an optional `severity_provider`. With one, the trigger and the severity scaling read the hybrid score (audit: `impact_origin: ASSESSMENT`, `severity_basis`, `extraction_mode`), the
scenario follows the **assessed** event class, and a sector read from the text binds sector shocks where the vocabulary scope found none (never over a resolved company; audited as `assessed_sector`).
Without a provider (the demo profile) nothing changes, and the run-id formula is unchanged for every run the assessment did not drive.

## API

`POST /api/analyze` (adds `assessment`, optional `source`), `GET /api/signals/{id}/assessment[?refine=true]`, `/evidence` (source evidence · model inference · scenario assumptions, never blended), `/timeline`,
`GET /api/stress-runs?signal_id=`, `POST /api/stress-test`, `GET /api/stress-runs/{id}`. `GET /api/meta` → `capabilities.llm` says which mode is running. Feed rows gain `severity_*` fields;
`min_impact` and `category` filters read the assessment so the feed and the detail page agree.

## Known limitations

* Weights and priors are judgements, not fitted; the range is sensitivity, not a confidence interval.
* The trained reference model stays experimental; its measurable skill is mostly the volatility regime.
* Duplicate detection is the existing token-overlap rule (same issuer, trusted clock, wording overlap): two reports with very different wording may stay separate signals.
* Pasted text has market data only if the frozen pack is ≤ 5 days old at the report's time; otherwise the regime factor is omitted and says so.
* Rule mode reads headlines and short posts; mid-sentence company names are not recognised (they are not guessed).
* Contradiction detection is minimal (same issuer, within 48 h, opposite and strong tone); both reports are kept.
* With the LLM on, report text goes to a third party. It is capped, cached, and the UI says so. CI never calls a provider (a scripted client and a scripted HTTP opener). The Groq path was exercised live by hand (see the journal); the Anthropic path has only the scripted tests.
* A language model's quotes and entities are checked, not trusted, but its *judgement* (event subtype, tone, uncertainty) is only as good as the model; the UI shows `AI-assisted` and what was dropped. Startup re-reads the journal of pasted texts through the cache, so a restart costs calls only for texts not yet cached.
