"""Where is the portfolio concentrated, and which current events bear on the same part of it?

Concentration is shown for issuer, sector, industry, geography, asset class and risk factor, and a slice is flagged only when it is meaningful: at least
``min_share`` of the book *and* several times an equal split across the dimension's items (a book with two sectors is always "concentrated" and is not flagged).
Cash and Unclassified are never flagged. Risk-factor exposure is the part of the book the transmission table says a factor reaches: these overlap, so they do not add to 100%.

Overlapping events: several independent events (one story is one event) that bear on the same risk factor AND reach the same holdings. The cluster is reported with the
shared holdings and the share of the book they are; a single event, or events that touch different holdings, make no cluster.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from ..adjust.models import AdjustmentNotice
from ..domain import AssetClass, Portfolio, PortfolioAsset
from ..intelligence.model import Availability
from .config import PropagationConfig, level_rank
from .mapping import PropagationMapper
from .models import (
    ConcentrationRow,
    ConcentrationView,
    DimensionConcentration,
    OverlapCluster,
    OverlapEvent,
    OverlapView,
    PropagationGraph,
    ReachedHolding,
    Status,
)

UNCLASSIFIED = "Unclassified"
NEVER_FLAGGED = {UNCLASSIFIED, AssetClass.CASH.value, AssetClass.OTHER.value}


@dataclass(frozen=True)
class OverlapItem:
    signal_id: str
    event_id: str
    headline: str
    published_at: datetime | None
    materiality: str
    severity: float | None
    graph: PropagationGraph


class ConcentrationAnalyzer:
    def __init__(self, cfg: PropagationConfig, industry_of: Callable[[PortfolioAsset], str | None],
                 entity_names: Callable[[], Mapping[str, str]] | None = None) -> None:
        self.cfg = cfg
        self._industry = industry_of
        self._names = entity_names or (lambda: {})

    # ----------------------------------------------------------------------------------------------------------------- view
    def view(self, portfolio: Portfolio, adjustments: AdjustmentNotice | None = None) -> ConcentrationView:
        total = portfolio.total_value
        c = self.cfg.concentration
        dims: list[DimensionConcentration] = []
        keys: dict[str, Callable[[PortfolioAsset], tuple[str, str]]] = {
            "issuer": lambda a: (a.entity_id, self._names().get(a.entity_id) or a.name.split(" - ")[0]),
            "sector": lambda a: (a.sector, a.sector),
            "industry": lambda a: ((i := self._industry(a) or UNCLASSIFIED), i),
            "geography": lambda a: (a.geography, a.geography),
            "asset_class": lambda a: (a.asset_type.value, a.asset_type.value.title()),
        }
        labels = {"issuer": "Issuer", "sector": "Sector", "industry": "Industry", "geography": "Geography", "asset_class": "Asset class"}
        plurals = {"issuer": "issuers", "sector": "sectors", "industry": "industries", "geography": "geographies", "asset_class": "asset classes"}
        flags: list[str] = []
        for dim, fn in keys.items():
            groups: dict[str, list] = defaultdict(lambda: ["", 0.0, 0])
            for a in portfolio.assets:
                k, lab = fn(a)
                g = groups[k]
                g[0], g[1], g[2] = lab, g[1] + a.market_value, g[2] + 1
            n = len(groups)
            rows, hhi = [], 0.0
            for k, (lab, v, cnt) in sorted(groups.items(), key=lambda kv: (-kv[1][1], kv[0])):
                share = v / total if total else 0.0
                hhi += share * share
                meaningful = (n >= c.min_items and k not in NEVER_FLAGGED and share >= c.min_share and share >= c.equal_weight_multiple / n)
                rows.append(ConcentrationRow(key=k, label=lab, value=v, share=share, position_count=cnt, flagged=meaningful))
                if meaningful:
                    flags.append(f"{labels[dim]} {lab}: {share:.0%} of the book, {share * n:.1f} times an equal split across {n} {plurals[dim]}.")
            # a Herfindahl index can never fall below 1/n, so the bar also scales with the number of items (four asset classes are always at least 0.25)
            hhi_bar = max(c.hhi_flag, c.hhi_equal_weight_multiple / n) if n else c.hhi_flag
            whole = n >= c.min_items and hhi >= hhi_bar
            reason = (None if n >= c.min_items else f"only {n} {plurals[dim]}: too few for a concentration test")
            if whole:
                flags.append(f"{labels[dim]} mix: Herfindahl index {hhi:.2f} across {n} {plurals[dim]} (flag at {hhi_bar:.2f}).")
            dims.append(DimensionConcentration(dimension=dim, label=labels[dim], rows=rows, item_count=n, hhi=hhi, effective_n=(1 / hhi if hhi else 0.0),
                                               top_share=rows[0].share if rows else 0.0, flagged=whole or any(r.flagged for r in rows), reason=reason,
                                               note="Unclassified holdings have no industry in the entity master and are never flagged." if dim == "industry" else None))
        # risk factors: the part of the book the transmission table says each reaches (overlapping, not a partition)
        rf_rows: list[ConcentrationRow] = []
        for rid, rf in self.cfg.risk_factors.items():
            reached: dict[str, float] = {}
            for edge in rf.transmission.values():
                if not edge.enabled:
                    continue
                for a in portfolio.assets:
                    if a.asset_type in (AssetClass.CASH, AssetClass.OTHER):
                        continue
                    if PropagationMapper._match(edge, a, self._industry(a), rf.engine_factor):  # noqa: SLF001 (the one rule for what a factor reaches)
                        reached[a.asset_id] = a.market_value
            v = sum(reached.values())
            share = v / total if total else 0.0
            rf_rows.append(ConcentrationRow(key=rid, label=rf.label, value=v, share=share, position_count=len(reached), flagged=False))
        rf_rows.sort(key=lambda r: (-r.share, r.key))
        dims.append(DimensionConcentration(
            dimension="risk_factor", label="Risk factor", rows=rf_rows, item_count=len(rf_rows), hhi=0.0, effective_n=0.0, top_share=rf_rows[0].share if rf_rows else 0.0,
            flagged=False, reason=None,
            note="Informational, never flagged: shares overlap (one holding can bear on several factors) and follow the transmission table, which is an assumption, not a measured sensitivity. "
                 "Where several current events bear on one factor and the same holdings, that is shown under overlapping events."))
        return ConcentrationView(
            portfolio_id=portfolio.portfolio_id, portfolio_name=portfolio.name, total_value=total, dimensions=dims, flags=flags, adjustments=adjustments,
            note=("Only meaningful concentration is flagged: at least "
                  f"{c.min_share:.0%} of the book and {c.equal_weight_multiple:g} times an equal split. Concentration is a description of holdings, not a forecast."))

    # --------------------------------------------------------------------------------------------------------------- overlaps
    def overlaps(self, portfolio: Portfolio, items: list[OverlapItem], *, considered: int | None = None,
                 adjustments: AdjustmentNotice | None = None) -> OverlapView:
        c = self.cfg.concentration
        total = portfolio.total_value
        keep = [i for i in items if i.materiality in ("LOW", "MEDIUM", "HIGH", "CRITICAL") and level_rank(i.materiality) >= level_rank(c.min_materiality)]
        # one story is one event: keep the most material report of each
        best: dict[str, OverlapItem] = {}
        for i in keep:
            cur = best.get(i.event_id)
            if cur is None or (level_rank(i.materiality), i.severity or 0, i.signal_id) > (level_rank(cur.materiality), cur.severity or 0, cur.signal_id):
                best[i.event_id] = i
        per_factor: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))  # factor -> event -> asset ids reached via it
        holding: dict[str, ReachedHolding] = {}
        for i in best.values():
            # only a factor the text itself is about (or the user set) counts: an event class that merely implies a factor does not make two events overlap
            evidenced = {f.id for f in i.graph.active_factors if f.status is not Status.SCENARIO_ASSUMPTION}
            for h in i.graph.reached:
                holding[h.asset_id] = h
                for route in h.routes:
                    rid = route.split(":", 1)[0]
                    if rid in evidenced:
                        per_factor[rid][i.event_id].add(h.asset_id)
        clusters: list[OverlapCluster] = []
        for rid, by_event in sorted(per_factor.items()):
            if len(by_event) < c.min_events:
                continue
            count: dict[str, int] = defaultdict(int)
            for assets in by_event.values():
                for a in assets:
                    count[a] += 1
            shared = [holding[a] for a, n in count.items() if n >= c.min_events]
            value = sum(h.market_value for h in shared)
            share = value / total if total else 0.0
            if not shared or share < c.min_overlap_share:
                continue
            shared_ids = {h.asset_id for h in shared}
            ev = [OverlapEvent(signal_id=best[e].signal_id, event_id=e, headline=best[e].headline[:160], published_at=best[e].published_at, materiality=best[e].materiality,
                               severity=best[e].severity) for e, assets in sorted(by_event.items()) if assets & shared_ids]
            if len(ev) < c.min_events:
                continue
            lab = self.cfg.risk_factors[rid].label
            clusters.append(OverlapCluster(
                risk_factor=rid, risk_factor_label=lab, events=ev, shared_holdings=sorted(shared, key=lambda h: -h.market_value)[:12], shared_value=value, shared_share=share,
                sentence=(f"{len(ev)} independent events bear on {lab.lower()} and reach the same {len(shared)} positions ({share:.1%} of the book): "
                          "the risk is concentrated in those holdings, not spread across the events.")))
        clusters.sort(key=lambda k: (-k.shared_share, k.risk_factor))
        n_events = len(best)
        return OverlapView(
            portfolio_id=portfolio.portfolio_id, availability=Availability.AVAILABLE, reason=None if clusters else "no risk factor is borne on by several independent events that reach the same holdings",
            window_days=c.window_days, considered=considered if considered is not None else n_events, clusters=clusters, adjustments=adjustments,
            note=(f"Events from the last {c.window_days:g} days at relevance {c.min_materiality} or above, one story counted once. Overlap needs {c.min_events}+ "
                  f"independent events sharing a risk factor and at least {c.min_overlap_share:.0%} of the book in common."))
