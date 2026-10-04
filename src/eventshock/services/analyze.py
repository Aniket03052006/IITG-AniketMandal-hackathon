"""Pasted text -> the engine. The same door the live feed uses, with a person at it.

The text is turned into a ``RawDocument`` (``adapter: manual-paste``) and ingested like any other report, so the result is an ordinary
``RiskSignal``: same models, same scope rules, same clustering (a pasted story that is already in the feed joins its cluster and shows
the real corroboration), same stress path. What this module adds is only the splitting of a paste into headline and lead, the length
cap, and the plain-language notes that say what was and was not done.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..domain import RawDocument, RiskSignal, SourceType, TimestampOrigin
from ..pipeline.config import ValidationConfig
from ..pipeline.engine import IngestOutcome, Outcome, RiskEngine
from ..store import CHANNEL_MANUAL, CombinedSignalRepository
from .live import Journal

HEADLINE_MAX = 240
FUTURE_SKEW = timedelta(minutes=5)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“])")


class AnalysisUnavailable(RuntimeError):
    """The engine is not running in this profile (the demo profile has no models)."""


class AnalysisInputError(ValueError):
    """The request itself is unusable (empty, or a time in the future)."""


@dataclass
class AnalysisResult:
    outcome: IngestOutcome
    signal: RiskSignal | None
    headline: str
    analysed_chars: int
    truncated: bool
    notes: list[str] = field(default_factory=list)


def split_paste(text: str, limit: int) -> tuple[str, str, bool]:
    """(headline, body, truncated). A first line of reasonable length is the headline; otherwise the first sentence is.

    The models were fitted on headlines and tweets, so a long article is read by its opening ``limit`` characters; ``truncated`` says
    when that cut something off.
    """
    clean = "\n".join(line.strip() for line in text.strip().splitlines())
    clean = re.sub(r"\n{2,}", "\n", clean)
    lines = clean.split("\n")
    if len(lines) > 1 and 0 < len(lines[0]) <= HEADLINE_MAX:
        headline, body = lines[0], " ".join(lines[1:])
    else:
        flat = " ".join(lines)
        first = _SENTENCE_END.split(flat, maxsplit=1)
        if len(first[0]) <= HEADLINE_MAX:
            headline, body = first[0], (first[1] if len(first) > 1 else "")
        else:
            cut = flat.rfind(" ", 0, HEADLINE_MAX)
            cut = cut if cut > 0 else HEADLINE_MAX
            headline, body = flat[:cut].rstrip(), flat[cut:].strip()
    room = max(0, limit - len(headline) - 1)
    truncated = len(body) > room
    return headline, (body[:room].rstrip() if truncated else body), truncated


class Analyzer:
    def __init__(self, engine: RiskEngine, signals: CombinedSignalRepository, validation: ValidationConfig, *,
                 journal: Journal | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self._engine, self._signals, self._limit = engine, signals, validation.max_text_chars
        self._journal = journal
        self._clock = clock or (lambda: datetime.now(UTC))

    def analyze(self, text: str, *, source_type: SourceType = SourceType.NEWS,
                published_at: datetime | None = None, source: str | None = None) -> AnalysisResult:
        if not text or not text.strip():
            raise AnalysisInputError("nothing to analyse: the text is empty")
        now = self._clock()
        if published_at is not None:
            if published_at.tzinfo is None or published_at.utcoffset() is None:
                raise AnalysisInputError("published_at must include a time zone")
            if published_at > now + FUTURE_SKEW:
                raise AnalysisInputError("published_at is in the future")
        headline, body, truncated = split_paste(text, self._limit)
        stamped = published_at.astimezone(UTC) if published_at else now
        digest = hashlib.sha256(f"{headline}\n{body}".encode()).hexdigest()
        doc_id = f"manual-{digest[:12]}"
        doc = RawDocument(
            id=doc_id, source=(source or "").strip() or "manual paste", source_type=source_type, published_at=stamped, ingested_at=max(now, stamped),
            headline=headline, body=body, url=None, language="en",
            raw_metadata={"adapter": "manual-paste", "record_ref": f"manual:{doc_id}", "content_sha256": digest,
                          "timestamp_origin": (TimestampOrigin.USER_ASSERTED if published_at else TimestampOrigin.ANALYSIS_TIME).value,
                          "domain": None})
        outcome = self._engine.ingest([doc], channel=CHANNEL_MANUAL, now=max(now, stamped))[0]
        signal = self._signals.get(outcome.signal_id) if outcome.signal_id else None
        notes = self._notes(outcome, signal, truncated, published_at is not None)
        if self._journal is not None and outcome.outcome is not Outcome.QUARANTINED:
            self._journal.append(CHANNEL_MANUAL, [doc])
        return AnalysisResult(outcome, signal, headline, len(headline) + len(body), truncated, notes)

    def _notes(self, o: IngestOutcome, s: RiskSignal | None, truncated: bool, dated: bool) -> list[str]:
        notes: list[str] = []
        if o.outcome is Outcome.QUARANTINED:
            return notes  # nothing was scored: say only why (the rejection), not how it would have been scored
        if truncated:
            notes.append(f"Only the first {self._limit} characters were analysed: the models read headlines and short posts.")
        if not dated:
            notes.append("No publication time was given, so the time you pasted it is used.")
        st = self._engine.status
        if st.event_fallback_reason:
            notes.append(f"Event type was scored by the reference model {st.event_model}: {st.event_fallback_reason}.")
        if s is not None:
            if o.outcome is Outcome.UPDATED or (o.outcome is Outcome.DUPLICATE and s.evidence.source_count > 1):
                notes.append(f"This story is already in the feed: {s.evidence.source_count} reports are grouped with it.")
        return notes
