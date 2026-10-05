"""The analogue index: L2-normalised float16 e5 vectors aligned with metadata rows, packed into three hash-pinned files.

``analogues.npz`` (vectors), ``analogues.jsonl`` (one metadata row per vector: the past headline, its reaction session, its realised outcome) and
``analogues.json`` (the manifest: encoder, point-in-time rule, quiet-day baselines, the pre-registration it was built under, and the sha256 of both files).
Loading verifies the hashes and refuses a modified pack. Only derived numbers and public headlines are stored: no prices.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.embeddings import quantize

FORMAT = "analogue-index-v1"
KEEP = ("id", "episode", "scope", "ticker", "sector", "s0", "s0_date", "available_from", "published_at", "timing", "clock", "text", "event_top",
        "vix_level", "car", "z", "abs_z", "outcome_version")


class AnalogueIndex:
    def __init__(self, vectors: np.ndarray, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
        if vectors.shape[0] != len(rows):
            raise ConfigError(f"analogue index: {vectors.shape[0]} vectors for {len(rows)} rows")
        self.vectors = vectors.astype(np.float32)
        self.rows = rows
        self.manifest = manifest
        self.version = str(manifest.get("version", FORMAT))
        self.available_from = np.asarray([r["available_from"] for r in rows])  # ISO dates compare lexicographically
        self.scope = np.asarray([r["scope"] for r in rows])

    def __len__(self) -> int:
        return len(self.rows)

    # --------------------------------------------------------------------------------------------------------- build / save / load
    @classmethod
    def build(cls, corpus_rows: Sequence[dict[str, Any]], embed: Callable[[list[str]], np.ndarray], *, encoder: str, baselines: dict[str, Any],
              preregistration_sha256: str, trusted_only: bool = True) -> AnalogueIndex:
        rows = [{k: r.get(k) for k in KEEP} for r in corpus_rows if r["clock"] == "TRUSTED" or not trusted_only]
        rows.sort(key=lambda r: (r["s0"], r["scope"], r.get("ticker") or "", r["id"]))
        vecs = quantize(embed([r["text"] for r in rows]))
        norms = np.linalg.norm(vecs, axis=1)
        if not np.allclose(norms, 1.0, atol=2e-3):
            raise ConfigError("analogue vectors are not unit length: the encoder output must be L2-normalised")
        manifest = {"format": FORMAT, "version": f"{FORMAT}+{encoder}", "encoder": encoder, "rows": len(rows), "dims": int(vecs.shape[1]),
                    "trusted_only": trusted_only, "baselines": baselines, "preregistration_sha256": preregistration_sha256,
                    "first_reaction_session": rows[0]["s0_date"], "last_reaction_session": rows[-1]["s0_date"]}
        return cls(vecs, rows, manifest)

    def save(self, out_dir: Path) -> dict[str, Any]:
        out_dir.mkdir(parents=True, exist_ok=True)
        npz, jsonl = out_dir / "analogues.npz", out_dir / "analogues.jsonl"
        np.savez_compressed(npz, vectors=self.vectors.astype(np.float16), ids=np.asarray([r["id"] for r in self.rows]))
        atomic_write_text(jsonl, "".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in self.rows))
        manifest = {**self.manifest, "vectors_sha256": hashlib.sha256(npz.read_bytes()).hexdigest(), "rows_sha256": hashlib.sha256(jsonl.read_bytes()).hexdigest(),
                    "bytes": {"vectors": npz.stat().st_size, "rows": jsonl.stat().st_size}}
        atomic_write_text(out_dir / "analogues.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        self.manifest = manifest
        return manifest

    @classmethod
    def load(cls, directory: Path) -> AnalogueIndex:
        mpath = directory / "analogues.json"
        if not mpath.is_file():
            raise ConfigError(f"no analogue index in {directory}: `make analogue-index`")
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if manifest.get("format") != FORMAT:
            raise ConfigError(f"{mpath}: format {manifest.get('format')!r}, expected {FORMAT!r}")
        for name, key in (("analogues.npz", "vectors_sha256"), ("analogues.jsonl", "rows_sha256")):
            actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
            if actual != manifest[key]:
                raise ConfigError(f"{directory / name} does not match its pinned hash ({actual[:12]} != {manifest[key][:12]}): the index was modified")
        z = np.load(directory / "analogues.npz", allow_pickle=False)
        rows = [json.loads(line) for line in (directory / "analogues.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if z["ids"].tolist() != [r["id"] for r in rows]:
            raise ConfigError("analogue index: vector ids and metadata rows are not aligned")
        return cls(z["vectors"].astype(np.float32), rows, manifest)
