"""Builders for event-intelligence tests: signals with exact texts, times, outlets and corroborating reports, and a service over them."""

from __future__ import annotations

from datetime import datetime, timedelta

from eventshock.config import REPO_ROOT
from eventshock.domain import (
    CorroboratingSource,
    DedupRelation,
    EventCategory,
    EventClassification,
    EventStatus,
    RawDocument,
    RiskSignal,
    SourceType,
    TimestampOrigin,
)
from eventshock.domain.documents import EntityMention
from eventshock.domain.provenance import DedupAudit, DedupMember, EntityAudit, SignalProvenance
from eventshock.intelligence.config import load_intelligence_config
from eventshock.intelligence.scope import HierarchicalScopeResolver
from eventshock.intelligence.service import IntelligenceService
from eventshock.store import CombinedSignalRepository, InMemorySignalRepository, LiveSignalStore
from tests.assess_helpers import SCOPE
from tests.helpers import NOW, make_event, make_signal

CFG = load_intelligence_config(REPO_ROOT / "configs")
BASE = datetime(2026, 9, 1, 9, tzinfo=NOW.tzinfo)

JPM = {"entity_id": "ENT_JPM", "entity_name": "JPMorgan Chase", "ticker": "JPM", "sector": "Financials", "country": "US", "link_confidence": 0.95}
XOM = {"entity_id": "ENT_XOM", "entity_name": "Exxon Mobil", "ticker": "XOM", "sector": "Energy", "country": "US", "link_confidence": 0.95}


def member(source: str, minutes: int, headline: str, *, url: str | None = None, relation: DedupRelation = DedupRelation.SAME_EVENT) -> dict:
    return {"source": source, "minutes": minutes, "headline": headline, "url": url, "relation": relation}


def sig(sid: str, headline: str, body: str = "", *, minutes: int = 0, entity: dict | None = None, category: EventCategory = EventCategory.REGULATORY_LEGAL,
        status: EventStatus = EventStatus.CLASSIFIED, source: str = "Wire A", url: str | None = None, members: list[dict] | None = None,
        origin: TimestampOrigin = TimestampOrigin.SOURCE, sentiment_negative: float = 0.7, with_scope: bool = True) -> RiskSignal:
    """A signal whose first report is ``headline``/``body`` at BASE + ``minutes``; ``members`` are its corroborating reports."""
    t = BASE + timedelta(minutes=minutes)
    ent = EntityMention(**entity) if entity else EntityMention()
    doc = RawDocument(id=f"doc_{sid}", source=source, source_type=SourceType.NEWS, published_at=t, ingested_at=t, headline=headline, body=body, url=url,
                      raw_metadata={"adapter": "test", "record_ref": sid, "content_sha256": "0" * 64})
    members = members or []
    s = make_signal(sid, category=category, entity_id=ent.entity_id)
    ev = make_event(category)
    if status is not EventStatus.CLASSIFIED:
        ev = EventClassification(category=category, probabilities=ev.probabilities, status=status, no_event_probability=0.9 if status is EventStatus.NO_EVENT else None)
    corro = [CorroboratingSource(source=m["source"], source_type=SourceType.NEWS, published_at=BASE + timedelta(minutes=m["minutes"]), headline=m["headline"],
                                 url=m["url"], relation=m["relation"].value) for m in members]
    prov = SignalProvenance(
        adapter="test", snapshot_id="snap", record_ref=sid, content_sha256="0" * 64, timestamp_origin=origin, pipeline_version="t",
        entity_audit=EntityAudit(rule="ALIAS" if entity else "NONE", matched_text=(entity or {}).get("entity_name")), stage_origins={},
        dedup=DedupAudit(cluster_id=f"cl_{sid}", member_count=1 + len(members), exact_duplicates_folded=0,
                         members=[DedupMember(document_id=f"doc_{sid}_m{i}", source=m["source"], url=m["url"], relation=m["relation"], similarity=0.7)
                                  for i, m in enumerate(members)]))
    s = s.model_copy(update={
        "document": doc, "entity": ent, "event": ev,
        "sentiment": s.sentiment.model_copy(update={"negative": sentiment_negative, "positive": 0.1, "neutral": round(0.9 - sentiment_negative, 6),
                                                    "score": round(0.1 - sentiment_negative, 6)}),
        "evidence": s.evidence.model_copy(update={"source_count": 1 + len(members), "unique_domain_count": 1 + len(members), "corroborating": corro}),
        "provenance": prov, "created_at": t})
    if with_scope:
        s = s.model_copy(update={"scope": SCOPE.resolve(f"{headline} {body}".strip(), ent, ev)})
    return s


def repo(signals: list[RiskSignal]) -> CombinedSignalRepository:
    return CombinedSignalRepository(InMemorySignalRepository(signals, BASE + timedelta(days=30)), LiveSignalStore())


def scope_resolver() -> HierarchicalScopeResolver:
    return HierarchicalScopeResolver(CFG, SCOPE)


def service(signals: list[RiskSignal], **kw) -> IntelligenceService:
    return IntelligenceService(CFG, repo(signals), scope_resolver(), clock=lambda: BASE + timedelta(days=1), **kw)


def rep(rid: str, headline: str, *, minutes: int = 0, body: str | None = None, source: str | None = None, domain: str | None = None, signal_id: str = "s",
        relation: str = "SAME_EVENT", trusted: bool = True, independent: bool = True):
    """A bare report (the unit the claim, lifecycle and velocity modules read)."""
    from eventshock.intelligence.grouping import GReport
    src = source or f"Wire {rid}"
    return GReport(id=rid, signal_id=signal_id, source=src, source_type="NEWS", domain=domain or f"{rid.lower()}.example", url=None,
                   published_at=BASE + timedelta(minutes=minutes), headline=headline, body=body, relation=relation, trusted=trusted, independent=independent)
