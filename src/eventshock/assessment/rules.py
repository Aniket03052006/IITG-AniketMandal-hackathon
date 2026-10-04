"""The deterministic extractor: cue phrases over the closed vocabulary, anchored to the trained models' readings.

This is both the no-key demo mode and the fallback when an LLM call fails. It reads only the text and the ``Reference`` (what the trained
pipeline already said); everything it reports is found verbatim in the text, so every claim has a quotable span.

Policy (kept simple on purpose, and shown to the user as ``ExtractionInfo.basis``):

* Event class: the trained event model keeps authority for a CLASSIFIED text unless the cues point elsewhere with weight >= 2 (one multi-word
  phrase, or two single words). Without a trained reading the cues decide; with neither, the text is not called an event.
* Tone: the trained sentiment model's score, unchanged. (No second, home-made sentiment rule is invented here.)
* Entities: the entity master's match, institutions from a small configured list, and a company-looking name at the start of a headline.
  Only the entity master can make an *issuer*; the others are mentions with ``resolved=False``.
"""

from __future__ import annotations

import re

from ..domain import EventCategory
from ..pipeline.scope import ScopeResolver
from .cues import cue_pattern, cue_weight, find_cue
from .model import (
    AssessedEntity,
    EvidenceSpan,
    ExtractionInfo,
    ExtractionMode,
    IndicatorHit,
    SemanticReading,
)
from .reference import Reference
from .vocab import NO_EVENT, OTHER, Vocab, primary_issuer

_NAME = r"[A-Z][\w&'.\-]*"
_ORG_SUFFIX = re.compile(rf"((?:{_NAME}\s+){{1,3}}(?:Inc|Corp|Corporation|Co|Ltd|plc|PLC|LLC|Group|Holdings|Bancorp))\b")
_OVERRIDE_WEIGHT = 2


