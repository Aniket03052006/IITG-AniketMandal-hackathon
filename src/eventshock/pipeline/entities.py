"""Entity resolution against the entity master: dictionary first, fuzzy last, UNKNOWN when unsure.

Rules, strongest first: cashtag / exchange-qualified ticker, legal name, strong alias, bare uppercase ticker,
weak alias (an ordinary word such as "Apple" or "Target": case-sensitive and only with finance context or
another strong mention), then a restrained fuzzy match. Everything considered — including what was
refused — is returned in the audit so a human can see why an entity was or was not chosen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from ..domain import UNKNOWN_ENTITY, Entity, EntityAudit, EntityCandidate, EntityMention, RejectedCandidate
from .config import EntityResolutionConfig
from .normalize import match_form

RESOLVER_VERSION_PREFIX = "dictionary"

_LEGAL_SUFFIX = re.compile(
    r",?\s+(?:Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Company|plc|p\.l\.c\.|Group|Holdings|Ltd\.?)$",
    re.IGNORECASE,
)
_CASHTAG = re.compile(r"(?<![A-Za-z0-9$])\$([A-Za-z]{1,5})(?:\.[A-Za-z])?(?![A-Za-z0-9])")
_EXCHANGE = re.compile(r"\b(?:NASDAQ|NYSE|NYSEARCA|AMEX|NYSE American)\s*:\s*([A-Z]{1,5})\b")
_BARE_TICKER = re.compile(r"(?<![A-Za-z0-9$])([A-Z]{3,5})(?![A-Za-z0-9])")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z&'’\-]+")


@dataclass(frozen=True)
class _Phrase:
    entity_id: str
    text: str  # original-case alias, shown in the audit
    rule: str  # LEGAL_NAME | ALIAS


@dataclass(frozen=True)
class _Hit:
    entity_id: str
    matched: str
    rule: str
    confidence: float
    pos: int


def _strip_legal(name: str) -> str:
    prev = None
    while prev != name:
        prev, name = name, _LEGAL_SUFFIX.sub("", name).strip()
    return name


class EntityResolver:
    def __init__(self, entities: list[Entity], cfg: EntityResolutionConfig) -> None:
        self.cfg = cfg
        self.version = f"{RESOLVER_VERSION_PREFIX}-{cfg.version}"
        self._by_id = {e.entity_id: e for e in entities}
        if len(self._by_id) != len(entities):
            raise ValueError("duplicate entity ids in the entity master")
        weak = set(cfg.weak_aliases)
        self._context = re.compile(
            r"(?<![a-z0-9])(?:" + "|".join(re.escape(match_form(w)) for w in cfg.finance_context) + r")(?![a-z0-9])"
        ) if cfg.finance_context else None

        self._neutralisers = [re.compile(p, re.IGNORECASE) for p in cfg.weak_alias_neutralisers]
        self._tickers: dict[str, str] = {}
        strong: dict[str, _Phrase] = {}
        self._weak: dict[str, str] = {}  # surface (case-sensitive) -> entity_id
        for e in entities:
            if e.ticker:
                t = e.ticker.upper()
                if t in self._tickers:
                    raise ValueError(f"ticker {t} belongs to two entities")
                self._tickers[t] = e.entity_id
            surfaces = [(e.name, "LEGAL_NAME"), (_strip_legal(e.name), "LEGAL_NAME"), *((a, "ALIAS") for a in e.aliases)]
            for surface, rule in surfaces:
                if not surface:
                    continue
                if surface in weak:
                    if self._weak.setdefault(surface, e.entity_id) != e.entity_id:
                        raise ValueError(f"weak alias {surface!r} belongs to two entities")
                    continue
                # "Amazon.com" also appears as "Amazon. com" (GDELT word-tokenises titles): index both spellings
                for form in {match_form(surface), match_form(surface.replace(".", " "))}:
                    if len(form) < 2:
                        continue
                    prev = strong.get(form)
                    if prev and prev.entity_id != e.entity_id:
                        raise ValueError(f"alias {surface!r} is shared by {prev.entity_id} and {e.entity_id}")
                    strong.setdefault(form, _Phrase(e.entity_id, surface, rule))
        self._strong = strong
        self._strong_re = (
            re.compile(r"(?<![a-z0-9$])(" + "|".join(re.escape(f) for f in sorted(strong, key=len, reverse=True)) + r")(?![a-z0-9])")
            if strong else None
        )
        self._weak_res = {
            s: re.compile(r"(?<![A-Za-z0-9])" + re.escape(s) + r"(?![A-Za-z0-9])") for s in self._weak
        }
        self._fuzzy_forms = [
            (form, p) for form, p in strong.items() if len(form) >= cfg.fuzzy.min_alias_chars
        ]

    # ------------------------------------------------------------------ public
    def resolve(self, text: str) -> tuple[EntityMention, EntityAudit]:
        c = self.cfg.confidence
        hits: list[_Hit] = []
        rejected: list[RejectedCandidate] = []
        unmatched: list[str] = []

        for m in [*_CASHTAG.finditer(text), *_EXCHANGE.finditer(text)]:
            ticker = m.group(1).upper()
            eid = self._tickers.get(ticker)
            if eid:
                hits.append(_Hit(eid, f"${ticker}", "CASHTAG", c.cashtag, m.start()))
            elif ticker not in unmatched:
                unmatched.append(ticker)

        folded = match_form(text)
        if self._strong_re:
            for m in self._strong_re.finditer(folded):
                p = self._strong[m.group(1)]
                conf = c.legal_name if p.rule == "LEGAL_NAME" else c.alias
                hits.append(_Hit(p.entity_id, p.text, p.rule, conf, m.start()))

        for m in _BARE_TICKER.finditer(text):
            eid = self._tickers.get(m.group(1))
            if eid:
                hits.append(_Hit(eid, m.group(1), "BARE_TICKER", c.weak_alias, m.start()))

        strong_ids = {h.entity_id for h in hits}
        has_context = bool(self._context and self._context.search(folded))
        weak_text = text
        for neutraliser in self._neutralisers:
            weak_text = neutraliser.sub(lambda m: " " * len(m.group(0)), weak_text)
        for surface, pattern in self._weak_res.items():
            m = pattern.search(weak_text)
            if not m:
                if pattern.search(text):  # present, but only inside an everyday phrase: record the refusal
                    rejected.append(RejectedCandidate(entity_id=self._weak[surface], matched_text=surface,
                                                      reason="everyday-language phrase, not a company reference"))
                continue
            eid = self._weak[surface]
            others = strong_ids - {eid}
            if has_context or others:
                hits.append(_Hit(eid, surface, "WEAK_ALIAS", c.weak_alias, m.start()))
            else:
                rejected.append(RejectedCandidate(
                    entity_id=eid, matched_text=surface,
                    reason="ambiguous name, no finance context and no other issuer mentioned"))

        if not hits and self.cfg.fuzzy.enabled:
            hit = self._fuzzy(text)
            if hit:
                hits.append(hit)

        return self._decide(hits, rejected, unmatched)

    # ----------------------------------------------------------------- helpers
    def _fuzzy(self, text: str) -> _Hit | None:
        words = [(m.group(0), m.start()) for m in _TOKEN.finditer(text)]
        best: tuple[float, _Hit] | None = None
        for i, (w, pos) in enumerate(words):
            if not w[0].isupper():
                continue
            for n in (1, 2, 3):
                gram = " ".join(x for x, _ in words[i : i + n])
                form = match_form(gram)
                if len(form) < self.cfg.fuzzy.min_alias_chars:
                    continue
                for target, p in self._fuzzy_forms:
                    if abs(len(target) - len(form)) > 2 or target[0] != form[0] or target == form:
                        continue
                    ratio = SequenceMatcher(None, form, target).ratio()
                    if ratio >= self.cfg.fuzzy.min_ratio and (best is None or ratio > best[0]):
                        best = (ratio, _Hit(p.entity_id, gram, "FUZZY", self.cfg.confidence.fuzzy, pos))
        return best[1] if best else None

    def _decide(self, hits: list[_Hit], rejected: list[RejectedCandidate],
                unmatched: list[str]) -> tuple[EntityMention, EntityAudit]:
        best: dict[str, _Hit] = {}
        for h in hits:
            cur = best.get(h.entity_id)
            if cur is None or (-h.confidence, h.pos) < (-cur.confidence, cur.pos):
                best[h.entity_id] = h
        ranked = sorted(best.values(), key=lambda h: (-h.confidence, h.pos, h.entity_id))
        candidates = [
            EntityCandidate(entity_id=h.entity_id, entity_name=self._by_id[h.entity_id].name,
                            matched_text=h.matched, rule=h.rule, confidence=h.confidence)
            for h in ranked
        ]
        if not ranked:
            return EntityMention(), EntityAudit(rule="NONE", rejected=rejected, unmatched_cashtags=unmatched)
        top = ranked[0]
        if unmatched and not any(h.rule == "CASHTAG" for h in ranked):
            # The text is about a ticker that is not in the master ("$BYND - JPMorgan cuts ..."). A company named
            # only by name is then most likely the analyst/counterparty, not the subject: do not shock it.
            rejected = [*rejected, *(RejectedCandidate(
                entity_id=h.entity_id, matched_text=h.matched,
                reason=f"text is about unlisted ticker(s) {', '.join('$' + t for t in unmatched)}; "
                       "a name-only match is probably the analyst or counterparty") for h in ranked)]
            return EntityMention(), EntityAudit(rule="SUBJECT_UNRESOLVED", candidates=candidates, rejected=rejected,
                                                unmatched_cashtags=unmatched)
        multi = len(ranked) > 1
        conf = min(top.confidence, self.cfg.multi_entity_cap) if multi else top.confidence
        audit = EntityAudit(rule=top.rule, matched_text=top.matched, multi_entity=multi,
                            candidates=candidates, rejected=rejected, unmatched_cashtags=unmatched)
        if conf < self.cfg.min_link_confidence:
            return EntityMention(), audit.model_copy(update={"rule": "BELOW_THRESHOLD"})
        e = self._by_id[top.entity_id]
        mention = EntityMention(entity_id=e.entity_id, entity_name=e.name, ticker=e.ticker, sector=e.sector,
                                country=e.country, link_confidence=round(conf, 4))
        return mention, audit


__all__ = ["UNKNOWN_ENTITY", "EntityResolver"]
