"""Shared ingestion types: rejected records and reason codes. Adapters never raise on bad *data*."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RejectCode(StrEnum):
    """Why a record was quarantined. Closed vocabulary so reports and tests can enumerate it."""

    MALFORMED_RECORD = "MALFORMED_RECORD"  # not valid JSON / not an object
    SCHEMA = "SCHEMA"  # required field missing or of the wrong type
    EMPTY_TEXT = "EMPTY_TEXT"
    TOO_SHORT = "TOO_SHORT"
    TOO_LONG = "TOO_LONG"
    LOW_QUALITY = "LOW_QUALITY"  # mostly symbols/digits
    MOJIBAKE = "MOJIBAKE"  # broken text encoding
    BAD_TIMESTAMP = "BAD_TIMESTAMP"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    OUTSIDE_WINDOW = "OUTSIDE_WINDOW"
    NON_ENGLISH = "NON_ENGLISH"
    BAD_URL = "BAD_URL"


@dataclass(frozen=True)
class Rejected:
    """A record that did not become a document. Kept (not dropped) so nothing disappears silently."""

    source: str
    record_ref: str  # "file:line"
    code: RejectCode
    detail: str = ""
    preview: str = ""  # first characters of the raw record, for the quarantine report
