"""Concentration: only meaningful concentration is flagged. Overlap: several independent events, one risk factor, the same holdings."""

from __future__ import annotations

from datetime import timedelta

import pytest

from eventshock.config import REPO_ROOT
from eventshock.domain import AssetClass, EventCategory
from eventshock.propagation.concentration import OverlapItem
from eventshock.propagation.config import load_propagation_config
from tests.prop_helpers import NOW, analyzer, asset, book, mapped

FED = "Fed signals another rate hike as inflation stays high"
RATE2 = "Treasury yields jump as the yield curve steepens on rate cut doubts"
MACRO = EventCategory.MACROECONOMIC


def dim(view, name):
    return next(d for d in view.dimensions if d.dimension == name)


class TestConcentration:
    def test_every_dimension_is_present(self):
        v = analyzer().view(book())
        assert [d.dimension for d in v.dimensions] == ["issuer", "sector", "industry", "geography", "asset_class", "risk_factor"]
        assert v.total_value == pytest.approx(book().total_value)

    def test_a_balanced_book_flags_nothing_in_issuers(self):
        pf = book([asset(f"x{i}", f"ENT_{i}", "Healthcare", 100_000) for i in range(10)])
        assert not any(r.flagged for r in dim(analyzer().view(pf), "issuer").rows)

    def test_one_dominant_issuer_is_flagged_with_the_equal_split_reason(self):
        pf = book([asset("big", "ENT_GS", "Financials", 5_000_000)])
        v = analyzer().view(pf)
        top = dim(v, "issuer").rows[0]
        assert top.key == "ENT_GS" and top.flagged and dim(v, "issuer").flagged
        assert any("Goldman" in f and "equal split" in f for f in v.flags)

    def test_a_dimension_with_two_items_is_never_flagged_by_the_multiple(self):
        d = dim(analyzer().view(book()), "geography")
        assert d.item_count == 2 and not any(r.flagged for r in d.rows) and "too few" in (d.reason or "")

    def test_cash_and_unclassified_are_never_flagged(self):
        pf = book([asset("cashbig", "ENT_CASH", "Cash", 9_000_000, AssetClass.CASH)])
        v = analyzer().view(pf)
        assert not next(r for r in dim(v, "asset_class").rows if r.key == "CASH").flagged
        pf2 = book([asset("u", "ENT_ZZ", "Healthcare", 9_000_000)])
        assert not next(r for r in dim(analyzer().view(pf2), "industry").rows if r.key == "Unclassified").flagged

    def test_risk_factor_reach_overlaps_and_is_not_a_partition(self):
        d = dim(analyzer().view(book()), "risk_factor")
        assert sum(r.share for r in d.rows) > 1.0 and d.hhi == 0.0 and "shares overlap" in (d.note or "")
        rates = next(r for r in d.rows if r.key == "RATES")
        assert rates.value > 0 and rates.position_count >= 3

    def test_government_bond_is_not_reached_by_credit_spreads(self):
        d = dim(analyzer().view(book(only=["ust_bd", "jpm_bd"])), "risk_factor")
        spread = next(r for r in d.rows if r.key == "CREDIT_SPREAD")
        assert spread.position_count == 1  # only the corporate bond: the Treasury has no spread sensitivity

    def test_a_book_of_a_few_classes_is_not_flagged_just_for_having_few(self):
        # four asset classes can never have a Herfindahl index below 0.25, so the bar scales with the number of items
        pf = book([asset("d", "ENT_MSFT", "Technology", 90_000, AssetClass.DERIVATIVE, delta=0.5)])
        d = dim(analyzer().view(pf), "asset_class")
        assert d.item_count == 5 and d.hhi >= 0.25
        balanced = book([asset("d", "ENT_MSFT", "Technology", 150_000, AssetClass.DERIVATIVE, delta=0.5)])
        assert not any("mix" in f and "Asset class" in f for f in analyzer().view(balanced).flags) or dim(analyzer().view(balanced), "asset_class").hhi >= 1.5 / 5

    def test_risk_factor_reach_is_informational_and_never_flagged(self):
        v = analyzer().view(book())
        assert not any(r.flagged for r in dim(v, "risk_factor").rows) and not dim(v, "risk_factor").flagged
        assert not any(f.startswith("Risk factor") for f in v.flags)

    def test_flags_use_plain_plurals(self):
        pf = book([asset("big", "ENT_GS", "Financials", 5_000_000)])
        assert not any("classs" in f or "sectorss" in f for f in analyzer().view(pf).flags)

    def test_thresholds_are_configurable(self):
        pf = book()
        base = analyzer().view(pf).flags
        cfg = load_propagation_config(REPO_ROOT / "configs", {"concentration.min_share": 0.9})
        assert len(analyzer(cfg).view(pf).flags) <= len(base)

    def test_deterministic(self):
        assert analyzer().view(book()).model_dump_json() == analyzer().view(book()).model_dump_json()


