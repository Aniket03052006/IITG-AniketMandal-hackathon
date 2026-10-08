"""The two-way table refuses to be anything but a regrouping of a total it can account for."""

from __future__ import annotations

import pytest

from eventshock.portfolio.crosstab import build_crosstab

E = [("Fin", "Financials", "EQUITY", "Equity", -30.0, "a"), ("Fin", "Financials", "BOND", "Bond", -10.0, "b"),
     ("Tech", "Technology", "EQUITY", "Equity", -5.0, "c"), ("Tech", "Technology", "EQUITY", "Equity", 2.0, "d")]


def test_cells_add_up_and_are_ordered_by_size() -> None:
    t = build_crosstab(E, unit="pnl", row_label="Sector", col_label="Factor", total=-43.0, largest_first=False)
    assert t.reconciled and t.sum == pytest.approx(-43.0) and abs(t.residual) < 1e-9
    assert [r.key for r in t.rows] == ["Fin", "Tech"] and [c.key for c in t.cols] == ["EQUITY", "BOND"]  # most negative first
    tech = next(c for c in t.cells if (c.row, c.col) == ("Tech", "EQUITY"))
    assert tech.value == pytest.approx(-3.0) and tech.position_count == 2  # two positions in one cell add


def test_a_table_that_does_not_add_up_raises_instead_of_being_drawn() -> None:
    with pytest.raises(ValueError, match="does not reconcile"):
        build_crosstab(E, unit="pnl", row_label="Sector", col_label="Factor", total=-40.0)


def test_zero_cells_are_left_out_and_largest_first_orders_by_value() -> None:
    t = build_crosstab([("a", "A", "x", "X", 5.0, "1"), ("a", "A", "y", "Y", 0.0, "2"), ("b", "B", "x", "X", 9.0, "3")], unit="market_value",
                       row_label="r", col_label="c", total=14.0)
    assert {(c.row, c.col) for c in t.cells} == {("a", "x"), ("b", "x")} and [r.key for r in t.rows] == ["b", "a"] and [c.key for c in t.cols] == ["x"]


def test_an_empty_table_for_an_empty_total_is_valid() -> None:
    t = build_crosstab([], unit="pnl", row_label="r", col_label="c", total=0.0)
    assert t.cells == [] and t.reconciled
