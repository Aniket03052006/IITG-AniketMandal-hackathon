"""Hierarchical scope: what is this event about, from the company up to the market, with the evidence for each level.

COMPANY -> INDUSTRY -> SECTOR -> GEOGRAPHY -> MACRO / THEME / MARKET, and UNRESOLVED when nothing defensible is found.

It reads the same vocabulary the pipeline's ``ScopeResolver`` reads (sectors, themes, regions: ``configs/scope.yaml``) plus an industry
layer and a theme-kind map (``configs/intelligence.yaml``). Company resolution is the pipeline's own (``signal.entity``); this module
never resolves a company, so it cannot invent one. A level with no evidence is left out of the path rather than filled in. Pure and
deterministic: it reads the signal and its text only.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..assessment.reference import analysed_text
from ..domain import UNKNOWN_ENTITY, EventCategory, EventStatus, RiskSignal
from ..pipeline.normalize import match_form
from ..pipeline.scope import ScopeResolver
from .config import IntelligenceConfig
from .model import (
    ConfidenceTier,
    EventScope,
    ResolutionStatus,
    ScopeConfidence,
    ScopeEvidenceSpan,
    ScopeNode,
    ScopeType,
)
from .textutil import cue_pattern, find_cues

_MACRO_CATEGORIES = {EventCategory.MACROECONOMIC}
_ROOT = ScopeNode(type=ScopeType.MARKET, value="Equity market", basis="HIERARCHY_ROOT")


def _locate(text: str, term: str, dimension: str) -> ScopeEvidenceSpan:
    pat = cue_pattern([term])
    hits = find_cues(pat, text)
    if hits:
        h = hits[0]
        return ScopeEvidenceSpan(dimension=dimension, term=term, quote=text[h.start:h.end], start=h.start, end=h.end)
    return ScopeEvidenceSpan(dimension=dimension, term=term)


class HierarchicalScopeResolver:
    def __init__(self, cfg: IntelligenceConfig, resolver: ScopeResolver, scope_eval_path: Path | None = None) -> None:
        self.cfg = cfg
        self.resolver = resolver
        self.version = f"{cfg.version}+{resolver.version}"
        sc = cfg.scope
        self._ind_owner = {match_form(t): name for name, ind in sc.industries.items() for t in ind.terms}
        self._ind_pat = cue_pattern([t for ind in sc.industries.values() for t in ind.terms])
        self._measured = self._read_measured(scope_eval_path)

    # --------------------------------------------------------------------------------------------------------------- measured
    @staticmethod
    def _read_measured(path: Path | None) -> dict[str, str]:
        if path is None or not path.is_file():
            return {}
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            out = {}
            for tier, key in (("STRONG", "STRONG"), ("WEAK", "WEAK")):
                s = d["by_strength"][key]
                out[tier] = (f"in a check on {d['documents_read']} replay documents whose company was known, the sector vocabulary agreed with the "
                             f"real sector for {s['correct']} of {s['predicted']} ({s['precision']:.0%}); an optimistic proxy for text naming no company")
            return out
        except (OSError, ValueError, KeyError):
            return {}

    # ---------------------------------------------------------------------------------------------------------------- helpers
    def region_name(self, code: str) -> str:
        return self.cfg.scope.region_names.get(code, code)

    def industry_hits(self, text: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for h in find_cues(self._ind_pat, text):
            name = self._ind_owner.get(match_form(h.cue))
            if name is None:
                continue
            terms = out.setdefault(name, [])
            if match_form(h.cue) not in [match_form(t) for t in terms]:
                terms.append(h.cue.lower())
        return out

    def theme_kind(self, theme: str) -> str:
        return self.cfg.scope.theme_kinds.get(theme, "THEME")

    def risk_factors_for(self, themes: list[str]) -> list[tuple[str, str]]:
        """(risk factor, the theme that bears on it), de-duplicated in a fixed order."""
        seen: dict[str, str] = {}
        for th in sorted(themes):
            for rf in self.cfg.scope.theme_risk_factors.get(th, []):
                seen.setdefault(rf, th)
        return sorted(seen.items())

    def _path(self, *nodes: ScopeNode | None) -> list[ScopeNode]:
        return [n for n in nodes if n is not None] + [_ROOT]

    # ------------------------------------------------------------------------------------------------------------------ resolve
    def resolve(self, signal: RiskSignal) -> EventScope:
        doc = signal.document
        text = analysed_text(doc.headline, doc.body)
        ent = signal.entity
        v = self.version
        event = signal.event

        if ent.entity_id != UNKNOWN_ENTITY:
            return self._company(signal, text)

        if event.status is EventStatus.NO_EVENT:
            return EventScope(
                scope_type=ScopeType.UNRESOLVED, scope_value=None, scope_path=[], scope_confidence=ScopeConfidence(
                    tier=ConfidenceTier.NONE, basis="the event model judged the text not to be a market event"),
                scope_evidence=[], resolution_status=ResolutionStatus.UNRESOLVED, resolver_version=v,
                reason="The event model judged this text not to be a market event, so no subject is assigned.")

        sectors = self.resolver.sector_hits(text)
        themes = self.resolver.theme_hits(text)
        regions = self.resolver.region_hits(text)
        industries = self.industry_hits(text)
        top_sector = self.resolver.unique_sector(sectors)
        sector_tied = bool(sectors) and top_sector is None
        sector_cands = sorted(sectors) if sector_tied else []

        secondary: list[ScopeNode] = [ScopeNode(type=ScopeType.GEOGRAPHY, value=self.region_name(r), basis="VOCABULARY") for r in sorted(regions)]
        ev_regions = [_locate(text, t, "region") for r in sorted(regions) for t in regions[r][:2]]

        # 1. a specific industry
        ranked = sorted(industries.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        if (ranked and not sector_tied and len(ranked[0][1]) >= self.cfg.scope.industry_min_terms
                and not (len(ranked) > 1 and len(ranked[1][1]) == len(ranked[0][1]))):
            name, terms = ranked[0]
            parent = self.cfg.scope.industries[name].sector
            tier = ConfidenceTier.MEDIUM if len(terms) >= 2 else ConfidenceTier.LOW
            status = ResolutionStatus.RESOLVED if tier is ConfidenceTier.MEDIUM else ResolutionStatus.PARTIAL
            geo = self._geo_node(regions)
            return EventScope(
                scope_type=ScopeType.INDUSTRY, scope_value=name,
                scope_path=self._path(ScopeNode(type=ScopeType.INDUSTRY, value=name, basis="VOCABULARY"),
                                      ScopeNode(type=ScopeType.SECTOR, value=parent, basis="VOCABULARY"), geo),
                scope_confidence=ScopeConfidence(tier=tier, basis=f"{len(terms)} distinct {name} term(s) and no company named"),
                scope_evidence=[_locate(text, t, "industry") for t in terms], resolution_status=status,
                secondary=[n for n in secondary if geo is None or n.value != geo.value], resolver_version=v,
                reason=f"No company was named; {', '.join(terms)} point{'s' if len(terms) == 1 else ''} to {name} ({parent}).")

        # 2. a sector with enough distinct terms
        if top_sector and len(top_sector[1]) >= self.resolver.cfg.sector.strong_min_terms:
            name, terms = top_sector
            return EventScope(
                scope_type=ScopeType.SECTOR, scope_value=name,
                scope_path=self._path(ScopeNode(type=ScopeType.SECTOR, value=name, basis="VOCABULARY"), self._geo_node(regions)),
                scope_confidence=ScopeConfidence(tier=ConfidenceTier.MEDIUM, basis=f"{len(terms)} distinct {name} terms and no competing sector",
                                                 measured=self._measured.get("STRONG")),
                scope_evidence=[_locate(text, t, "sector") for t in terms], resolution_status=ResolutionStatus.RESOLVED, secondary=secondary,
                resolver_version=v, reason=f"No company was named; {len(terms)} {name} terms ({', '.join(terms)}) point to that sector.")

        # 3. a macro / theme / market subject from vocabulary
        if themes:
            by_kind: dict[str, list[str]] = {}
            for th in sorted(themes, key=lambda t: (-len(themes[t]), t)):
                by_kind.setdefault(self.theme_kind(th), []).append(th)
            kind = max(by_kind, key=lambda k: (sum(len(themes[t]) for t in by_kind[k]), {"MACRO": 2, "THEME": 1, "MARKET": 0}[k]))
            main = by_kind[kind][0]
            stype = {"MACRO": ScopeType.MACRO, "THEME": ScopeType.THEME, "MARKET": ScopeType.MARKET}[kind]
            terms = [t for th in by_kind[kind] for t in themes[th]]
            others = [ScopeNode(type=ScopeType.THEME if self.theme_kind(t) != "MACRO" else ScopeType.MACRO, value=t.replace("_", " "), basis="VOCABULARY")
                      for t in sorted(themes) if t not in by_kind[kind]]
            nodes = [ScopeNode(type=stype, value=main.replace("_", " "), basis="VOCABULARY")] if stype is not ScopeType.MARKET else []
            return EventScope(
                scope_type=stype, scope_value=main.replace("_", " "),
                scope_path=self._path(*nodes, self._geo_node(regions)),
                scope_confidence=ScopeConfidence(tier=ConfidenceTier.MEDIUM, basis=f"market-wide vocabulary: {', '.join(terms[:4])}"),
                scope_evidence=[_locate(text, t, "theme") for t in terms[:4]], resolution_status=ResolutionStatus.RESOLVED,
                candidates=sector_cands, secondary=[*others, *secondary], resolver_version=v,
                reason=f"No company or sector was named; the text uses {kind.lower()} vocabulary ({', '.join(terms[:4])}).")

        # 4. a region the text points to
        if regions:
            geo = self._geo_node(regions) or ScopeNode(
                type=ScopeType.GEOGRAPHY, value=" / ".join(self.region_name(r) for r in sorted(regions)), basis="VOCABULARY")
            geopolitical = event.status is EventStatus.CLASSIFIED and event.category is EventCategory.GEOPOLITICAL
            return EventScope(
                scope_type=ScopeType.GEOGRAPHY, scope_value=geo.value, scope_path=self._path(geo),
                scope_confidence=ScopeConfidence(
                    tier=ConfidenceTier.MEDIUM if geopolitical else ConfidenceTier.LOW,
                    basis=("a place the text names, in a text the event model calls geopolitical" if geopolitical
                           else "a place the text names; nothing says what about it matters to markets")),
                scope_evidence=ev_regions, resolution_status=ResolutionStatus.PARTIAL, candidates=sector_cands,
                secondary=[n for n in secondary if n.value != geo.value and len(regions) == 1], resolver_version=v,
                reason=f"No company, sector or market theme was named; the text points to {geo.value}.")

        # 5. the event class alone says it is market-wide
        if event.status is EventStatus.CLASSIFIED and event.category in (EventCategory.MACROECONOMIC, EventCategory.GEOPOLITICAL):
            stype = ScopeType.MACRO if event.category in _MACRO_CATEGORIES else ScopeType.MARKET
            return EventScope(
                scope_type=stype, scope_value=event.category.value.replace("_", " ").title() if stype is ScopeType.MACRO else "Market-wide",
                scope_path=self._path(ScopeNode(type=stype, value="Macroeconomic", basis="EVENT_MODEL") if stype is ScopeType.MACRO else None),
                scope_confidence=ScopeConfidence(
                    tier=ConfidenceTier.LOW, basis="the trained event model's class only; no subject vocabulary in the text"),
                scope_evidence=[ScopeEvidenceSpan(dimension="event_class", term=event.category.value)],
                resolution_status=ResolutionStatus.PARTIAL, candidates=sector_cands, resolver_version=v,
                reason=(f"No company, sector or theme was named; the event model calls this {event.category.value.lower().replace('_', ' ')}, "
                        "which concerns the market as a whole."))

        # 6. one sector term
        if top_sector:
            name, terms = top_sector
            return EventScope(
                scope_type=ScopeType.SECTOR, scope_value=name,
                scope_path=self._path(ScopeNode(type=ScopeType.SECTOR, value=name, basis="VOCABULARY")),
                scope_confidence=ScopeConfidence(tier=ConfidenceTier.LOW, basis=f"a single {name} term ({terms[0]}) is the only hint",
                                                 measured=self._measured.get("WEAK")),
                scope_evidence=[_locate(text, t, "sector") for t in terms], resolution_status=ResolutionStatus.PARTIAL, secondary=secondary,
                resolver_version=v, reason=f"No company was named; a single {name} term ({terms[0]}) is the only hint of a subject.")

        # 7. nothing defensible
        if sector_tied:
            return EventScope(
                scope_type=ScopeType.UNRESOLVED, scope_value=None, scope_path=[],
                scope_confidence=ScopeConfidence(tier=ConfidenceTier.NONE, basis="several sectors are mentioned with equal weight"),
                scope_evidence=[_locate(text, t, "sector") for s in sector_cands for t in sectors[s][:1]],
                resolution_status=ResolutionStatus.AMBIGUOUS, candidates=sector_cands, resolver_version=v,
                reason=f"Kept as reported, not guessed about: {', '.join(sector_cands)} are mentioned with equal weight, so none is chosen.")
        why = ("the event type usually concerns a specific issuer, but no company, sector, region or market-wide theme could be identified"
               if event.status is EventStatus.CLASSIFIED else "no company, sector, region or market-wide theme could be identified")
        return EventScope(
            scope_type=ScopeType.UNRESOLVED, scope_value=None, scope_path=[],
            scope_confidence=ScopeConfidence(tier=ConfidenceTier.NONE, basis="no vocabulary evidence"), scope_evidence=[],
            resolution_status=ResolutionStatus.UNRESOLVED, resolver_version=v, reason=f"Kept as reported, not guessed about: {why}.")

    # --------------------------------------------------------------------------------------------------------------- company
    def _company(self, signal: RiskSignal, text: str) -> EventScope:
        ent = signal.entity
        name = ent.entity_name or ent.entity_id
        nodes: list[ScopeNode | None] = [ScopeNode(type=ScopeType.COMPANY, value=name, basis="ENTITY_RESOLVER")]
        industry = self.cfg.scope.ticker_industry.get(ent.ticker or "")
        nodes.append(ScopeNode(type=ScopeType.INDUSTRY, value=industry, basis="TICKER_MAP") if industry else None)
        nodes.append(ScopeNode(type=ScopeType.SECTOR, value=ent.sector, basis="ENTITY_MASTER") if ent.sector else None)
        nodes.append(ScopeNode(type=ScopeType.GEOGRAPHY, value=self.region_name(ent.country), basis="ENTITY_MASTER") if ent.country else None)
        audit = signal.provenance.entity_audit if signal.provenance else None
        evidence: list[ScopeEvidenceSpan] = []
        if audit and audit.matched_text:
            evidence.append(_locate(text, audit.matched_text, "company"))
        elif ent.entity_name:
            evidence.append(_locate(text, ent.entity_name, "company"))
        tier = (ConfidenceTier.HIGH if ent.link_confidence >= 0.9 else ConfidenceTier.MEDIUM if ent.link_confidence >= 0.7 else ConfidenceTier.LOW)
        basis = (f"the entity resolver matched {name} by rule {audit.rule}" if audit else f"{name} was named in the text") + f" (link confidence {ent.link_confidence:.2f})"
        others = []
        if audit and audit.multi_entity:
            others = sorted({c.entity_name for c in audit.candidates if c.entity_id != ent.entity_id})
        ambiguous = bool(others)
        return EventScope(
            scope_type=ScopeType.COMPANY, scope_value=name, scope_path=self._path(*nodes),
            scope_confidence=ScopeConfidence(tier=min(tier, ConfidenceTier.MEDIUM, key=_tier_rank) if ambiguous else tier, basis=basis),
            scope_evidence=evidence,
            resolution_status=ResolutionStatus.AMBIGUOUS if ambiguous else (ResolutionStatus.RESOLVED if tier is not ConfidenceTier.LOW else ResolutionStatus.PARTIAL),
            candidates=others, resolver_version=self.version,
            reason=(f"{name} was named in the text." if not ambiguous else
                    f"{name} and {len(others)} other compan{'y' if len(others) == 1 else 'ies'} ({', '.join(others)}) are named; "
                    f"the resolver's primary is {name} and the others are listed, not scored."))

    def _geo_node(self, regions: dict[str, list[str]]) -> ScopeNode | None:
        if len(regions) == 1:
            code = next(iter(regions))
            return ScopeNode(type=ScopeType.GEOGRAPHY, value=self.region_name(code), basis="VOCABULARY")
        return None  # several regions, or none: a single geography is not claimed


def _tier_rank(t: ConfidenceTier) -> int:
    return {ConfidenceTier.NONE: 0, ConfidenceTier.LOW: 1, ConfidenceTier.MEDIUM: 2, ConfidenceTier.HIGH: 3}[t]


__all__ = ["HierarchicalScopeResolver"]
