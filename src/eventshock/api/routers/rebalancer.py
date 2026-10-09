from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...config import REPO_ROOT
from ...rebalancer.backtest import RebalancerBacktestView, load_view
from ...rebalancer.lab import RebalancerLabView
from ...rebalancer.lab import load_view as load_lab_view
from ...rebalancer.ledger import LedgerError, LedgerStore, approved_allocation, view
from ...rebalancer.models import (
    DecisionRequest,
    LedgerAction,
    LedgerEntry,
    LedgerView,
    RebalanceCycleDetail,
    RebalanceDecisions,
    RebalancerOverview,
    RebalancerParams,
    RebalancerTimeline,
)
from ..deps import Container, get_container

router = APIRouter(prefix="/rebalancer", tags=["rebalancer"])
BACKTEST_PATH = REPO_ROOT / "data" / "rebalancer" / "backtest.json"
LAB_PATH = REPO_ROOT / "data" / "rebalancer" / "lab.json"

_TILT = Query(default=None, ge=0, description="what-if: tilt strength k (default: the shipped configuration)")
_HALF_LIFE = Query(default=None, gt=0, description="what-if: hours for a report's weight to halve")
_TURNOVER = Query(default=None, gt=0, le=1, description="what-if: the most of the index traded in one cycle (one-way)")
_STRATEGY = Query(default=None, description="which strategy (configs/rebalancer.yaml: strategies); default: the baseline `sentiment` rule")
_LIVE = Query(default=False, description="also read the live feed's reports (never pasted text); off by default so the index of record does not move with the feed")


def _svc(c: Container):  # noqa: ANN202
    if c.rebalancer is None:
        raise HTTPException(status_code=404, detail="the tactical index rebalancer is available in the replay profile only")
    return c.rebalancer


def _params(svc, tilt, half_life_hours, max_turnover) -> RebalancerParams:  # noqa: ANN001
    try:
        return svc.resolve_params(tilt, half_life_hours, max_turnover)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/overview", response_model=RebalancerOverview,
            description="The mock index (its stocks, equal-weight benchmark, bounds and the shipped parameters), the cycle clock, the rule drawn as a curve, and the labels and limitations. "
                        "`available` is false when no company report exists to build a timeline from.")
def get_overview(c: Container = Depends(get_container)) -> RebalancerOverview:
    return _svc(c).overview()


@router.get("/timeline", response_model=RebalancerTimeline,
            description="The weights of every stock at every cycle, with sentiment scores, report counts and turnover. The three optional parameters are a what-if for this request only "
                        "(`params.is_default` is false); the server's configuration never changes. A pure function of the frozen signals: two calls give the same answer.")
def get_timeline(tilt: float | None = _TILT, half_life_hours: float | None = _HALF_LIFE, max_turnover: float | None = _TURNOVER, include_live: bool = _LIVE,
                 strategy: str | None = _STRATEGY, c: Container = Depends(get_container)) -> RebalancerTimeline:
    svc = _svc(c)
    try:
        return svc.timeline(_params(svc, tilt, half_life_hours, max_turnover), include_live, strategy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/cycles/{index}", response_model=RebalanceCycleDetail,
            description="One cycle in full: every stock's score, target weight, weight, change and the named reason, and the reports behind each score (their contributions add up to it).")
def get_cycle(index: int, tilt: float | None = _TILT, half_life_hours: float | None = _HALF_LIFE, max_turnover: float | None = _TURNOVER, include_live: bool = _LIVE,
              strategy: str | None = _STRATEGY, c: Container = Depends(get_container)) -> RebalanceCycleDetail:
    svc = _svc(c)
    try:
        return svc.cycle(index, _params(svc, tilt, half_life_hours, max_turnover), include_live, strategy)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _ledger(c: Container) -> LedgerStore:
    if c.rebalancer_ledger is None:
        raise HTTPException(status_code=404, detail="the rebalancer ledger is available in the replay profile only")
    return c.rebalancer_ledger


@router.get("/cycles/{index}/decisions", response_model=RebalanceDecisions,
            description="One cycle as a rebalance proposal: for every stock the weight before, the target and the weight after, the trade, est. cost, the reports behind it (headline, time, sentiment, "
                        "contribution), evidence-quality, freshness and conflict flags, the rules that bound it and a template-written explanation. `latest_decision` is the simulated decision "
                        "recorded on this exact proposal, if any. `proposal_sha256` identifies the proposal: a decision made on a proposal that later changes is void.")
