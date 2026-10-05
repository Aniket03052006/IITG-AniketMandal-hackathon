"""Relevance of an event to a portfolio: an explicit lookup with named rules, never a weighted score."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.domain import EventCategory
from eventshock.intelligence.model import Availability
from eventshock.propagation.config import PropagationConfig, load_propagation_config
from eventshock.propagation.models import MappingBasis
from tests.intel_helpers import JPM
from tests.prop_helpers import PROP_CFG, assessor, asset, book, mapped

MACRO = "Fed signals another rate hike as inflation stays high"


def rule(m, rid):
    return next(r for r in m.rules if r.id == rid)


def level(headline=MACRO, severity=8.0, **kw):
    s, g = mapped(headline, **kw)
    return assessor().assess(g, severity), g


class TestLookup:
    def test_grid_cell_and_components_are_returned(self):
        m, g = level(MACRO, 8.0, category=EventCategory.MACROECONOMIC)
        assert m.availability is Availability.AVAILABLE
        assert m.exposure_row == "VERY_HIGH" and m.severity_column == "HIGH"
        assert m.level_from_grid == PROP_CFG.materiality.grid["VERY_HIGH"]["HIGH"] == "CRITICAL"
        assert {c.id for c in m.components} >= {"severity", "reach", "direct", "indirect", "evidenced", "assumed", "concentration", "basis"}
        assert rule(m, "grid.VERY_HIGH.HIGH").fired
        assert m.why and m.reached_share == pytest.approx(g.reached_share)

    def test_a_low_severity_lowers_the_level_on_the_same_exposure(self):
        hi, _ = level(MACRO, 9.0, category=EventCategory.MACROECONOMIC)
        lo, _ = level(MACRO, 2.0, category=EventCategory.MACROECONOMIC)
        order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        assert order.index(lo.level) < order.index(hi.level)

    def test_level_never_falls_as_severity_rises(self):
        order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        seen = [order.index(level(MACRO, sev, category=EventCategory.MACROECONOMIC)[0].level) for sev in (1, 3, 4, 6, 7, 8, 9, 10)]
        assert seen == sorted(seen)

    def test_no_decomposition_is_a_hidden_weighted_sum(self):
        m, _ = level(MACRO, 8.0, category=EventCategory.MACROECONOMIC)
        assert all(r.kind in ("GRID", "BUMP", "CAP") for r in m.rules)
        assert not hasattr(m, "score")


class TestRules:
    def test_concentration_bump(self):
        # one big position is most of the reached part of the book
        pf = book(only=["jpm_eq", "gs_eq", "cash"])
        pf = pf.model_copy(update={"assets": [a.model_copy(update={"market_value": 900_000, "notional": 900_000}) if a.asset_id == "jpm_eq" else a for a in pf.assets]})
        s, g = mapped("Regional banks face tougher capital rules", category=None, portfolio=pf)
        m = assessor().assess(g, 4.5)
        assert rule(m, "concentration_bump").fired and m.level != m.level_from_grid

    def test_assumption_only_reach_is_capped(self):
        s, g = mapped("Quarterly update posted", category=EventCategory.GEOPOLITICAL)  # reached only by the class assumption
        assert g.evidenced_share <= g.reached_share and g.mapping_basis in (MappingBasis.ASSUMPTION_ONLY, MappingBasis.EVIDENCED_SCOPE)
        m = assessor().assess(g, 9.5)
        if g.evidenced_share == 0:
            assert rule(m, "assumption_only_cap").fired and m.level in ("LOW", "MEDIUM")

    def test_severity_not_assessed_is_read_from_the_medium_column_and_capped(self):
        m, _ = level(MACRO, None, category=EventCategory.MACROECONOMIC)
        assert m.severity_column is None and m.level in ("LOW", "MEDIUM")
        assert rule(m, "severity_unavailable_cap").fired or m.level_from_grid in ("LOW", "MEDIUM")
        assert next(c for c in m.components if c.id == "severity").display == "not assessed"

    def test_direct_holding_is_a_fact_basis(self):
        m, g = level("JPMorgan Chase fined over compliance failures", 8.0, entity=JPM, category=None)
        assert m.mapping_basis is MappingBasis.DIRECT_FACT and next(c for c in m.components if c.id == "direct").value == pytest.approx(g.direct_share)


class TestAssumedReachLimit:
    def test_a_small_evidenced_reach_is_not_lifted_to_critical_by_assumed_edges(self):
        # the text is about Energy (a small evidenced slice), the class assumption reaches far more of the book
        m, g = level("Oil supply disruption as OPEC cuts output", 8.0, category=EventCategory.GEOPOLITICAL)
        assert g.assumed_share > g.evidenced_share
        order = ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
        row_ev = PROP_CFG.exposure_row(g.evidenced_share)
        assert order.index(m.exposure_row) <= order.index(row_ev) + 1
        assert rule(m, "assumed_reach_limit").fired == (order.index(PROP_CFG.exposure_row(g.reached_share)) > order.index(row_ev) + 1)

    def test_the_limit_names_both_shares(self):
        m, g = level("Oil supply disruption as OPEC cuts output", 8.0, category=EventCategory.GEOPOLITICAL)
        text = rule(m, "assumed_reach_limit").effect
        assert f"{g.evidenced_share:.1%}" in text

    def test_a_fully_evidenced_reach_is_untouched(self):
        m, g = level(MACRO, 8.0, category=EventCategory.MACROECONOMIC)
        assert g.assumed_share <= 0.2 * g.reached_share or not rule(m, "assumed_reach_limit").fired


class TestStates:
    def test_zero_exposure_is_none_not_low(self):
        pf = book(only=["ust_bd", "cash"])
        m, _ = level("Regional banks face tougher capital rules", 9.0, category=None, portfolio=pf)
        assert m.level == "NONE" and m.availability is Availability.AVAILABLE and "not relevant" in m.summary.lower()

    def test_no_defensible_mapping_is_undetermined(self):
        m, _ = level("Quarterly update posted", 9.0, category=None)
        assert m.level == "UNDETERMINED" and m.availability is Availability.ABSTAINED

    def test_deterministic(self):
        a = level(MACRO, 8.0, category=EventCategory.MACROECONOMIC)[0]
        b = level(MACRO, 8.0, category=EventCategory.MACROECONOMIC)[0]
        assert a.model_dump_json() == b.model_dump_json()

    def test_a_larger_book_share_can_only_raise_relevance(self):
        small, _ = level("Regional banks face tougher capital rules", 7.5, category=None)
        extra = [asset("big", "ENT_GS", "Financials", 5_000_000)]
        big, _ = level("Regional banks face tougher capital rules", 7.5, category=None, portfolio=book(extra))
        order = ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
        assert order.index(big.level) >= order.index(small.level)


class TestConfigGuards:
    def test_a_grid_that_falls_with_severity_is_rejected(self):
        with pytest.raises(ConfigError):
            load_propagation_config(REPO_ROOT / "configs", {"materiality.grid.HIGH.CRITICAL": "LOW"})

    def test_bands_must_be_ordered(self):
        with pytest.raises(ConfigError):
            load_propagation_config(REPO_ROOT / "configs", {"materiality.exposure_bands.medium_share": 0.5})

    def test_unknown_key_is_refused(self):
        with pytest.raises(ConfigError):
            load_propagation_config(REPO_ROOT / "configs", {"materiality.nope": 1})

    def test_shipped_config_is_valid_and_labelled_a_prior(self):
        text = (REPO_ROOT / "configs" / "propagation.yaml").read_text()
        assert "JUDGEMENT PRIOR" in text and isinstance(PROP_CFG, PropagationConfig)
        with pytest.raises(ValidationError):
            PropagationConfig.model_validate({})
