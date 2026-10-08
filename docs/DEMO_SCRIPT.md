# EventShock: the 3 minute 40 second demo

One deterministic path from an unstructured headline to a portfolio result, on real replay data. Nothing is typed, nothing calls out
to a live API, and every number below is reproduced exactly on every start (the replay clock is pinned to 2026-10-01 12:00 UTC).

**Start:** `make run`, open <http://127.0.0.1:8000> (light theme is the default; the toggle is the sun/moon button at the right of the top bar).
**Opening event:** the Desk opens on *After Iran Says Strait of Hormuz Is Closed Again, Oil Risk to Economy Rises Once More*
(`sig_8f79c8bbd6`): a real replay signal whose whole chain completes in the served configuration (severity above the trigger, a generated
scenario, a reached book). Its single source is shown as such: that honesty is part of the pitch.
**Anywhere:** `⌘K` (or `/`) opens *Jump to anything*: every page, every explanation drawer of the current page, and every event.
**Answers the jury's questions in order:** what happened · what the AI read · how severe · why trust it · what it does to the portfolio ·
can I test another scenario.

| # | Time | Presenter does | Judge sees | Presenter explains | Conclusion for the judge |
|---|------|----------------|------------|--------------------|--------------------------|
| 0 | 0:00 | Opens the **Desk**. | Left: the incoming wire (962 market events from 2,330 reports, newest first, each with its event-type glyph). Right: the selected headline in serif, and under it **one wire through six stations**: *What happened* (aol.com, 1 independent source) → *What the AI read* (Geopolitical, 71 % confident, tone +0.02) → *How severe* (**8/10 High**, range 6–8) → *Scenario it triggers* (Geopolitical flight-to-safety, generated for this event) → *What it reaches* (**Critical** materiality, 84.5 % of the book) → *Portfolio impact* (**$860.1M → $822.8M, −$37.3M, −4.33 %**). | "News in, portfolio consequence out. This one headline: what was reported, what the AI read, how severe, which scenario it triggers, what it reaches, and what it costs the book. Every number comes from the engine; nothing on this screen is typed in." | "The whole product is legible in one screen." |
| 1 | 0:30 | Points at **Why trust it** under the trace. | *1 independent source, insufficient evidence* · *4 quotes checked against the text* · *Lifecycle: developing*. | "We do not hide the weak part: one source only, so the evidence tier is *insufficient*. The reading is grounded in verbatim quotes, and the lifecycle is rule-driven." | "Confidence is shown as evidence, not as a badge." |
| 2 | 0:45 | Clicks two other events on the wire (or presses **J/K**). | The trace re-draws for each, including one that stops honestly (e.g. a low-severity event: *Below the trigger*, *Scenario unavailable* with the failed gate). | "Each event gets the same trace. When the chain should stop, it stops and says which gate failed: no stand-in number." | "Abstention is a feature." |
| 3 | 1:05 | Back on Hormuz, clicks **Open the event story**. | Serif headline, the severity verdict (**8/10 High**, rule-based reading, the four anchored answers: Severe · A market · Confirmed · Adverse), and the inspect buttons, each saying what it opens. | "Severity is a transparent scorecard of four anchored answers, not a black box. Each button says where it leads." Opens **Why this severity?**. | "Explainable at the surface, detail one click down." |
| 4 | 1:35 | Scrolls: the chain, then **Event intelligence**. | The same wire as the Desk (News → AI understanding → Risk signal → Scenario → Portfolio impact, ending in −$37.3M), then four question groups: how well evidenced, what it is, how it is moving, who it touches. | "The same visual sentence on every page. Corroboration and the model's own confidence are kept apart on purpose." | "Trust is decomposed, not asserted." |
| 5 | 2:05 | Clicks **Run the scenario** (or the Portfolio station). | **Stress Lab**: scenario cards (the event's own one marked *matches this event*), then **$860.1M → $822.8M, −$37.3M (−4.33 %)** and the value bridge: *The book* by asset class → *Shocks applied ×1.14* (−9.1 % market equity, −16.0 % event sector, −23 bp rates, +69 bp credit spread, PD ×1.29) → *Where it lands* (Equities −$29.3M, Bonds −$6.1M, Derivatives −$1.6M, Loans −$222.6K) → *Largest positions hit* → *After*. | "This is the mechanism, not just a number: which shocks, where they land, which positions carry them. Hover a class and it lights in both bars." | "A concrete, drillable portfolio consequence." |
| 6 | 2:45 | Clicks the **Oil supply shock (multi-factor)** card. | The same event re-run under another scenario: **−$32.5M (−3.78 %)**, the card highlighted, the bridge redrawn. | "Same event, different assumptions, one click. The shocks are assumptions; the arithmetic is deterministic." | "Scenarios are first-class, not hidden in a menu." |
| 7 | 3:05 | Drags **What if** severity, then opens **Evidence** in the sidebar. | The engine recomputes; then *How much evidence supports EventShock?* with its four verdict tiles (Impact met 15 of 22 checks, so *Experimental*). | "Nothing is called validated unless it passed a bar written before the results." | "Calibrated honesty: the limits are on screen before the question." |

**Close (3:40):** "From unstructured text to a stress result: one wire from the news to the book, with inputs, evidence, mathematics and audit
one click down, and a clear line between prediction, history, assumption and outcome."

## If something goes wrong

- Server not up: `make run` (UI is served from `web/dist`; `make build` if it is missing). Everything is read from the frozen replay pack, so
  there is no network dependency and the figures never change.
- Want a second example: the Desk's *Also try* link (Apple's $5.7bn patent verdict): three outlets carried it, so its evidence strip reads
  *moderate*, against Hormuz's *insufficient*. Nike's earnings preview (`/?signal=sig_90ee2542ae`) shows a chain that stops: severity 2,
  below the trigger, scenario unavailable, with the failed gate named.
