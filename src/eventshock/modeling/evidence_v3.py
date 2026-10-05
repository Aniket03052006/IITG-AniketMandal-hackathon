"""Loader for ``configs/evidence_v3.yaml``, the Stage 8 pre-registration.

The file fixes the audit decision rule, the severity-validity test and the retrieval design before any of them was run. This module only reads
it, checks that every section the code consumes is present (a typo must stop the run, not silently change a rule) and returns its sha256 so
that every evidence artifact can state exactly which pre-registration it was produced under.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from ..config import ConfigError

VERSION = "evidence-v3"
FILE = "evidence_v3.yaml"

_REQUIRED: dict[str, list[str]] = {
    "": ["version", "seed", "data", "split_column", "bootstrap", "outcome_audit", "severity_validity", "retrieval", "stress_history"],
    "bootstrap": ["resamples", "cluster", "ci"],
    "outcome_audit": ["null_sample", "sigma_estimators", "regime", "adopt_ewma_if", "diagnostics", "material_move_abs_z"],
    "outcome_audit.null_sample": ["n", "first_session_date", "exclude_within_sessions"],
    "outcome_audit.regime": ["variable", "tercile_cutpoints_from"],
    "outcome_audit.adopt_ewma_if": ["regime_log_variance_gap_reduction_at_least", "must_hold_in_both_halves", "overall_null_variance_within"],
    "severity_validity": ["corpus", "predictor", "outcome", "bands", "regime_baseline", "metrics", "labels"],
    "retrieval": ["encoder", "corpus", "point_in_time", "story_dedup", "diversity", "k", "reliability", "similarity_floor_rule",
                  "relevance_eval", "outcome_value"],
    "retrieval.point_in_time": ["window_sessions", "embargo_sessions"],
    "retrieval.reliability": ["min_distinct_episodes", "min_distinct_stories"],
    "stress_history": ["index", "rates", "horizons_sessions", "quantiles", "first_session_date"],
}


def _dig(doc: dict[str, Any], path: str) -> Any:
    cur: Any = doc
    for part in [p for p in path.split(".") if p]:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def load_evidence_v3(config_dir: Path) -> tuple[dict[str, Any], str]:
    """(parsed pre-registration, sha256 of the file's bytes). Raises ``ConfigError`` for a missing file or section."""
    path = config_dir / FILE
    if not path.is_file():
        raise ConfigError(f"missing pre-registration {path}")
    raw = path.read_bytes()
    doc = yaml.safe_load(raw)
    if not isinstance(doc, dict):
        raise ConfigError(f"{path} is not a mapping")
    if doc.get("version") != VERSION:
        raise ConfigError(f"{path}: version {doc.get('version')!r}, expected {VERSION!r}")
    problems = []
    for section, keys in _REQUIRED.items():
        node = _dig(doc, section) if section else doc
        if not isinstance(node, dict):
            problems.append(f"section {section!r} missing")
            continue
        problems += [f"{section or '<root>'}.{k} missing" for k in keys if k not in node]
    if problems:
        raise ConfigError(f"{path}: " + "; ".join(problems))
    return doc, hashlib.sha256(raw).hexdigest()
