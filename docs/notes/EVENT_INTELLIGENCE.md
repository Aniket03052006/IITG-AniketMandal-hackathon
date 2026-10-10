# Event intelligence (Stage 10)

EventShock used to answer "what does this company headline mean?". Stage 10 makes it answer the same question for **any** text: a company, an
industry or sector, a place, a macro theme, the whole market, or nothing that can be defended. It also says how well the event is evidenced,
whether it is new, how fast it is spreading, whether reports contradict each other, and where it is in its life.

Everything here is a **derived side-car**. Nothing is stored on a `RiskSignal`, so every pinned replay digest, fixture and golden stress run is
unchanged (`tests/e2e/test_replay_served.py`, `tests/e2e/test_intelligence_replay.py::test_every_signal_gets_intelligence_and_none_is_touched`).
Nothing here feeds severity, the trained models or the stress arithmetic (`tests/unit/test_intel_architecture.py` fails if any of those import it).

Four things are kept apart everywhere, as in earlier stages: what the **text says** (reports, claims, quotes), what a **model says** (event class,
sentiment, impact, each with its own confidence), what **rules over reports** say (scope, grouping, novelty, velocity, lifecycle), and what a
**scenario assumes** (risk-factor shocks, stress). Evidence strength and model confidence are separate tiles and separate fields by design.

## 1. Scope (`intelligence/scope.py`)

`scope_type` is one of COMPANY, INDUSTRY, SECTOR, GEOGRAPHY, MACRO, MARKET, THEME (a risk theme) or UNRESOLVED, with `scope_value`,
`scope_path` (most specific first, ending at the market), `scope_confidence` (a rule tier HIGH/MEDIUM/LOW/NONE, **not a probability**; it cites the
measured agreement in `docs/evidence/scope_eval.json` where one exists), `scope_evidence` (the words in the text, with offsets) and
`resolution_status` (RESOLVED / PARTIAL / AMBIGUOUS / UNRESOLVED, always with a reason).

Order of the rules, first match wins: a company the entity resolver found; "not a market event" gives UNRESOLVED; one industry; one sector with at
least two distinct terms; a macro / theme / market theme; a region; the event class alone (LOW, PARTIAL); one sector term (LOW, PARTIAL); else
UNRESOLVED (AMBIGUOUS if sectors tie). **A level with no evidence is omitted from the path, never filled in**: a company's industry comes only from
the ticker map in `configs/intelligence.yaml`, its sector and country from the entity master. This layer never resolves a company: it reads
`signal.entity`, so it cannot invent one. `pipeline/scope.py` and `configs/scope.yaml` are untouched.

## 2. One pipeline for live, replay and pasted text

`RawDocument` is the normalised observation every adapter produces. Live and pasted text already enter through `RiskEngine`; replay uses the batch
run. All three call the same `prepare_record`, `cluster_items`, `build_signal`, novelty and impact post-pass. **The parity test proves it**:
`tests/e2e/test_intelligence_replay.py::test_one_engine_serves_replay_live_and_pasted_text_alike` feeds whole clusters of replay records through the
incremental engine and through `run_documents` and asserts the signals are identical, field for field. Pasted text may carry a `headline` and a `url`;
the url only attributes the outlet (its domain counts for corroboration) and is **never fetched** (the server makes no outbound request for pasted
text; `tests/integration/test_intelligence_api.py` patches the socket to prove it).

## 3. Events, reports, independent sources (`intelligence/grouping.py`)

The pipeline's dedup folds copies and same-story reports of one issuer into a cluster (one signal). The grouping joins clusters into an **event**:
same trusted-clock window (48 h), the same resolved issuer (or, when neither names one, a shared vocabulary scope and much closer wording), the same
trained event class, IDF-weighted content cosine and shared key facts (numbers, names). An event is a star around its earliest report, so a chain of
weak links cannot grow a story; processing order does not matter; a report whose clock the replay assigned is never grouped. Every report stays visible
beneath the event. A report is an **independent source** when it is the first from a distinct outlet that does not carry another outlet's identical
text (syndication and exact copies collapse; a rewrite by another outlet counts, because it is that outlet reporting for itself).

On the 2,330 replay signals: 2,196 events (2,091 single-cluster, 84 of two, 15 of three, 4 of four, 2 of five); 290 events have untrusted clocks.

## 4. Evidence (`intelligence/evidence.py`)

