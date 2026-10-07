"""The final state is frozen: docs/freeze_manifest.json pins every model, config, gold, calendar, replay and evidence file."""
from __future__ import annotations

import json
import subprocess
import sys

from eventshock.config import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "freeze_manifest.py"


def test_freeze_check_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode == 0, r.stderr
    assert "freeze check passed" in r.stdout


def test_freeze_manifest_names_every_served_model_and_the_adjudication_queues():
    m = json.loads((REPO_ROOT / "docs/freeze_manifest.json").read_text())
    assert {v["id"] for v in m["models"].values()} == {"tfidf-lr-v1", "tfidf-lr-v2", "tfidf-lr-event-v1", "hybrid-event-v2", "impact-v1", "impact-v2"}
    for needed in ("data/gold_v2/adjudication_v2.csv", "data/gold_v2/gold_v2.csv", "data/gold/adjudication.csv", "data/replay/manifest.json",
                   "configs/evidence_v2.yaml", "configs/impact_model.yaml", "configs/event_model.yaml", "data/events/fomc.json"):
        assert needed in m["files"], needed
    assert "docs/freeze_manifest.json" not in m["files"]


def test_freeze_detects_a_changed_file(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import freeze_manifest as F

    d = tmp_path / "g"
    d.mkdir()
    (d / "a.csv").write_text("x")
    monkeypatch.setattr(F, "ROOT", tmp_path)
    monkeypatch.setattr(F, "GROUPS", {"g": ("g", "*.csv")})
    before = F.collect()
    (d / "a.csv").write_text("y")
    assert F.collect() != before and list(before) == ["g/a.csv"]
