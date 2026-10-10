# EventShock: demo video script, page by page, feature by feature

Written 2026-10-10 against the running app (replay profile, commit `391ea7b` plus the documentation pass). Every number in the **You see** columns was read from the live UI or the live API on 2026-10-09/10 unless the page says *(earlier stage)*. The older, shorter flows are in [DEMO_SCRIPT.md](DEMO_SCRIPT.md); this file replaces them for the video.

**Two cuts from one script.**

| Cut | Length | Use |
|---|---|---|
| **A: the 5-minute video** | 4:55 | the case study caps the live demo at 5 minutes; this is the cut to aim for if you submit only one |
| **B: the full tour** | 9:40 | the submission guidelines allow a 10-minute video; every page and feature below, in order |

Record B and cut A from it (beats are tagged **A** where they are in the short cut), or record them separately. Chapter timestamps for the YouTube description are at the end.

---

## 0. Before you record (not on camera)

**Start a clean server.** Your normal `.env` has `EVENTSHOCK_LLM=1`, so a default start sends pasted text to Groq, and your `data/live/` folder holds an earlier pasted headline, a saved *Portfolio 1* and the decision log; all of that would appear on screen. This command avoids it (checked on 2026-10-10, including the capture variable: it starts, serves 2,330 signals, reports rules mode, lists only the default book and has live off):

```bash
mkdir -p data/live/demo && EVENTSHOCK_LLM=0 EVENTSHOCK_LIVE_SOURCE=capture EVENTSHOCK_JOURNAL_PATH=data/live/demo/journal.jsonl EVENTSHOCK_PORTFOLIO_STORE_PATH=data/live/demo/portfolios EVENTSHOCK_DECISION_STORE_PATH=data/live/demo/decision EVENTSHOCK_REBALANCER_LEDGER_PATH=data/live/demo/ledger.jsonl EVENTSHOCK_OVERRIDES_PATH=data/live/demo/overrides.json python src/main.py
```

Open <http://127.0.0.1:8000>. Start-up takes about 45 s and the first Desk load about 10 s; wait for the wire to show *963 events · 2,330 reports* before you start recording. `rm -rf data/live/demo` afterwards (it is git-ignored). The server starts cleanly with `EVENTSHOCK_LIVE_SOURCE=capture` (checked). It is documented to make the poller read the committed capture file instead of the network, but **it does not stop the switch defaulting to a real source**: the stray click on 2026-10-09 (made without that variable) polled *GDELT + EDGAR*, and a toggle with the variable set was not tested. Treat the switch as live-fire.

**Screen.** 1440 × 900 browser viewport, light theme (the default), 100 % zoom, no bookmarks bar, notifications off, 1080p capture. Mouse slowly; pause on every number for two seconds.

**Do not click the Live switch to "look at it".** A click on the switch turns Live **on**: on 2026-10-09 one stray click started a GDELT + EDGAR poll attempt (nothing was ingested; it was switched off at once). Show Live only as in beat **X4**, and only after you have rehearsed it on a throwaway start.

**Mind these rough edges** (each is real; the table in section 12 says what to say):

1. The Stress Lab relevance card says *High · 100 %* while the Event page says *Critical · 84.5 %*.
2. The rebalancer sentence for JPM reads "Buy … its sentiment score is −0.23 (negative)".
3. The UI prints "82th percentile".
4. The trained impact model says 2/10 for the headline you call 8/10.

---

## 1. Opening (0:00 to 0:30) · **A** 0:00 to 0:25

| Do | You see | Say |
|---|---|---|
| Start on the Desk, hands off the mouse. | The Desk with the Hormuz headline selected, the six-station trace under it. | "Risk teams don't lack headlines. They lack a fast, traceable path from a headline to what it means for what they hold. This is EventShock: news, posts and filings go in; an auditable risk signal comes out; and that signal drives a transparent stress test on a portfolio. Nothing here is a trading signal and nothing is a forecast; every number says what it is. I'll show it page by page." |

---

## 2. The Desk: `/` (0:30 to 1:40) · **A** 0:25 to 1:10 (D1, D3, D4, D5)

*Feature: one screen from news to book.*

