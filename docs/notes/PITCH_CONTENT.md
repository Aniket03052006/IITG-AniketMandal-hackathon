# EventShock: pitch content for the deck, the video and the jury Q&A

Prepared 2026-10-09 from the repository at Stage 16. This is **content, not a deck**: distribute it across the five to seven slides you choose.
The submission guidelines suggest: title · problem and approach · system design · implementation highlights · key results · domain impact · limitations and next steps.

**Name.** The repository, the UI and every document call the product **EventShock**. The early PRD/research notes (kept locally in `guiding files/`) used the working name
*SignalForge*. Use one name on the slides; this file uses EventShock.

**Where the facts come from.** Every EventShock number below is read from the repository (model cards, `docs/evidence/*.json`, `data/rebalancer/*.json`, the running API, the
test suites) and was re-checked on 2026-10-09 unless a date says otherwise. Statements about other companies' products come from public vendor pages (list at the end).

**Labels used throughout**

| Label | Meaning |
|---|---|
| **[BUILT]** | implemented, runs in the shipped replay, has tests |
| **[MEASURED]** | a number produced by a command in this repository |
| **[ASSUMPTION]** | a judgement prior or scenario input; unvalidated, labelled as such in the product |
| **[PROPOSED]** | a business benefit or metric that has to be measured; **not** an achieved result |
| **[TO MEASURE]** | placeholder: no value exists yet. Never fill it with a guess |

## Deck requirements and a slide-by-slide map

**What the organisers require (from the submission guidelines and the problem statement).**

| # | Deliverable | What to submit | Where | Key requirement |
|---|---|---|---|---|
| 2 | **Presentation deck** | **5-7 slides**, PDF or PPTX | `docs/presentation.pdf` in the repo, **link in the README** | cover **problem approach, system design, key results and domain impact**; the case study adds that it should summarise **architecture, challenges and results** (no more than 7 slides) |
| 1 | Source code and architecture | working code + architecture diagram | public GitHub repo | setup and run commands; `docs/architecture.png` |
| 3 | Demo video | screen recording (guidelines: 10 min; the case study: live demo ≤ 5 min, so stay under 5) | link in the README, YouTube **unlisted** | quick end-to-end walkthrough |
| 4 | Data | CSV/JSON used to run the prototype | `/data` | sources and assumptions documented; no proprietary data |
| – | Live jury pitch (finalists) | live demo + Q&A | virtual panel | expect questions on design choices, code, data assumptions and use-case interpretation |

**Status of the deck [as of 2026-10-09].** `docs/presentation.pdf` does **not** exist yet, and the README has no link to it (`docs/notes/SUBMISSION_CHECKLIST.md` lists both as TODO). Build the deck from the map below, export it as `docs/presentation.pdf`, then add the link to the README header. Tie-breakers if scores are equal: Domain Understanding first, then Presentation & Communication, then submission time, so slides 2 and 6 matter more than they look.

