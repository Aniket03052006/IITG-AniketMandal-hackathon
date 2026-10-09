"""The backtest: point-in-time weights, costs, the rank-IC and placebo controls, and the refusal to run on holes in the data."""

from __future__ import annotations

from datetime import timedelta

import pytest

from eventshock.rebalancer.backtest import RebalancerBacktestView, _decision_time, build, load_view, spearman
from tests.rebalancer_helpers import BASE, TICKERS, cfg, service, sig


def write_prices(path, dates, ret_by_ticker, drop=None):
    """One CSV per ticker plus _GSPC: price 100 on the first date, then compounded by the given per-date return."""
    path.mkdir(parents=True, exist_ok=True)
    for t in [*TICKERS, "^GSPC"]:
        stem = "_GSPC" if t == "^GSPC" else t
        px, lines = 100.0, ["date,open,high,low,close,adj_close,volume"]
        for i, d in enumerate(dates):
            if i:
                px *= 1 + ret_by_ticker.get(t, lambda k: 0.0)(i)
            if drop and drop == (t, d):
                continue
            lines.append(f"{d},{px},{px},{px},{px},{px},1")
        (path / f"{stem}.csv").write_text("\n".join(lines), encoding="utf-8")


DATES = [(BASE + timedelta(days=k)).strftime("%Y-%m-%d") for k in range(0, 8)]


def burst(ticker, x, n=8, start=1.0):
    return [sig(f"b{ticker}{i}", ticker, x, hours=start + i * 2, source=f"s{i}") for i in range(n)]


def test_the_session_decision_time_is_the_new_york_close_in_summer_and_winter():
    assert _decision_time("2026-09-17").hour == 20     # EDT: 16:00 = 20:00 UTC
    assert _decision_time("2026-12-01").hour == 21     # EST: 16:00 = 21:00 UTC


def test_spearman_known_values_and_the_undefined_case():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None
    with pytest.raises(ValueError):
        spearman([1, 2], [1, 2])


def test_with_no_tilt_the_index_is_the_benchmark_and_the_active_return_is_zero(tmp_path):
    svc = service(burst("AAPL", 1.0) + burst("JPM", -1.0), as_of_hours=120, config=cfg(**{"tilt.strength": 0.0}))
    write_prices(tmp_path, DATES, {t: (lambda k, n=len(t): 0.01 * ((k * 7 + n) % 5 - 2)) for t in TICKERS})
    bt = build(svc, tmp_path, placebo_runs=5)
    # the index and the benchmark are the same portfolio, so they earn the same and pay the same cost; the turnover is only the daily reset of drifted weights to equal weight
    assert bt.summary.active_return == pytest.approx(0.0, abs=1e-12) and bt.summary.daily_active_mean == pytest.approx(0.0, abs=1e-15)
    assert bt.rebalanced == pytest.approx(bt.benchmark, abs=1e-15)


def test_a_score_that_predicts_the_next_move_earns_a_positive_ic_and_beats_its_placebo(tmp_path):
    sigs = burst("AAPL", 1.0, 12) + burst("NVDA", 1.0, 12) + burst("JPM", -1.0, 12) + burst("XOM", -1.0, 12)
    svc = service(sigs, as_of_hours=140, config=cfg(**{"turnover.max_per_cycle": 0.25}))
    up, down = {"AAPL", "NVDA"}, {"JPM", "XOM"}
    rets = {t: (lambda k: 0.02) if t in up else (lambda k: -0.02) if t in down else (lambda k: 0.0) for t in TICKERS}
    write_prices(tmp_path, DATES, rets)
    bt = build(svc, tmp_path, placebo_runs=40)
    assert bt.rank_ic.mean is not None and bt.rank_ic.mean > 0.3
    assert bt.summary.active_return > 0
    assert bt.placebo.active_return_percentile > 0.9 and bt.placebo.runs == 40


def test_a_session_before_the_first_report_cannot_see_it(tmp_path):
    """A report published after the previous close must not move the weights used for the next session."""
    late = [sig(f"late{i}", "AAPL", 1.0, hours=30 + i, source=f"s{i}") for i in range(6)]
    svc = service(burst("JPM", -0.5, 4) + late, as_of_hours=100)
    write_prices(tmp_path, DATES, {})
    bt = build(svc, tmp_path, placebo_runs=3)
    tl = svc.timeline(svc.default_params())
    j = tl.tickers.index("AAPL")
    close_of_day0 = _decision_time(DATES[0])
    before = [c for c in tl.cycles if c.at <= close_of_day0]
    assert before and all(c.scores[j] == 0.0 for c in before)
    assert bt.dates[0] >= DATES[1]


def test_a_hole_in_the_prices_is_a_loud_error(tmp_path):
    svc = service(burst("AAPL", 1.0, 12), as_of_hours=140)
    write_prices(tmp_path, DATES, {}, drop=("AAPL", DATES[3]))
    with pytest.raises(ValueError, match="no price"):
        build(svc, tmp_path, placebo_runs=2)


def test_a_missing_price_file_is_a_loud_error(tmp_path):
    svc = service(burst("AAPL", 1.0, 12), as_of_hours=140)
    with pytest.raises(FileNotFoundError):
        build(svc, tmp_path, placebo_runs=2)


def test_the_build_is_deterministic(tmp_path):
    sigs = burst("AAPL", 1.0, 12) + burst("JPM", -1.0, 12)
    svc = service(sigs, as_of_hours=140)
    write_prices(tmp_path, DATES, {t: (lambda k: 0.003 * (k % 3)) for t in TICKERS})
    assert build(svc, tmp_path, placebo_runs=10).model_dump_json() == build(svc, tmp_path, placebo_runs=10).model_dump_json()


def test_a_stale_or_missing_file_is_reported_not_hidden(tmp_path):
    svc = service(burst("AAPL", 1.0, 12) + burst("JPM", -1.0, 12), as_of_hours=140)
    assert load_view(svc, tmp_path / "nope.json").status == "UNAVAILABLE"
    prices = tmp_path / "px"
    write_prices(prices, DATES, {})
    out = tmp_path / "bt.json"
    out.write_text(build(svc, prices, placebo_runs=3).model_dump_json(), encoding="utf-8")
    v = load_view(svc, out)
    assert isinstance(v, RebalancerBacktestView) and v.status == "AVAILABLE" and v.backtest is not None
    other = service(burst("AAPL", -1.0, 12) + burst("JPM", 1.0, 12), as_of_hours=140)
    assert load_view(other, out).status == "STALE"
    out.write_text("{not json", encoding="utf-8")
    assert load_view(svc, out).status == "UNAVAILABLE"