| # | Do | You see | Say | Feature |
|---|---|---|---|---|
| D1 **A** | Point at the left column. | **Incoming wire**, *963 events · 2,330 reports*; chips All · Geopolitical · Macroeconomic · Credit · M&A · Regulatory · Product · Earnings · Market; rows with time, headline, source count, entity or scope, event type. On the right the selected headline: *After Iran Says Strait of Hormuz Is Closed Again, Oil Risk to Economy Rises Once More* (aol.com, 20 Sept 15:30 UTC, Market-wide · trade and conflict, Geopolitical), buttons *Open the event story* and *Stress-test in Stress Lab*, and "Also try: US jury says Apple owes record $5.7bn" (3 reports of one story). | "Real reports from two kinds of source, validated, de-duplicated and linked to companies. 2,330 reports collapse to 963 events on this wire: copies of one story are one row." | wire, de-duplication, event glyphs |
| D2 | Click **Geopolitical**, then press **J** and **K**; click *All* again and reselect the Hormuz row. | The wire filters; the trace redraws for each event; keyboard stepping. | "Filter by event type, step with J and K. Each event gets the same trace, and when the chain should stop it stops and names the gate that failed." | filters, keyboard navigation |
| D3 **A** | Walk the six stations left to right, two seconds each. | **1 What happened**: aol.com, 1 independent source, headline only, *insufficient evidence*. **2 What the AI read**: Geopolitical, 71 % confident, tone +0.02 neutral, *rule-based reading*. **3 How severe**: **8/10 High**, range 6 to 8, severity-v2, *Why 8?*. **4 Scenario it triggers**: *Geopolitical flight-to-safety, generated for this event*: −8.0 % market-wide, −14.0 % event sector, −18.0 % event issuer, +11 more, *Scenario simulation, not a prediction*. **5 What it reaches**: *Critical materiality, 84.5 % of the book reached*. **6 Portfolio impact**: **$860.1M → $822.8M, −$37.3M, −4.33 %**, *Deterministic engine*. | "News in, portfolio consequence out. What was reported, what the AI read, how severe, which scenario it triggers, what it reaches, and what it costs. Notice three separate readings: tone is neutral, the event class is geopolitical, severity is eight. Tone is not impact." | six-station trace |
| D4 **A** | Point at **Why trust it** under the trace. | *1 independent source, insufficient evidence* · *4 quotes checked against the text* · *rule-based reading, reliability moderate* · *Lifecycle: developing (NEW, rule-driven, never from falling volume)*. | "I will not hide the weak part: one source only, so the evidence tier is *insufficient*. The reading is grounded in four verbatim quotes. Confidence is shown as evidence, not as a badge." | evidence strip, honesty |
| D5 **A** | Scroll to the four counters. | **NEWS 2,330** · **AI UNDERSTANDING 1,082** (1,248 were not market events) · **RISK SIGNAL 1,082** · **SCENARIO → PORTFOLIO 27** reach severity ≥ 7. Below: *Live feed off*. | "The funnel: 2,330 reports; 1,248 judged *not a market event* and kept without a score; 1,082 scored; 27 cross the trigger and suggest a scenario. Live is off; the demo runs on a frozen, hash-pinned replay." | funnel, replay vs live |
| D6 | Scroll to **What changed recently** (the monitor strip) and the signals table. | *Replay · deterministic / Live* chips; *Cycle 28 of 28 · 01 Oct, 12:00 UTC*; cards such as *Lifecycle changed: US jury says Apple owes record $5.7bn* (Confirmed → Stale, 3 independent sources, evidence *Moderate*); below, a filterable table (*Severity ≥ 7*, *Show non-events (1248)*, search, *More filters and sorting*) with each row's severity, scope, event class, exposure and sentiment. | "An article about an existing event updates that event; it is never a new risk. And the table keeps the non-events: abstention is a feature." | monitor, table filters |

---

## 3. The Event page: `/events/sig_8f79c8bbd6` (1:40 to 3:10) · **A** 1:10 to 2:00 (E1, E2, E3)

Click **Open the event story**. The flow tracker under the title shows *Event · Understand · Impact · Evidence · Stress*; scroll with it.