**Seven slides (the guidelines' own outline, filled in).** Seven is the maximum; do not add an eighth. Every number on a slide must come from the fact sheet at the end of this file.

| Slide | Topic (required by) | What to put on it | Draw from | Visual |
|---|---|---|---|---|
| 1 | **Title** | EventShock: event-driven financial risk engine and portfolio stress lab; candidate Aniket Mandal, IIT Guwahati; S&P Global & Crisil Campus Hackathon 2026; the one-sentence pitch | section 1 | logo and one screenshot of the Desk (`docs/screenshots/`) |
| 2 | **Problem and approach** (*problem approach*; *domain*) | the information-to-risk gap: fragmented sources, repeats, tone mistaken for materiality, no link from an event to holdings, stress run too late. Then the approach in one line: text → three separate readings → evidence → exposure → deterministic stress | sections 2, 3, 4.1 | the manual workflow vs the EventShock chain, as a two-row strip |
| 3 | **System design** (*system design*; *architecture*) | the pipeline and where each component sits: sources → pipeline → models → signal → side-cars → stress engine and Module A → API → UI. Name the design rules: the LLM reads and code decides; derived views never touch the stored signal; never invent a number | section 7 | `docs/architecture.png` (use `architecture_simple.png` if the audience is non-technical) |
| 4 | **Implementation highlights** (*architecture*; *challenges*) | the three models and what they output; severity scorecard; evidence layer; stress engine formulas; Module A; why TF-IDF + logistic regression and gradient boosting rather than FinBERT/XGBoost; what was excluded and why. **Challenges** go here (list below) | sections 7, 8, 9 | a small table: stage → model → output → status (experimental) |
| 5 | **Key results** (*key results*) | the replay funnel (3,455 → 2,330 signals, 27 at severity ≥ 7); headline run $860.1 M → $822.8 M (−4.33 %); model metrics with their intervals; the honest findings (impact skill is calendar and regime; Module A within chance) | sections 4.3, 9, 10 | before/after value bridge screenshot + a metrics table with intervals |
| 6 | **Domain impact** (*domain impact*) | who uses it and what decision it supports; benefits as mechanisms with the measurement plan marked *to measure*; how it fits a risk desk's workflow; why it matters to S&P Global and Crisil | sections 3, 5, 12, 14 | the stakeholder table and the metric table, trimmed |
| 7 | **Limitations and next steps** | what is experimental, what is unvalidated, what is not claimed; the adoption path; next steps in priority order | sections 12, 13 | a four-column strip: can demonstrate · unvalidated · needs data · cannot claim |

**Challenges to name (the case study asks for them; all are documented in `docs/notes/PROJECT_JOURNEY.md`).**
1. *Severity v1 compressed the scale to 4-7* (a weighted average of vague inputs) → replaced by the anchored four-answer scorecard.
2. *Impact labels are a noisy proxy* → an outcome audit on 60,000 quiet-day pairs, a regime-neutral outcome definition and placebo windows; the honest result is that the model's skill comes from the calendar and regime.
3. *Leakage risk* → every feature registered by availability, chronological splits with an embargo, a calendar future-invariance check, and a UI timeline that withholds later facts.
4. *Event labels are AI-annotated* → disclosed everywhere; human adjudication was not done, so the event model stays experimental.
5. *A real engine bug* (the event-driven path dropped the currency from FX shocks, so base-currency positions took the shock) and *a regression* (derived views storing stress runs made results depend on whether the monitor had warmed) → both found by tests and fixed.
6. *Over-clean results looked like evidence* → in Module A, 21 of 21 sensitivity cells beat equal weight, but a shuffled-score placebo does too about half the time; the lab now prints how many cells would fall outside the placebo range by chance.
7. *Live feed fragility* → GDELT is rate-limited on some networks, so the demo runs from a hash-pinned replay with a simulated-live mode.

**Slide rules that follow from the honesty requirements.** Label every model "experimental". Write "scenario assumption" next to any shock size. Show intervals beside metrics. Never put the words "validated", "predicts losses" or "early warning" on a slide. If space is short, drop detail from slides 4 and 6, never the limitations on slide 7.

**The same content, reused.** The live pitch is slides 2, 3, 5 and 7 plus the demo in `docs/notes/DEMO_SCRIPT.md` (3 min 40 s); the 30-second and two-minute pitches in section 16 are the spoken versions; section 17 is the Q&A preparation.

---

## Read this before you pick slide claims: where the plan and the build differ

The PRD-era plan and the pitch brief mention FinBERT, XGBoost + SHAP, Streamlit, SQLite and DuckDB. **That is not what was built, and the slides must not say it was.**

| Planned in the PRD / brief | What is actually built | Why (honest reason) |
|---|---|---|
| FinBERT sentiment | `tfidf-lr-v2`: TF-IDF word + character n-grams → class-balanced logistic regression → temperature scaling | CPU-only, byte-reproducible, no torch at run time. FinBERT was **probed, not served**: on a 30-pair polarity probe, finbert-tone and ProsusAI/finbert got 93 % right against 77 % for the shipped model (a diagnostic, never used to choose). A FinBERT head was never compared on a labelled benchmark, so "FinBERT would be better" is plausible but unproven. It is the most obvious open improvement |
| Event classifier | `hybrid-event-v2`: TF-IDF + pinned e5-large sentence vectors → 9-way logistic regression (8 classes + NONE) that **abstains** below P 0.5 | won a pre-registered five-way representation comparison; labels are AI-annotated, not human |
| XGBoost impact + SHAP | scikit-learn **additive gradient boosting** (`impact-v2`, two scopes), rank-calibrated to 1-10 with an empirical interval; **exact additive attributions** instead of the SHAP library | tabular features, smaller dependency set, exact attributions by construction |
| Impact as the headline | The headline number is the transparent **`severity-v2` scorecard** (four anchored answers → fixed matrix); the trained `impact-v2` is shown beside it as a labelled *reference* | `impact-v2` does not meet its own pre-registered bar (no event-specific skill shown); the scorecard is auditable but **not outcome-calibrated** |
| Streamlit | FastAPI (93 operations) + React 19 / Vite / TypeScript | accessible, typed, product-grade UI |
| SQLite, Parquet, DuckDB | files + in-memory repositories behind Protocols | nothing in the MVP needs durability beyond files |
| Kafka, Neo4j, vector DB, agents | excluded on purpose | one process, tiny graph; retrieval is a static, hash-pinned e5 index, display only |

The brief also lists "empirically calibrated impact rather than arbitrary severity weights" as a differentiator. **Do not claim it.** The trained impact model is empirically
rank-calibrated, but it is *experimental* and its event-specific skill is not demonstrated (section 8); the headline severity is a transparent rubric, not a fitted model. The defensible
differentiator is the opposite one: **every score says what it is, how it was made and how far it can be trusted**.

---

## 1. Executive Pitch

**One sentence.** EventShock turns fragmented financial text (news, social posts, filings) into auditable risk signals and carries each signal all the way to a portfolio stress result
that an analyst can inspect, challenge and reproduce.

**The gap it addresses.** Financial institutions do not lack headlines. They lack a fast, traceable path from *a headline* to *what it means for what we hold*. Sentiment dashboards stop at
tone; stress-testing tools start from a scenario somebody already chose. EventShock connects the two and shows its work at every step.

**The workflow** (one chain, one code path for replay, pasted text and live feed):

`text from ≥ 2 sources → validate · de-duplicate · resolve the company → sentiment (how it is framed) · event class (what happened) · severity 1-10 (how big) → evidence (sources, novelty, quotes) → exposure mapping → deterministic stress test → before/after portfolio value with attribution`

**What is built [BUILT/MEASURED].** Replay of 3,455 real records (GDELT news metadata + a finance-tweet sample) → 244 quarantined with a reason, 184 exact duplicates folded → **2,330 signals**: 1,082 read as market events and scored, 1,248 judged *not a market event* (kept, never given a score), **27** reach severity ≥ 7 and so can trigger a scenario.
Module B (stress) runs a synthetic wholesale book of **103 positions, USD 860.1 M** (34 equities, 41 bonds, 19 loans, 9 derivatives, 34 real issuers). Module A (a mock 15-stock index whose weights follow sentiment) is also built.
Headline run: **$860.1 M → $822.8 M (−$37.3 M, −4.33 %)** under the Geopolitical flight-to-safety scenario; 84.5 % of the book is reached and the rest is shown as *not reached*, never as safe.
Engineering evidence: 2,368 backend tests and 782 frontend tests, a hash-pinned replay (`make freeze-check` passes: 88 files, 6 models), a real-server smoke test.

**What it is not.** A decision-support prototype. Not a trading bot, not an investment adviser, not a regulatory capital model, not a crash predictor. All three trained models are labelled *experimental*; nothing is called *validated*.

**The closing line for the deck:** *A transparent, reproducible path from information to exposure to loss, with honest labels on every number.*

---

## 2. Problem and Pain Points

Present these as **workflow pain points that many risk teams will recognise**, not as measured industry statistics, and not as problems every institution has to the same degree.

### 2.1 The business problem
An external event (a closure of a shipping chokepoint, a regulator's proposal, a downgrade, a merger rumour) matters to a bank only through **what it holds**: loans to affected borrowers, bonds of affected issuers, equities and derivatives, rate and currency sensitivities. The information that signals the event is scattered and unstructured. The portfolio that determines the consequence is structured and sits elsewhere. Someone has to connect them, quickly and defensibly.

### 2.2 The existing workflow and where it jams

| Step an analyst performs today | Bottleneck | Operational consequence |
|---|---|---|
| Watch several sources (wires, news aggregators, social feeds, filings) | fragmented sources, different formats, different clocks | an event is noticed late or by one person only |
| Decide what is material | volume and speed; negative tone is easily mistaken for financial materiality | attention goes to loud stories, not consequential ones |
| Spot repeats | the same event arrives as many near-identical reports | duplicate alerts; five articles read as five crises; or the opposite, a strong event dismissed as "already seen" |
| Judge reliability | rumours, conflicting reports, uneven source quality | slow, undocumented, person-dependent judgement |
| Work out who is affected | a company-level event does not say which loans, bonds or derivatives are vulnerable | manual mapping from event → issuer → sector → risk factor → positions |
| Ask "what would this do to us?" | scenario analysis is a separate tool and a separate request | delay between noticing and quantifying; the consequence arrives after the decision window |
| Explain it afterwards | the reasoning lives in someone's head and a chat thread | weak audit trail; a result that cannot be reproduced |

### 2.3 The gap that disconnected tools leave
Sentiment tools tell you how a text *reads*. Event feeds tell you *what* was detected. Stress tools tell you what a *chosen* shock does to a book. Nothing in the chain says: **this event, with this evidence, maps to these exposures, under these stated assumptions, with this result, and here is why**. Each hand-off is manual, so each hand-off is slow, inconsistent and hard to audit.

### 2.4 Why the gap matters to a financial institution
Risk governance expects explanations, versioned methods and reproducible numbers. A fast but unexplainable signal is unusable in a review; a thorough but slow process misses the window in which escalation is useful. The cost is not "a missed headline": it is delayed escalation, inconsistent treatment of similar events and thin audit trails. (Not quantified here; see the measurement plan in section 5.)

### 2.5 Which pain points EventShock addresses, and which it does not

| Pain point | Addressed? | How |
|---|---|---|
| Fragmented sources | **Yes** (two sources in the replay, a third live) | one engine for GDELT news, finance posts, SEC 8-K filings and pasted text |
| Information overload | **Partly** | ranked "what changed" digest and a rule-based review queue, each with its sort key shown (no blended score) |
| Negative sentiment ≠ materiality | **Yes, by design** | sentiment, event class and severity are three separate outputs; the stress engine deliberately ignores the sentiment value (tested) |
| Duplicates and repeats | **Yes** | exact de-duplication, syndicated/near copies become *corroboration*; event memory updates an existing event instead of raising a new one |
| Conflicts and source quality | **Partly** | independent-source count, evidence tier kept apart from model confidence, closed-lexicon claim contradiction (never inferred from tone); reliability is displayed, not scored |
| Event → exposure | **Yes** | propagation graph: every edge shows its rule and whether it is observed, a scenario assumption or yours |
| Delay to scenario analysis | **Yes** | a gated, labelled scenario is generated from the event and run in about ten milliseconds |
| What to investigate next | **Yes** | materiality (LOW-CRITICAL lookup), loss attribution by issuer/sector/factor/position, concentration flags, reverse stress |
| Currency / commodity exposure | **Only where a position carries it** | FX and commodity shocks apply to positions that declare the exposure; otherwise the answer is `NOT_APPLICABLE`, not zero |
| Real-time, production-scale monitoring | **No** | single-process prototype, 14-day replay window, live feed is opt-in |

---

## 3. Target Users and Stakeholders

| Stakeholder | Job | Sharpest pain | Decision they must make | What they assemble by hand today | How EventShock helps | Measurable improvement [TO MEASURE] |
|---|---|---|---|---|---|---|
| **Portfolio risk analyst** (primary user) | monitor exposure to external events | too many items, no triage | which events deserve a scenario today | news, filings, holdings, a scenario spreadsheet | one traced chain from headline to loss; review queue with the rule that queued each event | median time from publication to a reproducible stress result |
| **Market-risk team** | rates/equity/FX/commodity sensitivities | mapping an event to risk factors | whether to escalate and which factor moved | factor mapping by hand | event → factor → holdings graph, multi-factor scenarios, reverse stress | share of relevant exposure covered by the mapper |
| **Credit-risk analyst** | borrower and counterparty health | spotting stress in obligors early | which names to review or reprice | filings and news per obligor | issuer-scoped events, PD/LGD and spread shocks, 8-K feed as a second source | time to flag a relevant obligor event |
| **Risk manager** (reviewer, escalation owner) | sign-off and governance | trusting a number they did not produce | accept, challenge or escalate | the analyst's notes | provenance on every number, assumptions labelled, abstention instead of invention | share of signals with complete provenance |
| **Wholesale banking / treasury** | funding, liquidity, hedging | not knowing which book lines an event touches | whether to adjust limits or hedges | exposure extracts | exposure heatmaps, concentration flags, "not reached" bar | exposure identified vs a manual baseline |
| **Portfolio manager** | positioning | event-driven visibility without noise | whether an event changes the thesis | newsflow and a model | personal-portfolio comparison; Module A shows how a sentiment rule would move an index | analyst-time per event [TO MEASURE] |
| **Financial intelligence / research** | structured event data | unstructured text at volume | which events to publish or track | tagging and grouping | structured signals through an API, evidence tiers, event grouping | agreement of grouping with an analyst's grouping |

**Direct user vs economic buyer.** Direct users are the analysts and risk managers above. The **economic buyer** would be the head of risk or the chief risk officer's office, usually with technology, model-risk-management and data-licensing sign-off; a vendor sale would also involve procurement. Analysts would not buy it themselves. A hackathon prototype has no buyer and none is claimed.

---

## 4. Proposed Solution

### 4.1 In business language
**What goes in:** headlines and posts from several sources (news metadata, finance posts, SEC filings) or any text pasted by an analyst, plus a portfolio (the shipped synthetic book, or your own holdings typed as `AAPL 20%`).
**What happens:** the system cleans the text, drops duplicates, works out which company (if any) it concerns, then answers three separate questions: *how is it framed* (sentiment, −1 to +1), *what happened* (event class), *how big is it* (severity 1-10). It then checks the evidence: how many independent sources, what quotes support the reading, which model produced each number.
**What comes out:** a structured risk signal (JSON through an API) and, if severity is high enough, a stress scenario applied to the portfolio: value before, value after, who loses most, what was not reached.
**Who uses it:** analysts to triage and quantify; risk managers to review and sign off.
**What decision it supports:** *whether to escalate and what to investigate next.* It does not make the decision.

### 4.2 Why the portfolio view beats a feed or a sentiment dashboard
A feed says something happened. A sentiment dashboard says it reads badly. Neither says what it costs *us*. The portfolio view answers: which holdings are reached, under which stated shock, how much is lost, where, and how much of the book the scenario did **not** touch.

### 4.3 One worked example (real shipped output)
Headline (real replay signal `sig_8f79c8bbd6`): *"After Iran Says Strait of Hormuz Is Closed Again, Oil Risk to Economy Rises Once More."*

1. **Ingest:** GDELT article metadata; one source, and the screen says so ("weak evidence": single source).
2. **Resolve:** no company is named, so the scope is *market-wide*, not an invented company.
3. **Separate the three readings:** sentiment *neutral*; event class *Geopolitical*; severity **8 / 10**. Tone and severity disagree on purpose.
4. **Severity** comes from a four-answer scorecard (intensity, reach, certainty, direction → fixed matrix → bounded VIX and novelty adjustments) with a visible reason for each answer; the trained impact model is shown beside it as a reference.
5. **Evidence:** corroboration count, quoted text, model ids and artifact hashes, what was known at the report's time versus learned later.
6. **Map to exposure:** event → risk factors (equities, energy sector, spreads) → holdings, each edge with a rule and a basis; materiality computed by lookup.
7. **Stress (illustrative assumptions):** severity ≥ 7 triggers the Geopolitical scenario: shares −8 %, energy −14 % and so on. These are **scenario assumptions, not forecasts**.
8. **Result:** **$860.1 M → $822.8 M (−$37.3 M, −4.33 %)**; largest contributors by asset class, issuer and sector; 84.5 % of the book reached, 15.5 % shown hatched as *outside this scenario's reach*.
   Under the multi-factor *Oil supply shock* the same event gives −$32.5 M (−3.78 %); the propagation-generated scenario gives −$42.2 M (−4.91 %). Three defensible answers to a different question each; the UI labels which is which.
9. **Basis for investigation:** the analyst now knows where to look first, and can open every number's inputs, formula and audit trail.

> Say clearly: the system does **not** decide the true economic consequence of the event and executes nothing.

*If you prefer the "regulator proposes higher bank capital" example from the brief:* it maps to the **Regulatory / legal** class and the shipped `Regulatory capital shock` scenario (illustrative shocks: market equity −1 %, sector equity −4 %, issuer equity −10 %, sector spread +30 bp, issuer spread +100 bp, sector PD ×1.15, issuer PD ×1.4). Use it only as a mapping illustration: no shipped replay result for such a headline was checked for this document, so do not attach a portfolio number to it.

---

## 5. Business Value and Expected Impact

**Rule for this section:** no savings, hours, ROI or loss-reduction number exists. Everything below is a mechanism plus a way to measure it.

### 5.1 Benefits, mechanism, and evidence level

| Benefit | Mechanism (feature → improvement → why) | Evidence level |
|---|---|---|
| Faster conversion of text into structured signals | one pipeline normalises, validates, de-duplicates, resolves and scores in one pass → no manual tagging | **Demonstrable now**: pasted headline scored in about 0.4 s (rules mode, measured 2026-10-08 under load) |
| Less repeated review | de-duplication + event memory fold copies into one event with a corroboration count → one item instead of many | **Demonstrable**: 184 exact duplicates folded in the replay; grouping quality vs an analyst's is [TO MEASURE] |
| Faster identification of material events | severity separate from tone; 27 of 2,330 signals reach the trigger → the review queue shows the few that matter, with the rule that queued each | **Demonstrable** (counts); precision of the 27 against analyst judgement is [TO MEASURE] |
| More efficient triage | ranked digest with its sort key shown, no blended score → analysts see why something ranks first | Plausible; needs a user study |
| Earlier visibility into emerging risks | continuous scoring of incoming text | **Not demonstrated**: no lead-time claim exists; the realised-move audit found ordinary headlines barely distinguishable from an ordinary day (AUC 0.523) |
| Clear affected entities and sectors | scope hierarchy (company / industry / sector / geography / macro / market) with the matched terms; unresolved events never match a company | Demonstrable; scope accuracy measured by `make scope-eval` |
| Visibility of concentration | exposure and loss heatmaps, concentration flags raised only where meaningful, overlaps between events on the same factor | Demonstrable on the synthetic book |
| Consistent treatment of similar events | fixed taxonomy, fixed scenario catalog, fixed scorecard | Demonstrable (determinism); consistency across analysts is [TO MEASURE] |
| Faster initiation of scenario analysis | gated, generated scenario run in ~10 ms (`POST /api/stress-test`, 9-11 ms measured 2026-10-08) | **Demonstrable**: machine time; end-to-end analyst time is [TO MEASURE] |
| Transparent event → result mapping | exposure chain event → shock → exposure → change; attribution tables that reconcile to the total or the builder raises | **Demonstrable** and tested |
| Easier comparison of assumptions | scenario lab (base / assessed / custom), multi-factor scenarios, reverse stress | Demonstrable |
| Traceability and auditability | model id + artifact sha256 + origin on every stage; timeline of *what was known when*; append-only decisions and feedback | **Demonstrable** |
| Reproducibility | deterministic replay; run id is a hash of its inputs; pinned digests; `make freeze-check` | **Demonstrable** |
| Clear treatment of missing/contradictory evidence | `PARTIAL`, `UNAVAILABLE`, `NOT_APPLICABLE`, abstention, contradiction flags | **Demonstrable**; this is a deliberate design feature |

### 5.2 Three tiers
1. **The prototype can demonstrate directly:** determinism, provenance completeness, arithmetic reconciliation, the full chain on a replayed event, abstention states, speed of machine steps.
2. **Plausible but requires validation:** analyst time saved, triage quality, duplicate-grouping agreement, exposure coverage against an analyst's manual mapping, lead time over existing workflows.
3. **Requires production deployment and institutional integration:** real position feeds, licensed data, model validation sign-off, alert-fatigue effects, sustained monitoring.

### 5.3 Measurement plan (all **[TO MEASURE]**, none achieved)

| Metric | Definition | Baseline needed | Result |
|---|---|---|---|
| Analyst time saved | baseline review time − assisted review time, over comparable events | timed manual reviews of the same events | [TO MEASURE] |
| Triage lead time | median time from publication to a risk classification | analyst log or timestamps | [TO MEASURE] |
| Duplicate reduction | share of repeated items correctly grouped (precision/recall vs an analyst's grouping) | hand-grouped sample | [TO MEASURE] |
| Exposure coverage | share of relevant exposure identified by the mapper vs an analyst's mapping | analyst-labelled holdings for sample events | [TO MEASURE] |
| Scenario turnaround | time from event identification to a reproducible stress result | current process time | [TO MEASURE] (machine step ≈ 10 ms) |
| Audit completeness | share of signals with complete source, timestamp, model and scenario provenance | none (a property of the system) | [TO MEASURE]: count it over `GET /api/signals` before quoting a percentage |
| Review precision | share of queued events an analyst agrees needed a look | analyst judgement on a sample | [TO MEASURE] |

---

## 6. Product Differentiation

### 6.1 Positioning statement
> For risk analysts and managers who must turn external information into portfolio consequences, **EventShock** is an open, reproducible event-to-stress workflow that keeps sentiment, event type and severity separate, shows the evidence behind each, and carries the result to a transparent stress test. Unlike a sentiment feed or a standalone stress tool, it connects both and labels what every number is and is not.

### 6.2 Conceptual comparison

| Alternative | Does well | Leaves open | EventShock's intended distinction |
|---|---|---|---|
| Manual analyst monitoring | judgement, context, accountability | slow, uneven, hard to scale or audit | keeps the analyst in charge; automates triage, mapping and arithmetic |
| News aggregators and alerting | breadth and speed | alerts are not risk; duplicates; no exposure link | de-duplication, evidence tier, exposure mapping |
| Standalone sentiment tools | tone at scale | tone is not materiality or exposure | sentiment kept separate and **not an input** to the stress |
| LLM-based summarisation | fluent reading of long text | non-deterministic numbers; hard to audit; cost | LLM is an optional *reader* checked against the text; code decides every number; works with no key |
| Rule-based event scoring | transparent, cheap | brittle, no learned component, easy to over-claim | scorecard with visible reasons *plus* trained models, each labelled with its limits |
| Financial-intelligence platforms | licensed data, coverage, event/sentiment/risk analytics (see below) | closed, proprietary methods; a student cannot inspect or reproduce them | open and reproducible end to end; the audit trail is the product |
| Stress-testing systems without event intelligence | rigorous revaluation, regulatory scenarios | scenarios chosen by people, after the fact | the event picks and sizes a gated scenario, with its assumptions listed |

**Do not claim superiority over commercial products.** Public vendor material shows they already operate in these areas: Bloomberg describes sentiment functions and event-driven feeds with novelty and social-velocity analytics; RavenPack describes event detection, novelty, relevance, entity sentiment and risk uses; S&P Capital IQ Pro added a News Sentiment tool in Labs in September 2024 and Kensho has described a global event database; Crisil Intelligence (a company of S&P Global) offers risk solutions for banks. (Sources below; vendor marketing, not independent evaluation.)

### 6.3 Defensible differentiation: why the *combination* is meaningful
Individually none of these technologies is novel. Together they are:
1. **Open and reproducible:** a hash-pinned replay, deterministic ids, a freeze manifest. Anyone can re-run and get the same digest.
2. **Three separate readings:** sentiment (framing), event class (what happened), severity (how big). The stress engine ignores tone (tested).
3. **Honest scoring:** severity is a transparent scorecard; the trained impact score is shown as an *experimental reference*; both say they are uncalibrated against outcomes.
4. **Evidence and provenance as first-class output:** independent sources, novelty, quotes, model hashes, a "what was known when" timeline, with later facts withheld from earlier states.
5. **Exposure-aware scenario mapping:** shocks bind by scope (issuer, sector, market); a scenario that reaches nothing says `NOT_APPLICABLE`.
6. **Transparent arithmetic:** every attribution table reconciles to the total or the builder raises.
7. **End-to-end traceability:** one click from a headline to a loss, and back.

---

## 7. Technical Approach

### 7.1 Architecture (what to put on the system-design slide)
Use `docs/architecture.png` (lanes and flow), with `docs/architecture_simple.png` for the non-technical audience and `docs/architecture_detailed.png` for the Q&A. All three were regenerated for Stage 16.

| Layer | What it is | Status |
|---|---|---|
| Sources | GDELT DOC 2.0 / GKG 2.1 (news metadata, tone, organisations); Twitter Financial News (finance posts, MIT); SEC EDGAR 8-K (second live source, opt-in); FOMC calendar; Yahoo prices (derived statistics only); Kalshi prediction markets (observation only) | **[BUILT]** |
| Ingestion | provider adapters behind one interface; only `fetch.py` opens a socket; frozen replay pack verified by sha256 at start-up | **[BUILT]** |
| Pipeline | normalise → validate/quarantine → entity resolution (34 issuers, weak-alias guard) → de-duplication → one `RiskEngine` door for replay, pasted text and live | **[BUILT]** |
| Models | sentiment `tfidf-lr-v2`; event `hybrid-event-v2` (abstains); impact `impact-v2` (ISSUER and MARKET scopes) | **[BUILT]**, experimental |
| Evidence + provenance | independent sources, novelty, scope rules, model id / artifact hash / origin per stage | **[BUILT]** |
| Side-cars (derived on read, never stored on a signal) | severity scorecard + optional LLM reader · event intelligence · historical analogues · propagation · monitor, watchlists, review, brief · external markets | **[BUILT]** |
| Stress | scenario mapper (8 single-factor + 4 multi-factor + generated), deterministic engine, attribution, history check | **[BUILT]** |
| Module A | mock 15-stock sentiment-tilt index, decisions, lab, simulated ledger | **[BUILT]** (Stage 16) |
| API / UI | FastAPI, 93 operations, typed OpenAPI shared with a React dashboard (nine screens) | **[BUILT]** |
| Storage | files and in-memory repositories; no SQL | **[BUILT]**; SQLite is a deferred drop-in |

### 7.2 Design decisions and the one-line defence

| Decision | Defence |
|---|---|
| Hybrid classical-ML + deterministic stack rather than LLM-only | reproducible, cheap, offline, auditable; the LLM is optional and only *reads* into a closed schema checked against the text (entities must appear, quotes must be verbatim) |
| Deterministic stress engine, never a generative model, for the arithmetic | shocks are assumptions to be audited; the same inputs must give the same answer (the run id is a hash of its inputs) |
| No Kafka | one process, one demo machine; no throughput claim is made |
| No Neo4j | the exposure graph is tiny and every edge needs a rule and a basis, so relational rules suffice |
| No vector database or RAG that feeds a score | a static hash-pinned e5 index is used for display only: the pre-registered test found retrieval adds no information about the realised move beyond regime and calendar |
| No autonomous agents | a risk tool must not act on its own; every output is for a human |
| Replay mode | a frozen, hash-pinned window makes the demo deterministic and offline-safe; live GDELT is rate-limited on some networks and a live end-to-end poll was **not** observed from this machine |
| Synthetic portfolio | no real or confidential data may be used; real issuers + invented positions keep the exposure mapping meaningful and reproducible; realism is limited and said so |

---

## 8. Impact Scoring Methodology

### 8.1 Why sentiment alone is not enough
- **Sentiment** = how the text is framed (−1 … +1).
- **Event class** = what happened (Geopolitical, Macroeconomic, Credit/Funding, M&A/Corporate action, Regulatory/Legal, Product/Operations, Earnings/Financial performance, Market valuation; plus *not an event* and *uncertain*).
- **Impact / severity** = how large a market-relevant reaction this kind of event is expected to be.

A strongly negative headline can be immaterial; a neutral-sounding one (the Hormuz example is *neutral*, severity 8) can matter a great deal. The stress engine therefore ignores the sentiment value.

### 8.2 What is actually built (two numbers, kept apart)

**(a) `severity-v2`: the headline number and the stress trigger [BUILT, heuristic].**
Four anchored answers: intensity (0-4), reach, certainty, direction. Each is first derived by rules; the language model (if on) answers the same questions and may move one step from the rules' baseline, with a reason. Fixed matrix → certainty × direction scaling → two bounded data adjustments (VIX regime under a stated freshness policy; novelty) → 1-10. Tone, model confidence, outlet count and source reliability are **not** inputs. Every part is tagged AI / DATA / RULES / HYBRID / ASSUMPTION; the rules-only score is shown beside it.
*Status:* the scorecard is `HEURISTIC_UNCALIBRATED` against realised moves (2025 test correlation +0.007 [−0.025, +0.039]; 2026 live −0.021 [−0.086, +0.040]). The claim is "transparent triage scale, not outcome-calibrated", never "validated".

**(b) `impact-v2`: the trained reference [BUILT, experimental].**
- *Target:* the **size, not the direction,** of the two-session abnormal market response: log1p(|z|), z = abnormal return ÷ trailing volatility. ISSUER scope (one resolved company) and MARKET scope (S&P 500's own move, for texts naming no company).
- *Model:* additive gradient boosting on market state, timing, an event calendar (FOMC dates, SEC 8-K schedule) and the TF-IDF event model's probabilities; **rank-calibrated to 1-10 with an empirical 10-90 % interval**; exact additive attributions explain each prediction.
- *Protocol:* chronological; 5-session embargo; rolling-origin folds; 2024 validation, 2025 test and 2026 live scored once; every feature registered by availability in `modeling/leakage.py` (information known only after the event is refused as `POST_EVENT`); acceptance bar pre-registered and never edited after results.
- *Result:* held-out 2024-25 (9,897 issuer episodes) Spearman **+0.168 [+0.148, +0.187]**; 2026 news +0.084 [+0.013, +0.156]. But a placebo window *before* the event scores **higher** (+0.236), interval coverage over-covers (0.93 vs nominal 0.80), and the incremental-value study attributes the skill to the **calendar and volatility regime; text-model outputs add none.** ISSUER passes 9 of 11 pre-registered checks, MARKET 6 of 11 (2 not evaluable).
- *What it means:* "a reaction that large happened about this often in similar regimes" — not a forecast about this headline.

### 8.3 What the score must not be called
Not a probability of loss. Not a price forecast. Not causal. Not a trading recommendation. Not a hand-written severity disguised as ML (it is a hand-written, *transparent* rubric and says so). A market reaction is a **proxy** for event materiality, not a complete measure of financial risk.

### 8.4 Other model facts to have ready
- **Sentiment** `tfidf-lr-v2` (trained on 9,355 human-labelled finance tweets): same-source test macro-F1 **0.778** [0.749, 0.805] for v1 (v2 unchanged within noise there); on out-of-domain PhraseBank macro-F1 0.466 → **0.525** with v2; on news headlines (AI-labelled gold, n=280) v1 was 0.44 with poor calibration (ECE 0.23). Weak out of domain; stated.
- **Event** `hybrid-event-v2`: macro-F1 (uncertain counts as wrong) gold v1 **0.542** [0.418, 0.660], gold v2 **0.596** [0.508, 0.670], replay check **0.779** [0.655, 0.831]. Labels are AI-annotated; human adjudication was **skipped by decision**, so the independent-set check fails by construction and the model stays *experimental*. Weak classes are disclosed (GEOPOLITICAL F1 about 0.28).
- **Why this still matters:** the pipeline is built so that a better model slots in, and every result above can be reproduced by one command.

---

## 9. Portfolio Stress Testing

### 9.1 The portfolio
Synthetic wholesale book built on real issuers: 103 positions, USD 860.1 M: **34 equities, 41 bonds, 19 loans, 9 derivatives**. The sector tilt is derived from a public card-transaction spend mix (an acknowledged crude proxy). A read-only *Wholesale Book v2* preset adds ratings, spreads, convexity and counterparty parameters (synthetic, illustrative). A user may supply their own holdings; the synthetic book stays the default.

### 9.2 Scenario mapping ≠ one shock for everything

| Event class | Illustrative mapping (assumptions) |
|---|---|
| Geopolitical | equities down, energy sector hit harder, rates and spreads move, FX/commodity only where a position carries it |
| Macroeconomic | rates, equity and credit-spread shocks (multi-factor *Stagflation*, *Global downturn*) |
| Credit / funding | probability-of-default multiplier and credit-spread widening, liquidity-squeeze variant |
| Regulatory / legal | issuer and sector equity, earnings, spread and PD stress (the *Regulatory capital shock*) |
| Earnings | equity repricing and spread change |
| M&A, product/operations, market valuation | their own catalog templates |

Shocks **bind by scope**: an issuer shock needs a company-scoped event, a sector shock a sector, a market shock always. The most specific applicable shock wins (issuer > sector > market). Unresolved entities receive market-wide shocks only.

### 9.3 Simplified, transparent formulas (all first-order)
- Equity: ΔV = V × β × shock
- Bond: ΔV ≈ −V × D × (Δrates + Δspread)  (+ convexity term when set)
- Loan: ΔEL = EAD × (PD′·LGD′ − PD·LGD)  (+ spread-to-PD link, CVA when set)
- Derivative: ΔV ≈ delta × Δunderlying  (+ gamma when set)
- Severity scaling: scale = clamp(severity / 7, 0.5, 1.5); trigger: severity ≥ 7 (a product rule)
- Run id = hash of its inputs, so the same request gives the same result.

**All shock sizes are illustrative scenario assumptions, not forecasts.** Each scenario shock is also ranked against 1-, 5- and 21-session market history since 2014 (credit, PD and LGD shocks are reported as "not checkable").

### 9.4 What the user sees
Before/after value; a value bridge; loss by asset class, issuer, sector, risk factor and position (every table reconciles to the total within a cent or the builder raises); an exposure heatmap and a loss heatmap; concentration flags; a contagion map; **missing-exposure indicators** (a hatched "outside this scenario's reach" bar; uncovered positions listed, never treated as safe); a severity what-if slider; scenario lab and reverse stress (the mildest combination of up to three shocks that reaches a stated loss).

### 9.5 Honest boundaries
Not regulatory-grade (not FRTB or CCAR-style). It does not establish bank losses or capital adequacy. No curve twist or liquidity factor. Transmission weights, thresholds and sizes are unvalidated judgement priors.

### 9.6 Module A in one paragraph (the second downstream module)
A mock 15-stock index (AAPL, MSFT, NVDA, GOOGL, AMZN, META, JPM, BAC, GS, XOM, CVX, JNJ, UNH, PFE, WMT; six sectors) against an equal-weight benchmark. Per company: a decayed, one-source-one-vote, shrunk mean of `sentiment.score` → exponential tilt → exact projection onto per-stock bounds (3.33 %-10 %) → a turnover-capped step (4 % one-way per cycle). Every cycle self-checks (weights sum to 1, bounds, cap) or raises, and each stock carries a named reason. Dashboard of weights over time, trade decisions, strategy lab and a simulated approval ledger.
**Result, stated plainly:** +0.19 % against equal weight over 10 sessions, at the 82nd percentile of a 200-shuffle placebo, i.e. **within chance**. No skill is claimed; the page says so.

---

## 10. Evaluation and Results

### 10.1 Measured now

| Area | Result | Source / date |
|---|---|---|
| Replay funnel | 3,455 records → 244 quarantined (reason coded) → 184 exact duplicates folded → 2,330 signals (1,082 events, 1,248 not events, 27 at severity ≥ 7) | `GET /api/pipeline/report`, 2026-10-08 |
| Sentiment (v1, in-domain test, n=1,169) | macro-F1 0.778 [0.749, 0.805] vs 0.528 for the lexicon rule it replaced | model card |
| Sentiment (v2, out-of-domain PhraseBank) | macro-F1 0.525 (v1 0.466) | `docs/notes/SENTIMENT_MODEL.md` |
| Event type (abstentions count as wrong) | 0.542 / 0.596 / 0.779 on gold v1 / gold v2 / replay check | model card |
| Impact (issuer, 2024-25 held-out) | Spearman +0.168 [+0.148, +0.187]; placebo +0.236 (real < placebo) | `docs/evidence/impact_study.json` |
| Severity scorecard vs realised moves | +0.007 [−0.025, +0.039] (2025), −0.021 [−0.086, +0.040] (2026) → `HEURISTIC_UNCALIBRATED` | `severity_validity.json` |
| Outcome audit | ordinary company headlines barely distinguishable from an ordinary day (stratified AUC 0.523; 0.508 without earnings) | `outcome_audit.json` |
| Retrieval of precedent events | e5-large P@5 0.504 vs TF-IDF 0.443 (event queries 0.389 vs 0.255); adds no information about the realised move beyond regime + calendar | `analogue_*.json` |
| Module A back-test | +0.19 % vs equal weight, 82nd placebo percentile, 10 sessions: within chance | `data/rebalancer/backtest.json` |
| Stress engine | deterministic; positions reconcile to the P&L; headline run $860.1 M → $822.8 M (−4.33 %) | golden tests, API |
| Speed (2026-10-08, loaded machine, upper bounds) | stress run 9-11 ms; paste-and-score about 0.4 s; start-up 45 s | `docs/notes/SUBMISSION_CHECKLIST.md` |
| Engineering | 2,368 backend tests in 152 files; 782 frontend tests (all passed 2026-10-09); `make freeze-check` passed (88 files, 6 models); real-server smoke test | commands in README |

### 10.2 Evaluation plan: what still has to be shown

| Area | Metric | Status |
|---|---|---|
| NLP quality | class-wise precision/recall and macro-F1 vs a simpler baseline | sentiment and event: done as above; **human-adjudicated event labels: [TO MEASURE]** |
| Impact quality | MAE/RMSE, rank correlation, calibration by score bucket, ablations of novelty and corroboration | rank correlation and calibration: done; the novelty/corroboration ablation is **[TO MEASURE]** as a pre-registered study |
| Data quality | timestamp integrity, entity-link coverage, duplicate detection, source diversity, missing values | partly (quarantine reasons, scope evaluation); **entity-link coverage on live text: [TO MEASURE]** |
| System quality | latency, API reliability, provenance completeness, replay determinism, arithmetic consistency, attribution coverage | determinism, arithmetic and reconciliation tested; **sustained-load reliability: [TO MEASURE]** |
| Business value | time saved, triage lead time, duplicate grouping, exposure coverage | **[TO MEASURE]**, see section 5.3 |

**Why chronology matters.** Splitting by time with an embargo, and refusing any feature not known at event time, stops future information leaking into training. The impact model's features are individually registered by availability; the event calendar has a future-invariance check; the timeline UI withholds later facts from earlier states.

**What a strong result would look like (do not claim it yet):** an impact score whose rank correlation beats the pre-event placebo, whose interval coverage matches its nominal level, and whose text features add measurable skill beyond calendar and regime; event labels adjudicated by humans with agreement reported; and an analyst study showing shorter time-to-stress without worse judgement.

---

## 11. Feasibility and Implementation

### 11.1 Scope tiers
- **Minimum complete product (built):** two-source pipeline → sentiment, event, impact → API → portfolio stress with before/after dashboard.
- **Credibility features (built):** provenance, abstention, evidence tiers, deterministic replay, pre-registered evaluation, leakage guards, attribution that reconciles.
- **Extensions (built or optional):** Module A, personal portfolios, live switch, review queue, scenario lab, executive brief.
- **Not built:** a live demo that depends on a feed, production deployment, human-adjudicated labels, a recorded demo video and the final deck (open items in `docs/notes/SUBMISSION_CHECKLIST.md`).

### 11.2 Why it was feasible
A solo build was possible because every stage was frozen before the next began (basic → test → verify → freeze → move on), classical models train in minutes on a laptop, the data are public and small, the stress engine is plain Python, and the demo runs from a frozen replay so nothing depends on an outside service.

### 11.3 Risks, mitigations and what remains

| Risk | Mitigation | Remaining limitation |
|---|---|---|
| Impact-label quality (realised moves are a noisy proxy) | outcome audit, regime-neutral outcome-v3, placebo windows | proxy for materiality, not truth |
| Temporal leakage | registered feature availability, 5-session embargo, calendar future-invariance, timeline withholds later facts | live clocks are first-seen times, not publication times (flagged) |
| Taxonomy mismatch | eight classes + *not an event* + *uncertain*; abstention below P 0.5 | AI-annotated labels; weak classes |
| Duplicate reporting | exact fold; syndication and near copies become corroboration | near-duplicates across languages not handled |
| Contradictory sources | closed-lexicon contradiction, evidence tier apart from confidence | not paraphrase-robust |
| Entity-resolution errors | 34-issuer dictionary, weak-alias guard, `UNKNOWN_ENTITY` is a state | no NER; a multi-company headline can credit the wrong name |
| Source/API outages | replay mode; live off by default; poller reports OK/DEGRADED/ERROR | live GDELT rate-limited from some networks; not observed end to end |
| Unrealistic synthetic portfolio | public spend mix, real issuers, read-only v2 preset, personal portfolios allowed | invented positions; no real position feed |

---

## 12. Adoption and Future Potential

**Initial users.** One risk desk's event-monitoring workflow: analysts triaging external events for a defined portfolio.
**Where it fits.** Between the news/alert tools the desk already uses and its existing scenario or stress system: it produces a structured, explained *trigger and mapping*, and can hand a scenario definition downstream.
**Narrow first workflow (recommended).** "Overnight event triage for one book": ingest the desk's existing licensed feeds, map to that book's real positions, produce a morning review queue with scenarios pre-run and every assumption visible. Do not try to replace the institution's risk platform.
**Integration needs.** licensed news and market data; a position feed; identity and access control; logging to the firm's audit store; model-risk-management documentation.
**Data and licensing.** GDELT, tweets and EDGAR are public; commercial deployment would need licensed news, entity master data and prices.
**Governance.** model validation against the firm's standard; independent challenge of every prior; retained, tamper-evident decision logs (the review and ledger designs are append-only already); change control on configs (the freeze manifest is a start).
**What must be proven before reliance.** event-specific skill beyond regime and calendar; human-adjudicated labels; calibration; stability under live feeds; analyst-study evidence of benefit; security and resilience review.
**Hackathon prototype vs product.** Today: single user, no authentication, in-memory state rebuilt at start-up, a 14-day replay. A product needs queues and workers, a model-serving tier, a signal store, authentication, per-user portfolios, drift monitoring, scheduled retraining on human labels. None of that is built or claimed.
No pricing, market size, revenue or partnerships are asserted anywhere.
**Next steps in priority order:** record the demo; human adjudication of event labels; a compared FinBERT head; the novelty/corroboration ablation; a pinned demo event with conflicting claims.

---

## 13. Limitations and Risk Controls

| Can demonstrate | Unvalidated | Needs more data | Needs production engineering | Cannot responsibly be claimed |
|---|---|---|---|---|
| deterministic end-to-end chain; provenance; abstention; reconciling attribution; two modules; reproducible replay | all three models (experimental); severity scale (not outcome-calibrated); scenario sizes, thresholds, transmission weights; the rebalancer's half-life and tilt | human-adjudicated event labels; live-text entity coverage; more than 10 sessions for Module A; non-synthetic positions | authentication, durability, scale, monitoring, licensed data feeds | accuracy beyond the cards above; loss reduction; early warning; crash prediction; causality; regulatory-grade risk measurement; production readiness |

**Controls that exist in the product:** fail loudly on a modified artifact or snapshot; every stage records a model id and artifact hash; a `PARTIAL` signal never gets an invented score; four kinds of number are never blurred (model prediction, historical observation, scenario assumption, realised outcome); the "not called validated" wording is tested; the external prediction-market view is observation-only and provably never enters a score (replay tests: core outputs byte-identical with the provider on, off or failing).

**Explicit rejections to say out loud:** no fake accuracy; no claimed reduction in losses; no guaranteed early warning; no prediction of crashes; no causal attribution; no regulatory-grade claim; no production-readiness claim.

---

## 14. Why This Matters to S&P Global and Crisil

*Facts from the supplied project documents:* the case study asks for an NLP risk engine over at least two text sources and one downstream module, and lists GDELT, financial-news sentiment data and open banking transaction data as starting points; no real or confidential S&P Global or Crisil data may be used.
*Public facts:* S&P Global Market Intelligence offers AI-assisted tools including news sentiment inside Capital IQ Pro; Crisil Intelligence (a company of S&P Global) offers risk solutions for banks and financial institutions. Commercial products exist; **EventShock does not reproduce their capabilities or datasets.**
*Business interpretation (mine, not a supplied fact):* both organisations sit where **financial information becomes decisions**: structured intelligence on one side, risk analytics and portfolio monitoring on the other. The value in that space depends on three things a student prototype can show in miniature: turning unstructured text into structured events; connecting events to exposures and scenarios; and keeping every step auditable so a risk reviewer can trust it.
A transparent, reproducible event-to-stress prototype is a relevant student contribution because it demonstrates the **method and the discipline** (leakage control, abstention, provenance, honest labelling) rather than claiming a better product.

---

## 15. Why EventShock Deserves to Win

Only claim what the repository shows.

| Argument | Evidence |
|---|---|
| **Relevance** | meets the core engine requirement (two sources, sentiment −1…1, event class, 1-10 score, API) and implements **both** downstream modules (B fully; A as a derived, isolated side-car) |
| **Business usefulness** | one traced chain from headline to portfolio loss; a review queue; assumptions adjustable and labelled; clear "not reached" bars |
| **Technical depth** | trained sentiment, event and impact models with pre-registered acceptance bars; leakage registry; a deterministic engine with additive mechanics; 93-operation typed API |
| **Appropriate AI/ML choices** | classical models where they suffice; an LLM only as an optional, grounded reader; no LLM computes a number |
| **Financial-domain understanding** | scope hierarchy, risk-factor transmission, duration/convexity/PD/LGD/CVA mechanics, scenario history check, concentration |
| **Measurable evaluation** | confidence intervals, placebo windows, held-out years, an outcome audit, every claim traceable to a card or evidence file |
| **Explainability and auditability** | *Why?* on every number, provenance, timeline of what was known when, append-only decisions |
| **End-to-end implementation** | 2,368 backend and 782 frontend tests; freeze manifest; real-server smoke test |
| **Demo reliability** | frozen replay, live off by default, simulated-live from a committed capture |
| **Realistic scope, honest limits** | a limits column on every claim; findings that cut against the project (placebo ≥ real skill; Module A within chance) are shown, not hidden |

**Why connect NLP to a downstream workflow rather than stop at a classifier or dashboard.** A classifier's output is only valuable if somebody acts on it. Connecting it to exposure and a stress result tests whether the signal is *usable*: it exposes where the signal is weak (tone is not materiality), forces explicit assumptions, and gives a reviewer something concrete to challenge.

---

## 16. Pitch Talking Points

### 30-second pitch
"Risk teams don't lack headlines; they lack a fast, auditable path from a headline to what it does to what they hold. EventShock reads news, posts and filings from several sources, separates tone from event type from severity, shows the evidence, then maps the event to a portfolio and runs a transparent stress test: for example, the Hormuz closure takes a synthetic 860-million-dollar wholesale book down 4.3 percent under stated assumptions, with every number traceable. It is decision support, reproducible end to end, and honest about what is not yet validated."

### Two-minute pitch
"A risk analyst's morning is a race between information and decision. Reports arrive from many places, the same story arrives five times, negative tone gets mistaken for real financial materiality, and even when you know which company is involved, nobody tells you which loans, bonds or derivatives are exposed. Then the stress test is a different tool, run later.

EventShock closes that gap. Text from news metadata, finance posts and SEC filings goes through one pipeline: validate, de-duplicate, resolve the company. Three readings come out and they are kept apart: sentiment, how it is framed; event class, what happened; severity from one to ten, how big. Next to them is the evidence: how many independent sources, which quotes, which model, which version.

When severity reaches seven the system proposes a scenario, maps the event to risk factors and holdings and runs a deterministic stress test on a synthetic wholesale book of 103 positions. The result is before and after value, the largest contributors, and a bar showing what the scenario did not reach. On the replay's Hormuz headline the book goes from 860.1 to 822.8 million dollars. Those shock sizes are assumptions, labelled as such, not forecasts.

We built this the careful way. Models are trained chronologically with leakage guards and pre-registered acceptance bars, and when the results were unflattering we kept them: the impact model's apparent skill comes from the calendar and volatility regime, not the text, so it is marked experimental; the second module, a sentiment-driven index, lands within chance of a shuffled placebo, and we say that. Every number has a provenance, every run is reproducible from a hash-pinned replay, and the LLM never computes a figure.

EventShock isn't a trading bot or a regulatory model. It is a transparent, open way to turn information into exposure and exposure into a conversation a risk reviewer can trust."

---

## 17. Likely Judge Questions

**Business**

1. **Who would actually use this, and who pays?**
   Risk analysts and managers use it; the buyer would be the head of risk with technology, model-risk and data-licensing sign-off. As a hackathon prototype it has no buyer, price or customer, and none is claimed.
2. **What does it save?**
   Nothing is claimed. Section 5.3 defines the metrics (time to a reproducible stress result, duplicate grouping, exposure coverage) and they are marked *to measure*. What we can show today is machine time (about ten milliseconds for a stress run) and completeness of provenance.
3. **How is this different from Bloomberg, RavenPack or S&P's own sentiment tools?**
   They already offer sentiment, novelty and event analytics, and we do not claim to beat them. The distinction is openness and reproducibility, three separate readings, honest labelling and a traceable path to a portfolio result. A student cannot inspect a closed system; anyone can re-run this one.
4. **Why a synthetic portfolio?**
   Real or confidential data are not allowed. Real issuers with invented positions keep the exposure mapping meaningful and the results reproducible; the realism limit is stated.
5. **Could a bank rely on this tomorrow?**
   No. It needs licensed data, a real position feed, model validation, security and an analyst study. It is a prototype of the method.

**Technical**

6. **Why not FinBERT or an LLM?**
   FinBERT was probed (93 % vs 77 % on a 30-pair polarity probe) but not served: we wanted a CPU-only, byte-reproducible pipeline. A FinBERT head was never compared on a labelled benchmark, so it is the most obvious improvement, not a settled question. LLMs are optional readers; code produces every number.
7. **Your impact model has no event-specific skill. Why show it?**
   Because the pre-registered tests said so and we kept the result. The headline is the transparent severity scorecard; the trained impact is shown as a labelled reference. A model that overclaims is worse than one that reports its placebo.
8. **How do you avoid leakage?**
   Chronological splits with a 5-session embargo; every feature registered by availability, with post-event information refused; a calendar future-invariance check; test years scored once; the timeline never shows a later fact in an earlier state.
9. **Is severity validated?**
   No. It is `HEURISTIC_UNCALIBRATED` against realised moves (correlation +0.007 in 2025, −0.021 in 2026, both intervals spanning zero). It is a transparent triage scale; each of its four answers has a stated reason.
10. **Why a deterministic stress engine?**
    Shocks are assumptions that a reviewer must be able to audit, and the same inputs must give the same answer. Generative models cannot guarantee that and are the wrong tool for arithmetic.
11. **What happens when the model is unsure or the evidence is missing?**
    It abstains: event class *uncertain* below P 0.5, `PARTIAL` signals with no invented score, `NOT_APPLICABLE` when a scenario reaches no position, an `UNAVAILABLE` state when a clock is not trustworthy. Uncovered exposure is listed, not treated as safe.

**Implementation and honesty**

12. **Is the demo live?**
    The demo runs on a frozen, hash-pinned replay so it is reproducible and offline-safe. A live switch exists, is off at every start, and there is a simulated-live mode from a committed capture. Live GDELT is rate-limited on some networks and a full live poll was not observed from this machine.
13. **What is the weakest part?**
    Event labels are AI-annotated and no human adjudication was done; sentiment is weak out of domain (macro-F1 0.44-0.53 on news); impact skill comes from calendar and regime. All three are labelled experimental and documented.
14. **The rebalancer: does it make money?**
    It claims no skill. Against equal weight it is +0.19 % over 10 sessions, at the 82nd percentile of a shuffled-score placebo, so within chance. It is a transparent, bounded, turnover-limited map from sentiment to weight, with every constraint and a named reason per stock.
15. **What did you change your mind about?**
    The first severity design (a weighted average) compressed the scale to 4-7, so it was replaced by the scorecard. A real bug (FX shock currency dropped in the event-driven path) and a regression (derived views storing runs) were found and fixed. A model upgrade was re-pinned deliberately and journalled. The project journey (`docs/notes/PROJECT_JOURNEY.md`) records these.

---

## Appendix: verified fact sheet (for slides)

| Fact | Value |
|---|---|
| Replay funnel | 3,455 records → 244 quarantined, 184 duplicates folded → 2,330 signals (1,082 events · 1,248 not events · 27 at severity ≥ 7) |
| Models served | `tfidf-lr-v2`, `hybrid-event-v2`, `impact-v2` (all experimental) |
| Event classes | 8 (+ *not an event*, *uncertain*) |
| Scenarios | 8 single-factor, 4 multi-factor, plus a gated generated scenario |
| Book | 103 positions · USD 860.1 M · 34 equities · 41 bonds · 19 loans · 9 derivatives |
| Headline run | $860.1 M → $822.8 M (−$37.3 M, −4.33 %), 84.5 % of the book reached |
| API | 93 operations (OpenAPI), 21 routers |
| UI | 9 screens: Desk, Today, Review, Analyze, Event, Stress Lab, Portfolios, Rebalancer, Evidence |
| Tests | 2,368 backend (152 files), 782 frontend (42 files) |
| Frozen state | `make freeze-check` passed: 88 files, 6 models |
| Module A | 15 stocks · +0.19 % vs equal weight · 82nd placebo percentile · within chance |
| Data | public or synthetic only; GDELT, Twitter Financial News (MIT), SEC EDGAR, FOMC, Yahoo (derived statistics), Kaggle card transactions (spend mix) |

## Sources for statements about other companies (vendor material, not independent evaluation)

- S&P Global, [Capital IQ Pro Labs GenAI and analytics launch, 2024-09-19](https://press.spglobal.com/2024-09-19-S-P-Global-Market-Intelligence-Introduces-New-Generative-Artificial-Intelligence-GenAI-and-Advanced-Analytics-Solutions-through-S-P-Capital-IQ-Pro-Labs?asPDF=1)
- S&P Global, [relationship and investment in Kensho](https://spglobal.com/marketintelligence/en/media-center/press-release/sp-global-announces-strategic-relationship-and-investment-in-kensho)
- RavenPack, [RPNA upgrade (Finextra)](https://www.finextra.com/pressarticle/56610/ravenpack-upgrades-rpna) and [S&P 500 RavenPack AI Index brochure](https://spglobal.com/spdji/en/documents/brochure/brochure-sp-500-ravenpack-ai-index.pdf)
- Bloomberg, [Bloomberg enhances real-time news feeds (The TRADE)](https://www.thetradenews.com/bloomberg-enhances-real-time-news-feeds-offerings-with-customisable-capabilities-for-trading-and-risk-workflows)
- Crisil, [Risk solutions](https://www.crisil.com/content/intelligence/en/homepage/what-we-do/risk-solutions.html)
