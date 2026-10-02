from __future__ import annotations

import pytest

from eventshock.config import (
    ConfigError,
    Settings,
    StressConfig,
    load_app_config,
    load_scenarios,
    load_taxonomy,
)
from eventshock.domain import EventCategory
from eventshock.stress.scenarios import ScenarioCatalog
from tests.helpers import make_scenario


class TestShippedConfigs:
    def test_taxonomy_covers_all_categories(self, settings):
        tax = load_taxonomy(settings)
        assert {c.id for c in tax.categories} == set(EventCategory)

    def test_every_category_has_a_default_scenario_of_matching_category(self, settings):
        tax = load_taxonomy(settings)
        _, scenarios = load_scenarios(settings)
        ScenarioCatalog(scenarios, {c.id: c.default_scenario for c in tax.categories})

    def test_all_scenarios_are_labelled_illustrative(self, settings):
        _, scenarios = load_scenarios(settings)
        assert scenarios and all(s.illustrative for s in scenarios)

    def test_every_shock_has_a_rationale(self, settings):
        _, scenarios = load_scenarios(settings)
        assert all(sh.rationale for s in scenarios for sh in s.shocks)

    def test_threshold_default_is_seven(self, settings):
        assert load_app_config(settings).stress.trigger_threshold == 7


class TestCatalog:
    def test_default_for_returns_mapped_scenario(self):
        s = make_scenario(EventCategory.GEOPOLITICAL, sid="g")
        cat = ScenarioCatalog([s], {EventCategory.GEOPOLITICAL: "g"}, require_complete=False)
        assert cat.default_for(EventCategory.GEOPOLITICAL) is s
        assert cat.default_for(EventCategory.MACROECONOMIC) is None

    def test_incomplete_mapping_rejected_by_default(self):
        s = make_scenario(EventCategory.GEOPOLITICAL, sid="g")
        with pytest.raises(ValueError, match="no default scenario"):
            ScenarioCatalog([s], {EventCategory.GEOPOLITICAL: "g"})

    def test_unknown_scenario_in_mapping_rejected(self):
        with pytest.raises(ValueError, match="unknown scenario"):
            ScenarioCatalog([], {EventCategory.GEOPOLITICAL: "nope"}, require_complete=False)

    def test_category_mismatch_rejected(self):
        s = make_scenario(EventCategory.MACROECONOMIC, sid="m")
        with pytest.raises(ValueError, match="not"):
            ScenarioCatalog([s], {EventCategory.GEOPOLITICAL: "m"}, require_complete=False)

    def test_duplicate_ids_rejected(self):
        s = make_scenario(sid="x")
        with pytest.raises(ValueError, match="duplicate"):
            ScenarioCatalog([s, s], {}, require_complete=False)


class TestConfigErrors:
    def test_missing_config_dir_fails_loudly(self, tmp_path):
        with pytest.raises(ConfigError, match="missing config file"):
            load_app_config(Settings(config_dir=tmp_path))

    def test_bad_yaml_fails_loudly(self, tmp_path):
        (tmp_path / "app.yaml").write_text("a: [unclosed")
        with pytest.raises(ConfigError, match="invalid YAML"):
            load_app_config(Settings(config_dir=tmp_path))

    def test_inverted_scale_bounds_rejected(self):
        with pytest.raises(ValueError, match="severity_scale_min"):
            StressConfig(severity_scale_min=2, severity_scale_max=1)

    def test_env_threshold_override(self, monkeypatch):
        monkeypatch.setenv("EVENTSHOCK_TRIGGER_THRESHOLD", "9")
        assert load_app_config(Settings()).stress.trigger_threshold == 9
