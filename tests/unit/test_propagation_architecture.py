"""Propagation and adjustment are derived side-cars: nothing that scores, models, stresses or reads text imports them, and nothing is stored on a signal."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.propagation.config import load_propagation_config

SRC = REPO_ROOT / "src" / "eventshock"


@pytest.mark.parametrize("pkg", ["assessment", "pipeline", "stress", "modeling", "domain", "retrieval", "portfolio", "intelligence", "llm", "ingestion", "services"])
def test_nothing_below_the_api_imports_propagation_or_adjust(pkg):
    """A severity score, a model, the stress arithmetic, the pipeline or the intelligence layer that read these would make a user's manual adjustment or a
    portfolio-specific reading leak into the signals (and move the pinned digests)."""
    offenders = []
    for p in (SRC / pkg).rglob("*.py"):
        imports = " ".join(ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith(("import ", "from ")))
        if re.search(r"\b(propagation|adjust)\b", imports):
            offenders.append(str(p.relative_to(SRC)))
    assert offenders == []


def test_the_risk_signal_gains_no_propagation_field():
    from eventshock.domain import Evidence, RiskSignal, SignalScope
    for model in (RiskSignal, Evidence, SignalScope):
        assert not [f for f in model.model_fields if f.startswith(("materiality", "propagation", "generated", "attribution", "adjust"))]


def test_the_configs_that_adjustments_patch_do_not_import_the_adjust_layer():
    for rel in ("intelligence/config.py", "portfolio/config.py"):
        text = (SRC / rel).read_text(encoding="utf-8")
        assert "adjust" not in " ".join(ln for ln in text.splitlines() if ln.lstrip().startswith(("import ", "from ")))


def test_the_overrides_file_is_git_ignored():
    assert "data/live/overrides/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_a_misspelt_key_is_an_error_not_ignored(tmp_path: Path):
    raw = yaml.safe_load((REPO_ROOT / "configs" / "propagation.yaml").read_text(encoding="utf-8"))
    raw["generation"]["min_severty"] = 7
    (tmp_path / "propagation.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="min_severty"):
        load_propagation_config(tmp_path)


def test_every_category_has_a_template_and_every_referenced_factor_exists():
    cfg = load_propagation_config(REPO_ROOT / "configs")
    assert len(cfg.templates) == 8 and len(cfg.category_risk_factors) == 8
    raw = yaml.safe_load((REPO_ROOT / "configs" / "propagation.yaml").read_text(encoding="utf-8"))
    raw["category_risk_factors"]["GEOPOLITICAL"].append("NOT_A_FACTOR")
    with pytest.raises(ValueError, match="unknown risk factor"):
        type(cfg).model_validate(raw)


def test_the_shipped_propagation_config_states_that_nothing_is_fitted():
    text = (REPO_ROOT / "configs" / "propagation.yaml").read_text(encoding="utf-8")
    assert "JUDGEMENT PRIOR" in text and "none is fitted" in text and "causal claim" in text.replace("\n# ", " ")
