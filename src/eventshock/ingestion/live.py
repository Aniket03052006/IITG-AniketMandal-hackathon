"""Live sources: what GDELT saw recently (network) or a file of captured GDELT lines (offline), as raw lines for the same adapter.

This module adds no HTTP of its own: it drives ``fetch.fetch_gdelt`` (the package's one network path, with its retry, rate-limit and
shape checks) and hands every record to ``GdeltAdapter.parse`` through ``LiveGdeltAdapter``, so a live article is read by exactly the
code that reads a replayed one. A source returns *what it got and what failed*; it never fills a gap with invented records.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..config import ConfigError
from ..domain import RawDocument
from .base import Rejected
from .fetch import Transport, fetch_gdelt, urllib_transport
from .gdelt import GdeltAdapter, parse_seendate
from .snapshot import RawLine, iter_jsonl


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GdeltSourceConfig(_Strict):
    timespan_minutes: int = Field(default=90, ge=5, le=1440)
    maxrecords: int = Field(default=60, ge=1, le=250)
    throttle_seconds: float = Field(default=6.0, ge=5.0, description="GDELT allows one request per 5 seconds")
    queries: list[str] = Field(min_length=1)


class CaptureSourceConfig(_Strict):
    path: Path
    batch_size: int = Field(default=20, ge=1)
    interval_seconds: float = Field(default=10.0, ge=1.0, description="a capture is local, so it can be delivered faster than the live poll")


class EdgarSourceConfig(_Strict):
    """SEC EDGAR "current filings" Atom feed. Judgement priors, not validated: which filings are worth reading is a choice, said here."""

    count: int = Field(default=100, ge=10, le=100, description="entries asked for per poll (the feed's most recent filings)")
    form: str = Field(default="8-K", min_length=1)
    lookback_hours: float = Field(default=6.0, gt=0, description="a filing accepted longer ago than this is ignored (the engine would hold it as old news)")
    tracked_issuers: bool = Field(default=True, description="keep every filing by an issuer in the entity master (matched by CIK, not by name)")
    items: list[str] = Field(default_factory=list, description="8-K item codes that make a filing worth reading even for an untracked company")
    max_headline_chars: int = Field(default=220, ge=60)


class SourceConfig(_Strict):
    kind: Literal["gdelt", "capture", "edgar", "both"] = "gdelt"
    gdelt: GdeltSourceConfig
    capture: CaptureSourceConfig
    edgar: EdgarSourceConfig = EdgarSourceConfig()


class LiveGdeltAdapter(GdeltAdapter):
    """The replay GDELT adapter, named for what it reads so a signal's provenance says it came from the live feed."""

    name = "gdelt-live"


@dataclass
class LivePoll:
    """One poll: the raw records, the clock they are valid at, and exactly what went wrong (if anything)."""

    mode: str  # GDELT | CAPTURE
    clock: datetime
    records: list[dict[str, Any]] = field(default_factory=list)
    queries_ok: int = 0
    queries_failed: int = 0
    errors: list[str] = field(default_factory=list)
    exhausted: bool = False  # a capture has no more batches
    documents: list[RawDocument | Rejected] = field(default_factory=list)  # sources that build documents themselves (EDGAR) add them here
    note: str | None = None  # one line on what the poll saw (EDGAR: filings seen and kept), shown beside the status

    @property
    def failed(self) -> bool:
        return self.queries_failed > 0 and self.queries_ok == 0


class LiveSource(Protocol):
    mode: str  # GDELT | CAPTURE | EDGAR | GDELT+EDGAR (what the status shows)
    kind: str  # gdelt | capture | edgar | both (what the switch selects)

    def poll(self) -> LivePoll: ...


def to_documents(poll: LivePoll, *, snapshot_id: str = "live") -> list[RawDocument | Rejected]:
    """Raw GDELT records -> RawDocument / Rejected through the one GDELT adapter; documents a source built itself follow."""
    adapter = LiveGdeltAdapter(snapshot_id=snapshot_id, as_of=poll.clock, source_name="gdelt-live")
    out: list[RawDocument | Rejected] = []
    for n, rec in enumerate(poll.records, start=1):
        raw = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        out.append(adapter.parse(RawLine("gdelt-live", n, digest, rec, None, raw[:120])))
    return out + list(poll.documents)


