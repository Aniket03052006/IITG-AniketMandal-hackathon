"""Resolving what a user typed: validation, normalisation, labelled defaults, determinism."""

from __future__ import annotations

import pytest

from eventshock.domain import AssetClass
from eventshock.portfolio.models import EntryMode, FieldSource, HoldingInput, IssueLevel, PortfolioInput
from tests.portfolio_helpers import NOW, make_resolver, weights

R = make_resolver()


def res(inp: PortfolioInput):
    return R.resolve(inp, portfolio_id="pf_test", as_of=NOW)


def codes(r, level=None) -> set[str]:
    return {i.code for i in r.issues if level is None or i.level is level}


def test_the_brief_example_resolves_with_sources_and_weights() -> None:
    r = res(weights({"AAPL": 20, "JPM": 15, "MSFT": 15, "TLT": 25, "CASH": 25}))
    assert r.ok and r.total_value == 1_000_000 and codes(r, IssueLevel.ERROR) == set()
    by = {h.ticker: h for h in r.holdings}
    assert by["JPM"].value == pytest.approx(150_000) and by["JPM"].weight == pytest.approx(0.15)
    assert by["TLT"].asset_class is AssetClass.BOND and by["TLT"].duration == 17.0 and by["TLT"].spread_sensitivity == 0.0
    assert by["TLT"].sources["duration"] is FieldSource.REFERENCE
    assert by["CASH"].asset_class is AssetClass.CASH and by["CASH"].sector == "Cash"
    assert by["AAPL"].in_universe and by["AAPL"].beta == pytest.approx(1.2) and by["AAPL"].sources["beta"] is FieldSource.REFERENCE
    assert sum(h.weight for h in r.holdings) == pytest.approx(1.0)
    assert r.portfolio is not None and r.portfolio.total_value == pytest.approx(1_000_000)
    assert {a.entity_id for a in r.portfolio.assets} >= {"ENT_AAPL", "ENT_JPM", "USER_TLT"}


def test_a_negative_trailing_beta_is_clipped_at_zero_and_says_so() -> None:
    r = res(weights({"XOM": 100}))
    h = r.holdings[0]
    assert h.beta == 0.0 and "clipped" in " ".join(h.basis)


def test_weights_within_rounding_are_rescaled_and_noted() -> None:
    r = res(weights({"AAPL": 33.4, "JPM": 33.3, "MSFT": 33.0}))  # 99.7
    assert r.ok and "WEIGHTS_RESCALED" in codes(r, IssueLevel.INFO)
    assert sum(h.weight for h in r.holdings) == pytest.approx(1.0)


def test_short_weights_need_an_explicit_cash_remainder() -> None:
    bad = res(weights({"AAPL": 60, "JPM": 30}))
    assert not bad.ok and "WEIGHTS_SUM" in codes(bad, IssueLevel.ERROR) and bad.portfolio is None
    ok = res(weights({"AAPL": 60, "JPM": 30}, remainder_as_cash=True))
    assert ok.ok and "REMAINDER_CASH" in codes(ok, IssueLevel.INFO)
    cash = next(h for h in ok.holdings if h.asset_class is AssetClass.CASH)
    assert cash.value == pytest.approx(100_000) and sum(h.weight for h in ok.holdings) == pytest.approx(1.0)


def test_weights_above_one_hundred_are_always_an_error() -> None:
    r = res(weights({"AAPL": 70, "JPM": 50}, remainder_as_cash=True))
    assert not r.ok and "WEIGHTS_SUM" in codes(r, IssueLevel.ERROR)


def test_duplicates_nonpositive_and_missing_values_are_errors() -> None:
    assert "DUPLICATE_TICKER" in codes(res(PortfolioInput(name="t", holdings=[HoldingInput(ticker="AAPL", weight_pct=50), HoldingInput(ticker="aapl", weight_pct=50)])))
    assert "INVALID_WEIGHT" in codes(res(weights({"AAPL": 100, "JPM": -5})))
    assert "MISSING_WEIGHT" in codes(res(PortfolioInput(name="t", holdings=[HoldingInput(ticker="AAPL")])))
    assert "INVALID_TICKER" in codes(res(weights({"AA PL!": 100})))
    assert "NO_HOLDINGS" in codes(res(PortfolioInput(name="t", holdings=[])))
    assert "NAME_REQUIRED" in codes(res(weights({"AAPL": 100}, name="  ")))
    assert "BAD_TOTAL" in codes(res(weights({"AAPL": 100}, total_value=-5)))


def test_quantity_mode_values_and_missing_price() -> None:
    inp = PortfolioInput(name="q", mode=EntryMode.QUANTITY, holdings=[
        HoldingInput(ticker="AAPL", quantity=100, price=190, cost_basis=150), HoldingInput(ticker="CASH", quantity=5000)])
    r = res(inp)
    assert r.ok and r.total_value == pytest.approx(24_000)
    aapl = next(h for h in r.holdings if h.ticker == "AAPL")
    assert aapl.value == pytest.approx(19_000) and aapl.unrealised_pnl == pytest.approx(4_000) and aapl.weight == pytest.approx(19 / 24)
    missing = res(PortfolioInput(name="q", mode=EntryMode.QUANTITY, holdings=[HoldingInput(ticker="AAPL", quantity=10)]))
    assert not missing.ok and "MISSING_PRICE" in codes(missing, IssueLevel.ERROR)
    assert "INVALID_QUANTITY" in codes(res(PortfolioInput(name="q", mode=EntryMode.QUANTITY, holdings=[HoldingInput(ticker="AAPL", quantity=0, price=1)])))


