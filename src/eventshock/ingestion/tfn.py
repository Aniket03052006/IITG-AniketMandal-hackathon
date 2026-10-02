"""Twitter Financial News (zeroshot) adapter.

The dataset ships tweet text and a human sentiment label only: no id, author or time. Each record is
``{"split", "row", "text", "label"}``. Replay assigns a deterministic time inside the snapshot window and
flags it ``SYNTHETIC_REPLAY_CLOCK``; such documents are never correlated with others by time.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from ..domain import RawDocument, SourceType, TimestampOrigin
from .base import RejectCode, Rejected
from .snapshot import RawLine, iter_jsonl

LABELS = {0: "bearish", 1: "bullish", 2: "neutral"}
SOURCE_LABEL = "Twitter Financial News"
_TCO = re.compile(r"\s*https?://t\.co/\S+")  # shortlinks carry no information; the raw record keeps them


class TfnAdapter:
    name = "tfn-replay"
    source_type = SourceType.SOCIAL

    def __init__(self, *, snapshot_id: str, as_of: datetime, window_start: datetime, window_end: datetime,
                 source_name: str = "tfn-replay") -> None:
        self.snapshot_id = snapshot_id
        self.as_of = as_of
        self.window_start = window_start
        self.window_seconds = max(1, int((window_end - window_start).total_seconds()))
        self.source_name = source_name

    def replay_time(self, doc_id: str) -> datetime:
        """Stable pseudo-random instant in the window derived from the id (no RNG state, order independent)."""
        offset = int(hashlib.sha256(doc_id.encode()).hexdigest()[:12], 16) % self.window_seconds
        return self.window_start + timedelta(seconds=offset)

    def read(self, path: Path, display_name: str) -> Iterator[RawDocument | Rejected]:
        for line in iter_jsonl(path, display_name):
            yield self.parse(line)

    def parse(self, line: RawLine) -> RawDocument | Rejected:
        def reject(code: RejectCode, detail: str) -> Rejected:
            return Rejected(self.source_name, line.ref, code, detail, line.preview)

        if line.obj is None:
            return reject(RejectCode.MALFORMED_RECORD, line.error or "unreadable record")
        rec = line.obj
        text, label = rec.get("text"), rec.get("label")
        split, row = rec.get("split"), rec.get("row")
        if not isinstance(text, str):
            return reject(RejectCode.SCHEMA, "missing or non-string 'text'")
        if not text.strip():
            return reject(RejectCode.EMPTY_TEXT, "empty tweet")
        if isinstance(label, bool) or label not in LABELS:
            return reject(RejectCode.SCHEMA, f"label {label!r} not in {sorted(LABELS)}")
        if not isinstance(split, str) or isinstance(row, bool) or not isinstance(row, int):
            return reject(RejectCode.SCHEMA, "missing 'split'/'row' (needed for a stable id)")
        doc_id = f"tfn-{split}-{row}"
        published = self.replay_time(doc_id)
        try:
            return RawDocument(
                id=doc_id,
                source=SOURCE_LABEL,
                source_type=SourceType.SOCIAL,
                published_at=published,
                ingested_at=self.as_of,
                headline=_TCO.sub("", text).strip() or text,
                language="en",
                raw_metadata={
                    "adapter": self.name,
                    "snapshot_id": self.snapshot_id,
                    "record_ref": line.ref,
                    "content_sha256": line.sha256,
                    "timestamp_origin": TimestampOrigin.SYNTHETIC_REPLAY_CLOCK.value,
                    "domain": None,
                    "source_label": LABELS[label],
                },
            )
        except ValidationError as exc:
            return reject(RejectCode.SCHEMA, str(exc).splitlines()[0])
