"""Event intelligence is a side-car: nothing that scores, models or stresses reads it, and its configuration fails loudly when wrong."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.intelligence.config import IntelligenceConfig, load_intelligence_config

SRC = REPO_ROOT / "src" / "eventshock"


@pytest.mark.parametrize("pkg", ["assessment", "pipeline", "stress", "modeling", "domain", "retrieval", "portfolio"])
def test_no_scoring_or_modeling_code_imports_event_intelligence(pkg):
    """Velocity, lifecycle, novelty class and the evidence tier are evidence for a reader. They must never become an input to severity, the
    trained models, the stress arithmetic or the pipeline that builds the signals (which would also move the pinned digests)."""
    offenders = [str(p.relative_to(SRC)) for p in (SRC / pkg).rglob("*.py") if "intelligence" in " ".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith(("import ", "from ")))]
    assert offenders == []


def test_the_risk_signal_has_no_intelligence_field():
    from eventshock.domain import Evidence, RiskSignal, SignalScope
    for model in (RiskSignal, Evidence, SignalScope):
        assert not [f for f in model.model_fields if f.startswith(("lifecycle", "velocity", "contradiction", "scope_type", "scope_path", "evidence_strength"))]


def test_the_shipped_config_loads_and_every_threshold_is_stated():
    cfg = load_intelligence_config(REPO_ROOT / "configs")
    assert cfg.version == "intelligence-v1" and set(cfg.claims.axes) >= {"confirmation", "status", "deal", "operations", "guidance", "approval"}
    text = (REPO_ROOT / "configs" / "intelligence.yaml").read_text(encoding="utf-8")
    assert "JUDGEMENT PRIOR" in text and "none is fitted" in text


def test_a_misspelt_key_is_an_error_not_ignored(tmp_path: Path):
    raw = yaml.safe_load((REPO_ROOT / "configs" / "intelligence.yaml").read_text(encoding="utf-8"))
    raw["lifecycle"]["stale_after_hour"] = 72  # typo
    (tmp_path / "intelligence.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="stale_after_hour"):
        load_intelligence_config(tmp_path)


def test_a_cue_may_not_belong_to_two_poles():
    raw = yaml.safe_load((REPO_ROOT / "configs" / "intelligence.yaml").read_text(encoding="utf-8"))
    raw["claims"]["axes"]["deal"]["neg"].append("completes")  # already a positive cue
    with pytest.raises(ValueError, match="belongs to both"):
        IntelligenceConfig.model_validate(raw)


def test_an_industry_term_may_not_belong_to_two_industries():
    raw = yaml.safe_load((REPO_ROOT / "configs" / "intelligence.yaml").read_text(encoding="utf-8"))
    raw["scope"]["industries"]["Insurance"]["terms"].append("semiconductor")
    with pytest.raises(ValueError, match="belongs to both"):
        IntelligenceConfig.model_validate(raw)
