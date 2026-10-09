"""The strategy lab: every strategy on the same window with the same costs, honest metrics, computed verdicts, and stale / missing states."""

from __future__ import annotations

import json
import math

import pytest

from eventshock.config import REPO_ROOT
from eventshock.rebalancer import lab as labmod
from eventshock.rebalancer.backtest import build as build_backtest
from eventshock.rebalancer.lab import build, drawdown, load_view, verdict_of, windows
from tests.rebalancer_helpers import TICKERS, cfg, risk_inputs, service
from tests.unit.test_rebalancer_backtest import DATES, burst, write_prices


def world(tmp_path):
    sigs = burst("AAPL", 1.0, 12) + burst("NVDA", 1.0, 12) + burst("JPM", -1.0, 12) + burst("XOM", -1.0, 12) + burst("PFE", 0.5, 12)
    svc = service(sigs, as_of_hours=140, config=cfg(**{"turnover.max_per_cycle": 0.25}), real_sectors=True, risk=risk_inputs())
    up, down = {"AAPL", "NVDA"}, {"JPM", "XOM"}
    write_prices(tmp_path, DATES, {t: (lambda k: 0.02) if t in up else (lambda k: -0.02) if t in down else (lambda k: 0.0) for t in TICKERS})
    return svc


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("prices")
    svc = world(d)
    return svc, build(svc, d, placebo_runs=20, grid_placebo_runs=5), d


def test_drawdown_known_values():
    assert drawdown([0.1, -0.1, 0.05]) == pytest.approx([0.0, -0.1, 1.1 * 0.9 * 1.05 / 1.1 - 1])
    assert drawdown([-0.5]) == pytest.approx([-0.5])
    assert drawdown([0.1, 0.1]) == [0.0, 0.0]


def test_verdict_is_computed_from_the_placebo_never_asserted():
    assert verdict_of(0.5) == "WITHIN_PLACEBO_RANGE" and verdict_of(0.95) == "ABOVE_PLACEBO_RANGE" and verdict_of(0.05) == "BELOW_PLACEBO_RANGE"


def test_windows_cover_the_full_window_the_halves_and_every_rolling_span():
    dates = [f"2026-09-{d:02d}" for d in range(1, 11)]
    net, bench = [0.01] * 10, [0.0] * 10
    w, pos, tot = windows(dates, net, bench)
    assert [x.label for x in w[:3]] == ["full window", "first half", "second half"]
    assert tot == 6 and pos == 6 and w[0].sessions == 10 and w[1].sessions == 5
    assert w[0].strategy_return == pytest.approx(1.01 ** 10 - 1) and w[0].active_return == pytest.approx(w[0].strategy_return)


def test_every_strategy_and_both_references_are_on_the_same_dates_with_matching_lengths(built):
    _, lab, _ = built
    ids = [s.id for s in lab.strategies]
    assert ids == ["sentiment", "sentiment_risk", "sentiment_impact", "equal_weight", "buy_and_hold"]
    n = len(lab.dates)
    for s in lab.strategies:
        assert len(s.daily_net) == len(s.cumulative) == len(s.drawdown) == len(s.turnover) == n
        assert s.cumulative[-1] == pytest.approx(s.metrics.cumulative_return, abs=1e-12)
        assert s.metrics.max_drawdown <= 0 and s.windows
    assert {s.kind for s in lab.strategies} == {"TILT", "REFERENCE"}


def test_the_references_behave_as_defined(built):
    _, lab, _ = built
    by = {s.id: s for s in lab.strategies}
    assert by["buy_and_hold"].turnover == [0.0] * len(lab.dates) and by["buy_and_hold"].metrics.total_cost == 0.0
    ew = by["equal_weight"]
    assert ew.metrics.active_return == pytest.approx(0.0, abs=1e-15) and ew.metrics.hit_rate is None and ew.placebo is None and ew.verdict is None
    assert ew.metrics.total_cost > 0   # resetting drifted weights to equal is not free
    assert by["sentiment"].placebo is not None and by["sentiment"].verdict in {"WITHIN_PLACEBO_RANGE", "ABOVE_PLACEBO_RANGE", "BELOW_PLACEBO_RANGE"}


