"""Replay snapshots: a directory of immutable, hash-verified source files plus a manifest.

A snapshot is the unit of deterministic replay. The manifest pins every file by sha256, so a changed or
truncated file fails at load time instead of silently producing different signals.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

from ..config import ConfigError
from ..domain.base import ContractModel
from ..domain.documents import _require_aware
from ..domain.enums import SourceType

MANIFEST_NAME = "manifest.json"
SCHEMA_VERSION = 1


class SourceFile(ContractModel):
    name: str = Field(min_length=1, description="source id, e.g. gdelt-doc")
    adapter: str = Field(min_length=1)
    source_type: SourceType
    file: str
    sha256: str = Field(min_length=64, max_length=64)
    records: int = Field(ge=0)
    license: str
    attribution: str
    origin_url: str
    notes: str = ""


class AuxFile(ContractModel):
    file: str
    sha256: str = Field(min_length=64, max_length=64)


class SnapshotManifest(ContractModel):
    schema_version: int
    snapshot_id: str = Field(min_length=1)
    description: str = ""
    replay_as_of: datetime = Field(description="the replay clock: ingested_at / created_at of every output")
    window_start: datetime
    window_end: datetime
    sources: list[SourceFile] = Field(min_length=1)
    entities: AuxFile
    portfolio: AuxFile
    fetch_log: list[dict[str, Any]] = Field(default_factory=list)
    fetch_plan: list[str] = Field(
        default_factory=list,
        description="the query strings of the request plan that produced this snapshot; fetch_log entries for any other "
                    "query belong to an abandoned earlier plan (empty = unknown, show every entry)")

    aware_check = field_validator("replay_as_of", "window_start", "window_end")(_require_aware)

    @model_validator(mode="after")
    def _consistent(self) -> SnapshotManifest:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema_version {self.schema_version}")
        if not self.window_start < self.window_end:
            raise ValueError("window_start must precede window_end")
        if self.window_end > self.replay_as_of:
            raise ValueError("window_end cannot be after replay_as_of")
        names = [s.name for s in self.sources]
        if len(names) != len(set(names)):
            raise ValueError("duplicate source names")
        return self


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class RawLine:
    """One line of a source file. ``obj`` is None when the line is not a JSON object (``error`` says why)."""

    file: str
    line: int
    sha256: str
    obj: dict[str, Any] | None
    error: str | None = None
    preview: str = ""

    @property
    def ref(self) -> str:
        return f"{self.file}:{self.line}"


def iter_jsonl(path: Path, display_name: str) -> Iterator[RawLine]:
    """Yield every non-blank line; bad lines are reported, not raised."""
    with path.open("rb") as fh:
        for n, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            digest = sha256_bytes(stripped)
            preview = stripped[:120].decode("utf-8", errors="replace")
            try:
                obj = json.loads(stripped.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                yield RawLine(display_name, n, digest, None, f"invalid JSON: {exc}", preview)
                continue
            if not isinstance(obj, dict):
                yield RawLine(display_name, n, digest, None, "record is not a JSON object", preview)
                continue
            yield RawLine(display_name, n, digest, obj, None, preview)


def count_records(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for line in fh if line.strip())


@dataclass(frozen=True)
class Snapshot:
    root: Path
    manifest: SnapshotManifest

    def source_path(self, source: SourceFile) -> Path:
        return self.root / source.file

    def entities_path(self) -> Path:
        return self.root / self.manifest.entities.file

    def portfolio_path(self) -> Path:
        return self.root / self.manifest.portfolio.file


def _verify(root: Path, rel: str, expected_sha: str, label: str) -> Path:
    path = (root / rel).resolve()
    if root.resolve() not in path.parents:
        raise ConfigError(f"{label}: path escapes the snapshot directory: {rel}")
    if not path.is_file():
        raise ConfigError(f"{label}: file listed in the manifest is missing: {path}")
    actual = sha256_file(path)
    if actual != expected_sha:
        raise ConfigError(
            f"{label}: sha256 mismatch for {rel} (manifest {expected_sha[:12]}…, file {actual[:12]}…). "
            "The snapshot was modified; rebuild it with `make replay-pack` or restore the original."
        )
    return path


def load_snapshot(root: Path) -> Snapshot:
    """Load and fully verify a snapshot. Raises ``ConfigError`` on anything that would make replay ambiguous."""
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ConfigError(f"no {MANIFEST_NAME} in {root}; build one with `make replay-pack`")
    try:
        manifest = SnapshotManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfigError(f"invalid manifest {manifest_path}: {exc}") from exc
    for src in manifest.sources:
        path = _verify(root, src.file, src.sha256, f"source {src.name}")
        actual = count_records(path)
        if actual != src.records:
            raise ConfigError(f"source {src.name}: manifest says {src.records} records, file has {actual}")
    _verify(root, manifest.entities.file, manifest.entities.sha256, "entity master")
    _verify(root, manifest.portfolio.file, manifest.portfolio.sha256, "portfolio")
    return Snapshot(root=root, manifest=manifest)


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash never leaves a half-written snapshot file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
