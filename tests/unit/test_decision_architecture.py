"""The decision side-cars (monitor, watchlists, scenario lab, explanations, feedback, external markets, brief) are derived: nothing that scores, models, stresses, maps or reads text
imports them, nothing is stored on a signal, and what they persist stays out of git."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.decision.config import load_decision_config

SRC = REPO_ROOT / "src" / "eventshock"
SIDECARS = r"\b(decision|monitor|watchlist|lab|explain|feedback|markets|brief)\b"
CORE = ["assessment", "pipeline", "stress", "modeling", "domain", "retrieval", "portfolio", "intelligence", "propagation", "adjust", "llm", "ingestion", "services"]


@pytest.mark.parametrize("pkg", CORE)
def test_nothing_below_the_api_imports_a_decision_sidecar(pkg):
    """A score, a model, the stress arithmetic or the propagation layer that read these would let a market price, a feedback click or a user's scenario leak into the
    risk it is meant to sit beside (and move the pinned digests)."""
    offenders = []
    for p in (SRC / pkg).rglob("*.py"):
        if p.name == "kalshi_capture.py":   # the one network entry point of the external-market side-car lives under ingestion/ by the repo's rule
            continue
        imports = " ".join(ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith(("import ", "from ")))
        if re.search(SIDECARS, imports):
            offenders.append(str(p.relative_to(SRC)))
    assert offenders == []


def test_the_risk_signal_gains_no_decision_field():
    from eventshock.domain import Evidence, RiskSignal, SignalScope
    for model in (RiskSignal, Evidence, SignalScope):
        assert not [f for f in model.model_fields if f.startswith(("change_", "fingerprint", "update_kind", "watch", "feedback", "brief", "explanation", "external_market", "market_"))]


def test_what_the_sidecars_persist_is_git_ignored():
    assert "data/live/decision/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_the_config_says_every_number_is_a_judgement_prior():
    assert "JUDGEMENT PRIOR" in (REPO_ROOT / "configs" / "decision.yaml").read_text(encoding="utf-8")


def test_a_misspelt_key_is_an_error_not_ignored(tmp_path: Path):
    raw = yaml.safe_load((REPO_ROOT / "configs" / "decision.yaml").read_text(encoding="utf-8"))
    raw["monitor"]["escalation_delt"] = 1
    (tmp_path / "decision.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="escalation_delt"):
        load_decision_config(tmp_path)


def test_a_lifecycle_rule_cannot_be_two_kinds_of_update(tmp_path: Path):
    raw = yaml.safe_load((REPO_ROOT / "configs" / "decision.yaml").read_text(encoding="utf-8"))
    raw["memory"]["resolution_rules"].append("ESCALATION_CUE")
    (tmp_path / "decision.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="ESCALATION_CUE"):
        load_decision_config(tmp_path)


def test_the_tracking_floor_must_be_a_real_level(tmp_path: Path):
    raw = yaml.safe_load((REPO_ROOT / "configs" / "decision.yaml").read_text(encoding="utf-8"))
    raw["monitor"]["track_min_materiality"] = "NONE"
    (tmp_path / "decision.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="track_min_materiality"):
        load_decision_config(tmp_path)