class GdeltLiveSource:
    mode = "GDELT"
    kind = "gdelt"
    interval_seconds: float | None = None  # None: the service's poll_interval_seconds

    def __init__(self, cfg: GdeltSourceConfig, *, transport: Transport = urllib_transport,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], datetime] | None = None) -> None:
        self.cfg, self._transport, self._sleep = cfg, transport, sleep
        self._clock = clock or (lambda: datetime.now(UTC))

    def poll(self) -> LivePoll:
        now = self._clock()
        fmt = "%Y%m%d%H%M%S"
        res = fetch_gdelt(self.cfg.queries, start=(now - timedelta(minutes=self.cfg.timespan_minutes)).strftime(fmt),
                          end=now.strftime(fmt), maxrecords=self.cfg.maxrecords, transport=self._transport,
                          sleep=self._sleep, throttle=self.cfg.throttle_seconds)
        errors = [f"{e['query']}: {e.get('error', 'error')}" for e in res.log if e["status"] == "error"]
        return LivePoll(self.mode, now, res.records, queries_ok=len(res.log) - len(errors), queries_failed=len(errors), errors=errors)


class CaptureSource:
    """A file of GDELT DOC lines delivered in batches, oldest first, on the capture's own clock (the newest ``seendate`` so far).

    It is the offline twin of ``GdeltLiveSource``: the same records, the same adapter, the same engine, no network. The status
    endpoint names the mode, so a capture is never mistaken for the live feed.
    """

    mode = "CAPTURE"
    kind = "capture"

    def __init__(self, cfg: CaptureSourceConfig, *, base: Path) -> None:
        self.interval_seconds = cfg.interval_seconds
        path = cfg.path if cfg.path.is_absolute() else base / cfg.path
        if not path.is_file():
            raise ConfigError(f"capture file missing: {path}; create one with `make capture-gdelt` (network, throttled) or point EVENTSHOCK_CAPTURE_PATH at a file of GDELT DOC lines")
        lines = [ln.obj for ln in iter_jsonl(path, path.name) if ln.obj is not None]
        stamped = [(parse_seendate(r.get("seendate")), r) for r in lines]
        self._pending = [r for t, r in sorted((x for x in stamped if x[0] is not None), key=lambda x: x[0])]  # type: ignore[arg-type,return-value]
        self._batch = cfg.batch_size

    def poll(self) -> LivePoll:
        batch, self._pending = self._pending[: self._batch], self._pending[self._batch:]
        if not batch:
            return LivePoll(self.mode, datetime.now(UTC), exhausted=True)
        clock = max(t for t in (parse_seendate(r.get("seendate")) for r in batch) if t is not None)
        return LivePoll(self.mode, clock, batch, queries_ok=1, exhausted=not self._pending)


class CombinedSource:
    """Several live sources polled together as one: their records and documents are merged, and one source failing does not fail the poll.

    The poll fails only when every part failed (so the feed shows DEGRADED, not ERROR, while one source still delivers). Errors keep the
    name of the source that raised them.
    """

    kind = "both"

    def __init__(self, parts: list[LiveSource]) -> None:
        if len(parts) < 2:
            raise ValueError("a combined source needs at least two sources")
        self.parts = parts
        self.mode = "+".join(p.mode for p in parts)
        self.interval_seconds = None

    def poll(self) -> LivePoll:
        polls: list[LivePoll] = []
        errors: list[str] = []
        for part in self.parts:
            try:
                polls.append(part.poll())
            except Exception as exc:  # noqa: BLE001 (one source's bug must not stop the others)
                errors.append(f"{part.mode}: {type(exc).__name__}: {exc}")
        merged = LivePoll(self.mode, max((p.clock for p in polls), default=datetime.now(UTC)))
        merged_notes: list[str] = []
        for p in polls:
            merged.records += p.records
            merged.documents += p.documents
            if p.note:
                merged_notes.append(p.note)
            merged.queries_ok += p.queries_ok
            merged.queries_failed += p.queries_failed
            errors += [f"{p.mode}: {e}" for e in p.errors]
        merged.queries_failed += len(self.parts) - len(polls)
        merged.errors = errors
        merged.note = " · ".join(merged_notes) or None
        return merged