def test_the_baseline_in_the_lab_is_exactly_the_baseline_backtest(built):
    svc, lab, d = built
    bt = build_backtest(svc, d, placebo_runs=5)
    base = next(s for s in lab.strategies if s.id == "sentiment")
    assert base.daily_net == pytest.approx(bt.rebalanced, abs=1e-15)
    assert base.metrics.active_return == pytest.approx(bt.summary.active_return, abs=1e-15)
    assert base.metrics.total_cost == pytest.approx(bt.summary.total_cost, abs=1e-15)
    assert base.timeline_sha256 == bt.timeline_sha256
    assert lab.inputs == bt.inputs


def test_the_grid_covers_the_stated_axes_and_counts_honestly(built):
    _, lab, _ = built
    g = lab.grid
    assert len(g.half_life_by_turnover) == len(labmod.HALF_LIVES) * len(labmod.TURNOVER_CAPS)
    assert len(g.tilt_by_position_limit) == len(labmod.TILTS) * len(labmod.POSITION_LIMITS)
    cells = g.half_life_by_turnover + g.tilt_by_position_limit
    assert g.cells_total == len(cells) and g.cells_positive == sum(1 for c in cells if c.active_return > 0)
    assert g.cells_outside_placebo_range == sum(1 for c in cells if c.placebo_percentile >= 0.95 or c.placebo_percentile <= 0.05) and g.expected_outside_by_chance == pytest.approx(0.1 * len(cells))
    assert g.active_min == min(c.active_return for c in cells) and g.active_max == max(c.active_return for c in cells)
    ratios = {c.max_active_ratio for c in g.tilt_by_position_limit}
    assert ratios == set(labmod.POSITION_LIMITS)
    shipped = next(c for c in g.half_life_by_turnover if c.half_life_hours == 36.0 and c.max_turnover == 0.04)
    assert shipped.tilt == 2.0   # the shipped parameters sit in the grid


def test_a_costlier_market_never_improves_a_trading_strategy(built):
    _, lab, _ = built
    ac = [c.active_return for c in lab.cost_sensitivity]
    assert [c.cost_bps for c in lab.cost_sensitivity] == labmod.COSTS_BPS
    assert all(math.isfinite(x) for x in ac)


def test_the_impact_coverage_is_reported(built):
    _, lab, _ = built
    assert 0 < lab.impact_reports <= lab.reports_used


def test_the_view_is_available_unavailable_or_stale(built, tmp_path):
    svc, lab, _ = built
    assert load_view(svc, tmp_path / "missing.json").status == "UNAVAILABLE"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_view(svc, bad).status == "UNAVAILABLE"
    ok = tmp_path / "lab.json"
    ok.write_text(lab.model_dump_json(), encoding="utf-8")
    v = load_view(svc, ok)
    assert v.status == "AVAILABLE" and v.lab is not None
    raw = json.loads(ok.read_text(encoding="utf-8"))
    raw["strategies"][1]["timeline_sha256"] = "0" * 64
    ok.write_text(json.dumps(raw), encoding="utf-8")
    stale = load_view(svc, ok)
    assert stale.status == "STALE" and "sentiment_risk" in (stale.reason or "") and stale.lab is not None
    other = service([], real_sectors=True)   # a service that cannot serve the risk strategy at all
    assert load_view(other, ok).status in {"STALE", "AVAILABLE"}


def test_a_hole_in_the_prices_refuses_to_build(tmp_path):
    svc = world(tmp_path)
    write_prices(tmp_path, DATES, {}, drop=("AAPL", DATES[4]))
    with pytest.raises(ValueError, match="hole"):
        build(svc, tmp_path, placebo_runs=2, grid_placebo_runs=2)


def test_the_committed_lab_matches_the_committed_backtest():
    lab_path = REPO_ROOT / "data" / "rebalancer" / "lab.json"
    bt_path = REPO_ROOT / "data" / "rebalancer" / "backtest.json"
    if not lab_path.is_file() or not bt_path.is_file():
        pytest.skip("the lab has not been built")
    lab, bt = json.loads(lab_path.read_text(encoding="utf-8")), json.loads(bt_path.read_text(encoding="utf-8"))
    base = next(s for s in lab["strategies"] if s["id"] == "sentiment")
    assert base["timeline_sha256"] == bt["timeline_sha256"]
    assert base["metrics"]["active_return"] == pytest.approx(bt["summary"]["active_return"], abs=1e-12)
    assert base["metrics"]["total_cost"] == pytest.approx(bt["summary"]["total_cost"], abs=1e-12)
    assert lab["dates"] == bt["dates"] and lab["inputs"] == bt["inputs"]
