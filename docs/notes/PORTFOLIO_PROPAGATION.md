# Event to portfolio propagation (Stage 11)

Stage 10 says what an event is about. Stage 9 says what the portfolio holds. Stage 11 closes the loop between them:

EVENT → SCOPE → PORTFOLIO MATERIALITY → EXPOSURE PROPAGATION → SCENARIO → STRESS → ATTRIBUTION

A company match is no longer required. A Fed headline, an oil disruption, a regulation about banks and a geopolitical story each reach the book through
a **sector, an industry, a region, an asset class or a risk factor**, and every step says whether it is **observed**, an **assumption of the
scenario**, or an **assumption you set**.

Everything is a **derived side-car**, exactly like Stage 10: nothing is stored on a `RiskSignal`, so `GOLDEN_RUN_ID`, the replay digest and the
fixtures are unchanged (`tests/e2e/test_propagation_replay.py` pins that `GOLDEN_SERVED_DIGEST` holds after propagation, adjustment and reset).
`tests/unit/test_propagation_architecture.py` fails if the pipeline, models, stress engine, assessment, intelligence or portfolio code imports it.

Four things are kept apart everywhere (as in Stages 5 to 10): event **severity** (a transparent, uncalibrated triage score), **portfolio relevance**
(your holdings), **scenario assumptions** (judgement priors), and the **modeled change** the unchanged stress engine computes. None is a forecast.

## 1. Mapping (`propagation/mapping.py`, `PropagationGraph`)

Input: the Stage 10 `EventScope` (company / industry / sector / geography / macro / theme path and its evidence), the assessment's event class,
and the portfolio's own holdings. Output: nodes (event, subject, sector / industry / geography, risk factor, asset class, portfolio, position) and
edges. **Every edge has a relationship, a rule id, a basis (a quoted phrase, a fact or an assumption in words) and a status.**

| Status | What it is | Examples |
| --- | --- | --- |
| `OBSERVED` | a fact or a formula the engine applies to the holding's own attributes | the book holds the issuer; a ticker's industry; “rate hike” in the text; a bond's price falls with yields (its duration) |
| `SCENARIO_ASSUMPTION` | a judgement prior in `configs/propagation.yaml` | rates reach long-duration technology equities (weight 0.5); oil reaches industrials (0.5) |
| `USER_ASSUMPTION` | a value you adjusted or added | any edge, weight or size you changed in *Adjust assumptions* |

How a holding is reached (`MappingBasis`): `DIRECT_FACT` (the named issuer is held), `EVIDENCED_SCOPE` (a sector, industry or region the text or the entity
master names, or a structural sensitivity to a factor the text is about), `ASSUMPTION_ONLY` (only configured edges reach it). A holding reached by several routes
is **counted once**; cash and unsupported instruments are never reached. A government bond (spread sensitivity 0) is not reached by a credit-spread factor,
because the engine would not move it.

Risk factors (`RATES`, `EQUITY_MARKET`, `CREDIT_SPREAD`, `CREDIT_DEFAULT`, `OIL_ENERGY`, `INFLATION`, `FX`, `GEOPOLITICAL`, `REGULATION`) become active when
the text uses their vocabulary (the scope themes of `configs/scope.yaml`, or the terms in `propagation.yaml`) **or**, as an explicit assumption, because of the
event class (`category_risk_factors`). The stress engine has five factors; this layer adds **no new engine factor**: `OIL_ENERGY`, `INFLATION` and
`GEOPOLITICAL` act only through sector shocks written in the transmission table (labelled PROXY), and `FX` is recognised and reported but **never simulated**.

**Abstention.** If the text names nothing the event could attach to, and the event class carries no market-wide assumption, the graph says
`ABSTAINED` and why. It does not guess what the event is about. If a mapping exists but the book holds nothing it reaches, that is a different answer
(`AVAILABLE`, nothing reached) and the relevance is `NONE`.

This is **not causal inference**. It is a labelled map of how an event could reach holdings under stated assumptions.

## 2. Materiality (`propagation/materiality.py`)

Relevance of an event to a portfolio is **LOW / MEDIUM / HIGH / CRITICAL** (plus `NONE` when nothing is reached and `UNDETERMINED` when the mapping
abstains), by a lookup that anyone can check, not a weighted score:

1. The share of the book the event reaches (counted once) picks a **row**: LOW / MEDIUM / HIGH / VERY_HIGH (`exposure_bands`).
2. The event's severity picks a **column**: LOW / MEDIUM / HIGH / CRITICAL (`severity_bands`).
3. The `grid` names the level. The grid must never decrease along either axis; the config is refused otherwise.
3b. **Assumed-reach limit**: reach that rests only on assumed edges can lift the exposure row by at most one step above what the *evidenced* reach alone supports (a small evidenced slice plus a large assumed reach is not CRITICAL).
4. Then, in order: a **bump** (one position is at least half of what is reached: one step up), a **cap** when only assumed edges reach the book (MEDIUM),
   and a **cap** when severity was not assessed (read from the MEDIUM column, capped at MEDIUM).

