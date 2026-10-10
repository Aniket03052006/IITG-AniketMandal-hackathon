# Features and the pain points they answer

> **Status (2026-10-09, Stage 16).** Sections 1-9 were written for the Stage 5 interface and have been corrected where later stages changed them
> (the Risk Feed became the **Desk**, severity became the headline number, analogues now exist, the layout has a sidebar). Sections 10-15 cover what
> Stages 6-15 added; section 16 covers Module A, the tactical index rebalancer (Stage 16). Every "how we know it works" names a test or file that exists in the repository.

Every feature in the final UI exists because of a specific frustration an analyst, a risk manager or a hackathon judge has with
event-driven risk tools. This page maps each feature to the pain point it removes, shows where to see it, and says how we know it
works (a test, a rule, or a file you can open). Features that are honest limits rather than capabilities are marked **(limit)**.

**Who feels the pain**

- **Judge**: opens the product with zero context and has about four minutes.
- **Analyst**: has to act on a signal and defend it to a colleague.
- **Risk manager**: has to know what a signal means for a book, and how far to trust it.
- **Skeptic**: a technical reviewer who asks "is that real, or is it leakage?"

---

## 1. "I can't tell what this system actually does"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Pipeline in four real numbers** on the Desk (2,330 reports → 1,082 read as market events → 1,082 scored for severity → 27 reach severity ≥ 7) | A feed of headlines hides the pipeline. Nobody can see how many items were read, understood, scored and turned into a stress test. | Judge | Desk, under the trace | Counts come from `/api/signals`; asserted in `pages.test.tsx` ("opens with the story in four real numbers") |
| **Featured event** with *Open the event story* | "Where do I start?" A judge should not have to hunt for the one event that shows everything. | Judge | Desk (opens on `sig_8f79c8bbd6`, the Hormuz report) | `lib/featured.ts` names the hero, with a deterministic fallback; `featured.test.ts` |
| **Flow tracker** (Event → Understand → Impact → Evidence → Stress) | Pages built at different times feel unrelated; the user mentally stitches them together and loses track of which stage they are viewing. | Judge, analyst | Sticky bar on the Event and Stress pages | `story.test.tsx` (current stage, links, scroll in place) |
| **Chain graphic** on the event page | The relationship text → NLP → impact → scenario → portfolio lived only in documentation. | Judge | Event page, under the hero | Rendered from the signal itself; `pages.test.tsx` ("tells the story in chapters") |
| **One scripted demo path** (`docs/notes/DEMO_SCRIPT.md`) | A live demo that wanders through unrelated pages, or that depends on a live feed that may fail. | Judge, presenter | `docs/notes/DEMO_SCRIPT.md` | Walked from a fresh server; every figure read back from the page |
| **Deterministic replay clock** | Demos that change between runs, or break offline. | Presenter | Rail: "Clock pinned to 01 Oct 12:00" | `tests/e2e/test_replay_served.py` pins the output digest |

## 2. "A sentiment score is not an answer"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Event type + sentiment shown as two readings of the text**, with the note "Sentiment is tone, not impact" | Dashboards imply *negative sentiment → big impact*. That is false here: in our evaluation the calendar and market state carry the measurable skill and text outputs add none. | Skeptic, analyst | Event page, chain note and *Understand* | Test asserts the wording; study result in the Evidence tab |
| **Severity (1–10) as the headline**, separate from sentiment; the trained impact estimate is shown as a labelled reference | Severity is what drives action, but most tools bury it behind a tone score. The headline is a transparent four-answer scorecard (Section 10); the trained `impact-v2` number sits beside it and the two may disagree. | Risk manager | Event page hero | `pages.test.tsx` ("shows the raw prediction, calibrated score with range…"), `pages/assessment.test.tsx` |
| **Impact range bracket** (comparable events realised 1 to 9) | A single number looks more certain than it is. | Skeptic | Hero ladder | Range read from `score_low/high`; shown beside every model score |
| **Plain sentence under the score** ("High relative to comparable historical events…") | Judges do not read ladders; they read a sentence. | Judge | Hero | `lib/narrative.ts`, built only from returned fields |

