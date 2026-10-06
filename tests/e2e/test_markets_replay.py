"""External markets over the real replay pack: they never move a core number, a provider that is off / failing / synthetic / the captured snapshot changes nothing, and replay is deterministic."""

from __future__ import annotations

from eventshock.config import REPO_ROOT
from eventshock.markets.models import ProviderCategory, ProviderState
from eventshock.markets.provider import load_point_provider
from eventshock.markets.service import MarketService
from eventshock.pipeline.run import _digest
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST


class Exploding:
    name, category, synthetic = "kalshi", ProviderCategory.PREDICTION_MARKET, False

    def state(self):  # noqa: ANN201
        raise RuntimeError("down")

    def markets(self, *a):  # noqa: ANN002, ANN201
        raise RuntimeError("down")

    def history(self, *a):  # noqa: ANN002, ANN201
        raise RuntimeError("down")


def _swap(c, provider, state):  # noqa: ANN001, ANN201
    return MarketService(c.markets.cfg, provider, c.monitor, clock=lambda: c.signals.as_of, state=state)


def _core(replay_client, ids):  # noqa: ANN001, ANN201
    out = []
    for i in ids:
        out.append(replay_client.get(f"/api/signals/{i}/propagation").content)
        out.append(replay_client.get(f"/api/signals/{i}/relevance").content)
    return out


def test_no_provider_state_changes_a_core_output_or_the_digest(replay_client, replay_container):
    c = replay_container
    _, states = c.monitor.replay_states(None)
    ids = [s.lead_signal_id for s in sorted(states.states.values(), key=lambda s: (-(s.severity or 0), s.event_id))[:5]]
    before = _core(replay_client, ids)
    original = c.markets
    off = ProviderState(provider="kalshi", category=ProviderCategory.PREDICTION_MARKET, state="DISABLED", mode="off", reason="off")
    try:
        for provider, state in ((None, off), (Exploding(), off)):
            c.markets = _swap(c, provider, state)
            for s in states.states.values():
                v = c.markets.view(s.event_id)                                 # must degrade, never raise
                assert v.availability == "UNAVAILABLE" and v.match.market is None
            assert _core(replay_client, ids) == before
            assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST
    finally:
        c.markets = original
    assert _core(replay_client, ids) == before


def test_the_captured_snapshot_is_hash_pinned_and_every_event_view_is_honest(replay_container):
    c = replay_container
    path = REPO_ROOT / "data" / "external" / "kalshi_snapshot.json"
    p = load_point_provider(path, name="kalshi", previous_gap_hours=24, expect_synthetic=False, manifest=path.with_suffix(".manifest.json"))
    svc = _swap(c, p, p.state())
    _, states = c.monitor.replay_states(None)
    for s in list(states.states.values())[:40]:
        v = svc.view(s.event_id)
        assert v.match.status.value in {"MATCHED", "LOW_CONFIDENCE_MATCH", "NO_MATCH", "INSUFFICIENT_DATA"}
        if v.match.market is not None:                                          # nothing observed after the moment can be used
            assert v.match.market.observed_at <= v.as_of and not v.match.market.synthetic


def test_the_view_is_deterministic_across_a_rebuild(replay_container):
    from eventshock.api.deps import rebuild_sidecars
    c = replay_container
    _, states = c.monitor.replay_states(None)
    ids = sorted(states.states)[:20]
    before = [c.markets.view(i).model_dump_json() for i in ids]
    rebuild_sidecars(c, {})
    assert [c.markets.view(i).model_dump_json() for i in ids] == before
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST
