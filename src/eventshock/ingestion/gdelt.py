"""GDELT DOC 2.0 ``artlist`` adapter: one JSON object per article -> ``RawDocument`` or ``Rejected``.

GDELT supplies title, URL, domain, language and ``seendate`` only (no body, no tone). ``seendate`` is when
GDELT first saw the page, so it is kept as ``published_at`` but flagged ``GDELT_FIRST_SEEN``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..domain import RawDocument, SourceType, TimestampOrigin
from .base import RejectCode, Rejected
from .snapshot import RawLine, iter_jsonl

_LANG = {"english": "en"}
_NUM_SPACE = re.compile(r"(?<=\d)\s*([.,])\s*(?=\d)")
_PUNCT_BEFORE = re.compile(r"\s+([.,;:!?%)\]])")
_PUNCT_AFTER = re.compile(r"([(\[])\s+")


def untokenise(title: str) -> str:
    """GDELT titles are word-tokenised ("$5 . 7 billion", "( NYSE : GS )"); restore ordinary spacing."""
    title = _NUM_SPACE.sub(r"\1", title)
    title = _PUNCT_BEFORE.sub(r"\1", title)
    return _PUNCT_AFTER.sub(r"\1", title)


def parse_seendate(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


class GdeltAdapter:
    name = "gdelt-doc"
    source_type = SourceType.NEWS
    id_prefix = "gdelt"  # document ids are per source: the same URL in two sources must not share an id

    def __init__(self, *, snapshot_id: str, as_of: datetime, source_name: str = "gdelt-doc") -> None:
        self.snapshot_id = snapshot_id
        self.as_of = as_of
        self.source_name = source_name

    def _extra_metadata(self, rec: dict[str, Any]) -> dict[str, Any]:
        return {"timestamp_origin": TimestampOrigin.GDELT_FIRST_SEEN.value}

    def read(self, path: Path, display_name: str) -> Iterator[RawDocument | Rejected]:
        for line in iter_jsonl(path, display_name):
            yield self.parse(line)

    def parse(self, line: RawLine) -> RawDocument | Rejected:
        def reject(code: RejectCode, detail: str) -> Rejected:
            return Rejected(self.source_name, line.ref, code, detail, line.preview)

        if line.obj is None:
            return reject(RejectCode.MALFORMED_RECORD, line.error or "unreadable record")
        rec = line.obj
        url, title = rec.get("url"), rec.get("title")
        if not isinstance(url, str) or not url.strip():
            return reject(RejectCode.SCHEMA, "missing or non-string 'url'")
        if not isinstance(title, str):
            return reject(RejectCode.SCHEMA, "missing or non-string 'title'")
        published = parse_seendate(rec.get("seendate"))
        if published is None:
            return reject(RejectCode.BAD_TIMESTAMP, f"unparseable seendate {rec.get('seendate')!r}")
        if published > self.as_of:
            return reject(RejectCode.FUTURE_TIMESTAMP, f"seendate {published.isoformat()} after replay clock")
        if not title.strip():
            return reject(RejectCode.EMPTY_TEXT, "empty title")
        domain = rec.get("domain")
        language = rec.get("language")
        doc_id = f"{self.id_prefix}-" + hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:12]  # noqa: S324
        try:
            return RawDocument(
                id=doc_id,
                source=domain.strip() if isinstance(domain, str) and domain.strip() else "unknown-outlet",
                source_type=SourceType.NEWS,
                published_at=published,
                ingested_at=self.as_of,
                headline=untokenise(title),
                url=url.strip(),
                language=_LANG.get(str(language).strip().lower(), str(language).strip().lower() or "unknown"),
                raw_metadata={
                    **self._extra_metadata(rec),
                    "adapter": self.name,
                    "snapshot_id": self.snapshot_id,
                    "record_ref": line.ref,
                    "content_sha256": line.sha256,
                    "domain": domain if isinstance(domain, str) else None,
                    "source_country": rec.get("sourcecountry") if isinstance(rec.get("sourcecountry"), str) else None,
                    "gdelt_query": rec.get("x_query") if isinstance(rec.get("x_query"), str) else None,
                },
            )
        except ValidationError as exc:
            return reject(RejectCode.SCHEMA, str(exc).splitlines()[0])
