# External market intelligence (Kalshi) — Stage 12

An **observation**, not an input. The external-market view shows what an independent prediction market appears to price about an event's *theme*, beside EventShock's own assessment. It is a derived side-car (`src/eventshock/markets/`, `configs/external_markets.yaml`).
It **never** feeds the `RiskSignal`, impact, sentiment, classification, severity, mapping, stress or reverse stress; a replay test shows those outputs and `GOLDEN_SERVED_DIGEST` are byte-identical with the provider on, off and failing.

## Labels (never blurred)
`SOURCE EVENT` · `EVENTSHOCK ASSESSMENT` · `EXTERNAL MARKET OBSERVATION` · `SCENARIO ASSUMPTION` · `HISTORICAL OBSERVATION` · `REALISED OUTCOME`. The market timeline keeps these as separate row kinds; wording is descriptive ("directionally aligned"), never "Kalshi confirms".

## Providers (`MarketProvider`, behind an adapter)
| mode (`EVENTSHOCK_MARKETS`) | what it reads | when |
|---|---|---|
| `snapshot` (default) | `data/external/kalshi_snapshot.json`, hash-pinned by its manifest (a modified file stops start-up) | replay, demos, offline |
| `fixture` | `data/fixtures/external_markets/markets.json`, **SYNTHETIC**, every row labelled | tests, the nine required cases |
| `live` | Kalshi's public `trade-api/v2` (no key; rate limited; retries) | opt-in |
| `off` | nothing | |

A missing snapshot or a failing provider is a labelled `UNAVAILABLE` ("External market data unavailable."): nothing is invented. The Kalshi parser reads the current shape (dollar strings `*_dollars`, fixed-point `*_fp`, statuses `active` / `finalized`); a changed shape degrades to UNAVAILABLE rather than a guessed number. Implied probability = the last trade, else the midpoint of a tight quote (spread ≤ 0.05), else *not priced*. `make kalshi-snapshot` re-captures (network, ~6 minutes because of retries); `make market-fixtures` regenerates the fixture.
**Replay uses only observations at or before the moment** (no look-ahead); the previous observation is 24 h earlier. The captured snapshot reflects its capture date (2026-10-05), so many replay events honestly show NO_MATCH / INSUFFICIENT_DATA.

## Matching (not keyword overlap)
An event reaches a market only through a **curated theme** (FED_POLICY, US_INFLATION, US_LABOUR, US_TRADE_POLICY, US_SOVEREIGN_CREDIT → Kalshi series) and explicit gates, all shown in the UI:
event side — EVENT_CLASS, SCOPE (resolved; UNRESOLVED is never matched), SUBJECT (strong = a scope theme or two phrases; one phrase = LOW_CONFIDENCE), GEOGRAPHY (a stated conflicting place blocks; no stated place does not);
market side — OPEN, HORIZON (resolves within the configured window), FRESH (observed within the staleness limit).
Status: `MATCHED` · `LOW_CONFIDENCE_MATCH` · `NO_MATCH` · `INSUFFICIENT_DATA`. Among candidates the most active open market wins (open interest, then volume, then id).

## Interpretation (descriptive)
Rules R0–R4 compare the market's probability change (percentage points) with EventShock's severity/materiality: `MARKET_REPRICED` (≥ 10 pp), `ALIGNED`, `DIVERGENT`, `LOW_INFORMATION` (thin open interest / volume, or not priced). Orientation (does a higher probability mean more risk?) is configured per theme or read from the question ("above" / "below"), otherwise NEUTRAL and unmapped. Every interpretation says it does not show that either view is wrong.

## API and UI
`GET /api/events/{id}/external-markets`, `/market-timeline`, `/analogues` (alias of the signal endpoint), explanation subject `MARKET`, and the market section of the executive brief ("No relevant external prediction market identified." / "External market data unavailable."). UI: the *External market view* card in the Event page's Evidence chapter beside the historical analogues, with the matching gates, the merged timeline and "Why this market?".

## Limitations
The theme-to-series mapping and every threshold are unvalidated judgement priors. A market price is an aggregate of participants' bets, not ground truth, and thin markets are noisy. The geography gate is conservative (a trade headline naming only China is NO_MATCH for a US theme). One market per event is shown. Live mode is rate limited and best-effort.
