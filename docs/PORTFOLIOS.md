# Personal portfolios and portfolio-aware stress (Stage 9)

EventShock used to answer "is this news risky?" for one generic, synthetic book. This stage lets a user **optionally** describe their own portfolio and ask *what happened, how severe is it, how exposed am I, what scenario does it imply, and what would it do to my holdings, and why*.

Nothing here is required. With no portfolio chosen, every endpoint, run id, digest and screen is exactly what it was: the synthetic wholesale book is the default, it is read-only, and **"Use default portfolio"** (portfolio switcher in the rail, the Stress page, the Portfolios page) always puts it back.

## Four things that are never blended

| concept | what it is | where it comes from | label in the UI |
|---|---|---|---|
| **Event severity** | how serious the event reads (1-10) | the Stage 7 scorecard (`HEURISTIC_UNCALIBRATED`) | *Assessment* |
| **Portfolio relevance** | how much of *your* book the event's subject reaches (NONE / LOW / MEDIUM / HIGH, plus the share) | your holdings against the event's scope; display bands in `configs/portfolio.yaml` | *Your holdings* |
| **Scenario assumptions** | the shock sizes (illustrative) | `configs/scenarios.yaml` | *Scenario assumption* |
| **Modeled portfolio impact** | the deterministic engine's revaluation under those shocks | `stress/engine.py` | *Scenario assumption*; wording is "modeled change", never "forecast loss" |

Severity 8 with relevance LOW, or severity 5 with relevance HIGH, are both reportable; there is no combined score.

## Data model

- `PortfolioInput` (what the user typed, and what is stored): name, base currency, mode (`WEIGHT` or `QUANTITY`), optional total value, "remainder as cash", holdings. A holding is a ticker plus either a weight (percent) or a quantity and a price, and optional class, sector, region, currency, cost basis, beta, duration.
- `Resolver` (`portfolio/resolve.py`) is a pure function from that to the engine's `Portfolio`, with a `FieldSource` on every filled-in field (`USER`, `REFERENCE`, `DEFAULT_ASSUMPTION`, `DERIVED`) and a list of `Issue`s (`ERROR` blocks saving, `WARNING` is saved and shown, `INFO` says what EventShock did).
- Storage: one JSON file per portfolio in `data/live/portfolios/` (git-ignored; `EVENTSHOCK_PORTFOLIO_STORE_PATH` overrides; tests use a temp directory), written atomically, capped (25 portfolios, 200 holdings). A damaged file is skipped with a warning. Nothing under `data/replay` or `configs` is ever written to.

## Validation rules (reject or label, never guess silently)

- Weights must add up to 100%. Within 0.5 points they are rescaled and the portfolio says so; less than 100% needs the explicit "hold the rest as cash"; more than 100% is always an error.
- Duplicate tickers, non-positive weights/quantities/prices, missing price in `QUANTITY` mode (there is no price feed), a bond with no duration (cannot be guessed), a beta outside [-1, 3] are errors.
- Unknown ticker: allowed as an equity at beta 1.0, flagged "not one of the 34 issuers EventShock can name". Unknown sector: kept as typed, flagged "sector-level events will not reach it". Unsupported instrument class (`OTHER`, e.g. gold): held at its value, listed as **not stressed** (never as safe). A holding in another currency: valued as entered and flagged "FX not modelled".
- Quick entry (`AAPL 20%`, `AAPL 100 @ 190`, `Cash 25%`) is parsed by the same resolver; weights and quantities cannot be mixed on one portfolio.

## Exposure (`portfolio/exposure.py`)

Total value, weights, asset class, sector, region, issuer, an equity/bonds/cash/other split, largest positions, top-1 / top-5 / largest-issuer shares, HHI and effective number of positions, value-weighted beta, whole-portfolio market beta, value-weighted bond duration and DV01. Each metric ships with its formula. **Exposure is a description, not a risk**: the event decides whether it becomes relevant.

## Event to portfolio (all deterministic)

1. The event is read as before: a company, a sector, the market, or unresolved (`SignalScope`).
2. `RelevanceService` reports which part of the portfolio that subject reaches (issuer share, sector share, or, for market-wide events, the share of the book a market shock can move at all: cash and unsupported instruments cannot be reached). It uses the same `_binds` rule as the engine.
3. The scenario's shocks bind by scope exactly as before; the engine revalues the portfolio (`V·beta·s` for equities on market shocks, `-D·dy` for bonds, expected-loss for loans, delta-notional for derivatives).
4. `GET /api/stress-runs/{run_id}/exposure-chain` regroups **the run's own per-position results** into: event, the shock that applied, the holdings that took it (share and value), their own sensitivity (beta or duration), and the modeled change. Sentences are templates filled with those numbers; no model writes them and nothing is recomputed. Shocks that did not apply are listed with the reason, and holdings no shock moved are reported, not hidden.
5. `POST /api/portfolios/compare` runs the same event and scenario on two portfolios (the default may be one) and lines up per-factor and per-sector contributions as a percent of each portfolio's own value, with a templated "difference" sentence.

An unknown ticker can only be reached by sector and market-wide shocks, because an event about a named company can only resolve to one of the 34 issuers. Region shocks are still not modelled (regions appear as exposure only).

## What changed in the stress engine, and why (the six questions)

