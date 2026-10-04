"""Turn the language model's answer into a ``SemanticReading`` the rest of the system may believe.

The model's claims are checked, not trusted:

* an entity survives only if its name appears in the text; it is ``resolved`` only if the entity master matched it, and it can never become the
  signal's issuer (that comes from the master alone);
* an evidence quote survives only if it is a verbatim excerpt (found by position, so the UI can highlight it);
* every id (event class, subtype, sector, region, asset class, severity indicator) must be in the closed vocabulary, or it is dropped and noted.

What was dropped is returned as ``notes`` and shown to the user: silently cleaning would hide how much of the answer was unusable.
"""

from __future__ import annotations

import re

from ..domain import EventCategory
from ..llm.client import LLMBadOutput
from ..llm.config import GroundingConfig
from ..llm.schema import LLMExtraction
from .cues import find_cue, find_literal
from .model import AssessedEntity, EvidenceSpan, IndicatorHit, SemanticReading
from .reference import Reference
from .vocab import NO_EVENT, OTHER, Vocab, primary_issuer

_KINDS = {"COMPANY", "INSTITUTION", "REGULATOR", "GOVERNMENT", "OTHER"}
_ROLES = {"subject", "counterparty", "mentioned"}
_SUPPORTS = {"event_type", "sentiment", "entity", "sector", "region", "severity"}


def ground(raw: LLMExtraction, text: str, ref: Reference, vocab: Vocab, limits: GroundingConfig) -> tuple[SemanticReading, list[str]]:
    notes: list[str] = []
    allowed_types = {c.value for c in EventCategory} | {NO_EVENT}
    if raw.event_type not in allowed_types:
        raise LLMBadOutput(f"event_type {raw.event_type!r} is not in the taxonomy")
    event_type = raw.event_type
    subtype = vocab.valid_subtype(event_type, raw.event_subtype)
    if subtype != raw.event_subtype and raw.event_subtype != OTHER:
        notes.append(f"Subtype {raw.event_subtype!r} is not defined for {event_type}; reported as unspecified.")

    entities = _entities(raw, text, ref, limits, notes)
    sectors = _pick(raw.sectors, vocab.sectors, "sector", notes)
    regions = _pick(raw.regions, vocab.regions, "region", notes)
    assets = _pick(raw.affected_asset_classes, tuple(vocab.cfg.asset_classes), "asset class", notes)
    indicators = _indicators(raw.severity_indicators, text, vocab, notes)
    spans = _quotes(raw, text, limits, notes)

    score = round(float(raw.sentiment), 4)
    intensity = raw.sentiment_intensity if raw.sentiment_intensity in {"low", "medium", "high"} else vocab.sentiment_intensity(score)
    reading = SemanticReading(
        text=text, event_type=event_type, event_label=vocab.event_label(event_type), event_subtype=subtype,
        event_subtype_label=vocab.subtype_label(event_type, subtype), event_confidence=round(float(raw.event_confidence), 4),
        sentiment=score, sentiment_label=vocab.sentiment_label(score), sentiment_intensity=intensity,
        sentiment_confidence=raw.sentiment_confidence, entities=entities, primary_issuer=primary_issuer(ref), sectors=sectors,
        regions=regions, asset_classes=assets, severity_indicators=indicators, uncertainty=round(float(raw.uncertainty), 4),
        evidence=spans, rationale=(raw.rationale.strip() or None))
    return reading, notes


def _whole(needle: str, hay: str) -> bool:
    """``needle`` inside ``hay`` on word boundaries ("apple" in "apple inc", not in "pineapple co")."""
    return len(needle) >= 4 and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", hay) is not None


def _pick(values: list[str], allowed: tuple[str, ...], what: str, notes: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        if v in allowed:
            if v not in out:
                out.append(v)
        else:
            notes.append(f"Dropped {what} {v!r}: not in the vocabulary.")
    return out


def _indicators(ids: list[str], text: str, vocab: Vocab, notes: list[str]) -> list[IndicatorHit]:
    out: list[IndicatorHit] = []
    for i in ids:
        ind = vocab.cfg.indicators.get(i)
        if ind is None:
            notes.append(f"Dropped severity indicator {i!r}: not in the vocabulary.")
            continue
        if any(h.id == i for h in out):
            continue
        quote = None
        for cue in ind.cues:
            pos = find_cue(text, cue)
            if pos:
                quote = text[pos[0]:pos[1]]
                break
        out.append(IndicatorHit(id=i, label=ind.label, weight=ind.weight, quote=quote))
    return out


def _entities(raw: LLMExtraction, text: str, ref: Reference, limits: GroundingConfig, notes: list[str]) -> list[AssessedEntity]:
    master: dict[str, tuple[str, str | None, str | None, str | None]] = {}  # lower-cased surface -> (entity_id, ticker, sector, name)
    ent, audit = ref.entity, ref.entity_audit
    if ent is not None and not ent.is_unknown:
        for s in filter(None, [ent.entity_name, audit.matched_text if audit else None]):
            master[s.lower()] = (ent.entity_id, ent.ticker, ent.sector, ent.entity_name)
    for c in (audit.candidates if audit else []):
        master.setdefault(c.matched_text.lower(), (c.entity_id, None, None, c.entity_name))
    out: list[AssessedEntity] = []
    for e in raw.entities:
        pos = find_literal(text, e.surface)
        if pos is None:
            notes.append(f"Dropped entity {e.surface!r}: it does not appear in the text.")
            continue
        name = text[pos[0]:pos[1]]
        if any(x.name.lower() == name.lower() for x in out):
            continue
        hit = master.get(name.lower())
        if hit is None and len(name) >= 4:  # "Goldman Sachs" for "The Goldman Sachs Group, Inc.": a name inside a master name is that entity
            low = name.lower()
            hit = next((v for k, v in master.items() if _whole(low, k) or _whole(k, low)), None)
        kind = e.kind if e.kind in _KINDS else "OTHER"
        role = e.role if e.role in _ROLES else "mentioned"
        if hit:
            out.append(AssessedEntity(name=name, kind="COMPANY", role=role, resolved=True, entity_id=hit[0], ticker=hit[1], sector=hit[2]))
        else:
            out.append(AssessedEntity(name=name, kind=kind, role=role, resolved=False))
        if len(out) >= limits.max_entities:
            break
    return out


def _quotes(raw: LLMExtraction, text: str, limits: GroundingConfig, notes: list[str]) -> list[EvidenceSpan]:
    out: list[EvidenceSpan] = []
    dropped = 0
    too_broad = 0
    for q in raw.evidence:
        pos = find_literal(text, q.quote) if len(q.quote.strip()) >= limits.min_quote_chars else None
        if pos is None or q.supports not in _SUPPORTS:
            dropped += 1
            continue
        if len(text) > limits.share_applies_above_chars and (pos[1] - pos[0]) / len(text) > limits.max_quote_share:
            too_broad += 1  # the whole sentence is not evidence of anything in particular
            continue
        span = EvidenceSpan(quote=text[pos[0]:pos[1]], start=pos[0], end=pos[1], supports=q.supports)
        if span not in out:
            out.append(span)
        if len(out) >= limits.max_quotes:
            break
    if dropped:
        notes.append(f"Dropped {dropped} evidence quote(s) that are not verbatim excerpts of the text.")
    if too_broad:
        notes.append(f"Dropped {too_broad} evidence quote(s) that cover nearly the whole text and so point at nothing in particular.")
    return sorted(out, key=lambda s: (s.start, s.end))