class RuleExtractor:
    def __init__(self, vocab: Vocab, scope: ScopeResolver, *, max_quotes: int = 6, max_entities: int = 8) -> None:
        self.vocab, self._scope = vocab, scope
        self._max_quotes, self._max_entities = max_quotes, max_entities
        verbs = "|".join(re.escape(v) for v in vocab.cfg.org_verbs)
        self._lead_org = re.compile(rf"^(?:(?:The|A|An)\s+)?({_NAME}(?:\s+{_NAME}){{0,3}})\s+(?:{verbs})\b")
        self._not_org = {w.lower() for w in vocab.cfg.not_organisations}
        self._institutions = vocab.cfg.institutions
        for ind in vocab.cfg.indicators.values():  # a cue that cannot be compiled fails here, at start-up
            for cue in ind.cues:
                cue_pattern(cue)
        for subs in vocab.cfg.subtypes.values():
            for st in subs:
                for cue in st.cues:
                    cue_pattern(cue)

    # -------------------------------------------------------------------------------------------------------------------- API
    def extract(self, text: str, ref: Reference | None = None) -> tuple[SemanticReading, ExtractionInfo]:
        ref = ref or Reference()
        notes: list[str] = []
        indicators, ind_spans = self._indicators(text)
        event_type, subtype, evid_cues, basis = self._event(text, ref, notes)
        entities, ent_spans = self._entities(text, ref)
        sectors, sec_spans = self._sectors(text, ref)
        regions, reg_spans = self._regions(text, ref)
        assets = self._assets(indicators, ref)
        score = ref.sentiment if ref.sentiment is not None else 0.0
        if ref.sentiment is None:
            notes.append("No trained tone reading was available: tone is reported as neutral (0.0) rather than guessed.")
        confidence = self._event_confidence(event_type, ref)
        spans = self._spans([*evid_cues, *ind_spans, *ent_spans, *sec_spans, *reg_spans])
        v = self.vocab
        reading = SemanticReading(
            text=text, event_type=event_type, event_label=v.event_label(event_type), event_subtype=subtype,
            event_subtype_label=v.subtype_label(event_type, subtype), event_confidence=confidence, sentiment=score,
            sentiment_label=v.sentiment_label(score), sentiment_intensity=v.sentiment_intensity(score),
            sentiment_confidence=ref.sentiment_confidence, entities=entities, primary_issuer=primary_issuer(ref), sectors=sectors,
            regions=regions, asset_classes=assets, severity_indicators=indicators,
            uncertainty=None if confidence is None else round(1.0 - confidence, 4), evidence=spans, rationale=None)
        info = ExtractionInfo(
            mode=ExtractionMode.RULES, model_id=v.cfg.version, vocabulary_version=v.cfg.version, notes=notes, basis=basis)
        return reading, info

    # ------------------------------------------------------------------------------------------------------------------ pieces
    @staticmethod
    def _names(text: str, name: str) -> bool:
        """``name`` written exactly so (case-sensitive: "Fed" is an institution, "fed" is not) as a whole word."""
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text) is not None

    def _indicators(self, text: str) -> tuple[list[IndicatorHit], list[EvidenceSpan]]:
        hits, spans = [], []
        for iid, ind in self.vocab.cfg.indicators.items():
            for cue in ind.cues:
                pos = find_cue(text, cue)
                if pos:
                    hits.append(IndicatorHit(id=iid, label=ind.label, weight=ind.weight, quote=text[pos[0]:pos[1]]))
                    spans.append(EvidenceSpan(quote=text[pos[0]:pos[1]], start=pos[0], end=pos[1], supports="severity"))
                    break
        return hits, spans

    def _event(self, text: str, ref: Reference, notes: list[str]) -> tuple[str, str, list[EvidenceSpan], str]:
        """(event_type, subtype, spans of the cues that decided it, basis sentence)."""
        best: tuple[int, EventCategory, str, list[str]] | None = None
        per_cat: dict[EventCategory, tuple[int, str, list[str]]] = {}
        for cat, subs in self.vocab.cfg.subtypes.items():
            for st in subs:
                matched = [c for c in st.cues if find_cue(text, c)]
                w = sum(cue_weight(c) for c in matched)
                if w and (cat not in per_cat or w > per_cat[cat][0]):
                    per_cat[cat] = (w, st.id, matched)
        if per_cat:
            order = list(EventCategory)
            cat, (w, sid, matched) = max(per_cat.items(), key=lambda kv: (kv[1][0], kv[0].value == ref.event_category, -order.index(kv[0])))
            best = (w, cat, sid, matched)
        ref_cat = EventCategory(ref.event_category) if ref.event_category else None

        def spans_for(cues: list[str]) -> list[EvidenceSpan]:
            out = []
            for c in cues:
                pos = find_cue(text, c)
                if pos:
                    out.append(EvidenceSpan(quote=text[pos[0]:pos[1]], start=pos[0], end=pos[1], supports="event_type"))
            return out

        if ref.event_status == "NO_EVENT" and not (best and best[0] >= _OVERRIDE_WEIGHT):
            return NO_EVENT, OTHER, [], "The trained event model judged this text not to be a market event, and no strong cue phrase disagrees."
        if ref.event_is_finding and ref_cat is not None:
            if best and best[1] is not ref_cat and best[0] >= _OVERRIDE_WEIGHT:
                notes.append(f"Cue phrases ({', '.join(best[3])}) point to {best[1].value} with more weight than the trained model's {ref_cat.value}; the cues were used.")
                return best[1].value, best[2], spans_for(best[3]), "Event class and subtype from cue phrases in the text (they outweighed the trained model)."
            sid = self._subtype_in(text, ref_cat)
            return ref_cat.value, sid[0], spans_for(sid[1]), "Event class from the trained event model; subtype from cue phrases in the text."
        if best:
            return best[1].value, best[2], spans_for(best[3]), "Event class and subtype from cue phrases in the text" + (
                " (the trained model was not confident enough to commit)." if ref_cat else " (no trained reading was available).")
        if ref_cat is not None and ref.event_status == "UNCERTAIN":
            return NO_EVENT, OTHER, [], "The trained event model would not commit to a class and no cue phrase settles it: not called an event."
        return NO_EVENT, OTHER, [], "No cue phrase or trained reading identifies a market event."

    def _subtype_in(self, text: str, cat: EventCategory) -> tuple[str, list[str]]:
        best_id, best_w, best_cues = OTHER, 0, []
        for st in self.vocab.cfg.subtypes[cat]:
            matched = [c for c in st.cues if find_cue(text, c)]
            w = sum(cue_weight(c) for c in matched)
            if w > best_w:
                best_id, best_w, best_cues = st.id, w, matched
        return best_id, best_cues

    def _event_confidence(self, event_type: str, ref: Reference) -> float | None:
        if event_type != NO_EVENT and ref.event_category == event_type and ref.event_confidence is not None:
            return round(float(ref.event_confidence), 4)
        return None  # the cues decided against (or without) a trained reading: there is no calibrated probability to quote

    def _entities(self, text: str, ref: Reference) -> tuple[list[AssessedEntity], list[EvidenceSpan]]:
        out: list[AssessedEntity] = []
        spans: list[EvidenceSpan] = []
        seen: set[str] = set()

        def add(e: AssessedEntity) -> None:
            key = e.name.lower()
            pos = text.find(e.name)
            if pos < 0:
                pos = text.lower().find(key)
            if key in seen or pos < 0 or len(out) >= self._max_entities:
                return
            seen.add(key)
            out.append(e)
            spans.append(EvidenceSpan(quote=text[pos:pos + len(e.name)], start=pos, end=pos + len(e.name), supports="entity"))

        ent, audit = ref.entity, ref.entity_audit
        if ent is not None and not ent.is_unknown:
            surface = (audit.matched_text if audit and audit.matched_text else ent.entity_name) or ent.entity_id
            add(AssessedEntity(name=surface, kind="COMPANY", role="subject", resolved=True, entity_id=ent.entity_id,
                               ticker=ent.ticker, sector=ent.sector))
            for c in (audit.candidates if audit else []):
                if c.entity_id != ent.entity_id:
                    add(AssessedEntity(name=c.matched_text, kind="COMPANY", role="mentioned", resolved=True, entity_id=c.entity_id))
        for inst in self._institutions:
            if self._names(text, inst.name):
                add(AssessedEntity(name=inst.name, kind=inst.kind, role="mentioned", resolved=False))
        if ent is None or ent.is_unknown:
            m = self._lead_org.match(text)
            name = m.group(1) if m else None
            if name and name.lower() not in self._not_org and not any(name.lower() == i.name.lower() for i in self._institutions):
                add(AssessedEntity(name=name, kind="COMPANY", role="subject", resolved=False))
            else:
                s = _ORG_SUFFIX.search(text)
                if s and s.group(1).split()[0].lower() not in self._not_org:
                    add(AssessedEntity(name=s.group(1), kind="COMPANY", role="subject", resolved=False))
        return out, spans

    def _sectors(self, text: str, ref: Reference) -> tuple[list[str], list[EvidenceSpan]]:
        hits = self._scope.sector_hits(text)
        ranked = [k for k, _ in sorted(hits.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
        spans = []
        for k in ranked:
            for term in hits[k][:1]:
                pos = find_cue(text, term)
                if pos:
                    spans.append(EvidenceSpan(quote=text[pos[0]:pos[1]], start=pos[0], end=pos[1], supports="sector"))
        ent = ref.entity
        if ent is not None and not ent.is_unknown and ent.sector and ent.sector not in ranked:
            ranked.insert(0, ent.sector)
        return ranked, spans

    def _regions(self, text: str, ref: Reference) -> tuple[list[str], list[EvidenceSpan]]:
        hits = self._scope.region_hits(text)
        regions = sorted(hits)
        spans = []
        for k in regions:
            pos = find_cue(text, hits[k][0])
            if pos:
                spans.append(EvidenceSpan(quote=text[pos[0]:pos[1]], start=pos[0], end=pos[1], supports="region"))
        for inst in self._institutions:
            if inst.region and inst.region not in regions and self._names(text, inst.name):
                regions.append(inst.region)
                pos = text.find(inst.name)
                spans.append(EvidenceSpan(quote=inst.name, start=pos, end=pos + len(inst.name), supports="region"))
        ent = ref.entity
        if ent is not None and not ent.is_unknown and ent.country and ent.country not in regions:
            regions.append(ent.country)
        return sorted(regions), spans

    def _assets(self, indicators: list[IndicatorHit], ref: Reference) -> list[str]:
        want: set[str] = set()
        for h in indicators:
            want.update(self.vocab.cfg.indicators[h.id].assets)
        if ref.entity is not None and not ref.entity.is_unknown and indicators:
            want.add("EQUITY")
        return [a for a in self.vocab.cfg.asset_classes if a in want]

    def _spans(self, spans: list[EvidenceSpan]) -> list[EvidenceSpan]:
        seen: set[tuple[int, int, str]] = set()
        out = []
        for s in sorted(spans, key=lambda s: (s.start, s.end)):
            k = (s.start, s.end, s.supports)
            if k not in seen:
                seen.add(k)
                out.append(s)
        return out[: self._max_quotes * 2]