def item(sid, event, headline, portfolio, *, category=MACRO, severity=8.0, level_override=None, minutes=0):
    from eventshock.propagation.materiality import MaterialityAssessor
    from tests.prop_helpers import PROP_CFG
    s, g = mapped(headline, category=category, portfolio=portfolio)
    m = MaterialityAssessor(PROP_CFG).assess(g, severity)
    return OverlapItem(signal_id=sid, event_id=event, headline=headline, published_at=NOW - timedelta(minutes=minutes), materiality=level_override or m.level, severity=severity, graph=g)


class TestOverlap:
    def test_two_independent_events_on_the_same_factor_and_holdings_make_a_cluster(self):
        pf = book()
        v = analyzer().overlaps(pf, [item("a", "e1", FED, pf), item("b", "e2", RATE2, pf)])
        assert v.clusters, v.reason
        rates = next(c for c in v.clusters if c.risk_factor == "RATES")
        assert {e.event_id for e in rates.events} == {"e1", "e2"}
        assert rates.shared_share >= 0.05 and {h.asset_id for h in rates.shared_holdings} >= {"jpm_bd", "ust_bd"}
        assert "independent events" in rates.sentence and "concentrated" in rates.sentence

    def test_a_single_event_makes_no_cluster(self):
        pf = book()
        v = analyzer().overlaps(pf, [item("a", "e1", FED, pf)])
        assert v.clusters == [] and v.reason

    def test_two_reports_of_one_event_are_one_event(self):
        pf = book()
        v = analyzer().overlaps(pf, [item("a", "e1", FED, pf), item("a2", "e1", FED + " (second wire)", pf)])
        assert v.clusters == []

    def test_events_that_touch_different_holdings_do_not_overlap(self):
        pf = book()
        oil = item("o", "e3", "Oil supply disruption as OPEC cuts output", pf, category=None)
        banks = item("b", "e4", "Regional banks face tougher capital rules", pf, category=None)
        v = analyzer().overlaps(pf, [oil, banks])
        assert all(c.risk_factor not in ("OIL_ENERGY",) for c in v.clusters)

    def test_events_below_the_materiality_floor_are_ignored(self):
        pf = book()
        v = analyzer().overlaps(pf, [item("a", "e1", FED, pf), item("b", "e2", RATE2, pf, level_override="LOW")])
        assert v.clusters == []

    def test_min_events_and_overlap_share_are_configurable(self):
        pf = book()
        items = [item("a", "e1", FED, pf), item("b", "e2", RATE2, pf)]
        strict = load_propagation_config(REPO_ROOT / "configs", {"concentration.min_overlap_share": 0.99})
        assert analyzer(strict).overlaps(pf, items).clusters == []
        three = load_propagation_config(REPO_ROOT / "configs", {"concentration.min_events": 3})
        assert analyzer(three).overlaps(pf, items).clusters == []

    def test_an_event_class_that_merely_implies_a_factor_does_not_make_events_overlap(self):
        pf = book()
        # neither text mentions oil: OIL_ENERGY is only assumed from the class, so two such events do not "overlap" on it
        a = item("a", "e1", "Quarterly update posted", pf, category=EventCategory.GEOPOLITICAL, level_override="HIGH")
        b = item("b", "e2", "Another update posted", pf, category=EventCategory.GEOPOLITICAL, level_override="HIGH")
        v = analyzer().overlaps(pf, [a, b])
        assert not any(c.risk_factor == "OIL_ENERGY" for c in v.clusters)

    def test_events_whose_text_names_the_factor_do_overlap(self):
        pf = book()
        a = item("a", "e1", "Oil supply disruption as OPEC cuts output", pf, category=None)
        b = item("b", "e2", "Crude prices jump on pipeline outage", pf, category=None)
        v = analyzer().overlaps(pf, [a, b])
        assert any(c.risk_factor == "OIL_ENERGY" for c in v.clusters)

    def test_empty_input_is_an_answer_not_an_error(self):
        v = analyzer().overlaps(book(), [])
        assert v.clusters == [] and v.considered == 0
