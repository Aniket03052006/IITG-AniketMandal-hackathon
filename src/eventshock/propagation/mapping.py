"""Event -> scope -> risk factor -> portfolio -> holdings: an explainable mapping, not a causal model.

What reaches a holding, and how:
  * DIRECT_FACT      the event names an issuer the book holds (the entity resolver, a fact).
  * EVIDENCED_SCOPE  a sector / industry / region the text or the entity master names, or a holding's structural sensitivity to a risk factor the text is about
                     (a bond's duration, an equity's beta: formulas the stress engine applies to the holding's own attributes).
  * ASSUMPTION_ONLY  only a configured transmission edge reaches it (an assumption: configs/propagation.yaml, or what the user added or adjusted).
Each holding is counted once however many routes reach it. Where no defensible mapping exists the graph abstains and says why.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..adjust.models import AdjustmentNotice
from ..assessment.reference import analysed_text
from ..domain import AssetClass, EventCategory, Portfolio, PortfolioAsset, RiskFactor, RiskSignal, ScopeLevel
from ..domain.enums import UNKNOWN_ENTITY
from ..intelligence.model import Availability, EventScope, ScopeType
from ..intelligence.textutil import cue_pattern, find_cues
from .config import Edge, PropagationConfig
from .models import (
    MAPPING_LABEL,
    ActiveRiskFactor,
    GraphEdge,
    GraphNode,
    MappingBasis,
    PropagationGraph,
    ReachedHolding,
    Status,
)

_RANK = {MappingBasis.DIRECT_FACT: 3, MappingBasis.EVIDENCED_SCOPE: 2, MappingBasis.ASSUMPTION_ONLY: 1, MappingBasis.NONE: 0}
UNCLASSIFIED = "Unclassified"
LIMITATIONS = [
    "Transmission edges and shock sizes are judgement priors (configs/propagation.yaml), not measured relationships; the UI says so and nothing is validated.",
    "Industry is known only for the 25 tickers of the entity master (intelligence.yaml: ticker_industry); other holdings are Unclassified and are reached by sector, asset class or region.",
    "Currencies are recognised but not simulated (the stress engine has no FX factor); oil acts only through the sector shocks of the transmission table.",
    "A holding reached by several routes is counted once; reach is not impact. How much a holding moves is the stress engine's job, under the scenario's assumptions.",
]


@dataclass
class _Reach:
    asset: PortfolioAsset
    basis: MappingBasis = MappingBasis.NONE
    routes: list[str] = field(default_factory=list)

    def add(self, basis: MappingBasis, route: str) -> None:
        if _RANK[basis] > _RANK[self.basis]:
            self.basis = basis
        if route not in self.routes:
            self.routes.append(route)


class PropagationMapper:
    def __init__(self, cfg: PropagationConfig, *, ticker_industry: Mapping[str, str], region_names: Mapping[str, str],
                 entity_tickers: Callable[[], Mapping[str, str]], overrides: Mapping[str, Any] | None = None, max_position_nodes: int = 8) -> None:
        self.cfg = cfg
        self._ticker_industry = ticker_industry
        self._regions = region_names
        self._tickers = entity_tickers
        self._adjusted = [p.removeprefix("propagation.") for p in (overrides or {}) if p.startswith("propagation.")]
        self._max_pos = max_position_nodes
        self._patterns = {rid: cue_pattern(rf.terms) for rid, rf in cfg.risk_factors.items()}

    # ------------------------------------------------------------------------------------------------------------- helpers
    def industry_of(self, asset: PortfolioAsset) -> str | None:
        ticker = self._tickers().get(asset.entity_id)
        return self._ticker_industry.get(ticker) if ticker else None

    def _edge_adjusted(self, rf: str, eid: str) -> bool:
        head = f"risk_factors.{rf}.transmission.{eid}"
        return any(p == head or p.startswith(head + ".") for p in self._adjusted)

    def _category_adjusted(self, category: EventCategory | None) -> bool:
        return category is not None and f"category_risk_factors.{category.value}" in self._adjusted

    @staticmethod
    def _match(edge: Edge, a: PortfolioAsset, industry: str | None, engine_factor: RiskFactor | None = None) -> bool:
        if edge.kind == "SECTOR":
            return a.sector == edge.key
        if edge.kind == "INDUSTRY":
            return industry == edge.key
        if edge.kind == "ASSET_CLASS":
            if a.asset_type.value != edge.key:
                return False
            # a holding the engine does not move through this factor is not reached by it (a government bond takes no credit-spread shock)
            if engine_factor is RiskFactor.CREDIT_SPREAD_BPS and a.asset_type is AssetClass.BOND:
                return a.spread_sensitivity > 0
            if engine_factor is RiskFactor.RATES_BPS and a.asset_type is AssetClass.BOND:
                return (a.duration or 0) > 0
            return True
        return a.geography == edge.key

    # ----------------------------------------------------------------------------------------------------- risk factors
    def active_factors(self, signal: RiskSignal, text: str, category: EventCategory | None) -> list[ActiveRiskFactor]:
        found: dict[str, ActiveRiskFactor] = {}

        def add(rid: str, origin: str, status: Status, evidence: str) -> None:
            rf = self.cfg.risk_factors[rid]
            cur = found.get(rid)
            if cur is not None:
                if evidence not in cur.evidence:
                    cur.evidence.append(evidence)
                return
            note = ("recognised and reported, never simulated: the stress engine has no such factor" if rf.modelled == "NOT_MODELLED" else
                    "acts only through the sector shocks of the transmission table, not through an engine factor" if rf.modelled == "PROXY" else None)
            found[rid] = ActiveRiskFactor(id=rid, label=rf.label, modelled=rf.modelled, origin=origin, status=status, evidence=[evidence], note=note)

        sc = signal.scope
        if sc is not None:
            theme_terms = ", ".join(f"“{t}”" for t in sc.matched_terms.get("theme", [])[:3])
            for th in sorted(sc.themes):
                for rid in self.cfg.theme_risk_factors.get(th, []):
                    add(rid, "TEXT", Status.OBSERVED, f"the text uses {th.replace('_', ' ')} vocabulary" + (f" ({theme_terms})" if theme_terms else ""))
        for rid, pat in self._patterns.items():
            seen: list[str] = []
            for h in find_cues(pat, text):
                if h.cue.lower() not in (x.lower() for x in seen):
                    seen.append(h.cue)
            if seen:
                add(rid, "TEXT", Status.OBSERVED, "the text says " + ", ".join(f"“{s}”" for s in seen[:3]))
        if category is not None:
            user = self._category_adjusted(category)
            for rid in self.cfg.category_risk_factors.get(category, []):
                if rid not in found:
                    add(rid, "CATEGORY", Status.USER_ASSUMPTION if user else Status.SCENARIO_ASSUMPTION,
                        f"assumed for {category.value.replace('_', ' ').lower()} events: the text names no such factor")
        return list(found.values())

    # --------------------------------------------------------------------------------------------------------------- map
    def map(self, signal: RiskSignal, portfolio: Portfolio, scope: EventScope, category: EventCategory | None,
            adjustments: AdjustmentNotice | None = None) -> PropagationGraph:
        text = analysed_text(signal.document.headline, signal.document.body)
        total = portfolio.total_value
        held = [a for a in portfolio.assets if a.asset_type not in (AssetClass.CASH, AssetClass.OTHER)]
        industry = {a.asset_id: self.industry_of(a) for a in held}
        reach: dict[str, _Reach] = {}

        def mark(a: PortfolioAsset, basis: MappingBasis, route: str) -> None:
            reach.setdefault(a.asset_id, _Reach(a)).add(basis, route)

        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        not_reached: list[str] = []
        headline = signal.document.headline
        nodes["event"] = GraphNode(id="event", kind="EVENT", label=headline[:140], detail=category.value if category else None)
        nodes["portfolio"] = GraphNode(id="portfolio", kind="PORTFOLIO", label=portfolio.name, value=total, share=1.0 if total else None)

        def target(kind: str, key: str, label: str, assets: list[PortfolioAsset]) -> str:
            nid = f"target:{kind}:{key}"
            if nid not in nodes:
                v = sum(a.market_value for a in assets)
                nodes[nid] = GraphNode(id=nid, kind=kind, label=label, value=v, share=v / total if total else None,
                                       detail=f"{len(assets)} position{'s' if len(assets) != 1 else ''} held" if assets else "nothing held")
                if assets:
                    edges.append(GraphEdge(source=nid, target="portfolio", relationship="HELD_BY", rule_id="holdings",
                                           basis=f"{len(assets)} position(s), {v / total:.1%} of the book" if total else "holdings", status=Status.OBSERVED))
                else:
                    not_reached.append(f"{label}: the book holds nothing in it")
            return nid

        # ---- scope-driven reach (what the text or the entity master names)
        scope_ids: list[str] = []
        sc = signal.scope
        company = sc is not None and sc.level is ScopeLevel.COMPANY and signal.entity.entity_id != UNKNOWN_ENTITY
        path = [n for n in scope.scope_path if n.type is not ScopeType.MARKET]
        prev = "event"
        quotes = "; ".join(f"“{e.quote or e.term}”" for e in scope.scope_evidence[:3]) or scope.scope_confidence.basis
        path = [n for n in path if not (company and n.type is ScopeType.GEOGRAPHY)]  # a company's country is not a separate claim
        for i, n in enumerate(path):
            if n.type is ScopeType.COMPANY:
                nid = f"scope:COMPANY:{signal.entity.entity_id}"
                direct = [a for a in held if a.entity_id == signal.entity.entity_id]
                nodes[nid] = GraphNode(id=nid, kind="SCOPE", label=n.value, detail="the named company",
                                       value=sum(a.market_value for a in direct), share=(sum(a.market_value for a in direct) / total if total else None))
                for a in direct:
                    mark(a, MappingBasis.DIRECT_FACT, "issuer")
                if direct:
                    edges.append(GraphEdge(source=nid, target="portfolio", relationship="HELD_BY", rule_id="holdings",
                                           basis=f"{len(direct)} position(s) in {n.value}", status=Status.OBSERVED))
                else:
                    not_reached.append(f"{n.value}: not held")
            elif n.type is ScopeType.SECTOR:
                members = [a for a in held if a.sector == n.value]
                nid = target("SECTOR", n.value, n.value, members)
                for a in members:
                    mark(a, MappingBasis.EVIDENCED_SCOPE, f"sector:{n.value}")
            elif n.type is ScopeType.INDUSTRY:
                members = [a for a in held if industry[a.asset_id] == n.value]
                nid = target("INDUSTRY", n.value, n.value, members)
                for a in members:
                    mark(a, MappingBasis.EVIDENCED_SCOPE, f"industry:{n.value}")
            elif n.type is ScopeType.GEOGRAPHY:
                nid = f"scope:GEOGRAPHY:{n.value}"
                codes = [] if company or sc is None else list(sc.regions)
                members = [a for a in held if a.geography in codes]
                nodes[nid] = GraphNode(id=nid, kind="GEOGRAPHY", label=n.value, value=sum(a.market_value for a in members),
                                       share=(sum(a.market_value for a in members) / total if total else None),
                                       detail=f"{len(members)} position(s) held" if members else "nothing held there")
                for a in members:
                    mark(a, MappingBasis.EVIDENCED_SCOPE, f"region:{a.geography}")
                if members:
                    edges.append(GraphEdge(source=nid, target="portfolio", relationship="HELD_BY", rule_id="holdings",
                                           basis=f"{len(members)} position(s) in {n.value}", status=Status.OBSERVED))
                else:
                    not_reached.append(f"{n.value}: the book holds nothing there")
            else:  # MACRO / THEME: a subject, not a holding: it acts through the risk factors below
                nid = f"scope:{n.type.value}:{n.value}"
                nodes[nid] = GraphNode(id=nid, kind="SCOPE", label=n.value, detail=n.type.value.lower())
            if i == 0:
                edges.append(GraphEdge(source=prev, target=nid, relationship="EVIDENCED_BY", rule_id=f"scope.{n.basis.lower()}", basis=quotes,
                                       status=Status.OBSERVED))
            else:
                edges.append(GraphEdge(source=prev, target=nid, relationship="MEMBER_OF", rule_id=f"scope.{n.basis.lower()}",
                                       basis=f"{path[i - 1].value} is part of {n.value} ({n.basis.replace('_', ' ').lower()})", status=Status.OBSERVED))
            prev = nid
            scope_ids.append(nid)
        # a region the text points to beside the subject (a company's country is not a separate claim)
        if not company and sc is not None:
            for code in sc.regions:
                members = [a for a in held if a.geography == code]
                nid = f"scope:GEOGRAPHY:{self._regions.get(code, code)}"
                if nid in nodes:
                    continue
                nodes[nid] = GraphNode(id=nid, kind="GEOGRAPHY", label=self._regions.get(code, code), value=sum(a.market_value for a in members),
                                       share=(sum(a.market_value for a in members) / total if total else None),
                                       detail=f"{len(members)} position(s) held" if members else "nothing held there")
                edges.append(GraphEdge(source="event", target=nid, relationship="EVIDENCED_BY", rule_id="scope.region", basis=f"the text points to {self._regions.get(code, code)}",
                                       status=Status.OBSERVED))
                for a in members:
                    mark(a, MappingBasis.EVIDENCED_SCOPE, f"region:{code}")
                if members:
                    edges.append(GraphEdge(source=nid, target="portfolio", relationship="HELD_BY", rule_id="holdings",
                                           basis=f"{len(members)} position(s) in {nodes[nid].label}", status=Status.OBSERVED))
                else:
                    not_reached.append(f"{nodes[nid].label}: the book holds nothing there")

        # ---- risk-factor-driven reach (the text's vocabulary, or the class of event, plus the transmission table)
        factors = self.active_factors(signal, text, category)
        for f in factors:
            rf = self.cfg.risk_factors[f.id]
            rid = f"rf:{f.id}"
            nodes[rid] = GraphNode(id=rid, kind="RISK_FACTOR", label=rf.label, detail=f"{rf.modelled.lower().replace('_', ' ')}; " + ("; ".join(f.evidence)[:200]))
            edges.append(GraphEdge(source="event", target=rid, relationship="ABOUT", rule_id=("scope.theme_or_terms" if f.origin == "TEXT" else "category_risk_factors"),
                                   basis="; ".join(f.evidence), status=f.status))
            for eid, edge in rf.transmission.items():
                if not edge.enabled:
                    continue
                members = [a for a in held if self._match(edge, a, industry[a.asset_id], rf.engine_factor)]
                label = edge.key if edge.kind != "ASSET_CLASS" else f"{edge.key.title()} positions"
                tid = target(edge.kind if edge.kind != "ASSET_CLASS" else "ASSET_CLASS", edge.key, label, members)
                adjusted = self._edge_adjusted(f.id, eid)
                structural = (not adjusted and edge.kind == "ASSET_CLASS" and rf.modelled == "ENGINE" and f.status is Status.OBSERVED)
                status = Status.USER_ASSUMPTION if adjusted else Status.OBSERVED if structural else Status.SCENARIO_ASSUMPTION
                basis_txt = (f"{edge.rationale} The stress engine applies this to each holding's own attributes (duration, beta, default terms)." if structural
                             else edge.rationale + (" (adjusted by you)" if adjusted else ""))
                edges.append(GraphEdge(source=rid, target=tid, relationship="SENSITIVE_TO" if structural else "ASSUMED_TRANSMISSION",
                                       rule_id=f"risk_factors.{f.id}.transmission.{eid}", basis=basis_txt, status=status, weight=edge.weight))
                for a in members:
                    mark(a, MappingBasis.EVIDENCED_SCOPE if structural else MappingBasis.ASSUMPTION_ONLY, f"{f.id}:{eid}")

        reached = sorted(reach.values(), key=lambda r: (-r.asset.market_value, r.asset.asset_id))
        reached_value = sum(r.asset.market_value for r in reached)
        by = lambda pred: sum(r.asset.market_value for r in reached if pred(r)) / total if total else 0.0  # noqa: E731
        direct_share = by(lambda r: r.basis is MappingBasis.DIRECT_FACT)
        evidenced_share = by(lambda r: r.basis in (MappingBasis.DIRECT_FACT, MappingBasis.EVIDENCED_SCOPE))
        assumed_share = by(lambda r: r.basis is MappingBasis.ASSUMPTION_ONLY)
        reached_share = reached_value / total if total else 0.0
        basis = max((r.basis for r in reached), key=lambda b: _RANK[b], default=MappingBasis.NONE)
        holdings = [ReachedHolding(
            asset_id=r.asset.asset_id, name=r.asset.name, entity_id=r.asset.entity_id, asset_type=r.asset.asset_type.value, sector=r.asset.sector,
            industry=industry[r.asset.asset_id], geography=r.asset.geography, market_value=r.asset.market_value,
            share=r.asset.market_value / total if total else 0.0, basis=r.basis, routes=r.routes) for r in reached]
        for r in reached[: self._max_pos]:
            pid = f"pos:{r.asset.asset_id}"
            nodes[pid] = GraphNode(id=pid, kind="POSITION", label=r.asset.name, detail=f"{r.asset.asset_type.value.lower()} · {r.asset.sector}",
                                   value=r.asset.market_value, share=r.asset.market_value / total if total else None)
            edges.append(GraphEdge(source="portfolio", target=pid, relationship="HELD_BY", rule_id="holdings",
                                   basis=f"reached by {', '.join(r.routes[:3])}", status=Status.OBSERVED))

        no_subject = not path and not factors and (sc is None or not sc.regions)
        if no_subject:
            availability = Availability.ABSTAINED
            reason = ("No defensible mapping: the text names no company, sector, industry, region or risk-factor vocabulary, and the event class carries no "
                      "market-wide assumption. EventShock does not guess what it is about.")
        else:
            availability = Availability.AVAILABLE
            reason = None if reached else "A mapping exists, but the book holds nothing it reaches."
        return PropagationGraph(
            signal_id=signal.id, availability=availability, reason=reason, portfolio_id=portfolio.portfolio_id, portfolio_name=portfolio.name,
            event_category=category.value if category else None, nodes=list(nodes.values()), edges=edges, active_factors=factors, reached=holdings,
            reached_value=reached_value, reached_share=reached_share, direct_share=direct_share, indirect_share=max(reached_share - direct_share, 0.0),
            evidenced_share=evidenced_share, assumed_share=assumed_share, mapping_basis=basis, not_reached=sorted(set(not_reached)),
            labels=[MAPPING_LABEL], limitations=LIMITATIONS, adjustments=adjustments)
