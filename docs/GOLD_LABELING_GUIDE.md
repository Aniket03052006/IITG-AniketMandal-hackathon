# Gold set: labeling guide

The gold set is the **evaluation truth** for event classification and the domain check for sentiment. Weak labels (the 20-topic
crosswalk, `placeholder-v0`, the naive-Bayes probe) are never truth. This guide is what the annotator follows; it is also what
a human reviewer uses to overrule a label.

**Annotator disclosure.** The first-pass labels were produced by an AI annotator (`ai:claude`), blind to every weak label.
They are stored in `ai_*` columns. A human overrides a row by filling `human_*` in `data/gold/adjudication.csv`; the scorer prefers
`human_*` where present. AI labels are never described as human truth. A second blind pass over a seeded sample measures the
annotator's self-consistency, which bounds label noise but is **not** an independent inter-annotator kappa.

## What the sheet contains
`gold_id, source, published_at, ticker, text` and the label columns. Nothing else: no stratum, topic, placeholder class or probe
output (these are in `gold_manifest.json`, which labelers do not open until labels are final). Rows are ordered so that any
prefix is a proportionally stratified sample.

## Labels (per row)
| Column | Values | Meaning |
|---|---|---|
| `ai_sentiment` | `-1`, `0`, `1` | tone **toward the named issuer** from an investor's point of view (`0` = neutral, mixed, or no stance). For rows with no ticker: toward the company/market the text is about |
| `ai_event_class` | one of the 8 classes or `NONE` | the **type of event the text reports** (see below) |
| `ai_secondary_class` | a class or blank | only when a second class is clearly also reported; never equal to the primary |
| `ai_entity_ok` | `y` / `n` / `na` | history rows: is the ticker the company the text is mainly about? `na` for TFN rows (no ticker) |
| `ai_notes` | free text | one line for any `NONE`, ambiguous or `n` row |

## Event classes: decision rules
Ask first: **did something happen (or is something announced/expected) that a risk model should react to?** If the text is
chatter, a chart, a promotion, an opinion with no new fact, or a generic price remark, the class is `NONE`.

| Class | Use when the text reports | Not this |
|---|---|---|
| `GEOPOLITICAL` | armed conflict, sanctions, export controls, tariffs/trade restrictions, supply-route disruption, state-level tension | domestic party politics with no market channel (`NONE`) |
| `MACROECONOMIC` | central-bank action or guidance, inflation/growth/labour/trade data, FX or rates driven by macro | a single company's rate exposure (that company's event) |
| `CREDIT_FUNDING` | rating action, default or distress, liquidity, refinancing, debt issuance/repayment, covenant, funding stress | a stock price target (`MARKET_VALUATION`) |
| `MA_CORPORATE_ACTION` | acquisition, merger, divestiture, stake purchase, spin-off, IPO, buy-back, restructuring, delisting | dividend as part of results (`EARNINGS_FINANCIAL_PERFORMANCE`) |
| `REGULATORY_LEGAL` | lawsuit, settlement, investigation, fine, new rule, approval or denial by a regulator, class-action *announcement of a filing* | law-firm "investigating on behalf of investors" solicitations (`NONE` unless a real case is named) |
| `PRODUCT_OPERATIONS` | launch, recall, outage, breach, strike, plant/supply incident, trial result, production or delivery numbers, leadership/operational change tied to operations | earnings numbers (`EARNINGS_...`) |
| `EARNINGS_FINANCIAL_PERFORMANCE` | reported or guided results: EPS, revenue, margin, guidance change, dividend declared with results | analyst opinion about results (`MARKET_VALUATION`) |
| `MARKET_VALUATION` | analyst rating/price-target change, valuation view, index/sector repricing, momentum, volatility, flows | the event that caused the move (label the event) |
| `NONE` | not an event: promotion, spam, trade ideas/charts, opinion without a fact, jokes, questions | |

**Tie-breakers.** (1) Label the *cause*, not the price reaction ("shares fall after recall" is `PRODUCT_OPERATIONS`).
(2) Concrete company fact beats macro background. (3) If two classes are both clearly reported, pick the one the headline leads
with as primary and the other as secondary. (4) When genuinely unsure between a class and `NONE`, choose `NONE` and say why in the notes:
the model is allowed to abstain, and the gold set must measure that.

## Entity check (history rows)
`y` if the ticker's company is a main subject. `n` if it is a passing mention, a list of many tickers, a different company
with a similar name, or the text is not about the company at all.

## Sentiment: examples
- "Tesla beats on deliveries" -> `1`; "Boeing faces new probe" -> `-1`; "Fed holds rates" about no issuer -> `0`.
- Sarcasm and emoji: label the intended stance. A price target cut is `-1` for the issuer; an acquirer's shares falling on a
  deal is `-1` toward the acquirer even if the news is positive for the target.

## Workflow and honesty checks
1. `python -m eventshock.modeling gold-sample` builds the sheet and manifest (deterministic; refuses to overwrite labels).
2. Labels are applied in batches with `gold-apply` and checked with `gold-validate`.
3. `gold-adjudicate` writes ~60 rows (AI label disagrees with the crosswalk/placeholder, plus 20 random) for human review.
4. `gold-consistency` writes a blind re-label sheet; `gold-score` reports self-agreement.
5. `gold-score` reports, separately: population estimates (inclusion-probability weighted, from the `rand:*` and `tfn:*` strata),
   targeted-stratum results (unweighted, error discovery only), per-topic crosswalk precision, and agreement with any human overrides.