| # | Do | You see | Say | Feature |
|---|---|---|---|---|
| E1 **A** | Stay on the hero. | Badges *Geopolitical*, *aol.com*, *time is when GDELT first saw it*; **Severity 8/10 High**, scale Negligible 1-2 · Low 3-4 · Moderate 5-6 · High 7-8 · Extreme 9-10; *Range 6 to 8 if the judgement parameters were different (assumption sensitivity, not a statistical interval)*; the four answers **Severe · A market · Confirmed · Adverse**; the line *Severity 8/10 is above the automatic trigger (7)*; buttons *Run the scenario*, *Why this severity?*, *What the assessment used*, *Technical details*; header buttons *Why this priority? · Why am I seeing this? · Why this stress? · Executive brief · Give feedback on this event*. | "Severity is a transparent scorecard of four anchored answers, not a black box. And the range is labelled for what it is: sensitivity to our own judgement parameters, not a confidence interval." | severity verdict, drawers |
| E2 **A** | Open **Why this severity?** (or scroll to *How the score is built*). | Each answer with *Rules said* / *AI said* ("no language model read this text (rule-based mode)"); **Severe × a market** starts at **7.90**; Certainty 0.00; Direction 0.00; **Market regime: VIX 14.8** (2026-09-18 close) **−0.35**; **7.55 rounds to 8**; novelty not used (no issuer resolved); *Report reliability: moderate*; an arithmetic view of the formula; and the line *Reference: the trained market-reaction model says 2/10*. | "A fixed matrix gives 7.9; one bounded market adjustment takes off 0.35; that is 7.55, which rounds to eight. Tone, model confidence and outlet count are not inputs. And be aware: our own trained impact model says 2 out of 10 for this headline. It is experimental, it never drives the trigger, and the two disagree on screen rather than being hidden." | scorecard, reference model, disagreement shown |
| E3 **A** | Scroll to **Event intelligence**. | *Scope*: risk theme *trade and conflict* → geography *Middle East* → *Market-wide*. *Evidence strength: Insufficient* (1 independent source among 1 report); *Corroboration* diversity 1.00; *Conflicts: no conflict found*; *Model confidence* event 72 %, sentiment 50 % (kept apart from corroboration); *Lifecycle* Developing; *Novelty* New; *Narrative velocity: Abstained* (fewer than 3 reports); *Affected entities: none named*; *Affected sectors: Energy*. Then **What EventShock does not claim here**: company unknown, sector unknown, velocity abstained, contradiction abstained ("absence of evidence, not evidence that the reports agree"). | "Corroboration and the model's own confidence are different things, so they are different panels. And every part can say *not enough evidence*. A missing fact is left blank, never filled in." | event intelligence, abstention |
| E4 | Scroll to **Understand**. | Report text with **4 verbatim excerpts** marked; EVENT *Geopolitical / supply-route disruption, 71 %*; TONE *Neutral +0.02*; WHO *UNKNOWN_ENTITY*; AFFECTED sectors Energy, geography Middle East, asset classes Equities and Commodities; severity indicator *Supply disruption · "Strait"*; a *Trained text models* tab for comparison. | "The quotes are checked against the text. No company is named, so none is invented: the issuer stays unknown and the event is treated as market-wide." | grounding, no invented entity |
| E5 | Scroll to **Evidence**. | Three kinds of support kept apart: *Source evidence* (the quote), *Model inference* (event, tone, affected), *Scenario assumptions* (eight shocks at reference severity 7, `shock × clamp(severity / 7, 0.5, 1.5)`). **Historical analogues**: "not distinguishable from an ordinary day", 20 most similar of 50 distinct past stories, typical move −0.18 % (−1.2 % to +1.2 %), past reports such as *Oil prices extend gains as fears rise of potential Iran attacks* (11 Apr 2024, similarity 0.88, −0.90 %). **External market view**: *No relevant external prediction market identified* (captured Kalshi copy, 2026-10-05). | "Precedent is context, never a score input: the pre-registered test found it adds no information about the move beyond regime and calendar. And an outside prediction market is shown as an observation beside our view; here it found no match, and we say so." | analogues, external markets |
| E6 | Scroll to **What did EventShock know at this moment?** | *Before the report* (market state, used), *At the report* (the source text, used), *After the report* (the realised move, **not used**); the list *Deliberately excluded from the severity score* (later coverage, later filings, the realised move, the scheduled calendar items). | "This is the leakage answer. Everything dated after the report is shown for audit and marked as never used." | point-in-time timeline |
| E7 | Scroll to **Stress**. | *Mapped scenario* Geopolitical flight-to-safety; relevance **Critical, reaches 84.5 % of the book (35.7 % evidenced, 48.9 % only assumed)**; *My exposure: event → risk factor → holdings* with every edge labelled *Observed* or *Scenario assumption*; the **contagion map** (event → risk factors → where it lands: Consumer 36.2 %, Equity positions 35.2 %, Industrials 19.1 %… → largest holdings, e.g. Target term loan 4.2 %, NIKE equity 3.6 %); the scenario gate list, all seven *(met)*; "11 of 14 shocks bind to this event"; **Concentration and blind spots**: "No dimension of this portfolio is concentrated by the test below." | "Every edge has a rule and a basis. This is a mapping, not a causal model, and 48.9 % of that reach is only assumed; the page says so. The scenario is generated only if seven gates pass, and each gate is shown." | propagation, materiality, gates, concentration |

---

## 4. Stress Lab: `/stress` (3:10 to 4:30) · **A** 2:00 to 2:50 (S1, S2, S6)

Click **Stress-test in Stress Lab** from the Desk, or open `/stress?signal=sig_8f79c8bbd6`.

