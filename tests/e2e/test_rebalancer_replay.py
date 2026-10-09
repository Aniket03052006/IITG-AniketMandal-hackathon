"""The rebalancer over the real replay pack: it writes nothing onto a signal (the pinned digest holds), the replay run is identical every time and after a restart, and
**no report published after a cycle can influence it** (checked by deleting every later report from the real signals and comparing the cycles before the cut)."""

from __future__ import annotations

import pytest

from eventshock.pipeline.run import _digest
from eventshock.rebalancer.service import RebalancerService
from eventshock.store import CombinedSignalRepository, InMemorySignalRepository, LiveSignalStore
from tests.e2e.test_replay_served import GOLDEN_SERVED_DIGEST


def fresh(c, signals=None, as_of=None):  # noqa: ANN001, ANN201
    base = InMemorySignalRepository(signals if signals is not None else c.signals.base._signals, as_of or c.signals.as_of)  # noqa: SLF001
    return RebalancerService(c.rebalancer.cfg, signals=CombinedSignalRepository(base, LiveSignalStore()), entities=lambda: c.portfolio.entities())


def test_a_run_changes_nothing_and_a_fresh_service_agrees(replay_container):
    c = replay_container
    svc = c.rebalancer
    a = svc.timeline(svc.default_params()).model_dump_json()
    assert a == fresh(c).timeline(svc.default_params()).model_dump_json()
    assert _digest(c.signals.list()) == GOLDEN_SERVED_DIGEST


def test_the_grid_ends_at_the_replay_clock_and_covers_the_window(replay_container):
    svc = replay_container.rebalancer
    g = svc.grid()
    assert g[-1] == replay_container.signals.as_of and g == sorted(g) and 40 < len(g) <= svc.cfg.cycles.max_cycles
    assert all((b - a).total_seconds() <= svc.cfg.cycles.step_hours * 3600 for a, b in zip(g, g[1:], strict=False))


def test_the_real_signals_use_two_kinds_of_sources_but_only_the_trusted_clock_ones(replay_container):
    """Sources: news (GDELT) and, counted but not placed, social posts whose time the replay assigned."""
    tl = replay_container.rebalancer.timeline(replay_container.rebalancer.default_params())
    assert tl.reports_used > 500 and tl.excluded_untrusted_clock > 0


@pytest.mark.parametrize("fraction", [0.35, 0.7])
def test_deleting_every_later_report_changes_no_earlier_cycle(replay_container, fraction):
    c = replay_container
    svc = c.rebalancer
    full = svc.timeline(svc.default_params())
    cut = full.cycles[int(len(full.cycles) * fraction)].at
    kept = [s for s in c.signals.base._signals if s.document.published_at <= cut]  # noqa: SLF001
    assert len(kept) < len(c.signals.base._signals)  # noqa: SLF001
    short = fresh(c, kept, as_of=cut).timeline(svc.default_params())
    by_at = {x.at: x for x in full.cycles}
    compared = 0
    for x in short.cycles:
        if x.at <= cut and x.at in by_at:
            y = by_at[x.at]
            assert x.scores == y.scores and x.reports == y.reports, f"cycle {x.at} read a report published after it"
            assert x.weights == pytest.approx(y.weights, abs=1e-12)
            compared += 1
    assert compared > 10


def test_every_cycle_reconciles_for_any_parameters_in_range(replay_container):
    svc = replay_container.rebalancer
    for tilt in (0.0, 1.0, 6.0):
        for tov in (0.005, 0.04, 0.25):
            for hl in (6.0, 36.0, 240.0):
                p = svc.resolve_params(tilt, hl, tov)
                prev = [svc.cfg.benchmark_weight] * svc.cfg.n
                for cy in svc.timeline(p).cycles:
                    assert sum(cy.weights) == pytest.approx(1.0, abs=1e-9)
                    assert 0.5 * sum(abs(a - b) for a, b in zip(cy.weights, prev, strict=True)) <= tov + 1e-9
                    prev = cy.weights


def test_the_committed_backtest_was_built_from_the_weights_now_served(replay_container):
    """If a signal, a model or a parameter changes, the weights move and this fails until `make rebalancer-backtest` is run and the change journalled."""
    from eventshock.api.routers.rebalancer import BACKTEST_PATH
    from eventshock.rebalancer.backtest import load_view
    v = load_view(replay_container.rebalancer, BACKTEST_PATH)
    assert v.status == "AVAILABLE", v.reason
    assert v.backtest is not None and len(v.backtest.dates) >= 8 and v.backtest.placebo.runs >= 100


def test_the_committed_lab_was_built_from_the_weights_now_served(replay_container):
    """Every strategy's weight path is hash-pinned in the lab; a change to a signal, a model, a parameter or a constraint fails this until `make rebalancer-lab` is run and journalled."""
    from eventshock.api.routers.rebalancer import LAB_PATH
    from eventshock.rebalancer.lab import load_view
    v = load_view(replay_container.rebalancer, LAB_PATH)
    assert v.status == "AVAILABLE", v.reason
    assert v.lab is not None and len(v.lab.dates) >= 8 and v.lab.grid.cells_total == 21
    assert {s.id for s in v.lab.strategies} == {"sentiment", "sentiment_risk", "sentiment_impact", "equal_weight", "buy_and_hold"}


def test_the_baseline_path_is_the_one_the_backtest_was_built_from_whatever_else_is_loaded(replay_container):
    """The strategy work added constraint sets next to the baseline; the baseline's own digest must still be the committed one."""
    import json

    from eventshock.api.routers.rebalancer import BACKTEST_PATH
    from eventshock.rebalancer.backtest import timeline_digest
    svc = replay_container.rebalancer
    svc.timeline(svc.default_params(), strategy="sentiment_risk")   # warm the other strategies first
    svc.timeline(svc.default_params(), strategy="sentiment_impact")
    tl = svc.timeline(svc.default_params())
    committed = json.loads(BACKTEST_PATH.read_text(encoding="utf-8"))["timeline_sha256"]
    assert timeline_digest([c.weights for c in tl.cycles], tl.params) == committed


def test_deciding_on_proposals_writes_nothing_to_a_signal(replay_container):
    """The ledger is a side-car: approving a rebalance leaves every served signal (and so every pinned digest) exactly as it was."""
    from eventshock.rebalancer.ledger import LedgerStore, approved_allocation
    from eventshock.rebalancer.models import LedgerAction
    svc = replay_container.rebalancer
    before = _digest(replay_container.signals.list())
    p = svc.default_params()
    d = svc.decisions(len(svc.timeline(p).cycles) - 1, p)
    store = LedgerStore(None)
    w, acc, rej = approved_allocation(d, None)
    store.record(d, action=LedgerAction.APPROVE, approved=w, accepted=acc, rejected=rej, note="", analyst="t", include_live=False)
    assert _digest(replay_container.signals.list()) == before == GOLDEN_SERVED_DIGEST
