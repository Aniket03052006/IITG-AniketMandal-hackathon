"""Event -> scope -> risk factor -> holdings: every kind of subject, direct / indirect / zero / overlapping exposure, abstention, observed vs assumed."""

from __future__ import annotations

import pytest

from eventshock.domain import AssetClass, EventCategory
from eventshock.intelligence.model import Availability
from eventshock.propagation.models import MappingBasis, Status
from tests.intel_helpers import JPM, XOM
from tests.prop_helpers import APPLE, asset, book, mapped

TOTAL = book().total_value


def held(g, *ids):
    return {h.asset_id for h in g.reached} >= set(ids)


def by_id(g):
    return {h.asset_id: h for h in g.reached}


class TestSubjects:
    def test_company_event_reaches_the_issuer_directly_and_its_sector_by_read_across(self):
        s, g = mapped("JPMorgan Chase fined over compliance failures", entity=JPM, category=None)
        h = by_id(g)
        assert h["jpm_eq"].basis is MappingBasis.DIRECT_FACT and h["jpm_bd"].basis is MappingBasis.DIRECT_FACT
        assert h["gs_eq"].basis is MappingBasis.EVIDENCED_SCOPE  # a sector peer, not the issuer
        assert g.direct_share == pytest.approx(300_000 / TOTAL)
        assert g.indirect_share == pytest.approx(g.reached_share - g.direct_share)
        assert g.mapping_basis is MappingBasis.DIRECT_FACT
        assert "United States" not in " ".join(g.not_reached)  # a company's country is not a separate claim

    def test_sector_event_has_no_direct_exposure(self):
        _, g = mapped("Regional banks face tougher capital rules", category=None)
        assert g.direct_share == 0 and g.reached_share > 0
        assert {h.sector for h in g.reached} == {"Financials"}
        assert all(h.basis is MappingBasis.EVIDENCED_SCOPE for h in g.reached)

    def test_industry_event_is_reached_by_industry_when_held(self):
        # JPM and GS are Banks in the ticker map: an event about banks reaches them by INDUSTRY and the sector above
        _, g = mapped("Investment banks warn on trading revenue", category=None)
        assert any(r.startswith("industry:Banks") for h in g.reached for r in h.routes)
        assert {n.kind for n in g.nodes} >= {"INDUSTRY", "SECTOR"}

    def test_industry_not_held_is_reported_not_guessed(self):
        _, g = mapped("Semiconductor makers warn of weak demand", category=None)
        assert any("Semiconductors" in x for x in g.not_reached)
        assert not any(r == "industry:Semiconductors" for h in g.reached for r in h.routes)

    def test_macro_event_reaches_holdings_through_risk_factors(self):
        s, g = mapped("Fed signals another rate hike as inflation stays high", category=EventCategory.MACROECONOMIC)
        ids = {f.id for f in g.active_factors}
        assert {"RATES", "INFLATION"} <= ids
        assert all(f.status is Status.OBSERVED for f in g.active_factors if f.id in ("RATES", "INFLATION"))  # the text uses their vocabulary
        assert held(g, "jpm_bd", "ust_bd", "msft_eq")  # bonds by duration, equities, technology by the sector edge
        assert g.direct_share == 0

    def test_geography_event_reports_regions_without_holdings(self):
        _, g = mapped("Sanctions on Russia disrupt trade across Ukraine", category=EventCategory.GEOPOLITICAL)
        assert any("Russia" in x for x in g.not_reached)
        assert "GEOPOLITICAL" in {f.id for f in g.active_factors}

    def test_region_the_book_holds_is_reached(self):
        _, g = mapped("Bank of England signals a pause as British gilts rally", category=None)
        assert "bp_eq" in by_id(g) and any(r.startswith("region:GB") for r in by_id(g)["bp_eq"].routes)

    def test_risk_factor_event_quotes_its_evidence(self):
        s, g = mapped("Oil supply disruption as OPEC cuts output", category=None)
        oil = next(f for f in g.active_factors if f.id == "OIL_ENERGY")
        assert oil.origin == "TEXT" and oil.status is Status.OBSERVED
        assert any("“oil”" in e or "“opec”" in e.lower() for e in oil.evidence)
        assert {"xom_eq", "xom_ln"} <= set(by_id(g))  # Energy, by the sector edge or the scope

    def test_unresolved_event_with_no_class_abstains(self):
        _, g = mapped("Quarterly update posted", category=None)
        assert g.availability is Availability.ABSTAINED and g.reached == []
        assert "does not guess" in (g.reason or "")

    def test_unresolved_event_with_a_class_uses_only_the_class_assumption(self):
        _, g = mapped("Quarterly update posted", category=EventCategory.MACROECONOMIC)
        assert g.availability is Availability.AVAILABLE
        assert all(f.origin == "CATEGORY" and f.status is Status.SCENARIO_ASSUMPTION for f in g.active_factors)
        assert g.evidenced_share <= g.reached_share