| # | Do | You see | Say | Feature |
|---|---|---|---|---|
| S1 **A** | Pause on the page, then click **Run scenario**. | *Stressing the default synthetic book*; the event card (8, High); **12 scenario cards** (8 single-factor, 4 multi-factor), Geopolitical flight-to-safety marked *matches this event*; the portfolio panel: **$860.1M, 103 positions, 34 issuers**, "SYNTHETIC positions generated with a fixed seed on REAL listed issuers"; by asset class 35.2 / 33.6 / 30.7 / 0.4 %. After the click, **$860.1M → $822.8M, −$37.3M (−4.33 %)**. | "A synthetic wholesale book: 103 positions on real issuers, equities, bonds, loans and derivatives. Real names, invented positions, and it says so." | scenario cards, synthetic book |
| S2 **A** | Walk the value bridge. | **Shocks applied ×1.14**: −9.1 % market equity, −16.0 % event sector, −23 bp rates, +69 bp credit spread, PD 1.29×. **Where it lands**: Equities −$29.3M, Bonds −$6.1M, Derivatives −$1.6M, Loans −$222.6K. **Largest positions hit**: NIKE −$2.4M, Tesla −$2.0M, Target −$1.5M, Boeing −$1.5M, Exxon −$1.4M. **After**: "$37.3M removed · 4.33 %", drawn to scale. | "The mechanism, not just a number: which shocks, where they land, which positions carry them. The 1.14 is severity scaling. The shock sizes are assumptions, labelled *Scenario assumption*; the arithmetic is deterministic." | value bridge |
| S3 | Point at the banner under the cards, then at **Where the change comes from**. | The banner *Only market-wide shocks applied*: the sector (Energy) was read from the text by the assessment; issuer shocks do not apply; *3 scenario shocks did not apply to this event*. The drill-down *Portfolio → Asset class → Sector → Risk factor* (Equities 79 %, Bonds 16 %, Derivatives 4 %, Loans 1 %), labelled *Sensitivity, not cause*. | "If a shock does not apply, it says why. And this is sensitivity to the assumptions, not what caused the event." | applicability, drill-down |
| S4 | Open **Why is my portfolio exposed?** | *Modeled, not a forecast*: market equity −9.1 % on 32.5 % of the book (38 positions, $279.2M, beta 0.99) → −$25.9M; credit spread +69 bp on 41 bonds (duration 4.6 y) → −$9.1M; sector equity −16 % on 3.2 % (5 positions) → −$5.0M; PD ×1.29 on 19 loans → −$222.6K; rates −23 bp → **+$3.0M**; total −$37.3M. | "Each line is a shock, the exposure it hit, and the formula. Rates fall in a flight to safety, so bonds gain there; it is not all one direction." | per-shock explanation |
| S5 | Scroll to **Why the portfolio moved**. | Market-wide shocks −$32.3M (87 %), sector shocks −$5.0M (13 %); tabs *Kind of shock · Issuer · Sector · Industry · Market factor · Risk factor · Asset class · Position*; the **loss heatmap**: sector × market factor, Consumer −$13.5M the largest row; "The cells add up to −$37.3M (difference 0.00)". | "Every table is the same total regrouped, and each one adds up to the run or the builder refuses to draw it." | attribution, heatmap, reconciliation |
| S6 **A** | Scroll up, click the **Oil supply shock (multi-factor)** card. | The same event re-run under another scenario: **−3.78 %** (about −$32.5M) *(the API run was checked on 2026-10-10: −3.78 %; the card click was not re-driven today)*. | "Same event, different assumptions, one click. The result moves; the engine does not." | scenario switching, multi-factor |
| S7 | Scroll to **Test a different severity**; drag the slider. | *What-if assumption, not the assessed severity*: impact score applied (event's own 8), BASE vs SCENARIO −$37.3M / −4.33 %; "Scenario simulation, not a prediction". | "Slide the severity and the engine recomputes every position." | what-if slider |
| S8 | Open **Inspect this run**: *How calculated?*, *Assumptions*, *Show every position*, *Audit trail*; then *How large are this scenario's shocks by historical standards?* | Formulas typeset step by step; the shocks and why; all 103 positions before and after; run id, engine, portfolio hash; the scenario shocks ranked against 1/5/21-session history since 2014 (credit and PD shocks are *not checkable*). | "Reproducible: the run id is a hash of its inputs. And each shock is ranked against market history so you can see how extreme our assumptions are." | audit trail, history check |

---

## 5. Today: `/today` (4:30 to 4:55)

| # | Do | You see | Say | Feature |
|---|---|---|---|---|
| T1 | Open **Today**; point at the clock and the summary line. | *What should I care about right now?*; *Replay · deterministic / Live*; *Cycle 28 of 28 · 01 Oct, 12:00 UTC*; "400 tracked events, 112 changes in the last 4 cycles… Ordered by relevance to the portfolio (materiality tier), then severity, then the size of the change, then how recent it is, then the event id. **No importance score.**" | "What changed, ranked for the active portfolio, by a documented key shown on every card. Never a black-box score." | monitor, rank key |
| T2 | Scroll the sections; open **Why is this here, in this order?** on the first card. | *Top new risks* 58, *Escalations* 0, *Largest changes in portfolio exposure* 0, *…in modeled stress* 0, *Important evidence changes* 6 (e.g. *US ban on $1B worth of Canadian imports*: evidence Insufficient → Moderate, 1 → 2 independent sources), *Major conflicts* 0, *Concentration changes* 4 ("Equity market level: 70 events now share it… the risk is concentrated in those holdings"). Each card has *Event → Evidence → Scope → Portfolio exposure → Propagation → Stress → Attribution*, *Executive brief* and *Give feedback*. | "Empty sections say 'nothing in this section for this window'. On a frozen replay the escalation and conflict rules rarely fire; they are covered by tests rather than by this data, and I would rather say that than fake a card." | sections, honest empties |

---

## 6. Review: `/review` (4:55 to 5:20)

| # | Do | You see | Say | Feature |
|---|---|---|---|---|
| R1 | Open **Review**. | *Review queue*; counters Open **75** · Reviewed 0 · Dismissed 0; "75 of 400 tracked events need a look… Ordered, not scored". Item #1: *Oil rise, bond yields: Top factors behind Tuesday stock market crash* (macro · rates · severity 10/10 · 1 independent source · critical to the book 100 %) with three named rules: *High severity, one source*; *Material to the book*; *Large modeled loss* (−2.34 %). The Hormuz event is #4 (critical, 84.5 %, −4.91 %). | "Which events should a person look at, and why. Each item names the rule that queued it. A severity-10 headline from a single source is exactly what a human should check." | review queue, named rules |
| R2 | Click **Why this position?**; then **Mark reviewed** on one item (with the clean demo store). | The sort key; a *Reviewed* count of 1. | "A decision is a note: append-only, and it reopens if the event's own evidence changes. It never changes a model or a score." | append-only decisions |

---

## 7. Analyze: `/analyze` (5:20 to 6:10) · **A** 2:50 to 3:20 (A1, A2)

Run the server with `EVENTSHOCK_LLM=0` (section 0) so the banner reads *rule-based reading*; the severities below are the rules-mode values, **checked on 2026-10-10 through the API** (the page flow itself was not re-driven, to avoid sending text to a provider).

| # | Do | You see | Say | Feature |
|---|---|---|---|---|
| A1 **A** | Open **Analyze**; show the chips *A company · A sector · The market · Nothing to name* and *More examples: one per event class*; the *News / Social post* toggle. Paste **Fed raises rates by 25 basis points as expected**, click **Analyze**. | Severity **2/10**, far below the trigger; no stress runs; an option to run it as a what-if. | "Same engine as the replay, so a pasted line is scored exactly like a historical one. An expected 25-basis-point move is not an emergency: the scale starts at the bottom." | paste-and-score |
| A2 **A** | Paste **Escalating tensions threaten oil supply routes in the Gulf, shipping halted**. | Severity **7/10**, at the trigger; geopolitical scenario suggested; issuer unknown. Click **Run the scenario** to show before → after. | "No company is named, so none is invented. Seven crosses the trigger, so a scenario is suggested." | trigger, no invented entity |
| A3 | Paste **Bank run spreads as the lender collapses and funding freezes across markets**. | Severity **10/10**, credit / systemic scenario. Open **How the score is built** and the **Evidence** tab. | "The top of the scale is reachable: a systemic event is not 'seven instead of six'. Every part carries an origin: AI, data, rules, hybrid or assumption. In rules mode it says no language model read this text." | full scale |
| A4 | Return to the Desk. | The pasted items appear on the wire tagged *Pasted*. | "A pasted text becomes an ordinary signal: it joins a story, and can be stress-tested like any other." | one door for all sources |

---

## 8. Portfolios: `/portfolios` (6:10 to 6:50)

| # | Do | You see | Say | Feature |
|---|---|---|---|---|
| P1 | Open **Portfolios**; the tabs *Portfolios · Watchlists and monitor · Scenario lab*. | The default book *Synthetic Wholesale Banking Book (real issuers)*: read-only, 103 positions, **$860.1M**, 61.3 effective positions; asset class 35.2 / 33.6 / 30.7 / 0.4 %; sector Consumer 36.2 %, Industrials 19.1 %, Financials 17.0 %, Technology 12.9 %, Energy 8.8 %, Healthcare 6.0 %; region US 95.6 %, GB 4.4 %; largest issuers Target 7.8 %, Boeing 6.5 %, Walmart 6.3 %. The **exposure heatmap** (sector × asset class; "the cells add up to $860.1M (difference 0.00)"). *Concentration and sensitivity*: equity beta 1.00, bond duration 4.6 y, **−$133.4K per +1 bp**, −1.6 % for +100 bp. | "Where the book sits before any event. Every cell reconciles to the total, and the sensitivities are first-order, stated as such." | default book, exposure heatmap, sensitivities |
| P2 | **Create a portfolio**; paste `AAPL 20%`, `JPM 15%`, `MSFT 15%`, `TLT 25%`, `Cash 25%`; **Read these holdings**; **Save**. *(earlier stage; not re-driven on 2026-10-10)* | "What EventShock understood": TLT's duration looked up, a Treasury fund takes no credit-spread shock, cash is never stressed; the top bar chip changes to your portfolio. | "Bring your own book in plain text. The default stays the synthetic one, and one click, *Use default portfolio*, returns to it." | personal portfolios |
| P3 | Open **Watchlists and monitor** and **Scenario lab**. *(earlier stage)* | A watchlist matched on the resolved scope; the lab with base / assessed / custom scenarios and **Reverse stress** ("what would it take to lose 5 %?"). | "Watchlists never match an unresolved event to a company. And reverse stress searches a bounded grid; the loss it shows is a full engine run." | watchlists, scenario lab, reverse stress |

---

## 9. Rebalancer (Module A): `/rebalancer` (6:50 to 8:30) · **A** 3:20 to 4:05 (M1, M5)

| # | Do | You see | Say | Feature |
|---|---|---|---|---|
| M1 **A** | Open **Rebalancer**. | *Tactical index rebalancer*; three strategy chips (*Sentiment tilt (baseline)*, *+ risk limits*, *Sentiment × impact (experimental)*); the strip **15 stocks, equal-weight benchmark · 58 cycles every 6 h (17 Sept 06:00 to 1 Oct 12:00 UTC) · average turnover 2.03 % per cycle (118 % in total) · 577 reports used (60 social posts left off: their time was assigned by the replay) · NVDA +3.3 pp, JPM −2.7 pp**; the stacked **Weights over time** chart in sector hues with the toggle *Weights / Active vs benchmark*. | "Module B stresses a portfolio. Module A is the second downstream use of the same engine: the sentiment score drives the weights of a mock 15-stock index. Positive news raises a weight, negative lowers it, inside bounds and a turnover limit. Sixty social posts are left off because their time was assigned by the replay; we count them rather than hide them." | index, weights over time |
| M2 | Drag the **Cycle** slider; read the table; hover a ticker at the chart's right edge. | *Selected cycle 58 of 58, 1 Oct 12:00 UTC, turnover 0.46 %*; table columns Weight · Benchmark · Active · Change · Sentiment · Reports · **Why** (NVDA 10.00 % *At the upper bound*, XOM 8.96 % *Tilted up*, GOOGL *No clear sentiment*); *What was traded*: BUY 8, SELL 6. | "Every weight has a named reason, and the table holds the exact figures." | cycle slider, named reasons |
| M3 | Click **NVDA**. | *Why NVDA holds this weight*: sentiment +0.272 from 24 reports by 14 sources, each source at most one vote; the five largest headlines with outlet, age, decayed weight, sentiment and contribution (+0.211 of the score). | "You can check the score by adding up the headlines. One outlet cannot shout louder by publishing more." | explainable score |
| M4 | Open **How the rule works** and **What-if controls**; raise the tilt, then reset. | Four steps: Score (36 h half-life, one source one vote), Tilt (`e^(2 × score)`), Bounds (3.33 % to 10.00 %), Turnover (at most 4.00 % per cycle, no trade below 0.20 %); "every number is a judgement prior, written before any result was looked at"; a banner marks the what-if. | "Every number is a judgement prior and you can see how much each one matters. None is fitted." | transparent rule, what-if |
| M5 **A** | Scroll to **Back-test**. | *An illustration, not evidence of skill*, 10 sessions (2026-09-18 to 2026-10-01), 5 bp cost: rebalanced **−0.99 %** vs equal weight −1.18 %, **difference +0.19 %**; mean daily turnover 6.0 %; rank IC 0.098; **Control**: 200 shuffles land from −0.33 % to +0.32 % and the real result is at the 82nd percentile: "within what shuffled sentiment produces by chance, so this window shows no evidence the sentiment tilt helps". | "We built the control into the page. A shuffled-score placebo does about as well, so we claim a transparent rule, not alpha." | placebo, honest result |
| M6 | Click the **Trade decisions** tab. | *The rebalance at this cycle*: BUYS 5 · SELLS 3 · HELD 7 · turnover 0.46 % · est. cost $4,586 (0.05 bp of a mock $1 bn index); every stock with Before · Target · After · Trade · Room · *Held back by* (NVDA: *Upper bound −0.67 pp*); *Approve or reject this rebalance*; per-trade cards with a template sentence, flags (*Evidence adequate*, *Reports disagree 71 % positive / 29 % negative* for AMZN) and the mock notional as a share of daily volume. | "This is what a manager would be asked to approve, with the reason for every line and the rule that held it back. The sentence is a template, not a model." | trade decisions, constraint ladder |
| M7 | Click the **Strategy lab** tab. | Five rows: sentiment tilt −0.99 % (+0.19 %, **82nd** percentile), + risk limits −1.01 % (+0.17 %, 79th), sentiment × impact −1.07 % (+0.11 %, **84th**), equal weight −1.18 %, buy-and-hold −1.23 %; every verdict *Within what shuffled scores give*; windows; *How fragile is the baseline?*: **21 of 21 settings ahead of equal weight, 1 outside its placebo range, about 2.1 would be by chance**. | "Every strategy is inside its placebo range. All 21 settings beat equal weight, which sounds like robustness, and is not: shuffled scores beat it too. The grid is not a tuning surface." | strategy lab, anti-overfitting |
| M8 | Click **Trade decisions**, enter a name, click **Approve all trades**; open the **Ledger** tab. | The ledger starts at *0 decisions*; after approval an entry marked simulated appears; "A decision is valid only for the exact proposal it was made on". | "Nothing is sent to a broker and the served index never changes. If the proposal changes, the server refuses a stale approval." | simulated ledger |

---

## 10. Evidence: `/evidence` (8:30 to 9:10) · **A** 4:05 to 4:35 (V1, V3)

| # | Do | You see | Say | Feature |
|---|---|---|---|---|
| V1 **A** | Open **Evidence**. | *How much evidence supports EventShock?*; four tiles: **Sentiment** *Experimental model* (no pre-registered checks exist for this stage); **Event understanding** *Experimental* (3 of 4 pre-registered checks passed); **Impact** *Experimental* (**15 of 22** passed, 2 not evaluable); **Stress engine** *Deterministic*, "Not a model. Fixed formulas… What it cannot do is make the shocks true"; each says *Not called validated*. | "Nothing is called validated unless it passed a bar written before the results were seen, and the limits are on screen before anyone asks." | verdict tiles |
| V2 | Click through the tabs *Methodology · Evaluation · Datasets · Mathematics · Limitations · Outcome check · Scope · Analyst feedback · How it is built*. | Methodology: the four kinds of number (*Model prediction · Historical observation · Scenario assumption · Realised outcome*) and *Temporal discipline: nothing from the future* (feature counts: 5 known in advance, 13 published at event time, 50 from the report or prices before it, **18 refused**); *Outcome check*: the severity scale is "heuristic, not calibrated to outcomes". | "Every number says which of four kinds it is. Anything known only after the event is refused, and a model that asks for it does not run." | methodology, leakage rules, outcome check |
| V3 **A** | Stay on a tile and open **What was and was not met**. | The failed checks named (for impact: interval coverage and the pre-event placebo). | "We tested our own score, wrote the bar first and report that it missed. The trained impact model's skill comes from the calendar and the volatility regime, not the text." | pre-registration, honest failures |

---

## 11. The shell: features that sit on every page (use during the beats above, or as 0:20 at 9:10)

| # | Feature | Do | You see | Say |
|---|---|---|---|---|
| X1 | Sidebar and clock | Hover the groups. | **Monitor** (Desk, Today, Review, Analyze), **Investigate** (Event, Stress Lab, Rebalancer, Portfolios), **Trust** (Evidence); bottom left *Replay · real sources, clock 01 Oct, 12:00 UTC*. | "One navigation; the clock is pinned, so every number reproduces on every start." |
| X2 | **⌘K** *Jump to anything…* | Press ⌘K, type "stress". *(earlier stage; not re-driven today)* | Pages, drawers of the current page and events. | "Jump to any page, any explanation, any event." |
| X3 | Theme | Click the sun/moon button at the right of the top bar. | Light ↔ dark; remembered. | "Readable on a projector, and in the dark." |
| X4 | **Live** (optional, rehearse first) | Open the Live control only after reading section 0. *(earlier stage)* | Source choices *News + SEC filings*, *GDELT*, *SEC filings*, *Simulated live (captured file, offline)*; off at every start. | "Live is off at every start. Turning it on is the explicit act that allows outbound requests. The simulated choice replays a committed capture, so I can show the live path with no network." |
| X5 | **Adjust** | Click *Adjust* in the top bar; change one gate; reset. *(earlier stage)* | The change is labelled *user assumption* and counted on every answer; reset restores every default. | "Every judgement prior is adjustable and visibly yours; the shipped configs are never edited." |

---

## 12. Closing (9:10 to 9:40) · **A** 4:35 to 4:55

Return to the Desk (Hormuz selected).

> "From unstructured text to a stress result, on one screen: what was reported, what the AI read, how severe, what it reaches, what it costs the book. Every number carries its source, its formula and its limits, and nothing is called validated that has not passed a test written in advance. The models are experimental, the portfolio is synthetic and the shocks are assumptions. The value here is the traceable chain and an honest line between prediction, history, assumption and outcome. Thank you."

### What to say about the rough edges

| Edge | Say, if asked (or pre-empt it in one sentence) |
|---|---|
| Stress Lab relevance *High · 100 %* vs Event page *Critical · 84.5 %* | "Two different questions: the Stress Lab card says the whole book is exposed to a market-wide event; the Event page's propagation counts positions the mapped risk factors actually reach, 84.5 %, of which 48.9 % is assumed. I quote the 84.5 %." (Avoid lingering on the Stress Lab card.) |
| *Buy JPM … sentiment −0.23* | "A buy here is a step toward the target: JPM is still 2.7 points below its benchmark, and the index lagged its own target by 0.09 pp because of the turnover limit. The sentence states the score; the trade moves the weight toward what that score asks for." |
| "82th percentile" | A typo in the UI's ordinal; say "82nd". |
| Trained impact 2/10 vs severity 8/10 | Already on the page; say it first. |
| 963 events vs 1,082 scored | The wire counts events (report clusters); the counters count signals. |
| *Event type for new text is scored by tfidf-lr-event-v1 (the served event model needs an encoder that is not installed)* | Replay uses pinned vectors; new text uses the TF-IDF event model unless the optional encoder is installed; it is labelled. |
| Many empty sections on Today and a one-source Review queue | A frozen 14-day replay: escalations and conflicts rarely fire; say so. |

---

## 13. Fallbacks and recording notes

- **Server not up:** `make run` builds and serves (`make build` if `web/dist` is missing). Everything is read from the frozen replay, so no network is needed and the figures never change.
- **Page spinner on first load:** the signal list is 2.6 MB and takes about 10 s on a cold server; wait for *963 events*.
- **Second example if time allows:** the Desk's *Also try* link (Apple's $5.7bn patent verdict, three outlets, evidence *Moderate* vs Hormuz's *Insufficient*); `/?signal=sig_90ee2542ae` (Nike) shows a chain that stops honestly below the trigger. *(earlier stage)*
- **Voice-over:** one take per page, record the cursor, and add a two-second hold on each number. Do not read the table cells aloud; say the *Say* column in your own words.
- **Never say:** "validated", "predicts", "early warning", "alpha". **Always label** shock sizes "assumptions".

---

## 14. YouTube chapters (full tour, adjust after editing)

```
0:00 The problem and the one-screen answer
0:30 Desk: from headline to portfolio
1:40 Event page: severity, evidence, what was known when
3:10 Stress Lab: the loss and where it lands
4:30 Today: what changed
4:55 Review: what a person should look at
5:20 Analyze: paste a headline
6:10 Portfolios: your own book, reverse stress
6:50 Rebalancer (Module A): sentiment to weights
8:30 Evidence: how far to trust it
9:10 Close
```

**Cut A (4:55):** 0:00 intro · 0:25 Desk · 1:10 Event · 2:00 Stress Lab · 2:50 Analyze · 3:20 Rebalancer · 4:05 Evidence · 4:35 close. If it runs long, drop D5 and E3 first, never the Evidence beat.

---

## 15. What was verified, and what was not (2026-10-09/10)

**Driven in the real UI against the replay:** Desk (wire, trace, counters, monitor strip, table), Event page (all chapters), Stress Lab (the Run scenario click, bridge, attributions, what-if section present), Today, Review, the Analyze page, Portfolios (default book), Rebalancer (all four tabs), Evidence (tiles and tabs). **Checked through the API instead:** the three Analyze headlines in rules mode (severity 2, 7, 10); the Oil supply shock run (−3.78 %); the clean launch command. **Not re-driven today:** the Oil card click, the severity slider, creating a personal portfolio, watchlists, the scenario lab and reverse stress, the executive brief, the Adjust drawer, ⌘K, the theme toggle, the Live popover, and the approve/mark-reviewed clicks (marked *earlier stage* or described from the UI text). Rehearse those once before recording.
