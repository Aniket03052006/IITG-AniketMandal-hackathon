"""The tactical rebalancer is a derived side-car: nothing that scores, models, stresses, maps or reads text imports it, nothing is stored on a signal, and what it
derives stays out of the model and the pinned digests."""

from __future__ import annotations

import re

import pytest

from eventshock.config import REPO_ROOT

SRC = REPO_ROOT / "src" / "eventshock"
SIDECAR = r"\brebalancer\b"
CORE = ["assessment", "pipeline", "stress", "modeling", "domain", "retrieval", "portfolio", "intelligence", "propagation", "adjust", "llm", "ingestion", "services",
        "decision", "monitor", "watchlist", "lab", "explain", "feedback", "markets", "brief", "review"]


@pytest.mark.parametrize("pkg", CORE)
def test_nothing_else_imports_the_rebalancer(pkg):
    offenders = []
    for p in (SRC / pkg).rglob("*.py"):
        imports = " ".join(ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith(("import ", "from ")))
        if re.search(SIDECAR, imports):
            offenders.append(str(p.relative_to(SRC)))
    assert offenders == []


def test_the_rebalancer_reads_only_signals_and_the_entity_master():
    """It may use the domain contracts and the signal store; it must not reach into scoring, models or the stress engine."""
    forbidden = r"\b(assessment|stress|modeling|pipeline|llm|propagation|intelligence|monitor|decision)\b"
    offenders = []
    for p in (SRC / "rebalancer").rglob("*.py"):
        imports = " ".join(ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith(("import ", "from ")))
        if re.search(forbidden, imports):
            offenders.append(str(p.relative_to(SRC)))
    assert offenders == []


def test_the_risk_signal_gains_no_rebalancer_field():
    from eventshock.domain import Evidence, RiskSignal, SignalScope
    for model in (RiskSignal, Evidence, SignalScope):
        assert not [f for f in model.model_fields if f.startswith(("weight", "rebal", "tilt", "target_weight", "index_"))]
