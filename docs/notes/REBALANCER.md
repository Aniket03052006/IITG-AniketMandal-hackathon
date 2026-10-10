# Tactical index rebalancer (Module A, Stage 16)

The case study offers two downstream modules and asks for at least one. EventShock was built around **Module B** (the stress tester). This stage adds **Module A**: a mock index of 15 US large caps whose weights follow the **Sentiment Score** of the NLP risk engine (up → weight up, down → weight down), with a dashboard of the weights over time at `/rebalancer`.

It is a **derived side-car** in the Stage 10–12 pattern: nothing is stored on a `RiskSignal`, no model, severity score, scenario, replay file or pinned digest changed, and no core package may import it (`tests/unit/test_rebalancer_architecture.py`). Module B is untouched.

**What it claims, and what it does not.** The rebalancer is a *transparent, bounded, turnover-limited map from sentiment to weight*. It does not claim the tilt earns a return. EventShock's own Stage 8 finding (the realised move around an ordinary company headline is barely distinguishable from an ordinary day) is the reason the claim stops there, and the back-test is built to make that visible instead of hiding it.

## The rule

Universe: AAPL MSFT NVDA GOOGL AMZN META · JPM BAC GS · XOM CVX · JNJ UNH PFE · WMT (15 of the 34 issuers EventShock can name; six sectors; each has at least 22 trusted company reports in the replay). The config accepts 10–20. The benchmark is **equal weight** (the repo holds no market-cap data, and says so wherever the benchmark is shown).

At each cycle time *T* on a fixed grid (every 6 h, from the first trusted report to the replay clock):

1. **Evidence.** Reports published at or before *T*, about a company in the index, with a *trusted clock* (a time assigned by the replay is never placed on a timeline; those 60 social posts are counted and left off), a sentiment that is a model output (a `PARTIAL` signal is kept: it only means the event/impact stage declined to score a non-event, not that sentiment failed), and a company link at or above 0.5 confidence.
2. **Score** *S* ∈ [−1, 1] per company:
   `w = 0.5^(age / half-life)` (36 h; ignored beyond 5 half-lives) · **one source, one vote** (a source's weights sum is capped at 1) · `S = Σ_src c_src · x̄_src / (Σ c_src + n₀)` with `n₀ = 1.5` pseudo-reports at sentiment 0, so thin evidence gives a weak score. Only `sentiment.score` is read: severity, impact, event type, tone-independent confidence and source reliability are **not** inputs (the one exception is the experimental `sentiment_impact` strategy below, never the baseline). The contribution of every report adds up to the score exactly, which is how the page explains it.
3. **Tilt.** `p_i = b_i · exp(k · S_i) / Σ_j b_j · exp(k · S_j)` with `k = 2`. Invariant to a common shift of every score; `k = 0` holds the benchmark.
4. **Bounds.** The Euclidean projection of `p` onto `{ lo ≤ w_i ≤ hi, Σ w = 1 }` with `lo/hi = b·(1 ∓ 0.5)` inside a 1 % floor and a 12 % cap (so 3.33 %–10 % for 15 stocks): `w_i = clip(p_i − μ)`, μ by bisection. Exact, deterministic, order-preserving.
5. **Turnover.** `w_new = w_prev + α (w* − w_prev)`, `α = min(1, τ_max / TO)`, `TO = ½ Σ |w* − w_prev|` (one-way), `τ_max = 4 %` per cycle; a rebalance below 0.2 % is not traded. A convex combination of two feasible vectors is feasible, so nothing is re-projected.
6. **Self-check.** Every published cycle satisfies Σ w = 1, the bounds and the turnover cap, or the request raises. Each stock carries a named reason (`TILT_UP`, `TILT_DOWN`, `AT_UPPER_BOUND`, `AT_LOWER_BOUND`, `LIMITED_BY_TURNOVER`, `HELD_BELOW_MIN_TRADE`, `NO_EVIDENCE`, `NO_CLEAR_SENTIMENT`).

Every number lives in `configs/rebalancer.yaml`, headed **JUDGEMENT PRIOR**: none is fitted, calibrated or validated. The strict loader rejects a misspelt key, an index outside 10–20 stocks, bounds that exclude the benchmark, and a tilt or turnover above its stated limit.

## Trade decisions, risk-aware strategies, the strategy lab and the ledger (Stage 16, second pass)

The first pass answered "how do the weights move". This pass answers what a portfolio manager asks next: **what do I trade, on whose headlines, what stopped it from being bigger, does it beat the alternatives after costs, and who signed off?** Nothing in the baseline rule, `configs/rebalancer.yaml`'s original keys, the served weights, `data/rebalancer/backtest.json` or any pinned digest changed: the baseline's weight path hashes to the same `timeline_sha256` as before, and `tests/e2e/test_rebalancer_replay.py` pins it.

**Trade decisions** (`GET /api/rebalancer/cycles/{i}/decisions`, the *Trade decisions* tab). A cycle as a proposed rebalance. Per stock: weight before, the target the rule asked for, weight after the turnover limit, the trade and its side, an illustrative cost, a mock-dollar size and its share of the stock's average daily volume, the rules that held it back (with how many points each took), the evidence behind it (headline, outlet, publication time, tone, decayed weight, signed contribution), and three flags that describe the evidence and feed nothing: **thin** (less than one source's worth of evidence), **stale** (newest report older than a half-life) and **conflicting** (both a positive and a negative side hold at least a quarter of the absolute contribution). The sentence on each card is a template whose every clause is backed by a field of the same record (no model writes it). The proposal carries a `proposal_sha256` over the strategy, parameters, cycle and the three weight vectors.