Source count, unique domains, independent sources, `source_diversity` (independent / reports), syndicated copies, authoritative sources (a closed list;
0 with `authoritative_supported=false` means "not known", not "none"), first and latest observed, entity confidence, scope confidence tier, per-stage
model confidence and `source_disagreement` (from claim conflicts, never from sentiment spread). **`evidence_strength`** is STRONG / MODERATE / WEAK /
INSUFFICIENT from named rules over those counts, shown with the rule and reasons; an unresolved CONFLICTED claim caps it at WEAK.

## 5. Novelty (`intelligence/novelty.py`)

NEW / CONTINUATION / UPDATE / RECURRING / UNKNOWN against earlier events of the same subject inside a 30-day look-back: no prior gives NEW; a different
narrative gives NEW; the same narrative whose earlier event was RESOLVED / STALE, went quiet 7 days, or is described as "another / again / fresh" gives
RECURRING; new numbers or names give UPDATE; otherwise CONTINUATION. Untrusted clock or no subject gives UNKNOWN (an abstention). Nearest prior events,
new information and indicators are returned. The pipeline's own `novelty_score` is reported unchanged beside the label and is unrelated to it.

## 6. Narrative velocity (`intelligence/velocity.py`)

Cumulative independent sources over time buckets, growth ("1 → 6 independent sources over 4.0 h"), velocity (sources/hour), and acceleration only
when at least five reports and two windows of an hour exist (else null with the reason). Evidence only: a test asserts the module never reads severity.

## 7. Contradiction (`intelligence/claims.py`)

Rule-based extraction over a **closed lexicon** (six axes with two opposite poles: confirmed/denied, open/closed, completed/cancelled, running/shut
down, guidance raised/cut, approved/rejected) gives claims with subject, predicate, object, polarity, timestamp, source and the verbatim clause. A
negated cue ("has not confirmed") asserts nothing; a hedged one ("reportedly") is marked attributed; a cue in a background clause ("after the plant
shut down") is skipped; a report asserting both poles of an axis is a sequence, not a stance. Opposite poles of one axis from different reports that
share a topic, within 24 h, are a **conflict**: POSSIBLE (hedged, same outlet, untrusted time or thin overlap) or CONFLICTED (explicit, different
outlets). Beyond 24 h they are a change of state, reported separately. RESOLVED_CONFLICT needs a later authoritative report, the same outlet reversing
itself, or an explicit retraction: counting outlets is not establishing truth. Both sides are returned with provenance. The older sentiment-sign
`conflict_for` is shown only as "tone divergence, not a contradiction".

On the replay pack, claims were found in 52 of 2,330 events and none contradicted another; one false positive found during development (recovery
reports: "back online after the outage" against "recover after a brief outage") produced three of the rules above.

## 8. Lifecycle (`intelligence/lifecycle.py`)

DEVELOPING, CONFIRMED (enough independent sources or one authoritative, no open contradiction), ESCALATING / STABILIZING (cue phrases, or no further
escalation for 24 h), RESOLVED (an explicit resolution cue from an authoritative source or two independent outlets: **never inferred from falling
volume**), STALE (72 h without a report, not resolved; a new report revives it). Every transition records its rule, rule text and the reports that
caused it. It is recomputed from reports published at or before `as_of` only (tested future-invariant). Default `as_of`: now for live and pasted text,
the event's last report for replay (labelled `LAST_REPORT`, not the end of the data).

## 9. Abstention

Every section carries `availability` (AVAILABLE / PARTIAL / ABSTAINED / UNAVAILABLE) and a reason, and `abstentions[]` lists fields in the form
`company: UNKNOWN`, `impact: UNAVAILABLE`, `portfolio stress: NOT_TRIGGERED` with why. Untrusted clocks make velocity, lifecycle and novelty
UNAVAILABLE. Portfolio relevance and stress reuse the relevance service and the deterministic stress engine (default scenario, only when it applies).

## API

* `GET /api/signals/{id}/intelligence?as_of=&portfolio_id=` -> `EventIntelligence` (422 if `as_of` precedes the first report; 404 where the layer is off).
* `POST /api/analyze` accepts optional `headline` and `url`, and returns `intelligence` beside `assessment`.
* `SignalSummary.scope_type` / `scope_value`; `GET /api/signals?scope_type=`; `capabilities.intelligence`.

## Limitations (also on the page)

All thresholds and vocabularies in `configs/intelligence.yaml` are judgement priors written before any result was seen; none is fitted or validated.
Claim extraction misses paraphrase and reads only the first report of a cluster in full (the others keep their headline). The look-back for novelty
covers only the signals EventShock holds. The authoritative-domain list is closed. A syndicated wire story on twelve outlets is, correctly, one source.
