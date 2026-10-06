"""Watchlists over the real replay pack: activity is the same after a side-car rebuild, nothing is written onto a signal, and an unresolved event never matches a company."""

from __future__ import annotations

from eventshock.api.deps import rebuild_sidecars
from eventshock.pipeline.run import _digest
from eventshock.watchlist.models import WatchItem, WatchKind, WatchlistInput
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST


def test_activity_is_stable_across_a_rebuild_and_leaves_the_signals_alone(replay_container):
    c = replay_container
    svc = c.watchlists
    v = svc.vocabulary()
    w = svc.create(WatchlistInput(name="e2e", items=[WatchItem(kind=WatchKind.SECTOR, value="Financials"), WatchItem(kind=WatchKind.COMPANY, value=v.companies[0].value),
                                                     WatchItem(kind=WatchKind.EVENT_TYPE, value="REGULATORY_LEGAL"), WatchItem(kind=WatchKind.RISK_THEME, value="rates"),
                                                     WatchItem(kind=WatchKind.GEOGRAPHY, value="US"), WatchItem(kind=WatchKind.PORTFOLIO_EXPOSURE, value="top:3")]))
    try:
        k = len(c.monitor.cycles()) // 2
        before = svc.activity(w, cycle=k, window=3).model_dump_json()
        rebuild_sidecars(c, {})
        assert svc.activity(w, cycle=k, window=3).model_dump_json() == before
        a = svc.activity(w, cycle=k, window=3)
        assert [i.status for i in a.items if i.matched_events] and all(e.clock_trusted for i in a.items for e in i.events)
        unresolved = {s.id for s in c.signals.list() if s.entity.is_unknown}
        company = next(i for i in a.items if i.item.kind is WatchKind.COMPANY)
        assert not ({e.lead_signal_id for e in company.events} & unresolved)
        assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST
    finally:
        svc.delete(w.id)
