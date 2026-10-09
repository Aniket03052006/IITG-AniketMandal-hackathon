"""The service: which reports count, the cycle grid, up-weight / down-weight, the turnover cap, reason codes, determinism and point-in-time behaviour."""

from __future__ import annotations

import pytest

from eventshock.domain import SourceType, TimestampOrigin
from eventshock.rebalancer.models import WeightReason
from tests.rebalancer_helpers import BASE, TICKERS, cfg, service, sig

LO, HI = cfg().limits()


def burst(ticker: str, x: float, n: int = 6, start: float = 1.0, prefix: str = "b") -> list:
    """n reports from n different sources, every hour from ``start``."""
    return [sig(f"{prefix}{ticker}{i}", ticker, x, hours=start + i, source=f"src{i}") for i in range(n)]


def weights_at(svc, ticker: str, params=None):
    tl = svc.timeline(params or svc.default_params())
    j = tl.tickers.index(ticker)
    return [c.weights[j] for c in tl.cycles]


def test_no_company_reports_means_no_cycles_and_an_honest_overview():
    svc = service([])
    assert svc.grid() == []
    ov = svc.overview()
    assert ov.available is False and ov.cycle_count == 0
    tl = svc.timeline(svc.default_params())
    assert tl.cycles == [] and tl.reports_used == 0


def test_positive_sentiment_raises_a_weight_and_negative_lowers_it():
    svc = service(burst("AAPL", 0.8) + burst("XOM", -0.8))
    a, x = weights_at(svc, "AAPL"), weights_at(svc, "XOM")
    b = cfg().benchmark_weight
    assert a[-1] > b > x[-1]


def test_a_stock_with_no_reports_stays_at_the_benchmark_when_nothing_else_moves():
    svc = service([sig("only", "AAPL", 0.0, hours=1)])
    assert all(w == pytest.approx(cfg().benchmark_weight) for w in weights_at(svc, "MSFT"))


def test_every_cycle_sums_to_one_stays_in_bounds_and_respects_the_turnover_cap():
    svc = service(burst("AAPL", 1.0, 20) + burst("NVDA", 1.0, 20) + burst("JPM", -1.0, 20) + burst("XOM", -1.0, 20), as_of_hours=120)
    p = svc.resolve_params(tilt=6.0, max_turnover=0.02)
    tl = svc.timeline(p)
    prev = [cfg().benchmark_weight] * len(TICKERS)
    for c in tl.cycles:
        assert sum(c.weights) == pytest.approx(1.0, abs=1e-9)
        assert all(LO - 1e-9 <= w <= HI + 1e-9 for w in c.weights)
        assert 0.5 * sum(abs(a - b) for a, b in zip(c.weights, prev, strict=True)) <= 0.02 + 1e-9
        prev = c.weights


def test_a_lower_turnover_cap_reaches_the_same_place_later():
    sigs = burst("AAPL", 1.0, 20) + burst("JPM", -1.0, 20)
    svc = service(sigs, as_of_hours=120)
    fast = weights_at(svc, "AAPL", svc.resolve_params(max_turnover=0.25))
    slow = weights_at(svc, "AAPL", svc.resolve_params(max_turnover=0.005))
    assert slow[2] < fast[2] and slow[-1] > cfg().benchmark_weight


def test_a_stronger_tilt_moves_the_target_further_from_the_benchmark():
    svc = service(burst("AAPL", 0.7) + burst("JPM", -0.7), as_of_hours=120)
    mild = weights_at(svc, "AAPL", svc.resolve_params(tilt=0.5, max_turnover=0.25))[-1]
    strong = weights_at(svc, "AAPL", svc.resolve_params(tilt=5.0, max_turnover=0.25))[-1]
    assert strong > mild > cfg().benchmark_weight


def test_zero_tilt_holds_the_benchmark_throughout():
    svc = service(burst("AAPL", 1.0) + burst("JPM", -1.0))
    assert all(w == pytest.approx(cfg().benchmark_weight) for w in weights_at(svc, "AAPL", svc.resolve_params(tilt=0.0)))


