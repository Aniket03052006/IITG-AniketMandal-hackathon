"""Manual adjustment of the side-cars: the overrides file, the whitelist, validation through the real config models, apply / reset / roll back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eventshock.adjust.registry import spec_for, validate_path_value
from eventshock.adjust.service import AdjustmentService, build_effective
from eventshock.adjust.store import SCHEMA, OverridesStore
from eventshock.config import REPO_ROOT, ConfigError, Settings, load_scenarios, load_taxonomy
from eventshock.config_overrides import apply_overrides, strip_prefix
from eventshock.intelligence.config import load_intelligence_config
from eventshock.portfolio.config import load_portfolio_config

CONFIGS = REPO_ROOT / "configs"
EDGE = {"kind": "SECTOR", "key": "Healthcare", "weight": 0.3, "enabled": True, "shock": True, "rationale": "my own view"}


def make(tmp_path: Path, on_change=None) -> AdjustmentService:  # noqa: ANN001
    s = Settings(config_dir=CONFIGS)
    _, scenarios = load_scenarios(s)
    return AdjustmentService(CONFIGS, OverridesStore(tmp_path / "o.json"), scenarios, {c.id: c.default_scenario for c in load_taxonomy(s).categories}, on_change=on_change)


class TestApplyOverrides:
    def test_sets_a_nested_leaf_and_leaves_the_input_alone(self):
        raw = {"a": {"b": 1, "c": {"d": 2}}}
        out = apply_overrides(raw, {"a.c.d": 5, "a.new": "x"})
        assert out == {"a": {"b": 1, "c": {"d": 5}, "new": "x"}} and raw == {"a": {"b": 1, "c": {"d": 2}}}

    def test_a_missing_intermediate_key_is_an_error(self):
        with pytest.raises(ConfigError, match="does not exist"):
            apply_overrides({"a": {}}, {"a.zz.b": 1})

    def test_none_removes_the_key(self):
        assert apply_overrides({"a": {"b": 1, "c": 2}}, {"a.b": None}) == {"a": {"c": 2}}

    def test_strip_prefix(self):
        assert strip_prefix({"intelligence.x.y": 1, "portfolio.z": 2}, "intelligence") == {"x.y": 1}


class TestStore:
    def test_round_trip_and_atomic_write(self, tmp_path):
        st = OverridesStore(tmp_path / "d" / "o.json")
        assert st.values() == {} and st.version() == "default"
        st.replace({"propagation.generation.min_severity": 8})
        assert OverridesStore(tmp_path / "d" / "o.json").values() == {"propagation.generation.min_severity": 8}
        assert [p.name for p in (tmp_path / "d").iterdir()] == ["o.json"]  # no temp file left behind
        assert json.loads((tmp_path / "d" / "o.json").read_text())["schema"] == SCHEMA

    def test_emptying_removes_the_file(self, tmp_path):
        st = OverridesStore(tmp_path / "o.json")
        st.replace({"a.b": 1})
        st.replace({})
        assert not (tmp_path / "o.json").exists() and st.version() == "default"

    def test_a_corrupt_file_stops_start_up_with_a_clear_message(self, tmp_path):
        (tmp_path / "o.json").write_text("{not json")
        with pytest.raises(ConfigError, match="adjustments file"):
            OverridesStore(tmp_path / "o.json")

    def test_a_file_of_another_schema_is_refused(self, tmp_path):
        (tmp_path / "o.json").write_text(json.dumps({"schema": "other", "values": {}}))
        with pytest.raises(ConfigError, match="not an overrides-v1 file"):
            OverridesStore(tmp_path / "o.json")

    def test_version_changes_with_the_values(self, tmp_path):
        st = OverridesStore(tmp_path / "o.json")
        st.replace({"a.b": 1})
        v1 = st.version()
        st.replace({"a.b": 2})
        assert st.version() not in (v1, "default")


class TestWhitelist:
    DEFAULTS = None

    @pytest.fixture(autouse=True)
    def _defaults(self, tmp_path):
        self.svc = make(tmp_path)

    def check(self, path, value):
        return validate_path_value(path, value, self.svc._defaults, self.svc._shock_bounds)  # noqa: SLF001

    def test_a_value_inside_its_bounds_is_accepted(self):
        assert self.check("propagation.generation.min_severity", 8) is None
        assert self.check("intelligence.grouping.window_hours", 24) is None
        assert self.check("portfolio.relevance_bands.high_share", 0.3) is None
        assert self.check("propagation.materiality.grid.LOW.CRITICAL", "HIGH") is None

    @pytest.mark.parametrize(("path", "value"), [
        ("propagation.generation.min_severity", 11), ("propagation.generation.min_severity", "high"), ("propagation.generation.min_severity", True),
        ("propagation.generation.max_propagated_sectors", 2.5), ("propagation.generation.downside_only", "yes"),
        ("propagation.materiality.grid.LOW.LOW", "EXTREME"), ("propagation.risk_factors.RATES.transmission.bonds_duration.weight", 2),
        ("intelligence.grouping.window_hours", 0), ("intelligence.sources.authoritative_domains", "sec.gov"),
        ("propagation.generation.min_severity", float("nan"))])
    def test_a_value_outside_its_type_or_bounds_is_refused_with_a_reason(self, path, value):
        assert self.check(path, value)

    @pytest.mark.parametrize("path", ["propagation.version", "intelligence.claims.axes.deal.pos", "scenarios.scenarios", "severity.anchors", "models.event.path", "x"])
    def test_what_is_not_listed_cannot_be_adjusted(self, path):
        assert self.check(path, 1) == "this setting is not adjustable"

    def test_a_listed_pattern_over_a_missing_key_is_refused(self):
        assert self.check("propagation.risk_factors.RATES.transmission.nope.weight", 0.1) == "no such setting"

    def test_a_new_ticker_can_be_added_but_a_new_threshold_cannot(self):
        assert self.check("intelligence.scope.ticker_industry.ZZZZ", "Banks") is None
        assert self.check("intelligence.grouping.brand_new", 1) == "this setting is not adjustable"

    def test_user_edge_is_validated_as_an_edge(self):
        assert self.check("propagation.risk_factors.OIL_ENERGY.transmission.user_health", EDGE) is None
        assert "not a valid transmission edge" in self.check("propagation.risk_factors.OIL_ENERGY.transmission.user_health", {**EDGE, "weight": 5})
        assert "unknown risk factor" in self.check("propagation.risk_factors.NOPE.transmission.user_a", EDGE)

    def test_scenario_shock_sizes_have_per_factor_bounds(self):
        paths = [k.path for k in self.svc.state().knobs if ".shock_overrides." in k.path]
        assert paths
        eq = next(p for p in paths if p.endswith("EQUITY:MARKET"))
        assert self.check(eq, -0.2) is None and self.check(eq, -3) is not None

    def test_spec_lookup(self):
        assert spec_for("propagation.concentration.min_share").group == "relevance"
        assert spec_for("intelligence.lifecycle.stale_after_hours").group == "intelligence"
        assert spec_for("propagation.risk_factors.RATES.transmission.bonds_duration.weight").group == "mapping"
        assert spec_for("propagation.generation.min_severity").group == "scenario"


class TestService:
    def test_state_lists_every_group_with_defaults(self, tmp_path):
        st = make(tmp_path).state()
        assert st.count == 0 and st.version == "default" and not any(k.adjusted for k in st.knobs)
        assert {k.group for k in st.knobs} == {"scenario", "relevance", "mapping", "intelligence"}
        k = next(k for k in st.knobs if k.path == "propagation.generation.min_severity")
        assert (k.default, k.value, k.min, k.max, k.kind) == (7.0, 7.0, 1, 10, "number")
        assert any(k.path.startswith("intelligence.scope.ticker_industry.") for k in st.knobs)

    def test_put_persists_and_marks_the_value_adjusted(self, tmp_path):
        svc = make(tmp_path)
        assert svc.put({"propagation.generation.min_severity": 8}).ok
        k = next(k for k in svc.state().knobs if k.path == "propagation.generation.min_severity")
        assert k.adjusted and k.value == 8 and k.default == 7.0
        assert make(tmp_path).state().count == 1  # a new process reads the same file

    def test_a_value_equal_to_its_default_is_not_an_adjustment(self, tmp_path):
        svc = make(tmp_path)
        svc.put({"propagation.generation.min_severity": 8})
        svc.put({"propagation.generation.min_severity": 7})
        assert svc.state().count == 0 and svc.notice() is None

    def test_an_invalid_value_saves_nothing(self, tmp_path):
        svc = make(tmp_path)
        r = svc.put({"propagation.generation.min_severity": 99})
        assert not r.ok and r.issues[0].path == "propagation.generation.min_severity" and svc.state().count == 0

    def test_a_cross_field_violation_names_the_path_at_fault(self, tmp_path):
        svc = make(tmp_path)
        r = svc.validate({"propagation.materiality.exposure_bands.medium_share": 0.5, "propagation.generation.min_severity": 8})
        assert not r.ok and [i.path for i in r.issues] == ["propagation.materiality.exposure_bands.medium_share"]
        assert "medium_share < high_share" in r.issues[0].message and "[type=" not in r.issues[0].message

    def test_a_portfolio_band_that_crosses_is_refused(self, tmp_path):
        r = make(tmp_path).validate({"portfolio.relevance_bands.medium_share": 0.5})
        assert not r.ok and "below high_share" in r.issues[0].message

    def test_reset_one_and_all(self, tmp_path):
        svc = make(tmp_path)
        svc.put({"propagation.generation.min_severity": 8, "intelligence.grouping.window_hours": 24})
        svc.reset("propagation.generation.min_severity")
        assert [k.path for k in svc.state().knobs if k.adjusted] == ["intelligence.grouping.window_hours"]
        with pytest.raises(KeyError):
            svc.reset("propagation.generation.min_severity")
        svc.reset()
        assert svc.state().count == 0

    def test_on_change_receives_the_new_overrides(self, tmp_path):
        seen = []
        svc = make(tmp_path, on_change=seen.append)
        svc.put({"propagation.generation.min_severity": 8})
        svc.reset()
        assert seen == [{"propagation.generation.min_severity": 8}, {}]

    def test_a_failed_rebuild_rolls_the_file_back(self, tmp_path):
        calls = []

        def boom(ov):
            calls.append(dict(ov))
            if ov:
                raise ConfigError("cannot rebuild")
        svc = make(tmp_path, on_change=boom)
        with pytest.raises(ConfigError):
            svc.put({"propagation.generation.min_severity": 8})
        assert svc.state().count == 0 and OverridesStore(tmp_path / "o.json").values() == {}
        assert calls[-1] == {}  # the running state was put back too

    def test_an_added_edge_is_listed_and_can_be_removed(self, tmp_path):
        svc = make(tmp_path)
        assert svc.put({"propagation.risk_factors.OIL_ENERGY.transmission.user_health": EDGE}).ok
        st = svc.state()
        assert [(e.risk_factor, e.edge_id) for e in st.added_edges] == [("OIL_ENERGY", "user_health")]
        svc.reset("propagation.risk_factors.OIL_ENERGY.transmission.user_health")
        assert svc.state().added_edges == []


class TestEffectiveConfigs:
    def test_overrides_reach_all_three_configs(self):
        i, p, r = build_effective(CONFIGS, {"intelligence.grouping.window_hours": 12, "portfolio.relevance_bands.high_share": 0.3,
                                            "propagation.generation.min_severity": 5})
        assert i.grouping.window_hours == 12 and p.relevance_bands.high_share == 0.3 and r.generation.min_severity == 5
        assert p.band(0.25) == "MEDIUM"  # the adjusted band is what the feed uses

    def test_no_overrides_is_the_shipped_configuration(self):
        i, p, r = build_effective(CONFIGS, {})
        assert i == load_intelligence_config(CONFIGS) and p == load_portfolio_config(CONFIGS) and r.generation.min_severity == 7.0

    def test_a_new_ticker_industry_changes_the_vocabulary(self):
        i, _, _ = build_effective(CONFIGS, {"intelligence.scope.ticker_industry.AAPL": "Software and Cloud"})
        assert i.scope.ticker_industry["AAPL"] == "Software and Cloud"
        with pytest.raises(ConfigError):
            build_effective(CONFIGS, {"intelligence.scope.ticker_industry.AAPL": "Not An Industry"})
