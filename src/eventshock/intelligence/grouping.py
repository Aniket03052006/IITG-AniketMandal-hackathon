"""Event grouping: many report clusters about one thing become one event, without merging things that only look alike.

The pipeline's dedup already folds copies and same-story reports of one issuer into a *cluster*, which becomes one ``RiskSignal``. That
cannot join reports whose issuer is not resolved, or two clusters of one story that fell outside its window. This module groups
*signals* into *events* on top of that, as a side-car (the signals are not changed).

Rules, all of which must hold for a signal to join an event:

* both clocks are trusted (a replay-assigned or unknown time is never used to decide that two reports are one event) and within
  ``window_hours``;
* the same resolved issuer; or neither names an issuer and they share a vocabulary scope (sector / theme / region);
* the same trained event class (or both are not a classified event);
* IDF-weighted content cosine and shared key facts (numbers, names) above a threshold, stricter when no issuer is named.

An event is a *star* anchored to its earliest signal: a signal relates to the anchor, never to another member, so a chain of weak links
cannot grow a story. Order of arrival does not matter (signals are processed in (time, id) order). Every individual report stays
visible beneath the event, with whether it is an independent outlet or a copy of another's text.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from ..domain import TRUSTED_TIMESTAMPS, UNKNOWN_ENTITY, EventStatus, RiskSignal
from ..pipeline.normalize import content_tokens, domain_of
from .config import IntelligenceConfig
from .textutil import Idf, key_facts


@dataclass(frozen=True)
class GReport:
    id: str
    signal_id: str
    source: str
    source_type: str
    domain: str
    url: str | None
    published_at: datetime
    headline: str
    body: str | None  # only the cluster's first report keeps its body; the others carry their headline
    relation: str  # CANONICAL | SAME_EVENT | NEAR_DUPLICATE | SYNDICATED
    trusted: bool
    independent: bool = False


@dataclass
class Node:
    """One signal (one report cluster) as the grouping sees it."""

    signal: RiskSignal
    bag: frozenset[str]
    facts: frozenset[str]
    tags: frozenset[str]
    trusted: bool
    reports: list[GReport]
    folded_copies: int

    @property
    def time(self) -> datetime:
        return self.signal.document.published_at

    @property
    def entity_id(self) -> str:
        return self.signal.entity.entity_id

    @property
    def classified(self) -> str | None:
        ev = self.signal.event
        return ev.category.value if ev.status is EventStatus.CLASSIFIED else None


@dataclass
class Event:
    id: str
    anchor: Node
    nodes: list[Node] = field(default_factory=list)  # the anchor first

    @property
    def signal_ids(self) -> list[str]:
        return [n.signal.id for n in self.nodes]

    def reports(self) -> list[GReport]:
        out = [r for n in self.nodes for r in n.reports]
        return sorted(out, key=lambda r: (r.published_at, r.id))

    @property
    def trusted(self) -> bool:
        return all(n.trusted for n in self.nodes)


def domain_for(source: str, url: str | None, metadata_domain: object = None) -> str:
    d = domain_of(url) if url else None
    if d:
        return d
    if metadata_domain:
        return str(metadata_domain).lower()
    return (source or "unknown").strip().lower()


def scope_tags(signal: RiskSignal) -> frozenset[str]:
    sc = signal.scope
    tags: set[str] = set()
    if sc is not None:
        if sc.sector:
            tags.add(f"sector:{sc.sector}")
        tags.update(f"theme:{t}" for t in sc.themes)
        tags.update(f"region:{r}" for r in sc.regions)
    return frozenset(tags)


def build_node(signal: RiskSignal, cfg: IntelligenceConfig) -> Node:
    doc = signal.document
    prov = signal.provenance
    trusted = prov is None or prov.timestamp_origin in TRUSTED_TIMESTAMPS
    members = list(prov.dedup.members) if prov else []
    corro = list(signal.evidence.corroborating)
    ids = [m.document_id for m in members] if len(members) == len(corro) else [f"{signal.id}:m{i}" for i in range(len(corro))]
    reports = [GReport(id=doc.id, signal_id=signal.id, source=doc.source, source_type=doc.source_type.value,
                       domain=domain_for(doc.source, doc.url, doc.raw_metadata.get("domain")), url=doc.url, published_at=doc.published_at,
                       headline=doc.headline, body=doc.body or None, relation="CANONICAL", trusted=trusted)]
    for rid, c in zip(ids, corro, strict=True):
        reports.append(GReport(id=rid, signal_id=signal.id, source=c.source, source_type=c.source_type.value, domain=domain_for(c.source, c.url),
                               url=c.url, published_at=c.published_at, headline=c.headline, body=None, relation=c.relation, trusted=trusted))
    text = f"{doc.headline} {doc.body}".strip()
    facts = key_facts(f"{doc.headline}. {doc.body}")
    name_tokens = content_tokens(f"{signal.entity.entity_name or ''} {signal.entity.ticker or ''}") if signal.entity.entity_id != UNKNOWN_ENTITY else frozenset()
    facts = frozenset(f for f in facts if f not in name_tokens)
    return Node(signal=signal, bag=content_tokens(text), facts=facts, tags=scope_tags(signal), trusted=trusted, reports=reports,
                folded_copies=prov.dedup.exact_duplicates_folded if prov else 0)


def relate(anchor: Node, n: Node, idf: Idf, cfg: IntelligenceConfig) -> tuple[float, int] | None:
    """(cosine, shared key facts) when ``n`` belongs with ``anchor``'s event, else None."""
    g = cfg.grouping
    if not (anchor.trusted and n.trusted):
        return None
    if abs((n.time - anchor.time).total_seconds()) > g.window_hours * 3600:
        return None
    if anchor.classified != n.classified:
        return None
    a_known, n_known = anchor.entity_id != UNKNOWN_ENTITY, n.entity_id != UNKNOWN_ENTITY
    if a_known != n_known:
        return None
    if a_known:
        if anchor.entity_id != n.entity_id:
            return None
        min_cos, min_facts = g.min_cosine, g.min_shared_facts
    else:
        if bool(anchor.tags) != bool(n.tags) or (anchor.tags and not (anchor.tags & n.tags)):
            return None
        min_cos, min_facts = g.unresolved_min_cosine, g.unresolved_min_shared_facts
    cos = idf.cosine(anchor.bag, n.bag)
    shared = len(anchor.facts & n.facts)
    if cos < min_cos or shared < min_facts:
        return None
    return cos, shared


