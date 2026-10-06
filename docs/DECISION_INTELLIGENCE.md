# Decision intelligence (Stage 12)

The decision loop on top of the frozen risk engine: **what changed → does it matter to my book → what if it gets worse → what would it take to lose X% → why am I seeing this → what do I tell someone.**
Everything here is a *derived side-car*. Nothing is stored on a `RiskSignal`, so `GOLDEN_SERVED_DIGEST` (`70478b2d…`) and `GOLDEN_RUN_ID` (`run_10e9dc8e3b9a`) are unchanged; no trained model, severity anchor or replay-pack hash moved. Core packages
(`assessment pipeline stress modeling domain retrieval portfolio intelligence propagation adjust llm ingestion services`) may not import `decision monitor watchlist lab explain feedback markets brief`
(`tests/unit/test_decision_architecture.py`; the only exemption is `ingestion/kalshi_capture.py`, the network code of the Kalshi snapshot).

Every threshold, cap and bound lives in `configs/decision.yaml` and is a **judgement prior**: none is fitted, none is validated against outcomes. Say so wherever a figure from here is quoted.

## 1. Live risk monitor and event memory (`monitor/`)
* `EventState` is what EventShock held about one event at a moment (severity, lifecycle, evidence tier, conflict, materiality, exposure share, scenario P&L, fingerprint). Nothing is computed there; each field is read from an existing layer.
* `diff_states(previous, current)` is a pure function that returns `RiskChange`s by named rule (new event, escalated / de-escalated, evidence strengthened / weakened, conflict appeared / resolved, exposure changed, stress changed, lifecycle changed). A change id is a hash of the event, type and the two fingerprints, so the same transition is never logged twice.
* **REPLAY is a pure function over the frozen signals** at a fixed 12 h cycle grid (cycle 0 = baseline); it reads no wall clock and is identical on every call and after a side-car rebuild. **LIVE** diffs the live overlay through an observer on `LiveService` and persists to git-ignored `data/live/decision/`. Live is off by default.
* **Event memory** classifies every report as NEW_EVENT / CONTINUATION / UPDATE / ESCALATION / DE_ESCALATION / RESOLUTION by an explicit rule. Reports with replay-assigned clocks are never ordered; those parts answer UNAVAILABLE with the reason.
* In the frozen replay a cluster's severity and scenario are fixed, so exposure and stress changes are rare there; they are proven by fixtures and appear live under adjustments or a portfolio switch.

## 2. Watchlists (`watchlist/`)
COMPANY, SECTOR, INDUSTRY, GEOGRAPHY, EVENT_TYPE, RISK_THEME and PORTFOLIO_EXPOSURE items against the event's **resolved scope**. A company item matches only a company-scoped event; an UNRESOLVED event never matches a company or sector item. Values are validated against a closed vocabulary; an unknown company is refused, never stored. Atomic file store; a damaged file is skipped with a warning.

