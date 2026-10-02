"""Duplicate and same-event clustering. One cluster becomes one signal; other reports become evidence.

Relations (strongest first): same canonical URL / same text on the same outlet -> EXACT_DUPLICATE (folded,
never counted as a report); same text on another outlet -> SYNDICATED; token Jaccard >= near threshold ->
NEAR_DUPLICATE; lower overlap, same known issuer, close trusted timestamps -> SAME_EVENT.

Clusters are *stars*: a document joins a cluster by relating to its canonical (earliest) document, never to
an arbitrary member, so a chain of weak links cannot merge unrelated stories. Documents are only compared
within the same resolved entity. Timestamps that the replay assigned (SYNTHETIC_REPLAY_CLOCK) are never
used for time-window decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from ..domain import TRUSTED_TIMESTAMPS, UNKNOWN_ENTITY, DedupRelation, RawDocument, TimestampOrigin
from .config import DedupConfig
from .normalize import canonical_url, content_tokens, dedup_key, domain_of, jaccard


@dataclass(frozen=True)
class Item:
    """A validated, entity-resolved document ready for clustering."""

    doc: RawDocument
    entity_id: str
    origin: TimestampOrigin
    key: str
    tokens: frozenset[str]
    canon_url: str | None
    domain: str

    @staticmethod
    def build(doc: RawDocument, entity_id: str, origin: TimestampOrigin) -> Item:
        text = f"{doc.headline} {doc.body}".strip()
        domain = doc.raw_metadata.get("domain") or domain_of(doc.url) or doc.source
        return Item(doc, entity_id, origin, dedup_key(text), content_tokens(text),
                    canonical_url(doc.url) if doc.url else None, str(domain).lower())

    @property
    def trusted(self) -> bool:
        return self.origin in TRUSTED_TIMESTAMPS

    @property
    def sort_key(self) -> tuple:
        # total order: ties on time and id (e.g. one URL in two sources) fall back to source and record position
        md = self.doc.raw_metadata
        return (self.doc.published_at, self.doc.id, str(md.get("adapter", "")), str(md.get("record_ref", "")))


@dataclass
class Member:
    item: Item
    relation: DedupRelation
    similarity: float


@dataclass
class Cluster:
    canonical: Item
    members: list[Member] = field(default_factory=list)  # non-exact reports, excluding the canonical
    exact: list[Member] = field(default_factory=list)  # folded exact duplicates

    @property
    def reports(self) -> list[Item]:
        return [self.canonical, *(m.item for m in self.members)]

    @property
    def domains(self) -> set[str]:
        return {i.domain for i in self.reports}

    @property
    def all_items(self) -> list[Item]:
        return [*self.reports, *(m.item for m in self.exact)]


def relate(a: Item, b: Item, cfg: DedupConfig) -> tuple[DedupRelation, float] | None:
    """Relation of ``b`` (later) to ``a`` (the cluster canonical), or None."""
    if a.canon_url and a.canon_url == b.canon_url:
        return DedupRelation.EXACT_DUPLICATE, 1.0
    both_trusted = a.trusted and b.trusted
    if both_trusted and abs(b.doc.published_at - a.doc.published_at) > timedelta(hours=cfg.window_hours):
        return None
    if a.key and a.key == b.key:
        return (DedupRelation.EXACT_DUPLICATE if a.domain == b.domain else DedupRelation.SYNDICATED), 1.0
    sim = jaccard(a.tokens, b.tokens)
    if sim >= cfg.near_duplicate_threshold:
        return DedupRelation.NEAR_DUPLICATE, sim
    if (
        sim >= cfg.same_event_threshold
        and a.entity_id != UNKNOWN_ENTITY
        and both_trusted
        and len(a.tokens & b.tokens) >= cfg.same_event_min_shared_tokens
        and abs(b.doc.published_at - a.doc.published_at) <= timedelta(hours=cfg.same_event_window_hours)
    ):
        return DedupRelation.SAME_EVENT, sim
    return None


def cluster_items(items: list[Item], cfg: DedupConfig) -> list[Cluster]:
    """Deterministic: items are processed in (published_at, id, ...) order, whatever order they arrive in.

    Candidate clusters come from three indexes instead of a scan: canonical URL, equal text key, and an inverted
    token index (a cluster is a candidate when it shares >= 2 content tokens with the item, or >= 1 for a one-token
    item). Candidates are then tried in cluster-creation order, so the result equals the exhaustive scan except for
    tokens that occur in more than ``cfg.max_posting_length`` clusters of one entity: those are too common to
    discriminate and are ignored when generating candidates (equal URL / equal text still match through their own
    indexes). This keeps 100k+ documents tractable.
    """
    clusters: list[Cluster] = []
    per_entity: dict[str, list[Cluster]] = {}
    by_url: dict[tuple[str, str], list[int]] = {}
    by_key: dict[tuple[str, str], list[int]] = {}
    postings: dict[tuple[str, str], list[int]] = {}
    for item in sorted(items, key=lambda i: i.sort_key):
        block = per_entity.setdefault(item.entity_id, [])
        cand: set[int] = set()
        if item.canon_url:
            cand.update(by_url.get((item.entity_id, item.canon_url), ()))
        if item.key:
            cand.update(by_key.get((item.entity_id, item.key), ()))
        if item.tokens:
            need = min(2, len(item.tokens))
            counts: dict[int, int] = {}
            for tok in item.tokens:
                plist = postings.get((item.entity_id, tok), ())
                if len(plist) > cfg.max_posting_length:
                    continue
                for ci in plist:
                    counts[ci] = counts.get(ci, 0) + 1
            cand.update(ci for ci, n in counts.items() if n >= need)
        for ci in sorted(cand):
            cl = block[ci]
            rel = relate(cl.canonical, item, cfg)
            if rel is None:
                continue
            relation, sim = rel
            (cl.exact if relation is DedupRelation.EXACT_DUPLICATE else cl.members).append(
                Member(item, relation, round(sim, 4)))
            break
        else:
            cl = Cluster(item)
            clusters.append(cl)
            idx = len(block)
            block.append(cl)
            if item.canon_url:
                by_url.setdefault((item.entity_id, item.canon_url), []).append(idx)
            if item.key:
                by_key.setdefault((item.entity_id, item.key), []).append(idx)
            for tok in item.tokens:
                postings.setdefault((item.entity_id, tok), []).append(idx)
    return clusters
