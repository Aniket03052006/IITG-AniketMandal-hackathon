# Features and the pain points they answer

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
| **Story strip** on the Risk Feed (2,330 → 962 → 725 → 19) | A feed of headlines hides the pipeline. Nobody can see how many items were read, understood, scored and turned into a stress test. | Judge | Risk Feed, top | Counts come from `/api/signals`; asserted in `pages.test.tsx` ("opens with the story in four real numbers") |
| **Featured event** with *Open the event story* | "Where do I start?" A judge should not have to hunt for the one event that shows everything. | Judge | Risk Feed | `lib/featured.ts` names the hero, with a deterministic fallback; `featured.test.ts` |
| **Flow tracker** (Event → Understand → Impact → Evidence → Stress) | Pages built at different times feel unrelated; the user mentally stitches them together and loses track of which stage they are viewing. | Judge, analyst | Sticky bar on the Event and Stress pages | `story.test.tsx` (current stage, links, scroll in place) |
| **Chain graphic** on the event page | The relationship text → NLP → impact → scenario → portfolio lived only in documentation. | Judge | Event page, under the hero | Rendered from the signal itself; `pages.test.tsx` ("tells the story in chapters") |
| **One scripted demo path** (`docs/DEMO_SCRIPT.md`) | A live demo that wanders through unrelated pages, or that depends on a live feed that may fail. | Judge, presenter | `docs/DEMO_SCRIPT.md` | Walked from a fresh server; every figure read back from the page |
| **Deterministic replay clock** | Demos that change between runs, or break offline. | Presenter | Rail: "Clock pinned to 01 Oct 12:00" | `tests/e2e/test_replay_served.py` pins the output digest |

## 2. "A sentiment score is not an answer"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Event type + sentiment shown as two readings of the text**, with the note "Sentiment is tone, not impact" | Dashboards imply *negative sentiment → big impact*. That is false here: in our evaluation the calendar and market state carry the measurable skill and text outputs add none. | Skeptic, analyst | Event page, chain note and *Understand* | Test asserts the wording; study result in the Evidence tab |
| **Estimated impact (1–10) as the headline**, separate from sentiment | Severity is what drives action, but most tools bury it behind a tone score. | Risk manager | Event page hero | `pages.test.tsx` ("shows the raw prediction, calibrated score with range…") |
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
| **Comparable events as an aggregate (limit)**: "197 past ticker-sessions…not individual events" | A fabricated "92 % similar to a 2024 event" list. We have no per-event retrieval. | Skeptic | *Evidence* chapter | Shown as a distribution, labelled *Historical observation*; limit also in Technical details |
| **Placeholder signals degrade visibly** (rule tag, no range, "no comparable events", reason shown) | A weak entity link quietly yielding a confident number. | Risk manager | Open the Apple event (the Feed's *Also try*) | `pages.test.tsx` placeholder tests |

## 6. "So what does this do to my portfolio?"

| Feature | Pain point it removes | Who | See it | How we know it works |
|---|---|---|---|---|
| **Before → after hero** (value, change in dollars and percent) | The payoff is usually a table. | Risk manager, judge | Portfolio Stress | `pages.test.tsx` (figures asserted) |
| **To-scale bar** | A dramatic red number for a 0.8 % move. | Risk manager | Under the hero | Drawn from `pnl_pct` |
| **Hatched "outside this scenario's reach" bar** (63.8 % of the book) | Silence about what the scenario did not touch reads as "safe". | Risk manager | Under the hero | Test: "Not treated as safe" |
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
| **Light theme by default**, dark toggle | Dark-only dashboards are unreadable on projectors and in print. | Presenter | Left rail toggle | `tokens.test.ts` checks WCAG contrast for 22 token pairs in both themes |
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

---

### What we deliberately did *not* build, and why

- **A list of "similar historical events".** No per-event retrieval exists, and building one would be a modelling feature after the freeze.
- **A "probability of loss".** The impact score ranks relative severity; it is not a probability, a direction or a price forecast, and the UI says so wherever the score appears.
- **Anything that makes a model look validated.** Nothing is validated; every verdict says why.
