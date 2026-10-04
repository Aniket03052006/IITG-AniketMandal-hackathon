"""The long-lived risk engine: one door for pasted text, live feeds and captures, the same stages as the replay batch.

``run_documents`` turns a fixed list of records into signals once. ``RiskEngine`` does the same incrementally: records arrive,
are prepared by the *same* ``prepare_record``, the bounded window of live reports is re-clustered by the *same* ``cluster_items``,
and only clusters whose membership changed are rebuilt with the *same* ``build_signal`` + novelty + impact post-pass. Nothing
here knows where a record came from; the caller names a ``channel`` ("LIVE", "MANUAL") and the clock (``now``), so a capture can
be replayed with its own time and the engine stays deterministic given its inputs.

Failure policy: a record that cannot be scored is quarantined with the reason, never given a guessed value. If the served event
model cannot embed a new text (no encoder installed) the engine switches, once and visibly, to the reference TF-IDF model; the
model ids on every signal say which one ran.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ..domain import Entity, RawDocument, RiskSignal
from ..ingestion.base import Rejected
from ..store import LiveSignalStore
from .config import EnrichmentConfig, PipelineConfig
from .dedup import Cluster, Item, cluster_items
from .embeddings import EmbeddingUnavailable
from .enrich import Enricher
from .entities import EntityResolver
from .run import PIPELINE_VERSION, _sid, apply_novelty_one, build_signal, novelty_times, prepare_record
from .scope import ScopeResolver

log = logging.getLogger("eventshock.engine")


class Outcome(StrEnum):
    NEW = "NEW"  # a new signal was created
    UPDATED = "UPDATED"  # the report joined an existing signal (more sources for the same event)
    DUPLICATE = "DUPLICATE"  # the same document / the same text again: nothing changed
    QUARANTINED = "QUARANTINED"  # it could not be scored; `detail` says why


@dataclass(frozen=True)
class IngestOutcome:
    document_id: str
    outcome: Outcome
    signal_id: str | None = None
    code: str | None = None
    detail: str | None = None
    relation: str | None = None  # how the report relates to its signal's earliest report (null for NEW)


@dataclass
class EngineStatus:
    """What the engine is running with, for the status endpoints (read-only)."""

    event_model: str
    event_fallback_reason: str | None = None
    ingested: int = 0
    quarantined: int = 0
    last_ingest_at: datetime | None = None


@dataclass
class _Entry:
    item: Item
    mention: object
    audit: object
    channel: str


class RiskEngine:
    def __init__(self, *, entities: list[Entity], pipeline_cfg: PipelineConfig, enrich_cfg: EnrichmentConfig,
                 scope_resolver: ScopeResolver, enricher: Enricher, fallback_enricher: Enricher | None,
                 store: LiveSignalStore, event_model_id: str, fallback_event_model_id: str | None = None,
                 start_on_fallback: bool = False, snapshot_id: str = "live") -> None:
        self._resolver = EntityResolver(entities, pipeline_cfg.entity_resolution)
        self._cfg = pipeline_cfg
        self._enrich_cfg = enrich_cfg
        self._scope = scope_resolver
        self._primary, self._fallback = enricher, fallback_enricher
        self._on_fallback = start_on_fallback and fallback_enricher is not None
        self._enricher: Enricher = fallback_enricher if self._on_fallback else enricher  # type: ignore[assignment]
        self.store = store
        self._snapshot_id = snapshot_id
        self._entries: dict[str, _Entry] = {}  # document id -> entry, the clustering window
        self._doc_signal: dict[str, str] = {}  # document id -> the signal it belongs to
        self._fingerprint: dict[str, tuple] = {}  # signal id -> cluster fingerprint it was built from
        self._lock = threading.RLock()
        self.status = EngineStatus(
            event_model=(fallback_event_model_id if self._on_fallback else event_model_id) or event_model_id,
            event_fallback_reason=("the served event model needs an encoder that is not installed"
                                   if self._on_fallback else None))
        self._fallback_id = fallback_event_model_id

    # ------------------------------------------------------------------------------------------------------------ public
    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def ingest(self, records: Iterable[RawDocument | Rejected], *, channel: str, now: datetime) -> list[IngestOutcome]:
        """Take records in, return what happened to each. Safe to call from several threads (one at a time)."""
        with self._lock:
            return self._ingest(list(records), channel, now)

    # ------------------------------------------------------------------------------------------------------------ internals
    def _window_cfg(self) -> PipelineConfig:
        return self._cfg

    def _ingest(self, records: list[RawDocument | Rejected], channel: str, now: datetime) -> list[IngestOutcome]:
        window_start = now - self.store.retention
        outcomes: dict[int, IngestOutcome] = {}
        fresh: list[tuple[int, _Entry]] = []
        for idx, rec in enumerate(records):
            if isinstance(rec, RawDocument) and rec.id in self._entries:
                outcomes[idx] = IngestOutcome(rec.id, Outcome.DUPLICATE, self._doc_signal.get(rec.id))
                continue
            prep = prepare_record(rec, cfg=self._cfg, as_of=now, window_start=window_start, window_end=now,
                                  resolver=self._resolver, enricher=self._enricher)
            if prep.quarantined is not None:
                self.status.quarantined += 1
                q = prep.quarantined
                outcomes[idx] = IngestOutcome(getattr(rec, "id", q.record_ref), Outcome.QUARANTINED, None, q.code, q.detail)
                continue
            assert prep.item is not None
            if any(e.item.doc.id == prep.item.doc.id for _, e in fresh):  # the same document twice in one batch
                outcomes[idx] = IngestOutcome(prep.item.doc.id, Outcome.DUPLICATE, None)
                continue
            fresh.append((idx, _Entry(prep.item, prep.mention, prep.audit, channel)))
        if not fresh:
            self._expire(now)
            return [outcomes[i] for i in range(len(records))]

        before_ids = set(self._doc_signal.values())
        for _, e in fresh:
            self._entries[e.item.doc.id] = e
        self.status.ingested += len(fresh)
        self.status.last_ingest_at = now
        self._expire(now, keep={e.item.doc.id for _, e in fresh})

        clusters = cluster_items([e.item for e in self._entries.values()], self._cfg.dedup)
        times = novelty_times(clusters)
        mentions = {i: e.mention for i, e in self._entries.items()}
        audits = {i: e.audit for i, e in self._entries.items()}
        new_doc_signal: dict[str, str] = {}
        relation_of: dict[str, str] = {}
        rebuilt: list[RiskSignal] = []
        for c in clusters:
            sid = _sid("sig", c.canonical.doc.id)
            fp = (c.canonical.doc.id, tuple(sorted(m.item.doc.id for m in c.members)),
                  tuple(sorted(m.item.doc.id for m in c.exact)))
            for it in c.all_items:
                new_doc_signal[it.doc.id] = sid
            for m in [*c.members, *c.exact]:
                relation_of[m.item.doc.id] = m.relation.value
            if self._fingerprint.get(sid) == fp and self.store.get(sid) is not None:
                continue
            channel_of_cluster = self._entries[c.canonical.doc.id].channel
            sig = self._build(c, mentions, audits, times, now)
            self._fingerprint[sid] = fp
            self.store.upsert(sig, channel_of_cluster)
            rebuilt.append(sig)

        # a cluster whose earliest report changed has a new id: the old one keeps resolving to it
        current_ids = set(new_doc_signal.values())
        for doc_id, old in self._doc_signal.items():
            new = new_doc_signal.get(doc_id)
            if new and new != old and old not in current_ids:
                self.store.supersede(old, new)
                self._fingerprint.pop(old, None)
        self._doc_signal = new_doc_signal

        for idx, e in fresh:
            did = e.item.doc.id
            sid = self._doc_signal[did]
            rel = relation_of.get(did)
            if rel == "EXACT_DUPLICATE":
                outcomes[idx] = IngestOutcome(did, Outcome.DUPLICATE, sid, relation=rel)
            elif sid in before_ids:
                outcomes[idx] = IngestOutcome(did, Outcome.UPDATED, sid, relation=rel)
            else:
                outcomes[idx] = IngestOutcome(did, Outcome.NEW, sid, relation=rel)
        self.store.evict(now)
        return [outcomes[i] for i in range(len(records))]

    def _build(self, c: Cluster, mentions: dict, audits: dict, times: dict, now: datetime) -> RiskSignal:
        """build_signal + novelty + the impact post-pass, falling back once if the served event model cannot embed this text."""
        for attempt in (0, 1):
            enricher = self._enricher
            try:
                version = getattr(enricher, "version", self._enrich_cfg.version)
                sig = build_signal(c, mentions, audits, self._resolver, enricher, version, self._snapshot_id, now, self._scope)
                sig = apply_novelty_one(sig, c, times)
                refine = getattr(enricher, "refine_impact", None)
                return refine(sig) if refine is not None else sig
            except EmbeddingUnavailable as exc:
                if attempt or self._fallback is None or self._enricher is self._fallback:
                    raise
                log.warning("served event model cannot embed new text (%s): the reference TF-IDF model serves live text from now on", exc)
                self._enricher, self._on_fallback = self._fallback, True
                self.status.event_model = self._fallback_id or "reference"
                self.status.event_fallback_reason = str(exc)
        raise AssertionError("unreachable")

    def _expire(self, now: datetime, keep: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        """Forget window entries older than the store's retention (and cap the window), so memory stays bounded."""
        cutoff = now - self.store.retention
        old = [i for i, e in self._entries.items() if e.item.doc.published_at < cutoff and i not in keep]
        cap = 3 * self.store.max_signals
        if len(self._entries) - len(old) > cap:
            alive = sorted((e.item.doc.published_at, i) for i, e in self._entries.items() if i not in set(old) and i not in keep)
            old += [i for _, i in alive[: len(self._entries) - len(old) - cap]]
        for i in old:
            del self._entries[i]
            self._doc_signal.pop(i, None)
        if old:
            live_ids = set(self._doc_signal.values())
            self._fingerprint = {k: v for k, v in self._fingerprint.items() if k in live_ids}
            self.store.evict(now)

    # -------------------------------------------------------------------------------------------------------- introspection
    @property
    def window_size(self) -> int:
        return len(self._entries)

    @property
    def pipeline_version(self) -> str:
        return PIPELINE_VERSION
