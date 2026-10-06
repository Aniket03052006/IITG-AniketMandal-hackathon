"""The brief over the real replay pack: a failing or absent external-market provider changes only its own section, never another, and the brief survives a side-car rebuild unchanged."""

from __future__ import annotations

from eventshock.api.deps import rebuild_sidecars
from eventshock.brief.models import SECTIONS
from eventshock.markets.models import ProviderCategory, ProviderState
from eventshock.pipeline.run import _digest
from tests.e2e.test_markets_replay import Exploding, _swap
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST


def _top(c, n=6):  # noqa: ANN001, ANN201
    _, states = c.monitor.replay_states(None)
    return [s.event_id for s in sorted(states.states.values(), key=lambda s: (-(s.severity or 0), s.event_id))[:n]]


def test_a_failing_market_provider_changes_only_the_market_section(replay_container):
    c = replay_container
    ids = _top(c)
    original = c.markets
    off = ProviderState(provider="kalshi", category=ProviderCategory.PREDICTION_MARKET, state="DISABLED", mode="off", reason="off")
    base = {i: {s.id: s.model_dump_json() for s in c.brief.build(i).sections} for i in ids}
    try:
        c.markets = _swap(c, Exploding(), off)
        for i in ids:
            b = c.brief.build(i)
            assert [s.id for s in b.sections] == [x for x, _ in SECTIONS]
            now = {s.id: s.model_dump_json() for s in b.sections}
            same = {k for k in now if now[k] == base[i][k]}
            assert {k for k in now if k not in same} <= {"EXTERNAL_MARKET_VIEW", "WHAT_TO_MONITOR"}      # the monitoring rule M5 is the only other place a matched market can show
            assert next(s for s in b.sections if s.id == "EXTERNAL_MARKET_VIEW").statements[0].text == "External market data unavailable."
    finally:
        c.markets = original
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST


def test_the_brief_is_identical_after_a_sidecar_rebuild(replay_container):
    c = replay_container
    ids = _top(c, 4)
    before = [c.brief.build(i).model_dump_json() for i in ids]
    rebuild_sidecars(c, {})
    assert [c.brief.build(i).model_dump_json() for i in ids] == before