## 3. "I can't see why it said that"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **NLP stage panel**: input text → event type with calibrated confidence and the commit mark, sentiment gauge | "It's a black box." The reader never sees the text going in or how sure the model was. | Judge, analyst | *What the text says* | `pages.test.tsx` (classified, non-event, uncertain, in-sample warning) |
| **Abstention, shown as a result** ("Type uncertain", "Not a market event") | Classifiers that always guess produce confident nonsense. | Skeptic | *Understand*; Feed tags | Event model abstains below 0.5; UI states say what happens next (no impact scored) |
| **Why?** drawers (NLP and Impact) | Explanations either absent or dumped on screen for everyone. | Analyst | Buttons under each chapter | Drawer tests (`?open=why`, `?open=nlp`) |
| **Plain-named drivers** ("Days since the last earnings filing", not `earn_days_since_last`) | Raw feature ids mean nothing to a non-ML reader. | Analyst, judge | *How severe a reaction is likely* | `lib/featureLabels.ts` covers every input; "Attributions of the model's own arithmetic, not causes in the market" |
| **How calculated?** with typeset maths and a plain reading under each formula | Raw code strings (`scale = clamp(...)`) and formulas nobody can check. | Skeptic | Event and Stress drawers; Evidence → Mathematics | KaTeX tests; formulas built from structured numbers, never parsed from strings |
| **Technical details** (model id, lifecycle ladder, failed checks, calibration, limits) | Technical depth is either missing or crowds the first screen. | Skeptic | Drawer | Pulled from the model card; `pages.test.tsx` ("Technical details") |

## 4. "Is that leakage?"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Show inputs**: every input the model saw, grouped (report / text models / calendar / market) with its availability class | "What did it actually look at?" Without this, nobody can audit a score. | Skeptic | Event page → *Show inputs* | `GET /api/signals/{id}/context`; inputs are the exact numbers stored on the signal's audit |
| **Deliberately not used** list (outlet counts, later reports, later filings, the realised move) | Leakage is the first thing a reviewer suspects and the last thing a UI states. | Skeptic | Inside *Show inputs* | Shown only for model-scored signals; asserted in tests |
| **Strict point-in-time filings** (a filing is "before" only if accepted strictly earlier) | Look-ahead through "recent filings" features. | Skeptic | Timeline; context endpoint | `tests/unit/test_signal_context.py`; the calendar's own future-invariance check |
| **"What did EventShock know at this moment?" timeline** with three lanes: *available at the time*, *learned later*, *realised outcome* | Backtests quietly mix what was known with what happened. This lets a judge watch the difference. | Skeptic, judge | Event page → *Evidence* | `lib/timeline.ts` returns only what the cursor reached; a test proves later facts are absent from the page in earlier states |
| **Realised outcome shown, separately and even when unflattering** (predicted 7, realised 0.41σ, inside 1–9) | Cherry-picked results. | Skeptic | End of the timeline | All 706 matched signals exported, not a selection; kept off `RiskSignal` |
| **Timestamp honesty**: crawl-time warning, no timeline at all for replay-assigned times | Ordering events against an invented time misleads. | Skeptic | Hero chip; timeline note | Tests for `GDELT_FIRST_SEEN` and `SYNTHETIC_REPLAY_CLOCK` |