def test_old_news_fades_and_the_weight_returns_toward_the_benchmark():
    svc = service(burst("AAPL", 1.0, 6), as_of_hours=400)
    w = weights_at(svc, "AAPL", svc.resolve_params(max_turnover=0.25))
    assert max(w) > cfg().benchmark_weight + 0.005
    assert w[-1] == pytest.approx(cfg().benchmark_weight, abs=1e-6)   # 400 h later the report is past the 180 h lookback


def test_a_social_post_with_a_replay_assigned_clock_never_reaches_the_timeline():
    ok = burst("AAPL", 0.5)
    fake = [sig("tw1", "MSFT", 1.0, hours=2, origin=TimestampOrigin.SYNTHETIC_REPLAY_CLOCK, source_type=SourceType.SOCIAL, source="Twitter")]
    svc = service(ok + fake)
    tl = svc.timeline(svc.default_params())
    assert tl.excluded_untrusted_clock == 1 and tl.reports_used == len(ok)
    last = svc.cycle(len(svc.grid()) - 1, svc.default_params())
    msft, nvda = (next(n for n in last.names if n.ticker == t) for t in ("MSFT", "NVDA"))
    assert msft.reports == 0 and msft.weight == pytest.approx(nvda.weight)   # the post moved nothing: MSFT is treated like any stock with no report


def test_a_partial_signal_counts_because_only_its_event_stage_failed_but_a_placeholder_sentiment_does_not():
    sigs = burst("AAPL", 0.5, 3) + [sig("u", None, 0.9, hours=2), sig("p", "MSFT", 0.9, hours=2, complete=False), sig("l", "NVDA", 0.9, hours=2, link=0.2),
                                    sig("ph", "JPM", 0.9, hours=2, sentiment_origin="PLACEHOLDER_RULES")]
    svc = service(sigs)
    tl = svc.timeline(svc.default_params())
    assert tl.reports_used == 4        # AAPL x3 and the PARTIAL MSFT one (its sentiment is a model output; no impact is scored for a non-event)
    assert tl.excluded_other == 2      # the low-confidence link and the placeholder-rule sentiment; the unresolved one is not a COMPANY report at all


def test_a_company_outside_the_index_is_ignored():
    svc = service(burst("AAPL", 0.5, 2) + [sig("t", "TSLA", 1.0, hours=2)])
    assert svc.timeline(svc.default_params()).reports_used == 2


def test_the_run_is_deterministic_and_a_fresh_service_agrees():
    sigs = burst("AAPL", 0.9, 8) + burst("XOM", -0.9, 8)
    a, b = service(sigs), service(list(reversed(sigs)))
    assert a.timeline(a.default_params()).model_dump_json() == b.timeline(b.default_params()).model_dump_json()
    assert a.timeline(a.default_params()).model_dump_json() == a.timeline(a.default_params()).model_dump_json()


def test_future_reports_never_change_an_earlier_cycle():
    """Point-in-time: add reports that arrive later and every cycle before them is byte-identical."""
    early = burst("AAPL", 0.9, 6) + burst("XOM", -0.9, 6)
    late = burst("AAPL", -1.0, 10, start=60.0, prefix="late")
    short = service(early, as_of_hours=96)
    long = service(early + late, as_of_hours=96)
    a, b = short.timeline(short.default_params()), long.timeline(long.default_params())
    cut = next(c.at for c in b.cycles if c.at >= BASE.replace() and c.index >= 0 and (c.at - BASE).total_seconds() / 3600 >= 60)
    for ca, cb in zip(a.cycles, b.cycles, strict=False):
        if ca.at < cut:
            assert ca.weights == cb.weights and ca.scores == cb.scores


