"""Semantic validation of normalised documents. Returns a reject code or None; never mutates."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..domain import TRUSTED_TIMESTAMPS, RawDocument, TimestampOrigin
from ..ingestion.base import RejectCode
from .config import ValidationConfig

_MOJIBAKE_MARKERS = ("�", "Ã©", "Ã¨", "Ã¶", "Ã¼", "â€™", "â€œ", "â€\x9d", "â€“", "Â ")

# GDELT reports full language names; anything not listed is treated as "not English".
LANGUAGE_CODES = {"english": "en"}


def alpha_ratio(text: str) -> float:
    visible = [c for c in text if not c.isspace()]
    return sum(c.isalpha() for c in visible) / len(visible) if visible else 0.0


def validate_document(
    doc: RawDocument,
    *,
    cfg: ValidationConfig,
    as_of: datetime,
    window_start: datetime,
    window_end: datetime,
    timestamp_origin: TimestampOrigin,
) -> tuple[RejectCode, str] | None:
    text = f"{doc.headline} {doc.body}".strip()
    if not text:
        return RejectCode.EMPTY_TEXT, "no text left after normalisation"
    if any(m in text for m in _MOJIBAKE_MARKERS):
        return RejectCode.MOJIBAKE, "text contains encoding-damage markers"
    if len(doc.headline) < cfg.min_text_chars and len(text) < cfg.min_text_chars:
        return RejectCode.TOO_SHORT, f"{len(text)} chars < {cfg.min_text_chars}"
    if len(text) > cfg.max_text_chars:
        return RejectCode.TOO_LONG, f"{len(text)} chars > {cfg.max_text_chars}"
    if alpha_ratio(text) < cfg.min_alpha_ratio:
        return RejectCode.LOW_QUALITY, f"alphabetic ratio {alpha_ratio(text):.2f} < {cfg.min_alpha_ratio}"
    if doc.language.lower() not in cfg.allowed_languages:
        return RejectCode.NON_ENGLISH, f"language {doc.language!r} not in {cfg.allowed_languages}"
    if doc.published_at > as_of + timedelta(minutes=cfg.future_skew_minutes):
        return RejectCode.FUTURE_TIMESTAMP, f"published {doc.published_at.isoformat()} after replay clock"
    if timestamp_origin in TRUSTED_TIMESTAMPS and not window_start <= doc.published_at <= window_end:
        # The source APIs do not reliably honour the requested window (GDELT returns items after enddatetime),
        # so the window is enforced here, on our side.
        return RejectCode.OUTSIDE_WINDOW, f"published {doc.published_at.isoformat()} outside the snapshot window"
    return None
