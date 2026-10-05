# Severity benchmark (pre-registered)

`severity_benchmark.jsonl`: 64 synthetic headlines in eight groups (routine, minor operational, material corporate, regulatory/policy, geopolitical, credit,
systemic financial, favourable/mixed). Each carries an **expected semantic band** assigned by the author from financial reasoning *before any scoring run*:

| band | scores | meaning |
|---|---|---|
| negligible | 1-2 | routine; no market consequence |
| low | 3-4 | minor, contained, or a small favourable move |
| moderate | 5-6 | material to one issuer or one narrow segment |
| high | 7-8 | sector- or market-wide consequence, or a serious credit/geopolitical event |
| extreme | 9-10 | threatens financial-system stability or global markets |

These are semantic ranges, **not quotas**: the expected distribution is deliberately skewed (7 negligible, 21 low, 13 moderate, 14 high, 9 extreme), like a real corpus.

## What this is, and is not
* It evaluates the **architecture** (does the score discriminate between genuinely different levels of risk?), not individual headlines. No headline, wording or expected band
  was changed after seeing a score.
* The bands are one author's judgement, not ground truth. The author also wrote the rule vocabulary, so the **rule-mode result is optimistic**; the LLM-mode result (a model
  that has never seen the vocabulary or this file) is the stronger evidence. Neither is outcome validation: no market outcome is involved.
* The headlines are written without company names on purpose, so the result depends on the text and the architecture, not on the entity master.

## Pre-registered acceptance criteria (fixed before the first run of the new scorer)
Evaluated text-only (no trained-model reading), per mode:

1. **Rank agreement:** Spearman(expected band index, score) >= 0.80 (rules) and >= 0.85 (LLM).
2. **Band agreement:** >= 70% of items in their expected band, and >= 90% within one band.
3. **No gross misses:** no item expected `extreme` scores below 7; none expected `negligible` scores above 4.
4. **Spread:** min <= 2, max >= 9, p10 <= 3, p90 >= 8, and every one of the five bands occupied by at least 3 items.
5. **Monotone groups:** the median score of group G (systemic) > E (geopolitical) > C (material corporate) > A (routine).

A criterion that fails is reported as failed; the benchmark file is never edited to make it pass (its sha256 is recorded in `docs/evidence/severity_benchmark.json`).
Baseline (the previous formula, `hybrid-v1`) was measured on this same file first: `docs/evidence/severity_baseline_v1.json`.

## Development set and held-out set (added after the first LLM-mode run)
The first recorded LLM-mode run on `severity_benchmark.jsonl` showed a design flaw (the magnitude definitions mixed intensity with breadth, which the reach answer already
covers; the model also rated events the rubric calls systemic one level lower). Fixing that means changing the prompt and the rubric text **after seeing results on this file**,
so `severity_benchmark.jsonl` is from here on a **development set**: its numbers are no longer clean evidence, and the rule vocabulary (written by the same author who had
seen these headlines) is likewise development-tuned.

`severity_heldout.jsonl` (32 new headlines, same eight groups and the same band definitions, expected bands fixed before any run, sha256 in `docs/evidence/severity_benchmark.json`)
is the **held-out set**: it was written before the prompt and rubric revision, is scored exactly once per final configuration, and is the only result the reports call evidence.
Its distribution is skewed like a real corpus (6 negligible, 8 low, 5 moderate, 9 high, 4 extreme). The same pre-registered criteria apply, scaled to its size
("each band occupied by at least 3 items" becomes "at least 2").

## Recording status (2026-10-05)

`llm_outputs.jsonl` is a complete recording of the **development** set made with prompt `extract-v4` and `gpt-oss-20b` (the shipped prompt is v6). It is kept as history and for the replay-integrity test; the
"does not compress" guard on real model answers is skipped for it, because it is from a superseded prompt. No recording exists for the held-out set, and none for prompt v6 (the provider's daily quota was exhausted).
To produce them (fresh daily quota, about 90k tokens): `EVENTSHOCK_LLM_MODEL=openai/gpt-oss-120b python scripts/severity_benchmark.py record dev --fresh`, then `... record heldout`, then
`python scripts/severity_benchmark.py evaluate`. Report whatever comes out; do not edit the benchmark or the expectations afterwards.
