# EventShock: the 3 minute 40 second demo

One deterministic path from an unstructured headline to a portfolio result, on real replay data. Nothing is typed, nothing calls out
to a live API, and every number below is reproduced exactly on every start (the replay clock is pinned to 2026-10-01 12:00 UTC).

**Start:** `make run`, open <http://127.0.0.1:8000> (light theme is the default; the toggle is in the left rail).
**Hero event:** Nike's Q3 earnings preview (`sig_90ee2542ae`), the only all-model signal with a clean driver story, a filing before the
report, a filing after it, and a recorded outcome. It is also reachable as `/events/sig_90ee2542ae`.
**Answers the jury's eight questions in order:** what happened · what was detected · how the NLP works · how severe · why · what supports
it · what it does to the portfolio · can I test another scenario.

| # | Time | Presenter does | Judge sees | Presenter explains | Conclusion for the judge |
|---|------|----------------|------------|--------------------|--------------------------|
| 0 | 0:00 | Opens the Risk Feed. | Four real numbers in a row: **2,330** reports → **962** market events → **725** scored by the impact model → **19** reach impact ≥ 7. Below it, the featured event. | "EventShock reads financial text, works out what happened and how severe it is likely to be, then shows what that does to a portfolio. These counts are the whole pipeline on real data." | "This is a pipeline, not a sentiment dashboard." |
| 1 | 0:25 | Clicks **Open the event story**. | The headline, company (Nike, NKE), time, and an **estimated impact 7 / 10** with an *Experimental model* tag and a bracket 1–9. Under it a five-node chain: Report → NLP → Impact → Scenario → Portfolio. | "What happened: Nike earnings preview. Who: Nike. When: 30 Sept 03:00 UTC. EventShock detected an earnings event and estimates a *High* impact. The tag says this model is experimental and the bracket says comparable events realised anywhere from 1 to 9." | "Severity and its honest uncertainty are on the first screen." |
| 2 | 0:55 | Scrolls to **What the text says**; clicks **Why?**. | The input text, **Earnings / Performance** at 65 % calibrated confidence with the 50 % commit mark, and **Neutral +0.00** sentiment on a gauge. The drawer lists every class probability and the abstention rule. | "A trained text model reads the headline: word statistics plus semantic embeddings. It can say 'not an event' or 'uncertain' instead of guessing. Sentiment is tone; it is *not* impact: the note under the chain says so." | "The NLP is a real analytical stage, and it abstains when unsure." |
| 3 | 1:25 | Clicks **Show inputs**, then **How calculated?**. | Inputs grouped as *The report / What the text models read / Calendar context / Market state*, each marked *Known in advance / Published before the report / Event time*, plus the list **Deliberately not used**. The next drawer shows typeset formulas. | "These are exactly the numbers the model saw: earnings are due (calendar), Nike's usual volatility, the VIX. Nothing from after the report is allowed, and the realised move is never an input. The score is the model's estimate ranked against past events, mapped to a 1–10 ladder." | "Explainable and leakage-disciplined, with the maths on demand." |
| 4 | 2:00 | Scrolls to **What supports it**; drags the timeline slider to the end. | Comparable events: 197 past ticker-sessions, 26.9 % realised a move of 3σ or more against 3.2 % of all events. The timeline: an 8-K on 17 Sept (*Available at the time*), the report, then the earnings-release 8-K of 2 Oct (*Learned later*, hatched, "accepted after EventShock's replay clock"), then **Realised move 0.41σ**. | "Comparables are statistics of the model's own history, not individual events: we say so. Now watch what EventShock knew: at the moment it scored, only the 17 Sept filing. The earnings release came after and is never read. Finally, what actually happened: a 0.41σ move, which lies inside the 1–9 range the model stated. We show it because it was honest uncertainty, not because it flatters the score." | "Temporal integrity is demonstrated, not just asserted." |
| 5 | 2:40 | Clicks **Run scenario**. | **Portfolio value $860.1M → $853.1M, estimated scenario change −$6.9M (−0.81 %)**, labelled *Scenario simulation*. A to-scale bar, a hatched bar for the **63.8 % of the book (84 positions)** outside this scenario's reach, and the propagation strip (4 risk factors, 19 of 103 positions hit). Below: a waterfall by asset class and the drill-down. | "The impact of 7 triggers the *Earnings repricing* scenario at full scale. Equities carry 92 % of the change; Nike's own equity is $3.4M of it. We state plainly that most of the book is untouched: that is exposure to *this* scenario's assumptions, not safety." Click *Equities*, then *NIKE*. | "A concrete portfolio consequence, with coverage stated, drillable to a position." |
| 6 | 3:10 | Drags **Test a different severity** to 9. | Base **−$6.9M** vs scenario **−$8.9M (−1.04 %, ×1.29)**, recomputed by the real engine, tagged *Scenario simulation, not a prediction*. Optionally **How calculated?** shows the scale formula with these numbers. | "Same scenario, milder or harsher: the engine is deterministic arithmetic, no model, so the answer is reproducible. Drag down to 4 and the scale falls to ×0.57 (−$4.0M); the clamp only bites outside roughly 3.5 to 10.5." | "Interactive what-if on the real engine; simulation is never presented as prediction." |
| 7 | 3:25 | Opens **Evidence** (left rail). | *How much evidence supports EventShock?*: four tiles, Sentiment / Event understanding / Impact (all *Experimental*, with checks passed out of total) and Stress engine (*Deterministic, not a model*). | "Nothing is called validated unless it passed a bar written before the results. Impact met 15 of 22 checks and failed 5, so it is experimental, and the page says which. The study shows the calendar and market state carry the real skill; the text models add none beyond them." | "Calibrated honesty: the jury can see the limits before asking." |

**Close (3:40):** "From unstructured text to a stress result: understandable at the surface, with inputs, evidence, mathematics and audit one click
down, and a clear line between prediction, history, assumption and outcome."

## If something goes wrong

- Server not up: `make run` (UI is served from `web/dist`; `make build` if it is missing). Everything is read from the frozen replay pack, so
  there is no network dependency and the figures never change.
- Want a second example that shows graceful degradation: the Feed's *Also try* link (Apple's $5.7bn patent verdict). Three outlets
  carried it, but its entity link is weak, so the impact is a labelled **placeholder rule** with no uncertainty range, no model inputs,
  and no outcome: the UI says why and never shows an unvalidated number as authoritative.
- Dark theme for a projector: the toggle at the bottom of the left rail (the choice is remembered in the browser).

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