**Which constraint bound.** For every stock the service keeps a *constraint ladder*: the tilt, then its projection onto the constraints added one at a time (bounds, sector cap, volatility limit, liquidity floor), then the turnover step. Each stage is a joint projection, so the effect of a rule is the difference between two consecutive stages, and the effects telescope exactly to the final target (tested). A rule is *named* only if the stock was actually held by it, not merely redistributed to; the attribution is order-defined and says so.

**Strategies** (`configs/rebalancer.yaml: strategies`, a closed registry; a request names one with `?strategy=`, default `sentiment`):

| id | what changes | status |
|---|---|---|
| `sentiment` | nothing: the shipped rule | baseline, never altered |
| `sentiment_risk` | + a **sector cap** (a sector may hold its benchmark share × 1.25; sectors come from the entity master, so AMZN is Technology), + a **volatility-aware upper bound** (`b(1 + 0.5·min(1, σ_med/σ_i))`: a volatile stock may be overweight less; never below the benchmark), + a **liquidity floor** (average daily dollar volume below $0.5 bn: no overweight) | experimental |
| `sentiment_impact` | each report's tone × `0.5 + 0.5·(impact − 1)/9` (a report with no impact score counts as the lowest); it can only *shrink* a tone, so the score stays in [−1, 1] and still decomposes exactly | experimental |