class TestExposure:
    def test_zero_exposure_is_available_with_a_reason(self):
        pf = book(only=["msft_eq", "aapl_eq"])  # nothing in Energy
        _, g = mapped("Exxon Mobil faces a drilling ban", entity=XOM, category=None, portfolio=pf)
        assert g.direct_share == 0
        assert g.reached_share >= 0
        pf2 = book(only=["ust_bd", "cash"])
        _, g2 = mapped("Regional banks face tougher capital rules", category=None, portfolio=pf2)
        assert g2.reached == [] and g2.reached_share == 0 and g2.availability is Availability.AVAILABLE
        assert "holds nothing" in (g2.reason or "")

    def test_a_holding_reached_by_several_routes_is_counted_once(self):
        _, g = mapped("Fed signals another rate hike as inflation stays high", category=EventCategory.MACROECONOMIC)
        hs = by_id(g)
        assert len(hs) == len(g.reached)
        assert len(hs["jpm_bd"].routes) >= 2  # bond duration for rates and for credit spreads, and the financials edge
        assert g.reached_value == pytest.approx(sum(h.market_value for h in g.reached))
        assert g.reached_value <= TOTAL

    def test_cash_is_never_reached(self):
        _, g = mapped("Fed signals another rate hike as inflation stays high", category=EventCategory.MACROECONOMIC)
        assert "cash" not in by_id(g)

    def test_shares_split_direct_evidenced_and_assumed(self):
        _, g = mapped("JPMorgan Chase fined over compliance failures", entity=JPM, category=EventCategory.GEOPOLITICAL)
        assert g.direct_share > 0 and g.evidenced_share >= g.direct_share
        assert g.assumed_share > 0  # the geopolitical class assumption reaches more
        assert g.evidenced_share + g.assumed_share == pytest.approx(g.reached_share)

    def test_unclassified_holding_has_no_industry(self):
        _, g = mapped("Apple recalls a product line", entity=APPLE, category=None)
        assert by_id(g)["aapl_eq"].industry is None and by_id(g)["msft_eq"].industry == "Software and Cloud"


class TestStatus:
    def test_structural_edges_are_observed_and_table_edges_are_assumptions(self):
        _, g = mapped("Fed signals another rate hike as inflation stays high", category=EventCategory.MACROECONOMIC)
        edge = {e.rule_id: e for e in g.edges}
        assert edge["risk_factors.RATES.transmission.bonds_duration"].status is Status.OBSERVED  # the engine's own duration formula
        assert edge["risk_factors.RATES.transmission.tech_long_duration"].status is Status.SCENARIO_ASSUMPTION
        assert edge["risk_factors.RATES.transmission.tech_long_duration"].weight == 0.5

    def test_every_edge_carries_a_rule_a_basis_and_a_status(self):
        _, g = mapped("Oil supply disruption as OPEC cuts output", category=None)
        assert g.edges and all(e.rule_id and e.basis and e.status for e in g.edges)
        assert {n.kind for n in g.nodes} >= {"EVENT", "PORTFOLIO", "RISK_FACTOR", "POSITION"}

    def test_user_adjusted_edge_is_labelled_a_user_assumption(self):
        ov = {"propagation.risk_factors.RATES.transmission.tech_long_duration.weight": 0.9}
        from eventshock.config import REPO_ROOT
        from eventshock.propagation.config import load_propagation_config
        cfg = load_propagation_config(REPO_ROOT / "configs", {"risk_factors.RATES.transmission.tech_long_duration.weight": 0.9})
        _, g = mapped("Fed signals another rate hike as inflation stays high", category=EventCategory.MACROECONOMIC, cfg=cfg, overrides=ov)
        e = next(e for e in g.edges if e.rule_id.endswith("tech_long_duration"))
        assert e.status is Status.USER_ASSUMPTION and e.weight == 0.9

    def test_a_disabled_edge_is_not_followed(self):
        from eventshock.config import REPO_ROOT
        from eventshock.propagation.config import load_propagation_config
        cfg = load_propagation_config(REPO_ROOT / "configs", {"risk_factors.RATES.transmission.bonds_duration.enabled": False})
        _, g = mapped("Fed signals another rate hike as inflation stays high", category=EventCategory.MACROECONOMIC, cfg=cfg)
        assert not any(e.rule_id.endswith("RATES.transmission.bonds_duration") for e in g.edges)

    def test_labels_say_it_is_not_causal(self):
        _, g = mapped("Oil supply disruption as OPEC cuts output", category=None)
        assert any("not causal inference" in x for x in g.labels)

    def test_mapping_is_deterministic(self):
        a = mapped("Oil supply disruption as OPEC cuts output", category=None)[1]
        b = mapped("Oil supply disruption as OPEC cuts output", category=None)[1]
        assert a.model_dump_json() == b.model_dump_json()


def test_an_extra_asset_class_is_handled():
    pf = book([asset("der", "ENT_MSFT", "Technology", 10_000, AssetClass.DERIVATIVE, delta=0.5)])
    _, g = mapped("Fed signals another rate hike as inflation stays high", category=EventCategory.MACROECONOMIC, portfolio=pf)
    assert "der" in by_id(g)