- Dark theme for a projector: the sun/moon button at the right of the top bar, or `⌘K` → *Switch to dark theme* (the choice is remembered in the browser).

## Likely questions, with the honest answer

- **"Is the impact score validated?"** No. It is *experimental*: calibrated, but it missed pre-registered checks (e.g. more skill on the real
  window than on a pre-event placebo). The Evidence page lists them.
- **"Does sentiment drive impact?"** No. Sentiment and event type are two of several inputs; in our evaluation the calendar and market state
  carry the measurable skill and the text outputs add none. The UI draws them as readings of the text, not as the cause of the score.
- **"Are the comparable events real events?"** They are aggregate statistics of the model's own out-of-fold history, not retrieved
  individual events. We do not have per-event retrieval and do not pretend to.
- **"Why is the realised outcome 0.41σ when you said 7?"** The score ranks *relative* severity against history and the stated range is
  1 to 9; 0.41σ is a score of 1, inside it. One event is not evidence of accuracy either way.
- **"What stops future data leaking in?"** Every input has an availability class; a filing counts as *before* only if accepted strictly
  earlier than the report; a test swaps all later filings for decoys and requires identical features; splits are chronological with a
  five-session embargo. The timeline shows it live.
- **"Where do the shocks come from?"** They are illustrative assumptions per event type, scaled by impact (`clamp(I / I_ref, 0.5, 1.5)`),
  applied to a synthetic book. They are labelled *Scenario assumption* wherever they appear.


## Stage 7 addendum: the paste-a-headline demo (about 3 minutes, no network needed)

Start `make run` (rule-based mode: nothing leaves the machine; the page says so) or `make run-llm` (a language model reads the text). Open **Analyze**. The strongest three scenarios show the scale working end to end; paste each:

| # | Paste | Expected (rule mode) | Point to make |
|---|---|---|---|
| 1 | **Fed raises rates by 25 basis points as expected** | Severity about 2/10 (negligible/low), well below the trigger; "No stress ran", with *Run as a what-if*. | The scale starts at the bottom: an expected, small move is not an emergency. The tone being negative or positive does not matter, severity is the size of the development. |
| 2 | **Escalating tensions threaten oil supply routes in the Gulf, shipping halted** | Severity about 7/10 (high), above the trigger; Geopolitical scenario suggested. Who: UNKNOWN_ENTITY. | A named issuer is never invented; the scenario is chosen by the assessed class; open **Run the scenario** for portfolio before → after. |
| 3 | **Bank run spreads as the lender collapses and funding freezes across markets** | Severity 9-10/10 (extreme), above the trigger, credit/systemic scenario, large before → after move. | The top of the scale is reachable: systemic events are a different severity from a bad day, not 7 instead of 6. |

Then, for each, show **How the score is built** (matrix value, signed steps, running total; the AI-adjustment lines say "no language model read this text" in rule mode, or show the AI's answer, its reason, and whether it was within the bound), the origin chips (AI / Data / Rules / Hybrid / Assumption), the market note (the VIX date and how many sessions behind, or why it was excluded), the **Evidence** tab (source evidence vs model inference vs scenario assumption; an *inferred* indicator is never shown as a quote) and the **timeline** (later reports and filings shown, tagged *not used*).
Also try **Quantum Dynamics announces a major restructuring…**: the company is a mention, issuer `UNKNOWN_ENTITY`, no company data used. Honest framing for judges: the rule fallback is crude (it under-scores unseen wording on the held-out set); the language model is the reader when available, and the arithmetic after it is deterministic either way.


## Stage 8 addendum: analogues, the honest scale, and the scenario reality check (about 3 minutes, no network)

1. `make run`, open the Desk, pick a company event on the wire (for example a Microsoft data-centre report). On the Event page go to chapter 4, **Historical analogues**: past reports that look like this one, with the move after each, and the line "not distinguishable from an ordinary day" next to the ordinary-day yardstick. Say: precedent is context, never a score input.
2. Open a report that could not be tied to anything (an unresolved one): **"No reliable historical analogue found"**, with the reason. Say: EventShock refuses rather than pad.
3. Stress page -> *Scenario assumptions* drawer: **"How large are these shocks by historical standards?"** (for the macro scenario: the +100 bp rate shock is larger than any 21-session move on record; credit shocks are marked not checkable).
4. Evidence page -> **Outcome check**: the verdict "Heuristic: not calibrated to outcomes", the 2025/2026 intervals that include zero, and why (ordinary news is barely distinguishable from an ordinary day). Say: we tested our own score, wrote the bar first, and report that it failed.


## Optional: "what does this do to *my* portfolio?" (about 90 seconds, after the main demo)
1. Sidebar -> **Portfolios -> Create a portfolio**. Paste `AAPL 20%`, `JPM 15%`, `MSFT 15%`, `TLT 25%`, `Cash 25%` -> **Read these holdings**. Point at "What EventShock understood": TLT's duration is *looked up*, the Treasury fund takes no credit-spread shock, cash is never stressed. Save (it is used immediately).
2. **Stress Lab** on the Apple patent verdict (company event): the three separate answers (severity 7/10, relevance High 20%, modeled impact -3%), then **Why is my portfolio exposed?** (issuer shock on your 20%, sector, market). Say: "a modeled scenario change, not a forecast".
3. Switch to an Energy-sector event: relevance **None** (you hold no Energy), only market shocks reach you. Compare with the default book.
4. **Compare with another portfolio**, then **Use default portfolio** in the top bar: one click and everything is the synthetic book again.

## Stage 12 addendum: from "what changed?" to an executive brief (about 4 minutes, no network)

Start at **Today** (in the sidebar; `/today`). Replay data, the captured/fixture market data and every figure are deterministic.

| # | Presenter does | Judge sees | Presenter says |
|---|----------------|------------|----------------|
| 1 | Opens **Today**; points at the mode chips and replay clock. | Eight sections of cards with a *rank key*, no score; REPLAY is the default, LIVE says the feed is off. | "What should I care about right now? The order is a documented key, shown on every card. Nothing is a black-box score." |
| 2 | Opens **Why is this here, in this order?** on the first card; then **Full reasons**. | The five key parts, then structured reasons each labelled model output / product rule / scenario assumption / historical observation. | "Every reason says what kind of statement it is and which output it was read from." |
| 3 | Clicks the headline, then **Executive brief**. | Sixteen numbered sections, every sentence with a kind word and numbered sources; *Copy as Markdown*. | "Template-written, no language model: a statement without a source cannot be built." |
| 4 | On the event, scrolls to *Event memory* and *External market view*. | The timeline of reports classified by rule; a market card (or "No relevant external prediction market identified.") and the gates behind the match. | "A prediction market is shown as an observation beside our view; it never changes a number. Click *How it was matched*." |
| 5 | Opens **Stress**, then the **Scenario lab** disclosure: adds equity −10 %, rates +100 bp; compares with the base case. | Two results side by side, every size tagged SCENARIO ASSUMPTION, *SCENARIO SIMULATION — NOT A PREDICTION*. | "Your numbers are assumptions, run on the same deterministic engine." |
| 6 | Runs **Reverse stress** at −5 %. | A combination of shocks that reaches −5 % within 0.02 pp, the bounds, the method and "a hypothetical, not the most likely". | "What would it take to lose 5%? Bounded search; the loss shown is a full engine run." |
| 7 | **Portfolios → Watchlists**: watches Microsoft; gives feedback on an event. | Activity for the list; the feedback bar; the Evidence page's *Analyst feedback* tab says "not ground truth". | "Feedback is recorded for review; it does not train or change any model." |

If the Kalshi snapshot shows no match for an event, say so: that is the honest answer. `EVENTSHOCK_MARKETS=fixture make run` shows the synthetic, labelled fixture markets (the nine required cases).

## Stage 15 addendum: live switch, review queue, heatmaps and contagion map (about 3 minutes, no network)

Start `make run`. Everything below is deterministic on the replay except the Live switch, which is OFF until you turn it on.

| # | Presenter does | Judge sees | Presenter says |
|---|----------------|------------|----------------|
| 1 | Points at the **Live** switch in the top bar (it reads *Off*), opens its popover. | The source choices (*News + SEC filings*, *GDELT news feed*, *SEC EDGAR 8-K filings*, *Simulated live*); SEC choices are disabled with the reason when no SEC contact is configured. | "Live is off at every start; turning it on is the explicit act that allows outbound requests. A committed capture of real pack articles lets me show the live path with no network." |
| 2 | Chooses **Simulated live (captured file, offline)**, switches Live on, watches the Desk. | New reports appear on the wire, labelled as a simulated channel; the monitor and Today update. | "Same engine as the replay and as pasted text, so a live item is scored exactly like a historical one." Switch it off again; the signals already ingested stay. |
| 3 | Opens **Review** (sidebar). | A queue of events, each with the named rule that queued it (for example high severity from one source, material to the book), reviewed / dismissed / reopen buttons. | "Which events should a person look at, and why? Rules, not a score; the sort key is shown. A decision is append-only and the event reopens if its own evidence changes." (On the frozen replay the *sources disagree* and *escalating* rules fire for no event; they are covered by tests, not by this data.) |
| 4 | Opens the Hormuz event (`/events/sig_8f79c8bbd6`) and scrolls to *What a scenario does to the portfolio* (the stress chapter). | *Why it matters* and *My exposure: event → risk factor → holdings*, then the **contagion map**: event → risk factors → where it lands → the largest holdings, each line labelled observed / scenario assumption / user assumption. | "Every edge has a rule and a basis. This is a mapping, not a causal model." |
| 5 | Clicks **Run scenario**, scrolls to the **loss heatmap** in the attribution panel, then opens **Portfolios** for the **exposure heatmap**. | Sector × market factor cells that add up to the total loss; sector × asset class cells that add up to the book. | "Where the book sits, and where the shock landed. Every cell table reconciles to its total or the builder refuses to draw." |
| 6 | Opens **Adjust** in the top bar, changes one gate, then resets. | The change is labelled *user assumption* and counted on every answer; reset restores every default. | "Every judgement prior is adjustable and visibly yours; the shipped configs are never edited." |
