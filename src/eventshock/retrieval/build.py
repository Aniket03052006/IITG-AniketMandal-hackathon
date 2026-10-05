"""Build the committed analogue pack from the corpus and the encoder cache (``make analogue-index``), and the shared quiet-day baselines.

Only TRUSTED-clock episodes are packed (an exact publisher timestamp before the open or after the close), as float16 e5-large vectors plus the headline and
the realised outcome. The pack's manifest pins the sha256 of both files, the encoder, the point-in-time rule and the pre-registration it was built under.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..config import ConfigError
from ..modeling.evidence_v3 import load_evidence_v3
from .corpus import load_corpus
from .index import AnalogueIndex
from .relevance_eval import load_vectors

ENCODER = "intfloat/multilingual-e5-large"
CACHE = Path("data") / "modeling" / "embeddings" / "intfloat__multilingual-e5-large.npz"
PACK_DIR = Path("data") / "replay" / "analogues"


def load_baselines(repo_root: Path) -> dict[str, dict[str, float]]:
    """P(|z| >= 2) on an ordinary day, per scope, from the committed outcome audit (issuer: quiet sessions with no earnings in the window; market: all sessions)."""
    path = repo_root / "docs" / "evidence" / "outcome_audit.json"
    if not path.is_file():
        raise ConfigError(f"missing {path}: `make outcome-audit`")
    a = json.loads(path.read_text(encoding="utf-8"))
    return {"ISSUER": {"p_abs_z_ge_2": float(a["posthoc_ex_earnings"]["normalisation_quiet_ex_earnings"]["ewma094"]["p_abs_gt_2"])},
            "MARKET": {"p_abs_z_ge_2": float(a["market_session_baseline"]["p_abs_gt_2"])}}


def build_index(repo_root: Path, config_dir: Path, *, trusted_only: bool = True, log=print) -> AnalogueIndex:
    _, pre_sha = load_evidence_v3(config_dir)
    corpus = load_corpus(repo_root / "data" / "modeling" / "analogue_corpus.jsonl")
    cache = repo_root / CACHE
    vec_of: dict[str, np.ndarray] = {}
    rows = [r for r in corpus if r["clock"] == "TRUSTED" or not trusted_only]
    vecs = load_vectors(cache, [r["text"] for r in rows])
    for r, v in zip(rows, vecs, strict=True):
        vec_of[r["id"]] = v
    by_text = {r["text"]: r["id"] for r in rows}
    return AnalogueIndex.build(rows, lambda texts: np.stack([vec_of[by_text[t]] for t in texts]), encoder=ENCODER, baselines=load_baselines(repo_root),
                               preregistration_sha256=pre_sha, trusted_only=trusted_only)


def index_pack_dir(repo_root: Path) -> Path:
    return repo_root / PACK_DIR