def get_decisions(index: int, tilt: float | None = _TILT, half_life_hours: float | None = _HALF_LIFE, max_turnover: float | None = _TURNOVER, include_live: bool = _LIVE,
                  strategy: str | None = _STRATEGY, c: Container = Depends(get_container)) -> RebalanceDecisions:
    svc = _svc(c)
    params = _params(svc, tilt, half_life_hours, max_turnover)
    try:
        d = svc.decisions(index, params, include_live, strategy)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if c.rebalancer_ledger is not None:
        e = c.rebalancer_ledger.latest_for(d.strategy, index, (params.tilt, params.half_life_hours, params.max_turnover), include_live)
        if e is not None:
            d = d.model_copy(update={"latest_decision": e.model_copy(update={"stale": e.proposal_sha256 != d.proposal_sha256})})
    return d


@router.post("/proposals/decision", response_model=LedgerEntry,
             description="Record a simulated decision on a proposed rebalance: approve all of it, approve a subset of its trades, or reject it. Nothing is sent anywhere and the served index does not "
                         "change. `proposal_sha256` must be the digest of the proposal that was on screen (409 if it has changed). A partial approval must still be a fully invested allocation inside "
                         "the strategy's bounds and sector caps (422 names the broken rule).")
def post_decision(req: DecisionRequest, c: Container = Depends(get_container)) -> LedgerEntry:
    svc, store = _svc(c), _ledger(c)
    params = _params(svc, req.tilt, req.half_life_hours, req.max_turnover)
    try:
        d = svc.decisions(req.cycle_index, params, req.include_live, req.strategy)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if d.proposal_sha256 != req.proposal_sha256:
        raise HTTPException(status_code=409, detail="the proposal has changed since it was shown; reload it and decide again")
    try:
        if req.action is LedgerAction.APPROVE:
            approved, accepted, rejected = approved_allocation(d, req.accepted_tickers)
            svc.check_allocation(d.strategy, approved)
        else:
            approved = [x.before for x in sorted(d.decisions, key=lambda x: d.tickers.index(x.ticker))]
            accepted, rejected = [], sorted(x.ticker for x in d.decisions if x.side.value != "HOLD")
        return store.record(d, action=req.action, approved=approved, accepted=accepted, rejected=rejected, note=req.note, analyst=req.analyst, include_live=req.include_live)
    except LedgerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/ledger", response_model=LedgerView,
            description="The simulated trade ledger, newest first: each decision with the allocation before, proposed and approved, the cost, and whether its proposal is stale. "
                        "`chain_ok` is false if a line was edited or removed. `paper_book` is the allocation after the latest approval.")
def get_ledger(c: Container = Depends(get_container)) -> LedgerView:
    return view(_ledger(c), _svc(c))


@router.get("/backtest", response_model=RebalancerBacktestView,
            description="An illustration of the mechanics over the replay window, built offline from price files that are not redistributed (`make rebalancer-backtest`): returns against the equal-weight "
                        "benchmark after costs, the rank-IC of the score and a shuffled-score placebo. UNAVAILABLE when it has not been built; STALE when the weights it was built from differ from today's.")
def get_backtest(c: Container = Depends(get_container)) -> RebalancerBacktestView:
    return load_view(_svc(c), BACKTEST_PATH)


@router.get("/lab", response_model=RebalancerLabView,
            description="The strategy lab, built offline from price files that are not redistributed (`make rebalancer-lab`): the baseline sentiment rule, the experimental risk-limit and "
                        "sentiment-x-impact strategies, equal weight and buy-and-hold, on the same window with the same costs and the same shuffled-score placebo; windows, a sensitivity grid "
                        "(half-life, turnover cap, tilt, position limit) and cost sensitivity. Ten sessions: an illustration, never evidence of skill. UNAVAILABLE when not built; STALE when the "
                        "weights it was built from differ from today's.")
def get_lab(c: Container = Depends(get_container)) -> RebalancerLabView:
    return load_lab_view(_svc(c), LAB_PATH)