The response carries every input (severity, share reached, direct and indirect exposure, evidenced and only-assumed shares, concentration of the reached
part, mapping basis), the grid cell, and which rules fired. “Why is this event relevant to this portfolio?” is answered by those numbers in order.

## 3. Scenario generation (`propagation/scenario_gen.py`)

Deterministic and configurable. The template of an event class is **its catalog scenario** (`configs/scenarios.yaml`, magnitudes untouched), plus sector
shocks propagated from the active risk factors through the transmission table. Earnings, geopolitical, credit, M&A, regulatory, macro, product / operations
and market-valuation events each have one (`templates` in `propagation.yaml`).

A scenario is generated only when **all** of these hold (each is a gate the response lists, met or not):

| Gate | Default | Can a what-if bypass it? |
| --- | --- | --- |
| the text is read as a market event | | no |
| a template exists and is switched on | | no |
| a defensible mapping reaches at least one holding | | no |
| the event is not favourable (`downside_only`) | | yes |
| severity ≥ `min_severity` | 7 | yes |
| relevance ≥ `min_materiality` | MEDIUM | yes |
| at least one shock binds to this event and these holdings | | no |

Otherwise the answer is **SCENARIO UNAVAILABLE** with the reason; when only soft gates failed the scenario is shown as a preview that can be run as an explicit what-if.
Every generated scenario carries the label **SCENARIO SIMULATION — NOT A PREDICTION**, a version that is a hash of its shocks (an adjusted value is a different scenario and a
different run id), and a `ShockOrigin` for every shock: catalog base, propagated (with the risk factor and edge), or your override.

A propagated sector shock **replaces** the scenario's market-wide shock for that sector (the engine applies the most specific shock per factor), so it is written as the
market-wide shock plus an increment times the edge weight. Positive weights hurt and also widen that sector's credit spread; negative weights benefit. The event's own sector keeps
the catalog's sector shock. The one engine change is additive: `ShockSpec.sector` / `AppliedShock.sector` (a SECTOR shock may name its sector), with a regression test; the formulas
in `revalue_asset` are untouched and catalog scenarios name no sector, so their run ids are unchanged.

## 4. Attribution (`propagation/attribution.py`)