| change | principle | data | assumption | testable | verdict |
|---|---|---|---|---|---|
| `AssetClass.CASH` (zero shock, not "uncovered") | cash value is fixed by definition | none | none | yes | added |
| `AssetClass.OTHER` (held, not stressed, reported as uncovered) | no revaluation rule exists; refusing to call it safe | none | none | yes | added |
| `spread_sensitivity` on a bond (default 1) | government debt carries no credit spread; the engine used to widen spreads on every bond | reference table (Treasury funds 0, aggregate funds 0.5, corporate 1) | the 0.5 for aggregate funds is a stated assumption | yes (hand-checked) | added; hash-neutral for the synthetic book (default is omitted from serialisation, so its content hash, JSON and every run id are unchanged) |
| single-factor trailing beta for the 34 issuers (`data/replay/market/betas.json`, `make portfolio-betas`) | the market shock needs the market beta, not the two-factor partial in the impact model's context; the synthetic book's betas are random draws | 250 sessions to 2026-10-01, derived statistics only | stationarity over a year; Vasicek shrinkage toward 1 (prior variance from the cross-section of the 34); **clipped to [0, 3] when used** so a stress never credits a stock with a gain from a market fall on a one-year co-movement | yes (recompute from synthetic prices, no data before the window changes the fit) | used for personal portfolios only; the default book keeps its own |
| convexity | second-order bond price effect | none for user holdings | n/a | no | **not added for user holdings** (first-order duration overstates the loss for a large rate rise, stated in the exposure metric). **Added in Stage 13 as an opt-in position field** (`convexity`, omitted when unset), filled only on the synthetic Wholesale Book v2 where the bond terms are ours to define; see `docs/FINANCE_THEORY.md` §5 |
| volatility-regime scaling of shocks | shock size should follow the regime | the severity score is uncalibrated | would add unsupported precision | no evidence it improves anything | **rejected** |
| sector-specific transmission for macro / geopolitical events | oil shocks hit energy-importers, etc. | no transmission data | invented betas | no | **not added**: the existing scenarios bind market / sector / issuer only |
| PD / LGD / spread history | credit shocks should be ranked against history | none held | n/a | no | stays labelled "not checkable" |

Notable data finding: the fitted betas are well estimated (standard errors about 0.1) and widely dispersed (XOM -0.53, CVX -0.47, KO -0.22, JNJ -0.14, INTC 2.7 over the last year), unlike the synthetic book's sector-tilted draws around 1.0-1.3. That is why personal portfolios are visibly less sensitive to a market-wide shock than the default.

## Honesty

- The severity score stays `HEURISTIC_UNCALIBRATED`; a portfolio result is a **modeled scenario change under illustrative shocks**, never a forecast. The page says so beside each number.
- The scenario-vs-history reality check (`/scenarios/{id}/history-check`) is shown on the Stress page under the result, as context, not calibration.
- No LLM computes or phrases a portfolio number.

## Limits

A personal portfolio is in one currency and carries no FX or oil exposure of its own (the scenario lab and the committed Wholesale Book v2 can: a position carries a `currency` / `commodity_sensitivity`, and a position without one is never moved by an FX or oil shock); no shorts or leverage; no live prices (quantity mode needs a price you type); only the 34 issuers are nameable by events; user holdings are assumed correct (a ticker is not verified against any market); region exposure is shown but no scenario shocks a region; betas are a snapshot to 2026-10-01 and are rebuilt with `make portfolio-betas`; reference durations are indicative round numbers, flagged `REFERENCE` and editable per holding.

**Scenario sector shocks are always adverse.** The existing scenarios shock a named sector downward regardless of whether the event helps or hurts it, so an oil-supply event is modeled as a loss for an energy-heavy portfolio, though energy producers might gain. A question like "which of my holdings are oil-import-sensitive?" cannot be answered honestly without transmission data the repository does not hold; it is deliberately not faked.

## Commands

```bash
make portfolio-betas      # rebuild data/replay/market/betas.json (needs the git-ignored prices), then `make freeze-write`
make run                  # UI at http://127.0.0.1:8000 -> Portfolios -> Create a portfolio
make test lint types      # backend + web tests, ruff + tsc, regenerate the API types
make freeze-check smoke   # frozen state unchanged; real-server check incl. create -> stress -> chain -> delete
```

## Wholesale Book v2 (Stage 13, committed preset)

A second **read-only** synthetic book, `pf_wholesale_v2`: every position of the profile's default book with the Stage 13 mechanics filled in (bond convexity, loan tenor and spread pass-through, derivative gamma and counterparty PD/LGD, euro and sterling denominations, oil elasticities by sector, internal PD-bucket ratings) plus a government sleeve (`spread_sensitivity` 0) and a cash sleeve (USD and EUR). It is a superset of the default book, so comparing the two shows what the extra mechanics change.

- It is **not** a personal portfolio and is never listed with them: `GET /api/portfolios/presets` lists it; the id is accepted wherever `portfolio_id` is (stress, relevance, lab, propagation, brief, compare, exposure), kind `PRESET`. The default book remains the default, untouched.
- Files: `data/portfolio/book_v2_replay.json` (replay profile, `make book-v2`) and `data/fixtures/portfolio_v2.json` (demo profile, `scripts/generate_fixtures.py`); both come from `src/eventshock/portfolio/book_v2.py` with fixed seeds.
- Everything added is synthetic and illustrative. It is **API-only for now**: the portfolio switcher in the UI does not offer it.
- Companion scenarios: `configs/scenarios_multifactor.yaml` (stagflation, oil supply shock, funding squeeze, global downturn). They are served by id and are never the default scenario of an event class. A position without a currency or oil elasticity is not moved by FX or oil shocks, so these scenarios mainly differ from the base ones on Book v2.