## 3. Scenario lab (`lab/`)
BASE (no shocks: proves the baseline), ASSESSED (the event's propagation-generated scenario) and CUSTOM. Every user value is a **SCENARIO ASSUMPTION** and the result is **SCENARIO SIMULATION — NOT A PREDICTION**. Kinds: equity market, rates, credit spread, commodity (oil), FX, sector, issuer, and risk factors (INFLATION / GEOPOLITICAL are spread over sectors through the Stage 11 transmission weights).
Bounds are configured. A shock nothing in the book carries reports `NOT_APPLICABLE`, never a zero P&L. Ids are `scn_lab_` + a hash of the portfolio, type and sorted shocks (order-insensitive). Two to three scenarios compare side by side with an assumption diff.
**Engine extension (additive, omitted at default so hashes do not move):** `RiskFactor.FX_PCT` / `COMMODITY_PCT`, `ShockSpec.currency` / `entity_id`, `PortfolioAsset.currency` / `commodity_sensitivity`. Exposure is *data on the position*, never a prior in the engine: FX applies to positions whose currency matches, oil to equities and derivatives that carry an elasticity. The opt-in `exposure_priors` flag applies labelled sector priors to a *copy* of the book. Known limits: the default synthetic book has no currency or oil data, so those shocks are `NOT_APPLICABLE` unless a prior or a personal portfolio supplies it.

## 4. Reverse stress (`lab/reverse.py`)
"What would it take to lose X%?" A bounded, deterministic **grid + bisection** (`BOUNDED_GRID_MINIMAX`): probe each basket axis, keep at most three by *marginal* loss (a sector shock replaces the market shock inside its sector, so stand-alone loss misleads), grid seven levels, pick the combination whose largest share of its own bound is smallest, then bisect to the target within 0.02 pp. Statuses ACHIEVABLE / NOT_ACHIEVABLE (the largest loss the bounds allow, with the binding bounds) / NO_EXPOSURE. The reported combination is re-run in full by the lab, so the loss shown is a complete engine run. It is a hypothetical, not the most likely combination.

## 5. "Why?" explanations (`explain/`)
Subjects PRIORITY, VISIBILITY, CHANGE, STRESS, LAB, REVERSE and MARKET. A reason has a closed code, a value, the **kind** of statement it is (model output / product rule / scenario assumption / historical observation / external market observation), the output it was read from and provenance. `finish()` raises if a material output has no reason.

## 6. Executive digest (`monitor/digest.py`, route `/today`)
Eight sections (new risks, escalations, exposure changes, stress changes, evidence changes, conflicts, concentration changes, watchlist activity). **Nothing is scored.** The order is one lexicographic key (materiality tier → severity → size of the change → recency → id) that every card shows as five named parts. Each section is capped (5) with its true total beside it. A card drills event → evidence → scope → exposure → propagation → stress → attribution into the existing pages.

## 7. Analyst feedback (`feedback/`)
Append-only JSONL, validated type/value pairs (RELEVANCE: relevant / partially / irrelevant; SCOPE and EVENT: correct / incorrect), analyst id from the body, then `X-Analyst-Id`, else `anonymous`. Statistics are labelled **ANALYST FEEDBACK — not ground truth, not used to train or change any model**. A test compares eight served endpoints before and after submissions.

## 8. Executive risk brief (`brief/`)
Sixteen sections in a fixed order, **template-written** from structured outputs (no language model). Each statement carries its kind and source ids that resolve to a `sources` registry with the endpoint where the same output can be read; a statement without a source is a build error. Absent inputs print fixed sentences. Deterministic JSON and Markdown. Deferred on purpose: an LLM narrator (30-call cap, no recorded prompt, 16-section grounding burden).

## API
`/api/monitor/{status,cycles,changes,refresh,digest}`, `/api/watchlists…`, `/api/scenarios`, `/scenarios/validate|compare|explanation`, `/api/lab/options`, `/api/reverse-stress[/explanation]`, `/api/feedback[/statistics]`,
`/api/events/{id}/{timeline,explanation,external-markets,market-timeline,analogues,brief}` (`{id}` is an event id or any signal id in it). Capabilities: `monitor watchlists scenario_lab explanations feedback external_markets executive_brief`.

## Determinism and invariants (all tested)
Replay results are identical across calls and after `rebuild_sidecars`; derived views never store stress runs (`store=False`; a real regression was found here, see the journal); `GOLDEN_SERVED_DIGEST` and the stress goldens hold after every sweep; ids are content hashes; every list has a documented sort key with the id as the last tiebreak; feedback and the brief mutate nothing.

## Known limitations
Thresholds, bounds, the basket, the digest order, and the oil/FX sector priors are unvalidated priors. FX and oil are engine factors but the Stage 11 *propagation* does not model them (unchanged on purpose, to keep its goldens). The digest's concentration section is dominated by market-wide factors on the replay. Live monitoring needs the live feed on. Reverse stress returns one combination among many.
