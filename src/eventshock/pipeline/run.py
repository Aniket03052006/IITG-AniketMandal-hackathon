"""The ingestion pipeline: records -> normalise -> validate -> resolve entity -> cluster -> enrich -> RiskSignal.

``run_documents`` is a pure function of its arguments (no clock, no randomness, no I/O); ``run_snapshot``
adds only the reading of a verified local snapshot. Every input record ends in exactly one place: the
quarantine, a folded exact duplicate, or a report inside a signal.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..domain import (
    UNKNOWN_ENTITY,
    CorroboratingSource,
    DedupAudit,
    DedupMember,
    DedupRelation,
    Entity,
    Evidence,
    ModelVersions,
    RawDocument,
    RiskSignal,
    SignalProvenance,
    SignalStatus,
    TimestampOrigin,
)
from ..ingestion.base import RejectCode, Rejected
from ..ingestion.gdelt import GdeltAdapter
from ..ingestion.snapshot import Snapshot
from ..ingestion.tfn import TfnAdapter
from .config import EnrichmentConfig, PipelineConfig
from .dedup import Cluster, Item, cluster_items
from .enrich import Enricher, EnrichmentInput, PlaceholderEnricher
from .entities import EntityResolver
from .models import FetchQuery, PipelineCounts, PipelineReport, QuarantinedRecord, SourceReport
from .normalize import canonical_url, clean_text
from .validate import validate_document

PIPELINE_VERSION = "pipeline-2.0"
QUARANTINE_SAMPLE = 60


@dataclass
class PipelineResult:
    signals: list[RiskSignal]
    quarantined: list[QuarantinedRecord]
    clusters: list[Cluster]
    report: PipelineReport


@dataclass(frozen=True)
class SourceMeta:
    name: str
    source_type: object
    license: str = ""
    attribution: str = ""
    origin_url: str = ""
    notes: str = ""


def _origin(doc: RawDocument) -> TimestampOrigin:
    try:
        return TimestampOrigin(doc.raw_metadata.get("timestamp_origin", TimestampOrigin.SOURCE))
    except ValueError:
        return TimestampOrigin.SOURCE


def _normalise(doc: RawDocument) -> RawDocument | tuple[RejectCode, str]:
    headline, body = clean_text(doc.headline), clean_text(doc.body)
    url = doc.url
    if url is not None:
        if canonical_url(url) is None:
            return RejectCode.BAD_URL, f"unusable URL {url[:80]!r}"
        url = url.strip()
    return doc.model_copy(update={"headline": headline, "body": body, "url": url})


def _digest(signals: Iterable[RiskSignal]) -> str:
    payload = json.dumps([s.model_dump(mode="json") for s in sorted(signals, key=lambda s: s.id)],
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sid(prefix: str, doc_id: str) -> str:
    return f"{prefix}_{hashlib.sha1(doc_id.encode()).hexdigest()[:10]}"  # noqa: S324


def run_documents(
    records: Iterable[RawDocument | Rejected],
    *,
    snapshot_id: str,
    description: str = "",
    as_of: datetime,
    window_start: datetime,
    window_end: datetime,
    entities: list[Entity],
    cfg: PipelineConfig,
    enrich_cfg: EnrichmentConfig,
    sources: list[SourceMeta] | None = None,
    enricher: Enricher | None = None,
) -> PipelineResult:
    resolver = EntityResolver(entities, cfg.entity_resolution)
    enricher = enricher or PlaceholderEnricher(enrich_cfg)
    enrich_version = getattr(enricher, "version", enrich_cfg.version)

    quarantined: list[QuarantinedRecord] = []
    per_source: dict[str, Counter] = {}
    items: list[Item] = []
    audits: dict[str, object] = {}
    mentions: dict[str, object] = {}

    def bump(source: str, key: str, n: int = 1) -> None:
        per_source.setdefault(source, Counter())[key] += n

    for rec in records:
        if isinstance(rec, Rejected):
            bump(rec.source, "records")
            bump(rec.source, "quarantined")
            quarantined.append(QuarantinedRecord(source=rec.source, record_ref=rec.record_ref, code=rec.code.value,
                                                 detail=rec.detail, preview=rec.preview))
            continue
        src = str(rec.raw_metadata.get("adapter", rec.source))
        bump(src, "records")
        ref = str(rec.raw_metadata.get("record_ref", rec.id))
        norm = _normalise(rec)
        problem = norm if isinstance(norm, tuple) else validate_document(
            norm, cfg=cfg.validation, as_of=as_of, window_start=window_start, window_end=window_end,
            timestamp_origin=_origin(rec))
        if problem is not None:
            code, detail = problem
            bump(src, "quarantined")
            quarantined.append(QuarantinedRecord(source=src, record_ref=ref, code=code.value, detail=detail,
                                                 preview=rec.headline[:120]))
            continue
        doc: RawDocument = norm  # type: ignore[assignment]
        unscorable = enricher.unscorable(f"{doc.headline} {doc.body}".strip())
        if unscorable:  # the enrichment stage has nothing to score: quarantine, never invent a value
            bump(src, "quarantined")
            quarantined.append(QuarantinedRecord(source=src, record_ref=ref, code=RejectCode.UNSCORABLE_TEXT.value,
                                                 detail=unscorable, preview=rec.headline[:120]))
            continue
        mention, audit = resolver.resolve(f"{doc.headline} {doc.body}".strip())
        audits[doc.id], mentions[doc.id] = audit, mention
        items.append(Item.build(doc, mention.entity_id, _origin(rec)))
        bump(src, "accepted")

    clusters = cluster_items(items, cfg.dedup)
    signals = [_build_signal(c, mentions, audits, resolver, enricher, enrich_version, snapshot_id, as_of)
               for c in clusters]
    # novelty needs the other clusters, so it is filled in a second pass
    signals = _apply_novelty(signals, clusters)

    for c in clusters:
        src = str(c.canonical.doc.raw_metadata.get("adapter", c.canonical.doc.source))
        bump(src, "signals")
        for m in c.exact:
            bump(str(m.item.doc.raw_metadata.get("adapter", m.item.doc.source)), "exact_dups")

    report = _report(snapshot_id, description, as_of, window_start, window_end, resolver.version, enrich_version,
                     signals, clusters, quarantined, per_source, audits, sources or [], enricher.report_stage_origins)
    return PipelineResult(signals=signals, quarantined=quarantined, clusters=clusters, report=report)


def _build_signal(c: Cluster, mentions: dict, audits: dict, resolver: EntityResolver, enricher: Enricher,
                  enrich_version: str, snapshot_id: str, as_of: datetime) -> RiskSignal:
    canon = c.canonical
    doc = canon.doc
    mention, audit = mentions[doc.id], audits[doc.id]
    reports = c.reports
    domains = c.domains
    text = f"{doc.headline} {doc.body}".strip()
    enr = enricher.enrich(EnrichmentInput(text=text, source_label=doc.raw_metadata.get("source_label"),
                                          unique_domains=len(domains)))

    trusted = sorted(i.doc.published_at for i in c.all_items if i.trusted)
    recent = sum(1 for t in trusted if as_of - timedelta(hours=24) <= t <= as_of)
    span_h = max(1.0, (trusted[-1] - trusted[0]).total_seconds() / 3600) if trusted else 1.0
    velocity = round(len(c.all_items) / span_h, 4) if trusted else 0.0

    members = sorted(c.members, key=lambda m: m.item.sort_key)
    cluster_id = _sid("cl", doc.id)
    return RiskSignal(
        id=_sid("sig", doc.id),
        document=doc,
        entity=mention,
        sentiment=enr.sentiment,
        event=enr.event,
        impact=enr.impact,
        evidence=Evidence(
            source_count=len(reports), unique_domain_count=len(domains), recent_mention_count=recent,
            coverage_velocity=velocity, novelty_score=1.0, model_confidence=round(enr.event.confidence, 4),
            contradicted_by=[],
            corroborating=[
                CorroboratingSource(source=m.item.doc.source, source_type=m.item.doc.source_type,
                                    published_at=m.item.doc.published_at, headline=m.item.doc.headline,
                                    url=m.item.doc.url, relation=m.relation.value)
                for m in members
            ],
        ),
        status=SignalStatus.COMPLETE,
        data_origin=enr.data_origin,
        model_versions=ModelVersions(sentiment=enr.versions["sentiment"], event=enr.versions["event"],
                                     impact=enr.versions["impact"], entity_resolver=resolver.version),
        created_at=as_of,
        provenance=SignalProvenance(
            adapter=str(doc.raw_metadata.get("adapter", "unknown")),
            snapshot_id=snapshot_id,
            record_ref=str(doc.raw_metadata.get("record_ref", "")),
            content_sha256=str(doc.raw_metadata.get("content_sha256", "")),
            timestamp_origin=canon.origin,
            pipeline_version=PIPELINE_VERSION,
            entity_audit=audit,
            dedup=DedupAudit(
                cluster_id=cluster_id, member_count=len(reports), exact_duplicates_folded=len(c.exact),
                members=[DedupMember(document_id=m.item.doc.id, source=m.item.doc.source, url=m.item.doc.url,
                                     relation=m.relation, similarity=m.similarity) for m in members]),
            stage_origins=enr.stage_origins,
            sentiment=enr.sentiment_audit,
        ),
    )


def _apply_novelty(signals: list[RiskSignal], clusters: list[Cluster]) -> list[RiskSignal]:
    """Novelty = 1 / (1 + log2(1 + k)), k = earlier trusted clusters for the same known issuer within 72 h."""
    from bisect import bisect_left

    times: dict[str, list[datetime]] = {}
    for c in clusters:
        if c.canonical.trusted and c.canonical.entity_id != UNKNOWN_ENTITY:
            times.setdefault(c.canonical.entity_id, []).append(c.canonical.doc.published_at)
    for v in times.values():
        v.sort()
    out: list[RiskSignal] = []
    for s, c in zip(signals, clusters, strict=True):
        k = 0
        if c.canonical.trusted and s.entity.entity_id != UNKNOWN_ENTITY:
            t = c.canonical.doc.published_at
            ts = times[c.canonical.entity_id]
            k = bisect_left(ts, t) - bisect_left(ts, t - timedelta(hours=72))  # earlier = strictly before t
        novelty = round(1.0 / (1.0 + math.log2(1 + k)), 4)
        out.append(s.model_copy(update={"evidence": s.evidence.model_copy(update={"novelty_score": novelty})}))
    return out


def _report(snapshot_id, description, as_of, w0, w1, resolver_version, enrich_version, signals, clusters,
            quarantined, per_source, audits, metas: list[SourceMeta], stage_origins: dict[str, str]) -> PipelineReport:
    relations = Counter(m.relation for c in clusters for m in c.members)
    exact = sum(len(c.exact) for c in clusters)
    reports_in = sum(len(c.reports) for c in clusters)
    unknown = sum(1 for s in signals if s.entity.entity_id == UNKNOWN_ENTITY)
    all_audits = [audits[i.doc.id] for c in clusters for i in c.all_items]
    counts = PipelineCounts(
        records_read=sum(v["records"] for v in per_source.values()),
        quarantined=len(quarantined),
        accepted=reports_in + exact,
        exact_duplicates_folded=exact,
        reports_in_signals=reports_in,
        signals=len(signals),
        entity_resolved=len(signals) - unknown,
        entity_unknown=unknown,
        multi_entity=sum(1 for a in all_audits if a.multi_entity),
        rejected_ambiguous_mentions=sum(len(a.rejected) for a in all_audits),
        syndicated=relations[DedupRelation.SYNDICATED],
        near_duplicates=relations[DedupRelation.NEAR_DUPLICATE],
        same_event=relations[DedupRelation.SAME_EVENT],
    )
    meta_by = {m.name: m for m in metas}
    sources = []
    for name in sorted(per_source):
        v, m = per_source[name], meta_by.get(name)
        sources.append(SourceReport(
            name=name, source_type=m.source_type if m else "NEWS", license=m.license if m else "",
            attribution=m.attribution if m else "", origin_url=m.origin_url if m else "", notes=m.notes if m else "",
            records=v["records"], quarantined=v["quarantined"], accepted=v["accepted"],
            exact_duplicates_folded=v["exact_dups"], signals=v["signals"]))
    return PipelineReport(
        snapshot_id=snapshot_id, description=description, replay_as_of=as_of, window_start=w0, window_end=w1,
        pipeline_version=PIPELINE_VERSION, entity_resolver_version=resolver_version, enrichment_version=enrich_version,
        output_digest=_digest(signals), counts=counts, sources=sources,
        quarantine_by_code=dict(sorted(Counter(q.code for q in quarantined).items())),
        quarantine_sample=quarantined[:QUARANTINE_SAMPLE],
        stage_origins=stage_origins,
    )


def _make_adapter(name: str, m: Any) -> Any:
    """Adapter registry: manifest ``adapter`` -> reader. Imports are lazy where they would form an import cycle."""
    common = dict(snapshot_id=m.snapshot_id, as_of=m.replay_as_of)
    if name == "gdelt-doc":
        return GdeltAdapter(source_name=name, **common)
    if name == "gdelt-gkg":
        from ..ingestion.gkg import GkgAdapter  # gkg imports pipeline.normalize

        return GkgAdapter(source_name=name, **common)
    if name == "tfn-replay":
        return TfnAdapter(source_name=name, window_start=m.window_start, window_end=m.window_end, **common)
    from ..ingestion import history

    classes = {"stock-tweets": history.StockTweetsAdapter, "headlines": history.HeadlinesAdapter,
               "top-tweets": history.TopTweetsAdapter}
    if name in classes:
        return classes[name](source_name=name, **common)
    raise ValueError(f"no adapter registered for {name!r}")


def read_snapshot(snapshot: Snapshot) -> tuple[list[RawDocument | Rejected], list[SourceMeta]]:
    """Read every source file of a verified snapshot through its adapter (in manifest order)."""
    m = snapshot.manifest
    records: list[RawDocument | Rejected] = []
    metas: list[SourceMeta] = []
    for src in m.sources:
        adapter = _make_adapter(src.adapter, m)
        records.extend(adapter.read(snapshot.source_path(src), src.file))
        metas.append(SourceMeta(src.adapter, src.source_type, src.license, src.attribution, src.origin_url, src.notes))
    return records, metas


def load_entities(path: Path) -> list[Entity]:
    return [Entity.model_validate(e) for e in json.loads(path.read_text(encoding="utf-8"))]


def summarise_fetch_log(entries: list[dict], plan: list[str] | None = None) -> tuple[list[FetchQuery], int]:
    """Collapse the per-attempt download log to one row per query (latest status wins, attempts counted).

    ``plan`` is the request plan that produced the snapshot. A request outside it belongs to an abandoned earlier plan
    (its coverage was re-requested differently): it is counted, not listed. Failures of the current plan are never hidden.
    """
    rows: dict[str, FetchQuery] = {}
    for e in entries:
        q = str(e.get("query", ""))
        prev = rows.get(q)
        ok = e.get("status") == "ok"
        rows[q] = FetchQuery(
            query=q, status="ok" if ok else "error", attempts=(prev.attempts if prev else 0) + 1,
            returned=int(e.get("returned", 0)) if ok else (prev.returned if prev else 0),
            added=int(e.get("added", 0)) if ok else (prev.added if prev else 0),
            last_error="" if ok else str(e.get("error", "")).split("sort=hybridrel: ")[-1][-160:])
    return sorted(rows.values(), key=lambda r: (r.status == "ok", r.query))


def run_snapshot(snapshot: Snapshot, cfg: PipelineConfig, enrich_cfg: EnrichmentConfig,
                 enricher: Enricher | None = None) -> PipelineResult:
    records, metas = read_snapshot(snapshot)
    m = snapshot.manifest
    result = run_documents(
        records, snapshot_id=m.snapshot_id, description=m.description, as_of=m.replay_as_of,
        window_start=m.window_start, window_end=m.window_end, entities=load_entities(snapshot.entities_path()),
        cfg=cfg, enrich_cfg=enrich_cfg, sources=metas, enricher=enricher)
    fetch_log, superseded = summarise_fetch_log(m.fetch_log, m.fetch_plan)
    result.report = result.report.model_copy(update={"fetch_log": fetch_log, "superseded_requests": superseded})
    return result