class EventIndex:
    """All signals grouped into events. Deterministic: the same signals give the same events whatever order they arrive in."""

    def __init__(self, signals: list[RiskSignal], cfg: IntelligenceConfig) -> None:
        self.cfg = cfg
        nodes = sorted((build_node(s, cfg) for s in signals), key=lambda n: (n.time, n.signal.id))
        self.idf = Idf(n.bag for n in nodes)
        self.nodes: dict[str, Node] = {n.signal.id: n for n in nodes}
        self.events: list[Event] = []
        self._of: dict[str, Event] = {}
        postings: dict[str, list[int]] = {}
        g = cfg.grouping
        for n in nodes:
            ev: Event | None = None
            if n.trusted:
                counts: dict[int, int] = {}
                for tok in n.bag:
                    plist = postings.get(tok, ())
                    if len(plist) > g.max_posting_length:
                        continue
                    for ei in plist:
                        counts[ei] = counts.get(ei, 0) + 1
                need = min(g.min_shared_tokens, max(1, len(n.bag)))
                for ei in sorted(ci for ci, k in counts.items() if k >= need):
                    cand = self.events[ei]
                    if relate(cand.anchor, n, self.idf, cfg) is not None:
                        ev = cand
                        break
            if ev is None:
                ev = Event(id="evt_" + hashlib.sha1(n.reports[0].id.encode()).hexdigest()[:10], anchor=n)  # noqa: S324
                self.events.append(ev)
                for tok in n.bag:
                    postings.setdefault(tok, []).append(len(self.events) - 1)
            ev.nodes.append(n)
            self._of[n.signal.id] = ev
        self._by_id = {e.id: e for e in self.events}
        self._scope_index: dict[str, list[tuple[datetime, Event]]] | None = None

    def event_of(self, signal_id: str) -> Event | None:
        return self._of.get(signal_id)

    def event(self, event_id: str) -> Event | None:
        return self._by_id.get(event_id)

    def priors(self, event: Event, scope_key: str | None, before: datetime, lookback_hours: float) -> list[Event]:
        """Earlier events of the same subject within the look-back, nearest in time first."""
        if scope_key is None:
            return []
        out: list[tuple[datetime, Event]] = []
        for first, e in self._by_scope().get(scope_key, ()):
            if e is event:
                continue
            if first >= before or (before - first).total_seconds() > lookback_hours * 3600:
                continue
            out.append((first, e))
        return [e for _, e in sorted(out, key=lambda fe: fe[0], reverse=True)]

    def _by_scope(self) -> dict[str, list[tuple[datetime, Event]]]:
        """Trusted events by the subject they share (built once: a late-cycle monitor asks for priors of every event, and a scan of all events per call was the cost)."""
        if self._scope_index is None:
            idx: dict[str, list[tuple[datetime, Event]]] = {}
            for e in self.events:
                if not e.trusted:
                    continue
                key = scope_key_of(e.anchor)
                if key is not None:
                    idx.setdefault(key, []).append((min(n.time for n in e.nodes), e))
            self._scope_index = idx
        return self._scope_index


def scope_key_of(node: Node) -> str | None:
    """The subject two events must share to be compared for novelty: the issuer, else the sector / theme / region tags, else None."""
    if node.entity_id != UNKNOWN_ENTITY:
        return f"entity:{node.entity_id}"
    if node.tags:
        return "tags:" + ",".join(sorted(node.tags))
    return None


def mark_independence(reports: list[GReport], copy_relations: set[str]) -> list[GReport]:
    """The first report of each outlet that is not a copy of another's text is independent; everything else is not."""
    seen: set[str] = set()
    out: list[GReport] = []
    for r in sorted(reports, key=lambda r: (r.published_at, r.id)):
        ind = r.relation not in copy_relations and bool(r.domain) and r.domain not in seen
        if ind:
            seen.add(r.domain)
        out.append(GReport(**{**r.__dict__, "independent": ind}))
    return out