For any completed run, the total modeled change is regrouped by kind of shock (issuer-specific / sector / market-wide / other), issuer, sector, industry, the engine's market factors, risk
factor (through each shock's origin), asset class and position. Every table is built from the engine's own per-position, per-factor changes plus any part a position's per-factor figures do not
explain (`Other`), **adds up to the total within a cent, and the builder raises if one does not**. It is a sensitivity decomposition under the scenario's assumptions, not causal attribution.
Industry is a derived view (the engine shocks sectors).

## 5. Concentration and blind spots (`propagation/concentration.py`)

Issuer, sector, industry, geography, asset class and risk factor. A slice is flagged only when it is at least `min_share` of the book **and** `equal_weight_multiple` times an equal split,
in a dimension with at least `min_items` items; a dimension is flagged when its Herfindahl index is at least both `hhi_flag` and `hhi_equal_weight_multiple` / n (a handful of items can never
fall below 0.25). Cash, Other and Unclassified are never flagged; risk-factor reach (an assumption, overlapping) is shown but never flagged.

Overlapping events: recent signals at or above `min_materiality` (one story counted once, via the Stage 10 event grouping) that are **about the same risk factor in their text** (an event class that merely
implies a factor does not count) **and** reach the same holdings (at least `min_overlap_share` of the book) form a cluster: EVENT A, B, C → same risk factor → same holdings → concentrated risk.

## 6. Manual adjustment of the side-cars (`adjust/`)

Stage 11 makes the side-cars adjustable by hand (`Adjust assumptions` in the sidebar, `?open=adjust` anywhere).

- **What can be adjusted** (`adjust/registry.py`, an explicit whitelist with bounds): scenario gates and shock sizes; relevance bands, the materiality grid and caps, concentration and overlap thresholds; the
  transmission table (weight, on / off, writes-a-shock, edges you add); the Stage 10 intelligence priors (grouping, evidence, novelty, velocity, contradiction window, lifecycle numbers, ticker-industry map, theme-factor map,
  authoritative domains). **Not adjustable**: claim and lifecycle cue lexicons, severity anchors, the scenario catalog, models, any pinned digest.
- **Where it is stored**: `data/live/overrides/overrides.json` (git-ignored; `EVENTSHOCK_OVERRIDES_PATH`), a sparse map of dotted path to value, written atomically. A damaged file stops start-up with a clear message instead of being ignored.
  The shipped `configs/*.yaml` are never written, so the frozen defaults and the freeze manifest do not move.
- **How it is validated**: bounds in the registry, then the override is patched into the raw YAML **before** the existing strict model validates it, so every cross-field rule still applies (bands in order, a grid that never decreases, a known industry, no unknown key).
  `POST /api/adjustments/validate` is a dry run that names the path at fault; `PUT` saves nothing when any value is refused.
- **How it takes effect**: the three side-cars (relevance bands, intelligence, propagation) are rebuilt from defaults plus overrides and swapped in; if the rebuild fails the file is rolled back. Overrides are **server-global** (this is a single-user local app, like the saved portfolios).
- **Honesty**: every side-car answer carries `adjustments` (the count and the paths) when any value is adjusted, omitted otherwise so default payloads are unchanged; an adjusted edge or size is `USER_ASSUMPTION`; a reset puts every byte of every answer back
  (`tests/integration/test_propagation_api.py`, `tests/e2e/test_propagation_replay.py`). Adjusted values are your assumptions and are not validated.

## 7. API

`GET /api/signals/{id}/propagation`, `GET /api/signals/{id}/materiality`, `POST /api/signals/{id}/portfolio-stress`, `GET /api/stress-runs/{id}/attribution`, `GET /api/concentration`, `GET /api/concentration/overlaps` (optionally `signal_id=`),
`GET|PUT|DELETE /api/adjustments`, `POST /api/adjustments/validate`, `POST /api/adjustments/reset`. All take the optional `portfolio_id` (the synthetic book when omitted). `capabilities.propagation` / `capabilities.adjustments` in `/api/meta`.

## 8. Limits

- The transmission table and every shock size are judgement priors; nothing here is validated against outcomes. The UI says so next to each.
- Industry is known only for the 25 tickers of the entity master (`intelligence.yaml: ticker_industry`); other holdings are Unclassified and are reached by sector, asset class or region. Industry edges extend the reach but write no shock (the engine shocks sectors).
- Propagation itself writes no FX or oil shock: the engine has `FX_PCT` / `COMMODITY_PCT` factors (Stage 12, the scenario lab, and the Stage 13 multi-factor scenarios), but a position is moved by them only when it carries its own `currency` / `commodity_sensitivity`; the generated scenario of this module acts on oil only through sector proxies, and the default book carries no such exposure.
- Generated scenarios are downside simulations; a favourable event is refused unless run as a what-if.
- Overlaps look only at signals in the store (the replay pack, plus anything pasted or live), and the window is anchored at the replay's own as-of, so it describes the loaded events, not the world.
- Adjustments are global to the server instance, not per browser.

## 9. Tests and commands

`tests/unit/test_propagation_{mapping,materiality,scenario,attribution,concentration,architecture}.py`, `test_adjust.py`, `test_stress_sector_shock.py`; `tests/integration/test_propagation_api.py`; `tests/e2e/test_propagation_replay.py`;
`web/src/components/propagation/propagation.test.tsx`, `web/src/components/adjust/adjust.test.tsx`; `make smoke` (generates a scenario for a real replay event, checks the attribution adds up, adjusts and resets).
After a deliberate change to `configs/propagation.yaml`, run `make freeze-write` and journal it.

## 10. Stage 15 addendum: loss heatmap and contagion map (2026-10-08)

* **Loss heatmap.** `StressAttribution.matrix` is a sector × market-factor cross-tabulation of the engine's own per-position, per-factor changes (`portfolio/crosstab.py`, the same builder as the exposure heatmap in [PORTFOLIOS.md](PORTFOLIOS.md)). It appears inside the existing attribution panel (Event page's stress chapter, Stress Lab, a Lab result). Every cell table reconciles to the total or the builder raises (`tests/unit/test_propagation_attribution.py`, `tests/unit/test_crosstab.py`). A cell is a regrouping of modeled change under the scenario's assumptions, not causal attribution.
* **Contagion map.** `web/src/components/propagation/ContagionMap.tsx` draws the propagation graph this API already returns, with no backend change: event → risk factors → where it lands (asset classes, sectors, industries, each with its share of the book) → the eight largest holdings reached. The geometry is a pure function, `web/src/lib/contagion.ts::layoutContagion` (four fixed columns, no overlap, deterministic; `contagion.test.ts`, `ContagionMap.test.tsx`). Each line carries the edge's status (observed / scenario assumption / user assumption). It draws a mapping, not a causal model; an abstained graph draws nothing and keeps its explanation.