The sector cap is an exact Euclidean projection (`weights.project_grouped`: KKT form `w_i = clip(p_i − μ − λ_g)`, nested bisection; tested for optimality against many feasible points and for equality with the plain projection when no cap binds). The risk bounds are **static** (volatility and dollar volume measured at one early date, `data/rebalancer/risk_inputs.json`, `make rebalancer-risk-inputs`), so they are point-in-time safe for every cycle and a convex step between two feasible vectors stays feasible. Impact is a **magnitude with no direction**, and the trained impact model has no measured event-specific skill (`docs/notes/IMPACT_MODEL.md`): this variant can only change how much a tone counts, which is why it is an experiment and is never promoted on the strength of one window. The unit tests prove that none of it leaks into the baseline (the same service serves both and the baseline's weights are unchanged after the others run).

**Strategy lab** (`GET /api/rebalancer/lab`, `make rebalancer-lab`, `data/rebalancer/lab.json`). Every strategy plus two references (equal weight; buy-and-hold, equal at the start and never traded) on the same sessions, with the same 5 bp cost, point-in-time weights and the same fixed-seed shuffled-score placebo. Per strategy: return, difference from equal weight, annualised volatility (indicative only at ten sessions), maximum drawdown, hit rate, turnover, cost, rank IC, the full window, both halves and every rolling five-session window, and a **verdict computed from the placebo** (within / above / below the shuffled range). Beside it: a sensitivity grid of the baseline over half-life × turnover cap and tilt × position limit (21 settings, 100 placebo runs each), and the result at 0, 5, 10 and 25 bp. The grid reports how many cells fall outside their own placebo range *and how many would by chance alone*, because the best of 21 cells is the luckiest cell, not a recommendation: the shipped parameters were fixed before any result existed and the grid does not change them. The committed file stores the weight-path digest of each strategy; `lab` is reported STALE if the served weights differ. The baseline entry is tested to equal `backtest.json` exactly.

**Approval workflow and ledger** (`POST /api/rebalancer/proposals/decision`, `GET /api/rebalancer/ledger`, the *Ledger* tab). An analyst can approve all of a proposal, approve a subset of its trades, or reject it. **Simulated: nothing is sent anywhere and the served index never changes** (the e2e test writes ledger entries and re-checks the signal digest). The request carries the `proposal_sha256` it was looking at; if the strategy, parameters, cycle or evidence have changed the server answers 409 instead of recording a decision on something the analyst did not see. A partial approval keeps the index fully invested by scaling the larger side so what is bought equals what is sold; every approved allocation is checked for sum, bounds and sector caps (422 names the broken rule), and accepting only buys or only sells is refused. The ledger is an append-only JSONL file (`data/live/rebalancer/ledger.jsonl`, git-ignored, `EVENTSHOCK_REBALANCER_LEDGER_PATH`), each line carrying the hash of the line before it: an edited or removed line breaks the chain, `chain_ok` goes false, and the ledger then refuses new entries. An entry shows as *stale* when its proposal is no longer the one the service would make.

**Result of the lab (10 sessions; journalled in `docs/notes/PROJECT_JOURNEY.md`).** Every tilt strategy is inside its own placebo range (baseline 82nd percentile, risk limits 79th, sentiment × impact 84th). All 21 grid cells ended ahead of equal weight (+0.01 % to +0.28 %), but only one fell outside its placebo range against about two expected by chance, and the shuffled scores themselves land from −0.33 % to +0.32 %: being ahead of a daily-reset equal weight is not evidence. The risk limits cost 0.02 points of return in this window and bought nothing measurable; the impact variant trades less (0.035 vs 0.060 of the index a day) and returned less. None of this is a claim of skill.

## Why these choices (research notes)

| Choice | Basis | What it costs |
|---|---|---|
| Benchmark + bounded tilt, not "last score → weight" | Sentiment-weighted index designs (for example a DAX40 sentiment-driven index paper) cap single names and penalise weight changes; a raw map would swing on one headline | A modest, slow-moving index |
| Exponential tilt with a temperature | A softmax gives a smooth, monotone map, but it is scale-sensitive and over-concentrates at low temperature (per the `weight_by_softmax` documentation); hence the bounds | `k` is a prior; a different scale of scores would need a different `k` |
| Hard turnover cap + minimum trade (not a penalty term) | Turnover conventions differ (½·L1 vs L1, per MathWorks vs PortfolioAnalytics docs); a cap is explicit, testable and keeps the path feasible | The index can lag its target (the page says when) |
| Decay, shrinkage, one-source-one-vote | The data is sparse (about 2 company reports per stock per day) and noisy; one outlet can publish many near-copies | Fast news is slightly damped |
| Half-life 36 h | **No source gave a measured half-life for news sentiment**; vendor material is promotional and a 2026 study found the edge thin after costs. So it is a disclosed prior, and a what-if slider | Unvalidated |
| Equal-weight benchmark | No committed market caps | Not what an S&P index weights |
| Sentiment only | Same rule as the severity scorecard: tone, confidence and reliability are shown, not mixed | An event of high severity but neutral tone does not move the index |

## API

`GET /api/rebalancer/overview` · `/timeline` · `/cycles/{index}` · `/cycles/{index}/decisions` · `/backtest` · `/lab` · `/ledger` and `POST /proposals/decision` (replay profile; `capabilities.rebalancer`). `strategy` selects a strategy on the first four (422 for an unknown or unavailable one). `tilt`, `half_life_hours` and `max_turnover` are a **what-if for one request** (`params.is_default` is false; the server's configuration never changes; each is range-checked, 422 otherwise). `include_live=true` also reads the live feed's reports on the same grid (never pasted text); it is off by default so the index of record does not move because a live report arrived. Replay is a pure function of the frozen signals: two calls give the same answer, and **no report published after a cycle can influence it** (`tests/e2e/test_rebalancer_replay.py` deletes every later real report and compares the earlier cycles byte for byte).

## The back-test (an illustration)

`make rebalancer-backtest` reads the git-ignored price files (Yahoo data is not redistributed, `docs/notes/DATA_LICENSES.md`) and commits only a derived `data/rebalancer/backtest.json` (daily returns, cumulative curves, turnover, the sha256 of every price file used and of the weight path it was built from). The weights in force during session *d* are those of the last cycle at or before the **close of session d−1** (16:00 New York). Both the index and the benchmark pay 5 bp one-way on the turnover from their drifted weights. A file built from different weights than those now served is reported **STALE**, not shown as current.

Result on the frozen replay (10 sessions, 18 Sep to 1 Oct 2026): index −0.99 %, equal-weight benchmark −1.18 %, difference +0.19 %, mean rank IC +0.10. The control that matters is the **placebo**: the same scores in the same cycles given to the wrong companies (200 fixed-seed shuffles) produce a difference between −0.33 % and +0.32 % (5th–95th percentile); the real difference sits at the 82nd percentile. **That is inside what chance gives, so this window shows no evidence the sentiment tilt helps**, and the page says exactly that.

## Verified, and not

Verified: the arithmetic (property tests over seeded random inputs: sums, bounds, monotonicity, projection optimality, the turnover cap), the evidence rules (decay, source cap, point-in-time, order independence, exact decomposition), determinism, future-invariance on the real signals, every cycle of the real replay reconciles for a grid of parameters, the API contract and 422s, the architecture guard, the UI states (loading, empty, error, what-if, stale / missing back-test) and both themes.

Not verified, and stated as such: that sentiment predicts returns (it does not show it here); the parameters; the sentiment model's calibration against this task; any live-feed behaviour beyond the unit test that live reports count only when asked.

## Known limits

- 14 days, about ten sessions: a mechanics demonstration, not a performance claim.
- Equal-weight benchmark; target weights, no intra-cycle drift; one-way cost only.
- A multi-company headline resolves to one company and can add its sentiment to the wrong name (seen in the data: a market-coverage press release moved NVDA). The company link floor (0.5) and the one-source cap damp it; they do not remove it.
- Social posts carry no real clock and are excluded from the timeline.
- If the replay window were longer than `max_cycles` (120 cycles = 30 days), the earliest cycles fold into the benchmark start.

## Files

`src/eventshock/rebalancer/{config,models,scoring,weights,service,backtest,risk,decisions,lab,ledger}.py` · `configs/rebalancer.yaml` · `src/eventshock/api/routers/rebalancer.py` · `scripts/build_rebalancer_{backtest,risk_inputs,lab}.py` · `data/rebalancer/{backtest,risk_inputs,lab}.json` · `web/src/pages/RebalancerPage.tsx`, `web/src/components/rebalancer/*`, `web/src/lib/rebalancer.ts`. Tests: `tests/unit/test_rebalancer_*.py`, `tests/integration/test_rebalancer_api.py`, `tests/e2e/test_rebalancer_replay.py`, `web/src/{lib,components/rebalancer,pages}/*rebalancer*.test.ts(x)`.
