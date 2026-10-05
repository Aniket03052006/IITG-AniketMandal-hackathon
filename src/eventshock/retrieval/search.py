"""Point-in-time analogue search.

Rules (``configs/evidence_v3.yaml: retrieval``), each enforced here and pinned by a test:

1. **Eligibility.** A past episode may be used only if its reaction window plus the embargo closed before the query: ``available_from <= query_date``.
   Nothing later than the query can reach the result, whatever else is in the index (``test_future_invariance``).
2. **One analogue per outcome.** An episode (a ticker-session, or a market session) is one observation, however many reports it holds.
3. **Story collapse.** Near-duplicates (same ticker, within a few sessions, cosine at least ``dedup_cosine``) are one story: the effective sample is stories.
4. **Diversity caps** per ticker and per ticker-month.
5. **Reliability.** Too few distinct episodes or stories above the similarity floor means ``NO_RELIABLE_ANALOGUE``: nothing is padded, and what was found
   is shown separately as ``below_bar``, never as precedent.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..modeling.impact_stats import wilson
from .index import AnalogueIndex
from .model import Analogue, AnalogueAggregate, AnalogueSet

MAX_CANDIDATES = 60   # similarity-ranked candidates considered before collapse (bounds the work; far more than any answer needs)


@dataclass(frozen=True)
class SearchParams:
    k: int = 5
    similarity_floor: float = 0.84
    min_distinct_episodes: int = 5
    min_distinct_stories: int = 3
    dedup_cosine: float = 0.92
    dedup_within_sessions: int = 10
    max_per_ticker: int = 3
    max_per_ticker_month: int = 2
    aggregate_over: int = 20     # statistics use up to this many distinct stories (display still shows k)

    @classmethod
    def from_config(cls, pre: dict, floor: float, aggregate_over: int = 20) -> SearchParams:
        r = pre["retrieval"]
        return cls(k=int(r["k"]), similarity_floor=floor, min_distinct_episodes=int(r["reliability"]["min_distinct_episodes"]),
                   min_distinct_stories=int(r["reliability"]["min_distinct_stories"]), dedup_cosine=float(r["story_dedup"]["cosine_at_least"]),
                   dedup_within_sessions=int(r["story_dedup"]["within_sessions"]), max_per_ticker=int(r["diversity"]["max_per_ticker"]),
                   max_per_ticker_month=int(r["diversity"]["max_per_ticker_month"]), aggregate_over=aggregate_over)


def _as_item(index: AnalogueIndex, i: int, sim: float) -> Analogue:
    r = index.rows[i]
    return Analogue(id=r["id"], headline=r["text"], published_at=r["published_at"], reaction_session=r["s0_date"], scope=r["scope"], ticker=r["ticker"],
                    sector=r["sector"], similarity=round(float(sim), 4), car_pct=round(100 * r["car"], 3), z=round(r["z"], 3), abs_z=round(r["abs_z"], 3),
                    vix_level=None if r["vix_level"] is None else round(r["vix_level"], 2), outcome_version=r["outcome_version"], model_event_type=r["event_top"])


def _same_story(index: AnalogueIndex, a: int, b: int, p: SearchParams) -> bool:
    ra, rb = index.rows[a], index.rows[b]
    if ra["episode"] == rb["episode"]:
        return True
    if ra["scope"] == "ISSUER" and ra["ticker"] != rb["ticker"]:
        return False
    return abs(ra["s0"] - rb["s0"]) <= p.dedup_within_sessions and float(index.vectors[a] @ index.vectors[b]) >= p.dedup_cosine


def aggregate(items: list[Analogue], n_episodes: int, n_stories: int, baseline: float) -> AnalogueAggregate:
    car = np.asarray([i.car_pct for i in items])
    k, n = int(sum(1 for i in items if i.abs_z >= 2.0)), len(items)
    lo, hi = wilson(k, n)
    share = k / n
    distinct = lo > baseline
    return AnalogueAggregate(
        n_episodes=n_episodes, n_stories=n_stories, n_used=n, car_pct_q10=round(float(np.quantile(car, 0.1)), 3), car_pct_q50=round(float(np.quantile(car, 0.5)), 3),
        car_pct_q90=round(float(np.quantile(car, 0.9)), 3), abs_car_pct_median=round(float(np.median(np.abs(car))), 3), share_move_ge_2sigma=round(share, 4),
        share_lo=round(lo, 4), share_hi=round(hi, 4), quiet_day_share=round(baseline, 4), lift=round(share / baseline, 2) if baseline > 0 else None,
        distinguishable_from_quiet_day=bool(distinct),
        reading=("The market's reaction after these past reports was larger than on an ordinary day." if distinct else
                 "The market's reaction after these past reports is not distinguishable from an ordinary day: similar headlines were usually followed by "
                 "an ordinary move."))


@dataclass(frozen=True)
class Collected:
    """What the point-in-time search found before any reliability judgement: shared by the product search and the outcome-value experiment."""
    eligible: int
    above_floor: int
    reps: list[tuple[int, float]]          # one (row index, similarity) per distinct story, most similar first
    n_episodes: int                        # distinct outcome keys above the floor (before story collapse)
    nearest: list[tuple[int, float]]       # the three nearest eligible rows, floor or not


def collect(index: AnalogueIndex, query_vec: np.ndarray, *, query_date: str, scope: str, params: SearchParams, sector: str | None = None,
            event_type: str | None = None, exclude_ids: frozenset[str] = frozenset()) -> Collected:
    """Eligible (point-in-time) candidates ranked by similarity, collapsed into distinct stories. No reliability decision is made here."""
    q = np.asarray(query_vec, dtype=np.float32)
    norm = float(np.linalg.norm(q))
    if q.shape != (index.vectors.shape[1],) or not norm:
        raise ValueError(f"query vector must have {index.vectors.shape[1]} non-zero dims")
    q = q / norm
    mask = (index.scope == scope) & (index.available_from <= query_date)
    if sector:
        mask &= np.asarray([r["sector"] == sector for r in index.rows])
    if event_type:
        mask &= np.asarray([r["event_top"] == event_type for r in index.rows])
    if exclude_ids:
        mask &= np.asarray([r["id"] not in exclude_ids for r in index.rows])
    cand = np.flatnonzero(mask)
    if cand.size == 0:
        return Collected(0, 0, [], 0, [])
    sims = index.vectors[cand] @ q
    order = np.lexsort((np.asarray([index.rows[i]["id"] for i in cand]), -sims))      # similarity desc, ties by id: deterministic
    ranked = [(int(cand[o]), float(sims[o])) for o in order]
    above = [(i, s) for i, s in ranked if s >= params.similarity_floor][:MAX_CANDIDATES]
    reps: list[tuple[int, float]] = []
    for i, s in above:
        if not any(_same_story(index, i, j, params) for j, _ in reps):
            reps.append((i, s))
    return Collected(int(cand.size), len(above), reps, len({index.rows[i]["episode"] for i, _ in above}), ranked[:3])


def search(index: AnalogueIndex, query_vec: np.ndarray, *, query_date: str, scope: str, params: SearchParams, ticker: str | None = None,
           sector: str | None = None, event_type: str | None = None, exclude_ids: frozenset[str] = frozenset()) -> AnalogueSet:
    """Analogues for one query. ``query_date`` is the report's publication date (ISO): conservative for the point-in-time rule."""
    c = collect(index, query_vec, query_date=query_date, scope=scope, params=params, sector=sector, event_type=event_type, exclude_ids=exclude_ids)
    base = {"scope": scope, "query_date": query_date, "similarity_floor": params.similarity_floor, "eligible": c.eligible, "index_version": index.version,
            "above_floor": c.above_floor}
    if c.eligible == 0:
        return AnalogueSet(status="NO_RELIABLE_ANALOGUE", reason="No past report is old enough to be used: nothing before this date is indexed for this kind of report.", **base)
    reps, nearest = c.reps, [_as_item(index, i, s) for i, s in c.nearest]
    caveats = ["Past outcomes are hindsight about other reports, not a forecast for this one.",
               "Only reports with an exact publisher timestamp before the open or after the close are indexed, so the whole reaction window follows the report."]
    if c.n_episodes < params.min_distinct_episodes or len(reps) < params.min_distinct_stories:
        why = (f"Only {c.n_episodes} distinct past episode(s) ({len(reps)} distinct stor{'y' if len(reps) == 1 else 'ies'}) resemble this report closely enough "
               f"(similarity at least {params.similarity_floor:g}); at least {params.min_distinct_episodes} episodes and {params.min_distinct_stories} stories are needed.")
        return AnalogueSet(status="NO_RELIABLE_ANALOGUE", reason=why, below_bar=nearest, caveats=caveats, **base)

    shown: list[tuple[int, float]] = []
    per_ticker: dict[str | None, int] = {}
    per_month: dict[tuple[str | None, str], int] = {}
    for i, s in reps:
        r = index.rows[i]
        key_m = (r["ticker"], r["s0_date"][:7])
        # the per-company cap is about companies: market-wide reports have no ticker and are spread over months instead
        if (r["ticker"] is not None and per_ticker.get(r["ticker"], 0) >= params.max_per_ticker) or per_month.get(key_m, 0) >= params.max_per_ticker_month:
            continue
        per_ticker[r["ticker"]] = per_ticker.get(r["ticker"], 0) + 1
        per_month[key_m] = per_month.get(key_m, 0) + 1
        shown.append((i, s))
    items = [_as_item(index, i, s) for i, s in shown[: params.k]]
    if len(shown) < params.min_distinct_stories:
        return AnalogueSet(status="NO_RELIABLE_ANALOGUE", reason="After per-company diversity limits fewer than the required distinct stories remain.",
                           below_bar=nearest, caveats=caveats, **base)
    agg = aggregate([_as_item(index, i, s) for i, s in shown[: params.aggregate_over]], c.n_episodes, len(reps), float(index.manifest["baselines"][scope]["p_abs_z_ge_2"]))
    return AnalogueSet(status="OK", reason=f"{len(items)} of {len(reps)} distinct past stories shown (similarity at least {params.similarity_floor:g}).",
                       items=items, aggregate=agg, caveats=caveats, **base)