def test_reasons_are_named_and_checked():
    svc = service(burst("AAPL", 1.0, 20) + burst("JPM", -1.0, 20), as_of_hours=120)
    p = svc.resolve_params(tilt=6.0, max_turnover=0.25)
    last = svc.cycle(len(svc.grid()) - 1, p)
    r = {n.ticker: n.reason for n in last.names}
    assert r["AAPL"] in (WeightReason.AT_UPPER_BOUND, WeightReason.TILT_UP) and r["JPM"] in (WeightReason.AT_LOWER_BOUND, WeightReason.TILT_DOWN)
    assert r["MSFT"] in (WeightReason.NO_EVIDENCE, WeightReason.NO_CLEAR_SENTIMENT, WeightReason.TILT_UP, WeightReason.TILT_DOWN)
    capped = svc.cycle(3, svc.resolve_params(tilt=6.0, max_turnover=0.002))
    assert WeightReason.LIMITED_BY_TURNOVER in {n.reason for n in capped.names} or capped.status != "LIMITED_BY_TURNOVER"


def test_the_drivers_of_a_name_add_up_to_its_score_and_name_real_reports():
    sigs = burst("AAPL", 0.6, 4)
    svc = service(sigs)
    d = svc.cycle(len(svc.grid()) - 1, svc.default_params())
    aapl = next(n for n in d.names if n.ticker == "AAPL")
    assert sum(x.contribution for x in d.drivers["AAPL"]) == pytest.approx(aapl.score, abs=1e-12)
    assert {x.signal_id for x in d.drivers["AAPL"]} <= {s.id for s in sigs}


def test_a_cycle_that_does_not_exist_is_a_lookup_error():
    svc = service(burst("AAPL", 0.5))
    with pytest.raises(LookupError):
        svc.cycle(10_000, svc.default_params())
    with pytest.raises(LookupError, match="no cycles"):
        service([]).cycle(0, service([]).default_params())


@pytest.mark.parametrize("kw", [dict(tilt=-1), dict(tilt=99), dict(half_life_hours=0.1), dict(half_life_hours=9999), dict(max_turnover=0), dict(max_turnover=0.9)])
def test_a_parameter_outside_its_limits_is_refused(kw):
    with pytest.raises(ValueError):
        service([]).resolve_params(**kw)


def test_overriding_a_parameter_is_labelled_as_a_what_if():
    svc = service([])
    assert svc.resolve_params().is_default is True
    assert svc.resolve_params(tilt=3.0).is_default is False
    assert svc.resolve_params(tilt=svc.cfg.tilt.strength).is_default is True


def test_live_reports_count_only_when_asked_and_pasted_text_never():
    base = burst("AAPL", 0.5, 3)
    live = [sig("lv1", "MSFT", 1.0, hours=100, source="LiveWire")]
    svc = service(base, live=live, as_of_hours=96)
    off = svc.timeline(svc.default_params(), include_live=False)
    on = svc.timeline(svc.default_params(), include_live=True)
    assert off.reports_used == 3 and on.reports_used == 4
    assert on.cycles[-1].at > off.cycles[-1].at
    assert on.cycles[-1].weights[on.tickers.index("MSFT")] > off.cycles[-1].weights[off.tickers.index("MSFT")]


def test_the_curve_is_monotone_and_crosses_the_benchmark_at_zero():
    c = service([]).curve(2.0)
    t = [p["target"] for p in c]
    assert t == sorted(t) and c[10]["score"] == 0.0 and c[10]["target"] == pytest.approx(cfg().benchmark_weight)
    assert max(p["bounded"] for p in c) <= HI + 1e-9 and min(p["bounded"] for p in c) >= LO - 1e-9


def test_a_universe_ticker_the_entity_master_lacks_is_a_loud_error():
    from eventshock.rebalancer.service import RebalancerService
    from tests.rebalancer_helpers import repo
    with pytest.raises(ValueError, match="entity master"):
        RebalancerService(cfg(), signals=repo([]), entities=lambda: [])