def test_unknown_ticker_is_allowed_but_labelled() -> None:
    r = res(weights({"ZZZZ": 50, "AAPL": 50}))
    z = next(h for h in r.holdings if h.ticker == "ZZZZ")
    assert r.ok and "UNKNOWN_TICKER" in codes(r, IssueLevel.WARNING)
    assert not z.in_universe and z.beta == 1.0 and z.sources["beta"] is FieldSource.DEFAULT_ASSUMPTION and z.sector == "Other"
    assert r.portfolio is not None and next(a for a in r.portfolio.assets if a.name == "ZZZZ").entity_id == "USER_ZZZZ"


def test_sector_aliases_and_unknown_sectors() -> None:
    a = res(PortfolioInput(name="s", holdings=[HoldingInput(ticker="ZZZZ", weight_pct=100, sector="tech")]))
    assert a.holdings[0].sector == "Technology" and "UNKNOWN_SECTOR" not in codes(a)
    b = res(PortfolioInput(name="s", holdings=[HoldingInput(ticker="ZZZZ", weight_pct=100, sector="Aerospace")]))
    assert b.ok and b.holdings[0].sector == "Aerospace" and "UNKNOWN_SECTOR" in codes(b, IssueLevel.WARNING)


def test_bonds_need_duration_unless_a_reference_has_one() -> None:
    bad = res(PortfolioInput(name="b", holdings=[HoldingInput(ticker="XBOND", weight_pct=100, asset_class="BOND")]))
    assert not bad.ok and "MISSING_DURATION" in codes(bad, IssueLevel.ERROR)
    ok = res(PortfolioInput(name="b", holdings=[HoldingInput(ticker="XBOND", weight_pct=100, asset_class="BOND", duration=5.0)]))
    assert ok.ok and ok.holdings[0].spread_sensitivity == 1.0 and ok.holdings[0].sources["spread_sensitivity"] is FieldSource.DEFAULT_ASSUMPTION
    assert "DURATION_RANGE" in codes(res(PortfolioInput(name="b", holdings=[HoldingInput(ticker="XBOND", weight_pct=100, asset_class="BOND", duration=45)])))


def test_a_bond_of_a_known_issuer_binds_to_that_issuer() -> None:
    r = res(PortfolioInput(name="b", holdings=[HoldingInput(ticker="AAPL", weight_pct=100, asset_class="BOND", duration=4.0)]))
    assert r.portfolio is not None and r.portfolio.assets[0].entity_id == "ENT_AAPL" and r.portfolio.assets[0].asset_type is AssetClass.BOND


def test_unsupported_instruments_are_held_unstressed_and_flagged() -> None:
    r = res(weights({"GLD": 20, "AAPL": 80}))
    gld = next(h for h in r.holdings if h.ticker == "GLD")
    assert gld.asset_class is AssetClass.OTHER and "NOT_STRESSED" in codes(r, IssueLevel.WARNING)


def test_other_currency_is_flagged_not_converted() -> None:
    r = res(PortfolioInput(name="c", base_currency="INR", holdings=[HoldingInput(ticker="ZZZZ", weight_pct=100, currency="USD")]))
    assert r.ok and "FX_NOT_MODELLED" in codes(r, IssueLevel.WARNING) and r.base_currency == "INR"


def test_resolution_is_deterministic() -> None:
    inp = weights({"AAPL": 20, "JPM": 15, "MSFT": 15, "TLT": 25, "CASH": 25})
    a, b = res(inp), res(inp)
    assert a.portfolio is not None and b.portfolio is not None and a.portfolio.content_hash() == b.portfolio.content_hash()
    assert a.model_dump_json() == b.model_dump_json()


@pytest.mark.parametrize("text,mode", [("AAPL 20%\nJPM 15%\nMSFT 15%\nTLT 25%\nCash 25%", EntryMode.WEIGHT),
                                       ("AAPL 100 @ 190\nJPM 50 x 210.5\nCash 5,000", EntryMode.QUANTITY),
                                       ("# my book\nAAPL: 60%\nJPM, 40%  # core", EntryMode.WEIGHT)])
def test_quick_text_is_parsed_and_resolved(text: str, mode: EntryMode) -> None:
    p = R.parse_quick(text, name="q", base_currency="USD", as_of=NOW)
    assert p.draft is not None and p.draft.mode is mode and p.resolved is not None and p.resolved.ok, p.issues


def test_quick_text_rejects_mixed_and_unreadable_lines() -> None:
    mixed = R.parse_quick("AAPL 20%\nJPM 100 @ 200", name="q", base_currency="USD", as_of=NOW)
    assert mixed.draft is None and "MIXED_MODES" in {i.code for i in mixed.issues}
    bad = R.parse_quick("AAPL lots", name="q", base_currency="USD", as_of=NOW)
    assert bad.draft is None and "UNREADABLE_LINE" in {i.code for i in bad.issues}
    assert R.parse_quick("   \n# nothing", name="q", base_currency="USD", as_of=NOW).draft is None


def test_quick_weights_that_do_not_sum_show_the_error_at_once() -> None:
    p = R.parse_quick("AAPL 20%\nJPM 15%", name="q", base_currency="USD", as_of=NOW)
    assert p.draft is not None and p.resolved is not None and not p.resolved.ok and "WEIGHTS_SUM" in codes(p.resolved)
