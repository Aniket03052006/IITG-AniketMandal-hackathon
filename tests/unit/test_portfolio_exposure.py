"""Portfolio exposure: weights, groupings, concentration, beta and duration, checked by hand."""

from __future__ import annotations

import pytest

from eventshock.domain import AssetClass
from eventshock.portfolio.exposure import compute_exposure
from tests.helpers import make_asset, make_portfolio

PF = make_portfolio([
    make_asset(asset_id="e1", entity_id="E1", sector="Fin", market_value=400_000, notional=400_000, beta=1.5),
    make_asset(asset_id="e2", entity_id="E2", sector="Tech", market_value=200_000, notional=200_000, beta=0.5, geography="GB"),
    make_asset(asset_id="b1", entity_id="E1", sector="Fin", asset_type=AssetClass.BOND, duration=10.0, market_value=200_000, notional=200_000),
    make_asset(asset_id="c1", entity_id="CASH", sector="Cash", asset_type=AssetClass.CASH, market_value=100_000, notional=100_000),
    make_asset(asset_id="o1", entity_id="O1", sector="Other", asset_type=AssetClass.OTHER, market_value=100_000, notional=100_000),
])


def metric(d, key):
    return next(m.value for m in d.metrics if m.key == key)


def test_weights_and_groupings() -> None:
    d = compute_exposure(PF)
    assert d.total_value == 1_000_000 and d.position_count == 5
    assert {r.key: r.share for r in d.by_asset_class} == pytest.approx({"EQUITY": 0.6, "BOND": 0.2, "CASH": 0.1, "OTHER": 0.1})
    assert {r.key: r.share for r in d.by_sector}["Fin"] == pytest.approx(0.6)
    assert {r.key: r.share for r in d.by_region} == pytest.approx({"US": 0.8, "GB": 0.2})
    assert {r.key: r.share for r in d.by_issuer}["E1"] == pytest.approx(0.6)  # equity and bond of one issuer add
    assert "CASH" not in {r.key for r in d.by_issuer}  # cash is not an issuer
    assert [r.label for r in d.split] == ["Equities", "Bonds", "Cash", "Loans, derivatives & other"] or {r.key for r in d.split} == {"equity", "bonds", "cash", "other"}
    assert sum(r.share for r in d.by_sector) == pytest.approx(1.0)


def test_concentration() -> None:
    d = compute_exposure(PF)
    assert metric(d, "top_position") == pytest.approx(0.4) and metric(d, "top5_positions") == pytest.approx(1.0)
    hhi = 0.4**2 + 0.2**2 + 0.2**2 + 0.1**2 + 0.1**2
    assert metric(d, "hhi") == pytest.approx(hhi) and metric(d, "effective_n") == pytest.approx(1 / hhi)
    assert metric(d, "top_issuer") == pytest.approx(0.6)


def test_beta_and_duration_metrics() -> None:
    d = compute_exposure(PF)
    assert metric(d, "equity_beta") == pytest.approx((400 * 1.5 + 200 * 0.5) / 600)
    assert metric(d, "market_beta") == pytest.approx(0.4 * 1.5 + 0.2 * 0.5)
    assert metric(d, "bond_duration") == pytest.approx(10.0)
    assert metric(d, "dv01") == pytest.approx(-200_000 * 10 / 10_000)
    assert metric(d, "rates_100bp") == pytest.approx(-0.02)
    assert all(m.formula for m in d.metrics)


def test_unsupported_instruments_are_reported_not_hidden() -> None:
    d = compute_exposure(PF)
    assert [r.key for r in d.not_stressed] == ["o1"] and d.not_stressed[0].share == pytest.approx(0.1)
    assert any("cannot stress" in n for n in d.notes)


def test_all_cash_has_no_beta_or_duration_metric() -> None:
    d = compute_exposure(make_portfolio([make_asset(asset_id="c", asset_type=AssetClass.CASH, entity_id="CASH", sector="Cash")]))
    assert {m.key for m in d.metrics}.isdisjoint({"equity_beta", "market_beta", "bond_duration", "dv01"})
    assert d.largest_positions[0].weight == pytest.approx(1.0)
