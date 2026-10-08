"""The live feed as a service: configuration, the input journal, polling with back-off, and an honest status.

Design rules (see docs/ARCHITECTURE.md, "Live information"):
* Off unless enabled (at start-up by configuration, or at run time by the switch in the UI: ``set_state``). When on, the only network
  path is ``ingestion.fetch`` (through ``GdeltLiveSource``). Switching off keeps every signal already ingested and starts no new request.
* A failed poll changes the *status*, never the data: no signal is created, no value invented, and the replay signals keep serving.
* Raw inputs are journalled (git-ignored) so a restart is warm and a live session can be replayed through the same engine.
* Everything is bounded: the store caps age and count, the journal is compacted to the retention window at start.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import ConfigError
from ..domain import RawDocument
from ..domain.base import ContractModel
from ..ingestion.live import LivePoll, LiveSource, SourceConfig, to_documents
from ..pipeline.config import UnknownSameEventConfig
from ..pipeline.engine import Outcome, RiskEngine
from ..store import CHANNEL_LIVE, CHANNEL_MANUAL, LiveSignalStore

log = logging.getLogger("eventshock.live")
MAX_BACKOFF_SECONDS = 1800.0
ERROR_AFTER_FAILURES = 3
CAPTURE_RETENTION_HOURS = 24.0 * 365  # a capture's articles are old by design: keep them for the length of the replay
IDLE_TICK_SECONDS = 1.0  # while off (or finished) the loop only checks whether the switch was flipped


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveDedupConfig(_Strict):
    unknown_same_event: UnknownSameEventConfig | None = None


class LiveConfig(_Strict):
    version: str
    enabled: bool = False
    poll_interval_seconds: float = Field(default=300.0, ge=30.0)
    retention_hours: float = Field(default=48.0, gt=0)
    max_signals: int = Field(default=1500, ge=10)
    journal: Path
    source: SourceConfig
    dedup: LiveDedupConfig = LiveDedupConfig()

    @model_validator(mode="after")
    def _journal_is_relative(self) -> LiveConfig:
        if self.journal.is_absolute():
            raise ValueError("journal must be a path relative to the repository root")
        return self


def load_live_config(config_dir: Path) -> LiveConfig:
    path = config_dir / "live.yaml"
    if not path.is_file():
        raise ConfigError(f"missing config file: {path}")
    try:
        return LiveConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc


class LiveUnavailable(Exception):
    """The switch cannot be turned on (no such source, its file is missing, or live does not exist in this profile)."""


class SourceChoice(ContractModel):
    kind: str = Field(description="gdelt | capture")
    label: str
    network: bool = Field(description="turning it on makes outbound requests")
    available: bool
    reason: str | None = Field(description="why it cannot be selected, when it cannot")


class LiveStatus(ContractModel):
    enabled: bool
    state: str = Field(description="OFF | OK | DEGRADED | ERROR | IDLE (a capture has no more batches)")
    source_mode: str | None = Field(description="GDELT (the live API) | CAPTURE (a file replayed as if live: simulated)")
    source_kind: str | None = Field(description="the selected source (gdelt | capture); null while off")
    source_choices: list[SourceChoice] = Field(description="what the switch can turn on, and why a choice is unavailable")
    simulated: bool
    poll_interval_seconds: float | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    next_attempt_at: datetime | None
    last_error: str | None
    last_poll_note: str | None = Field(default=None, description="what the last poll saw, when the source can say (SEC filings listed, recent, matched)")
    consecutive_failures: int
    fetched_total: int
    fetched_by_adapter: dict[str, int] = Field(description="documents received per adapter (gdelt-live, sec-edgar-live): shows which sources actually delivered")
    new_total: int
    updated_total: int
    quarantined_total: int
    live_signal_count: int
    seq: int = Field(description="changes whenever a live signal is added, updated or dropped; clients refetch when it moves")
    retention_hours: float
    event_model: str = Field(description="the event model scoring live text")
    event_model_note: str | None = Field(description="why it is not the served hybrid, when it is not")
    market_context_through: str | None = Field(
        description="last session of the frozen market context; later reports get the labelled placeholder impact")


class Journal:
    """Append-only JSONL of raw inputs (channel + RawDocument). Bounded by compaction at start."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, channel: str, docs: list[RawDocument]) -> None:
        if not docs:
            return
        lines = "".join(json.dumps({"channel": channel, "doc": d.model_dump(mode="json")}, ensure_ascii=False,
                                   separators=(",", ":")) + "\n" for d in docs)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(lines)

    def load(self, cutoff: datetime) -> list[tuple[str, RawDocument]]:
        """Entries published at or after ``cutoff``, in file order. A damaged line is skipped and logged, never fatal."""
        if not self.path.is_file():
            return []
        out: list[tuple[str, RawDocument]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for n, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    doc = RawDocument.model_validate(rec["doc"])
                    channel = str(rec["channel"])
                except (ValueError, KeyError, TypeError) as exc:
                    log.warning("journal %s line %d skipped: %s", self.path, n, exc)
                    continue
                if doc.published_at >= cutoff:
                    out.append((channel, doc))
        return out

    def compact(self, kept: list[tuple[str, RawDocument]]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".journal.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                for ch, d in kept:
                    fh.write(json.dumps({"channel": ch, "doc": d.model_dump(mode="json")}, ensure_ascii=False, separators=(",", ":")) + "\n")
            os.replace(tmp, self.path)


class LiveService:
    def __init__(self, *, cfg: LiveConfig, engine: RiskEngine, store: LiveSignalStore, source: LiveSource | None,
                 journal: Journal | None, event_model_note: Callable[[], tuple[str, str | None]],
                 market_through: str | None, clock: Callable[[], datetime] | None = None,
                 on_applied: Callable[[datetime], None] | None = None,
                 source_factory: Callable[[str], LiveSource] | None = None,
                 source_choices: Callable[[], list[SourceChoice]] | None = None) -> None:
        self.cfg, self.engine, self.store, self.source, self.journal = cfg, engine, store, source, journal
        self._source_factory = source_factory  # builds a source by kind when the switch is turned on (None: the switch is not offered)
        self._source_choices = source_choices or (lambda: [])
        self._switch_lock = threading.Lock()
        self._generation = 0  # counts switch flips, so a sleeping poll loop notices at once
        self.on_applied = on_applied  # called with the poll's clock after a poll was applied; a failure in it is logged, never raised into the poller
        self._event_model_note = event_model_note
        self._market_through = market_through
        self._clock = clock or (lambda: datetime.now(UTC))
        self._poll_lock = threading.Lock()
        self._state = "OFF" if source is None else "IDLE"
        self._last_attempt: datetime | None = None
        self._last_success: datetime | None = None
        self._next: datetime | None = None
        self._last_error: str | None = None
        self._failures = 0
        self._fetched = self._new = self._updated = self._quarantined = 0
        self._by_adapter: dict[str, int] = {}
        self._note: str | None = None
        self._exhausted = False

    # ------------------------------------------------------------------------------------------------------------ status
    def status(self) -> LiveStatus:
        model, note = self._event_model_note()
        mode = self.source.mode if self.source else None
        return LiveStatus(
            enabled=self.source is not None, state=self._state, source_mode=mode, source_kind=getattr(self.source, "kind", mode.lower()) if self.source else None,
            source_choices=self._source_choices(), simulated=mode == "CAPTURE",
            poll_interval_seconds=((getattr(self.source, "interval_seconds", None) or self.cfg.poll_interval_seconds)
                                   if self.source else None), last_attempt_at=self._last_attempt,
            last_success_at=self._last_success, next_attempt_at=self._next, last_error=self._last_error, last_poll_note=self._note,
            consecutive_failures=self._failures, fetched_total=self._fetched, fetched_by_adapter=dict(self._by_adapter), new_total=self._new, updated_total=self._updated,
            quarantined_total=self._quarantined, live_signal_count=len(self.store), seq=self.store.seq,
            retention_hours=self.cfg.retention_hours, event_model=model, event_model_note=note,
            market_context_through=self._market_through)

    # ------------------------------------------------------------------------------------------------------------ the switch
    def set_state(self, enabled: bool, kind: str | None = None) -> LiveStatus:
        """Turn the feed on (with ``kind``, default the first available choice) or off. Idempotent.

        Off keeps every signal already ingested and starts no further request; a request already in flight finishes but its result
        is discarded (see ``refresh``). On builds a fresh source, so a capture starts from its first batch. A source that cannot be
        built leaves the feed OFF and raises ``LiveUnavailable`` with the reason: nothing is half-started.
        """
        with self._switch_lock:
            if not enabled:
                self._generation += 1
                self.source, self._state, self._next, self._exhausted = None, "OFF", None, False
                self._failures, self._last_error, self._note = 0, None, None
                return self.status()
            if self._source_factory is None:
                raise LiveUnavailable("the live feed is not available in this profile")
            choices = {c.kind: c for c in self._source_choices()}
            wanted = kind or next((c.kind for c in choices.values() if c.available), None)
            if wanted is None or wanted not in choices:
                raise LiveUnavailable(f"unknown live source {kind!r}; choices: {', '.join(choices) or 'none'}")
            if not choices[wanted].available:
                raise LiveUnavailable(choices[wanted].reason or f"the {wanted} source is not available")
            try:
                source = self._source_factory(wanted)
            except ConfigError as exc:
                self._last_error = str(exc)
                raise LiveUnavailable(str(exc)) from exc
            self.store.retention = timedelta(hours=max(self.cfg.retention_hours, CAPTURE_RETENTION_HOURS)
                                             if source.mode == "CAPTURE" else self.cfg.retention_hours)
            self._generation += 1
            self.source, self._state, self._next, self._exhausted = source, "IDLE", None, False
            self._failures, self._last_error, self._note = 0, None, None
            return self.status()

    # ------------------------------------------------------------------------------------------------------------- polling
    def refresh(self) -> LiveStatus:
        """Poll once (blocking). Failures are recorded, not raised; the data already served is untouched.

        If the switch was flipped while the request was in flight, the result is dropped: a feed that was turned off adds nothing.
        """
        if self.source is None:
            return self.status()
        with self._poll_lock:
            source = self.source
            if source is None:
                return self.status()
            self._last_attempt = self._clock()
            try:
                poll = source.poll()
            except Exception as exc:  # noqa: BLE001 (a source bug must degrade the feed, not kill the poller)
                log.exception("live poll crashed")
                if self.source is source:
                    self._record_failure(f"{type(exc).__name__}: {exc}")
                return self.status()
            if self.source is source:
                self._apply(poll)
            return self.status()

    def _apply(self, poll: LivePoll) -> None:
        if poll.exhausted and not poll.records:
            self._state, self._exhausted = "IDLE", True
            return
        if poll.failed:
            self._record_failure("; ".join(poll.errors)[:300] or "no query succeeded")
            return
        docs = to_documents(poll)
        outcomes = self.engine.ingest(docs, channel=CHANNEL_LIVE, now=poll.clock)
        self._fetched += len(poll.records) + len(poll.documents)
        self._note = poll.note
        for d in docs:
            if isinstance(d, RawDocument):
                adapter = str(d.raw_metadata.get("adapter", "unknown"))
                self._by_adapter[adapter] = self._by_adapter.get(adapter, 0) + 1
        self._new += sum(o.outcome is Outcome.NEW for o in outcomes)
        self._updated += sum(o.outcome is Outcome.UPDATED for o in outcomes)
        self._quarantined += sum(o.outcome is Outcome.QUARANTINED for o in outcomes)
        if self.journal is not None and poll.mode != "CAPTURE":
            self.journal.append(CHANNEL_LIVE, [d for d, o in zip(docs, outcomes, strict=True)
                                               if isinstance(d, RawDocument) and o.outcome is not Outcome.QUARANTINED])
        self._last_success = self._last_attempt
        partial = poll.queries_failed > 0
        self._failures = 0 if not partial else self._failures
        self._last_error = "; ".join(poll.errors)[:300] if partial else None
        self._state = "DEGRADED" if partial else ("IDLE" if poll.exhausted else "OK")
        self._exhausted = poll.exhausted
        self._schedule(0)
        if self.on_applied is not None:
            try:
                self.on_applied(poll.clock)
            except Exception:  # noqa: BLE001 (an observer must never break the feed)
                log.exception("live observer failed")

    def _record_failure(self, error: str) -> None:
        self._failures += 1
        self._last_error = error
        self._state = "ERROR" if (self._failures >= ERROR_AFTER_FAILURES or self._last_success is None) else "DEGRADED"
        self._schedule(self._failures)
        log.warning("live poll failed (%d in a row): %s", self._failures, error)

    def _schedule(self, failures: int) -> None:
        base = getattr(self.source, "interval_seconds", None) or self.cfg.poll_interval_seconds
        delay = min(base * (2 ** failures), MAX_BACKOFF_SECONDS)
        self._next = self._clock() + timedelta(seconds=delay)

    async def run(self, stop: asyncio.Event) -> None:
        """Poll until ``stop`` is set. The blocking poll runs in a worker thread so requests stay responsive.

        The loop lives for the whole process: while the feed is off (or a capture has finished) it only watches the switch, once a
        second, and makes no request. Turning the feed on starts polling at once; turning it off ends the current wait.
        """
        while not stop.is_set():
            if self.source is None or self._exhausted:
                await self._sleep(stop, IDLE_TICK_SECONDS)
                continue
            generation = self._generation
            await asyncio.to_thread(self.refresh)
            if self._exhausted:
                continue
            wait = max(1.0, (self._next - self._clock()).total_seconds()) if self._next else self.cfg.poll_interval_seconds
            waited = 0.0
            while waited < wait and not stop.is_set() and generation == self._generation:
                tick = min(IDLE_TICK_SECONDS, wait - waited)
                await self._sleep(stop, tick)
                waited += tick

    @staticmethod
    async def _sleep(stop: asyncio.Event, seconds: float) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except TimeoutError:
            return

    # ------------------------------------------------------------------------------------------------------------ warm start
    def warm_start(self) -> int:
        """Re-ingest the journal (inputs only: signals are recomputed by the same engine). Returns the documents re-ingested."""
        if self.journal is None:
            return 0
        now = self._clock()
        kept = self.journal.load(now - timedelta(hours=self.cfg.retention_hours))
        self.journal.compact(kept)
        n = 0
        for channel in (CHANNEL_LIVE, CHANNEL_MANUAL):
            docs = [d for ch, d in kept if ch == channel]
            if docs:
                n += len(docs)
                self.engine.ingest(docs, channel=channel, now=now)
        return n