## 5. "I don't know how much to trust it"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Lifecycle tags** (placeholder rule / experimental model / validated model) | An unvalidated number looks authoritative. | Risk manager | Next to every impact | Tags unchanged from the frozen lifecycle; nothing is shown as validated |
| **Four kinds of number**, each with icon + pattern + word: model prediction, historical observation, scenario assumption, realised outcome | Predictions, history, assumptions and outcomes blur into one stream of numbers. | Risk manager, skeptic | Badges across the app; Evidence → Methodology | `story.test.tsx` (all four named, own pattern class) |
| **Evidence tiles**: "How much evidence supports EventShock?" with checks passed out of total | Trust claims without a scoreboard. | Judge, skeptic | Evidence page | Counts read from the model cards (e.g. impact 15 of 22, 5 not met, 2 not evaluable) |
| **Not-called-validated language** | Over-claiming. | Skeptic | Evidence tiles | `pages.test.tsx` ("Not called validated" ×3, no "Validated model") |
| **Limitations tab** | Limits buried in a footnote. | Skeptic | Evidence → Limitations | Text comes from the evidence bundle |
| **Comparable events as an aggregate (limit)**: "197 past ticker-sessions…not individual events" | A fabricated "92 % similar to a 2024 event" list. This panel is the model's own bucket statistics, not retrieval. (Individual historical analogues exist separately, see Section 10.) | Skeptic | *Evidence* chapter | Shown as a distribution, labelled *Historical observation*; limit also in Technical details |
| **Placeholder signals degrade visibly** (rule tag, no range, "no comparable events", reason shown) | A weak entity link quietly yielding a confident number. | Risk manager | Open the Apple event (the Feed's *Also try*) | `pages.test.tsx` placeholder tests |

## 6. "So what does this do to my portfolio?"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Before → after hero** (value, change in dollars and percent) | The payoff is usually a table. | Risk manager, judge | Portfolio Stress | `pages.test.tsx` (figures asserted) |
| **To-scale bar** | A dramatic red number for a 0.8 % move. | Risk manager | Under the hero | Drawn from `pnl_pct` |
| **Hatched "outside this scenario's reach" bar** (for the Hormuz event 84.5 % of the book is reached, so the rest is hatched) | Silence about what the scenario did not touch reads as "safe". | Risk manager | Under the hero | Test: "Not treated as safe" |
| **Propagation strip** (event → scenario → shocks → positions hit → change) | The link between an event and a result is invisible. | Judge | Under the hero | Built from the run's own shocks and positions |
| **Change waterfall by asset class** | Totals hide where the change comes from, and a change this small vanishes on a value axis. | Risk manager | Portfolio Stress | Drawn from zero, not from portfolio value (stated in code) |
| **Drill-down** (portfolio → class/sector/factor → issuer → position) | Dense tables nobody reads. | Risk manager | *Where the change comes from* | Drill test; every level from the same run |
| **"Sensitivity, not cause" label** | Reading exposure to a scenario's shocks as causal attribution of the event. | Skeptic | Drill-down header | Test asserts the wording |
| **Severity slider (what-if)** with BASE vs SCENARIO | Static outputs; "what if it were worse?" needs a rerun. | Risk manager, judge | *Test a different severity* | Posts to the real engine (`force`, `impact_override`); test inspects the request |
| **"Scenario simulation, not a prediction"** | Simulations passed off as forecasts. | Skeptic | Hero and what-if | Test asserts the label |
| **Assumptions, positions and audit trail in drawers** | The first screen drowning in shock tables and 103 rows. | Analyst, skeptic | Stress buttons | Drawer tests |
| **Unresolved company → market-wide scenario** | A dead end ("Entity unresolved"). | Analyst | Event hero | Test: explains why and offers the next step |

## 7. "There is too much on screen"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Progressive disclosure**: Why? / Show inputs / How calculated? / Technical details / Audit trail | Everything everywhere: a first-time user meets hashes, model cards and provenance before knowing what happened. | Judge | Event page | Drawers are modal, keyboard-safe, focus-returning |
| **Drawers addressed by URL** (`?open=inputs`) | A presenter or screenshot cannot land on a specific explanation. | Presenter | Any drawer link | Drawer tests open from the URL |
| **Evidence page tabs** (Methodology, Evaluation, Datasets, Mathematics, Limitations, How it is built) | A 7-section research report as a single scroll. | Skeptic | Evidence | Tab tests (arrows, Home/End) |
| **Pipeline as one picture** with audit detail behind expanders | The old page was engineering information with no hierarchy. | Judge | Evidence → How it is built | `pages.test.tsx` pipeline tests |
| **State notices** that say what happened, why, and what to do next | "Entity unresolved." and a dead end. | Analyst | Every unusual state | `story.test.tsx` (order of the three answers) |

## 8. "I have to present this on any machine, in any room"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Light theme by default**, dark toggle | Dark-only dashboards are unreadable on projectors and in print. | Presenter | Sun/moon button at the right of the top bar (or ⌘K) | `tokens.test.ts` checks WCAG contrast for every token pair in both themes (245 checks) |
| **Locked tokens enforced by a test** | "No inline colours" was a convention nobody could verify. | Maintainer | `tokens.test.ts` | Fails on any raw colour literal outside the token file |
| **Phone to wide-desktop layouts** | Panels that break below 1280 px. | Judge on a laptop | 375 / 768 / 1024 / 1280 / 1440 px | A width sweep found and fixed several clipping bugs; screenshots in `docs/screenshots/` |
| **Reduced-motion support; animations only for state changes** | Decorative motion that distracts or sickens. | Everyone | Score resolve, bars, timeline | Global rule; tween fallback guarantees true values even when animation frames never fire |
| **Keyboard and screen-reader support** (dialog roles, tab roles, labelled sliders, textual twins of every colour cue) | Colour-only signals; mouse-only controls. | Everyone | Throughout | Role/name queries in the tests |

## 9. Backend support behind it

| Feature | Pain point it removes | Where | How we know it works |
|---|---|---|---|
| `GET /api/signals/{id}/context` (grouped inputs, filings before/after, realised outcome) | The UI needed honest data for "what did it know" without touching the models | `services/signal_context.py` | 18 unit tests on a synthetic calendar + 6 replay-API tests; the replay output digest is unchanged |
| `data/outcomes/replay_outcomes.json` via `make outcomes` | Realised outcomes lived only in a git-ignored 264 MB table, so a fresh clone could not show them | `scripts/export_outcomes.py` | Joined on (scope, issuer, session): 706 of 725 model-scored signals; schema and loader tests |
| `scripts/screenshots.mjs` | Screenshots that differ per machine or capture half-animated frames | `docs/screenshots/` | Chrome over CDP, true device emulation, motion off, URL-addressed pages |


## 10. "Is the headline number defensible?" (Stages 7-8)

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Severity-v2 scorecard**: four anchored answers (intensity, reach, certainty, direction) → fixed matrix → two bounded data adjustments → 1-10, with the score range labelled as assumption sensitivity | A weighted average of vague inputs that compressed the scale to 4-7 and could not be argued with. | Risk manager, skeptic | Event page hero, *Why this severity?*; Analyze | `tests/unit/test_severity_scorecard.py`, `pages/assessment.test.tsx`; benchmark in `data/benchmarks/` |
| **The AI only reads; code decides**; every part tagged AI / data / rules / hybrid / assumption; the rules-only score shown beside it | "Is an LLM making up the number?" | Skeptic | Hero tags, scorecard drawer | `tests/unit/test_assessment_service.py`; grounding rejects entities and quotes not in the text |
| **Works with no key**: *rule-based reading* label, nothing leaves the machine | A demo that depends on an API key or a provider quota. | Presenter | Chip on Analyze and the Desk | `capabilities.llm` in `/api/meta`; no test calls a real provider (`tests/fakes.py`) |
| **Outcome check tab**: severity against realised moves, labelled *heuristic, uncalibrated* | Claiming a scale is "validated" because it looks sensible. | Skeptic | Evidence → Outcome check | `docs/evidence/severity_validity.json`; `components/evidence/OutcomeCheckTab.test.tsx` |
| **Historical analogues**: precedent reports found by similarity, point-in-time, with hindsight outcomes labelled as such, and a *no reliable analogue* state | A fake "similar event" list, or hindsight leaking into the present. | Analyst | Event page, analogues panel | `tests/unit/test_analogue_*.py`; `AnaloguesPanel.test.tsx`; future-invariance tested |
| **Scenario history check**: each scenario shock ranked against 1/5/21-session history since 2014 | Shock sizes with no sense of how extreme they are. | Risk manager | Stress Lab, per scenario | `components/portfolio/HistoryCheck.test.tsx`; credit/PD/LGD shocks reported as *not checkable* |
| **Provenance and kinds of number everywhere** (retrieved, hindsight, assumption, model, observation) | Predictions, precedents and assumptions blurring into one number. | Skeptic | Badges across the app | `lib/provenance.test.ts` |

## 11. "I need it for my own book and my own text" (Stages 6, 9)

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Analyze**: paste any headline or post; same engine as the replay and the live feed; opens as an ordinary event | A demo that only works on pre-baked examples. | Judge, analyst | Analyze | `tests/unit/test_analyze_live.py`, `tests/integration/test_analyze_api.py`; a duplicate paste is reported `DUPLICATE`, not re-counted |
| **Scope instead of "entity unresolved"**: company, sector, market or unresolved, with the matched terms | A dead end when no listed company is named. | Analyst | Event hero, Feed filters | `tests/unit/test_scope.py`; vocabulary measured by `make scope-eval` |
| **Personal portfolios**: describe holdings in plain text (`AAPL 20%`, `TLT 25%`, `Cash 25%`), validate, save, compare with the default | Stress results only for a book nobody owns. | Risk manager | Portfolios | `tests/unit/test_portfolio_*.py`, `pages/portfolio.test.tsx`; the synthetic book stays the default and one click returns to it |
| **Exposure heatmap** (sector × asset class) and **loss heatmap** (sector × market factor) | Exposure read one dimension at a time, three tables side by side. | Risk manager | Portfolios; the stress attribution panel | `tests/unit/test_crosstab.py` (cells reconcile or the builder raises), `Heatmap.test.tsx` |
| **Concentration flags** only where meaningful | A warning on every book. | Risk manager | Portfolios | `tests/unit/test_propagation_concentration.py` |

## 12. "How does this event reach my book?" (Stages 10-11, 15)

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Event intelligence**: scope hierarchy, independent-source count, evidence tier (kept apart from model confidence), novelty, narrative velocity, contradiction, lifecycle with a timeline | One confidence badge hiding whether the story is one outlet or ten. | Analyst, skeptic | Event page, intelligence panel | `tests/unit/test_intel_*.py`; replay and engine parity in `tests/e2e/test_intelligence_replay.py` |
| **Propagation chain**: event → scope → risk factor → holdings; every edge shows its rule and whether it is observed, a scenario assumption or yours | "Why does an oil story hit my bank loans?" | Risk manager | Event page, stress chapter | `tests/unit/test_propagation_mapping.py`; `propagation.test.tsx`; abstains when nothing defensible exists |
| **Materiality** (LOW to CRITICAL) from an exposure × severity lookup, never a blended score | A single opaque "risk score". | Risk manager | Event page | `tests/unit/test_propagation_materiality.py` |
| **Generated scenario**, gated (severity, relevance, direction, mapping, reach) and labelled *SCENARIO SIMULATION, NOT A PREDICTION*; *SCENARIO UNAVAILABLE* names the failed gate | Inventing a stress test when the event does not warrant one. | Skeptic | Event page; the Desk's scenario station | `tests/unit/test_propagation_scenario.py` |
| **Contagion map**: the propagation graph as a picture (event → factors → where it lands → largest holdings) | An edge list is complete but not readable at a glance. | Judge | Event page | `lib/contagion.test.ts`, `ContagionMap.test.tsx` (layout, no overlap, deterministic) |
| **Attribution that reconciles**: the loss by shock kind, issuer, sector, factor, asset class and position | Totals without a story, or tables that do not add up. | Risk manager | Stress attribution panel | `tests/unit/test_propagation_attribution.py` (every table equals the total within a cent or the builder raises) |
| **Adjust assumptions** drawer: change gates, sizes, thresholds and transmission weights; everything labelled *user assumption* and counted; one click restores every default | Hard-coded judgement priors nobody can challenge. | Analyst | ⌘K → Adjust, or the top bar | `tests/unit/test_adjust.py`, `components/adjust/adjust.test.tsx`; shipped configs never touched |

## 13. "What changed since I last looked, and what needs a person?" (Stages 12, 15)

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Today**: what changed, by named rule, ranked for the active portfolio with the sort key shown (no blended score) | Alert fatigue; an opaque priority. | Analyst | Today | `tests/unit/test_digest.py`, `tests/unit/test_monitor_*.py`, `pages/today.test.tsx` |
| **Event memory**: an article about an existing event updates it, never a new risk | Five articles read as five crises. | Analyst | Today, event page | `tests/unit/test_monitor_memory.py` |
| **Watchlists** matched on the resolved scope (an unresolved event never matches a company) | Alerts for the wrong company. | Analyst | Portfolios | `tests/unit/test_watchlist.py` (26), `watchlist.test.tsx` |
| **Review queue**: events queued by a named rule (sources disagree, high severity with an unresolved subject, high severity from one source, material to the book, large generated-scenario loss, escalating, evidence changed); reviewed / dismissed decisions are append-only and reopen when the event's own evidence changes | "Which of these should a person look at?" and "did anyone?" | Analyst | Review | `tests/unit/test_review.py`, `tests/integration/test_review_api.py`, `pages/review.test.tsx`; thresholds are unvalidated priors and say so |
| **Why?** reasons: structured, every statement sourced; empty explanation raises | A story told after the fact. | Skeptic | Why drawer | `tests/unit/test_explain.py`, `components/explain/explain.test.tsx` |
| **Executive brief**: sixteen fixed sections, template-written, deterministic; no language model writes it | A summary that invents. | Judge, risk manager | Event page → Brief | `tests/unit/test_brief.py`, `components/brief/brief.test.tsx` |
| **Feedback** (append-only, "not ground truth") | Feedback that quietly retrains or alters a model. | Analyst | Event page | `tests/unit/test_feedback.py` (append-only log, a damaged line is skipped, statistics say what they are not); feedback never feeds a model |

## 14. "What if it were worse, and what would it take to hurt us?" (Stages 12-13)

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Scenario lab**: base, assessed, or custom scenario, every user value labelled *scenario assumption*; compare scenarios | Static results; "what if oil also spiked?" needs a developer. | Risk manager | Stress Lab and Portfolios (scenario lab) | `tests/unit/test_lab.py`, `components/lab/lab.test.tsx` |
| **Multi-factor scenarios** (oil, rates, spread, equity, credit together) as first-class cards | One-factor shocks that miss how crises combine. | Risk manager | Stress Lab scenario rail | `tests/integration/test_multifactor_scenarios_api.py`; the Hormuz event under *Oil supply shock* gives -$32.5M (-3.78 %) |
| **Reverse stress**: the mildest combination of up to three shocks that reaches a loss target (bounded grid; the answer is re-run in full) | Only forward questions can be asked. | Risk manager | Scenario lab | `tests/unit/test_reverse_stress.py`, `components/lab/reverse.test.tsx` |
| **Honest abstention in the engine**: a scenario that reaches no position is `NOT_APPLICABLE`, never a zero P&L; uncovered positions are listed | "No loss" reading as "safe". | Skeptic | Stress Lab | `tests/unit/test_stress_scope.py` |
| **External markets (Kalshi)** shown beside an event as an observation, never an input to any score | A prediction-market price quietly steering the number. | Analyst | Event page | `tests/unit/test_markets_*.py`, `markets.test.tsx`; replay tests prove core outputs are byte-identical with the provider on, off or failing |

## 15. "Is it live? And can I judge it without a feed?" (Stages 6, 15)

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Live switch**, OFF at every start; turning it on is the explicit act that allows outbound requests; choices: news + SEC filings, GDELT, SEC filings, simulated | A demo that quietly calls the internet, or a "live" claim you cannot see. | Presenter, skeptic | Top bar switch, ⌘K | `tests/unit/test_analyze_live.py`, `components/live/LiveToggle.test.tsx`; the status shows what the server reports, never an optimistic state |
| **Simulated live** from a committed capture of 216 real, previously unseen pack articles | A live demo that fails when the news feed rate-limits. | Presenter | Live switch → Simulated | `tests/unit/test_sample_capture.py` (the file equals its derivation from the pack) |
| **SEC EDGAR 8-K as a second live source**, with keep rules shown as judgement priors | Only one news source. | Judge (two-source requirement) | Live switch | `tests/unit/test_edgar_live.py`; needs `EVENTSHOCK_SEC_CONTACT` |
| **Replay vs live labelled on every signal** (channel and timestamp origin) | Mixing frozen and live data. | Skeptic | Feed rows, event hero | `tests/e2e/test_replay_served.py` pins the replay digest |

## 16. "What would sentiment do to an index, and who signed off on the trade?" (Stage 16, Module A)

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Sentiment-to-weight index**: 15 stocks, equal-weight benchmark, decayed one-source-one-vote score, exponential tilt, bounds, turnover cap | "Sentiment up, weight up" implemented naively swings an index on one headline, or copies one outlet's near-duplicates five times. | Portfolio manager | Rebalancer → *Index* | `tests/unit/test_rebalancer_{scoring,weights,service}.py`; every cycle self-checks (sum 1, bounds, cap) or raises |
| **Named reason per stock** (`TILT_UP`, `AT_UPPER_BOUND`, `LIMITED_BY_TURNOVER`, `NO_EVIDENCE` …) | A weight that moved with no explanation. | Analyst | Rebalancer → *Index* | reasons are part of the cycle record; contributions of every report add up to the score exactly |
| **Weights over time** (stacked, sector hues, ticker beside each band) with tilt, half-life and turnover as a what-if | A static table of weights; no way to ask "what if it reacted faster?". | Judge, analyst | Rebalancer → *Index* | `components/rebalancer/*`, `pages/rebalancer.test.tsx`; the what-if is marked `params.is_default = false` |
| **Trade decisions**: before → target → after, trade, evidence with times, *thin / stale / conflict* flags, the rules that bound each stock, a template-written sentence | A rebalance with no audit trail. | Analyst, risk manager | Rebalancer → *Trade decisions* | `tests/unit/test_rebalancer_decisions.py`; the constraint-ladder effects telescope exactly to the final target |
| **Risk-aware strategies** (sector cap, volatility bound, liquidity floor; tone × impact) behind a closed registry | A tilt that ignores concentration and liquidity, or a hidden variant. | Risk manager | `?strategy=` | `tests/unit/test_rebalancer_{grouped,strategies}.py`; the baseline's weight-path digest is pinned unchanged |
| **Strategy lab against equal weight, buy-and-hold and a placebo** with a sensitivity grid | Back-tests that show the winner only. | Skeptic | Rebalancer → *Lab* | `tests/unit/test_rebalancer_{backtest,lab}.py`; verdict is computed from the placebo; every strategy is *within chance* (baseline: 82nd percentile) and the page says so |
| **Simulated approval ledger**: approve, partly approve or reject; append-only, hash-chained; 409 on a changed proposal | "Who approved this?" and approving something that has since changed. | Risk manager | Rebalancer → *Ledger* | `tests/unit/test_rebalancer_ledger.py`; a broken chain refuses new entries; nothing is sent anywhere and the served index never moves |
| **Isolation**: nothing imports the rebalancer; only `sentiment.score` is read | A downstream module contaminating the core signal. | Skeptic | tests | `tests/unit/test_rebalancer_architecture.py`, `tests/e2e/test_rebalancer_replay.py` (signal digest unchanged) |

---

### What we deliberately did *not* build, and why

- **Analogues as a score input.** Individual historical analogues exist (Section 10) but are display-only: the pre-registered test found they add no information about the realised move beyond regime and calendar, so no analogue-derived number enters any score.
- **A "probability of loss".** The impact score ranks relative severity; it is not a probability, a direction or a price forecast, and the UI says so wherever the score appears.
- **Anything that makes a model look validated.** Nothing is validated; every verdict says why.
- **A blended priority or risk score.** Today and Review use a documented sort key and show it; materiality is a lookup.
- **Assignment, SLAs and notifications in the review queue**: a single-user prototype would only be theatre.
- **Autonomous agents, a generative chatbot, or a language model that writes the brief.** The model reads text; templates and code write everything else.
