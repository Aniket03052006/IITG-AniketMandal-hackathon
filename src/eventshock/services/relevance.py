"""What does this event mean for this portfolio? Exposure first, scenario second, nothing predicted.

Given a signal's scope, this reads the book (never a model) and reports which part of it the event reaches: the named issuer, the
sector, the regions the text points to, or the whole book through market-wide shocks. It also says how many of the default
scenario's shocks bind to this kind of event, using the same rule the stress engine applies (``stress_service._binds``).
Every figure is a holding of the synthetic portfolio, i.e. a historical/observed quantity of the book; the scenario's shock sizes
stay labelled illustrative and are not touched here.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from collections.abc import Callable
from enum import StrEnum

from pydantic import Field

from ..domain import AssetClass, Portfolio, RiskSignal, ScopeLevel
from ..domain.base import ContractModel
from ..ports import PortfolioRepository
from ..stress.scenarios import ScenarioCatalog
from .stress_service import _binds


class RelevanceLevel(StrEnum):
    DIRECT = "DIRECT"  # the book holds the named issuer
    SECTOR = "SECTOR"  # the event is about a sector (or an issuer the book does not hold, in a sector it does)
    MARKET_WIDE = "MARKET_WIDE"  # the whole book through market-wide shocks
    NONE = "NONE"  # the book has no exposure to what the event is about
    UNDETERMINED = "UNDETERMINED"  # nothing was identified, so relevance cannot be stated


class ExposureSlice(ContractModel):
    kind: str = Field(description="ISSUER | SECTOR | REGION | BOOK")
    key: str
    label: str
    market_value: float
    share: float = Field(description="of the whole book's market value")
    asset_count: int
    by_asset_class: dict[str, float] = Field(description="market value of the slice, by asset class")


class ScenarioReach(ContractModel):
    scenario_id: str
    scenario_name: str
    shocks_total: int
    shocks_bound: int = Field(description="of the scenario's shocks, how many reach this kind of event")
    note: str


class PortfolioRelevance(ContractModel):
    signal_id: str
    scope_level: str
    level: RelevanceLevel
    share: float | None = Field(description="of the book the most specific slice covers; null when undetermined")
    summary: str
    path: list[str] = Field(description="the chain from what the event is about to the book, most specific first")
    slices: list[ExposureSlice]
    reach: ScenarioReach | None = None
    band: str = Field(default="UNDETERMINED", description="NONE | LOW | MEDIUM | HIGH | UNDETERMINED: a display band on `share` (configs/portfolio.yaml), not a score; separate from severity and from the modeled impact")
    portfolio_id: str = ""
    portfolio_name: str = ""


class _Index:
    """Aggregates of the (immutable) book, built once per portfolio hash."""

    def __init__(self, portfolio) -> None:  # noqa: ANN001
        self.total = portfolio.total_value
        self.names = {a.entity_id: a.name.split(" - ")[0] for a in portfolio.assets}
        self.groups: dict[str, dict[str, dict]] = {"ISSUER": {}, "SECTOR": {}, "REGION": {}}
        for a in portfolio.assets:
            for kind, key in (("ISSUER", a.entity_id), ("SECTOR", a.sector), ("REGION", a.geography)):
                g = self.groups[kind].setdefault(key, {"value": 0.0, "n": 0, "cls": defaultdict(float)})
                g["value"] += a.market_value
                g["n"] += 1
                g["cls"][a.asset_type.value] += a.market_value
        self.book = {"value": self.total, "n": len(portfolio.assets), "cls": defaultdict(float)}
        for a in portfolio.assets:
            self.book["cls"][a.asset_type.value] += a.market_value
        # the part of the book a market-wide shock can move at all: cash and unsupported instruments cannot be reached
        self.shockable = sum(a.market_value for a in portfolio.assets if a.asset_type not in (AssetClass.CASH, AssetClass.OTHER))

    def slice(self, kind: str, key: str, label: str) -> ExposureSlice | None:
        g = self.book if kind == "BOOK" else self.groups[kind].get(key)
        if g is None:
            return None
        return ExposureSlice(kind=kind, key=key, label=label, market_value=g["value"],
                             share=g["value"] / self.total if self.total else 0.0, asset_count=g["n"],
                             by_asset_class={k: round(v, 2) for k, v in sorted(g["cls"].items())})


class RelevanceService:
    def __init__(self, portfolio: PortfolioRepository, catalog: ScenarioCatalog, band: Callable[[float | None], str] | None = None) -> None:
        self._portfolio = portfolio
        self._catalog = catalog
        self._band = band or (lambda share: "UNDETERMINED" if share is None else ("NONE" if share <= 0 else "HIGH" if share >= 0.2 else "MEDIUM" if share >= 0.05 else "LOW"))
        self._index: OrderedDict[str, _Index] = OrderedDict()  # a few books at once: switching portfolios must not rebuild every time

    def band(self, share: float | None) -> str:
        return self._band(share)

    def _idx(self, portfolio: Portfolio | None = None) -> _Index:
        pf = portfolio if portfolio is not None else self._portfolio.get()
        h = pf.content_hash()
        ix = self._index.get(h)
        if ix is None:
            ix = self._index[h] = _Index(pf)
            while len(self._index) > 8:
                self._index.popitem(last=False)
        else:
            self._index.move_to_end(h)
        return ix

    # ------------------------------------------------------------------------------------------------------------ feed row
    def headline(self, signal: RiskSignal, portfolio: Portfolio | None = None) -> tuple[RelevanceLevel, float | None]:
        """Level and share only (cheap, for the feed)."""
        r = self.assess(signal, with_reach=False, portfolio=portfolio)
        return r.level, r.share

    # --------------------------------------------------------------------------------------------------------------- detail
    def assess(self, signal: RiskSignal, *, with_reach: bool = True, portfolio: Portfolio | None = None) -> PortfolioRelevance:
        pf = portfolio if portfolio is not None else self._portfolio.get()
        ix = self._idx(pf)
        sc = signal.scope
        assert sc is not None
        slices: list[ExposureSlice] = []
        path: list[str] = []

        def add(kind: str, key: str, label: str) -> ExposureSlice | None:
            sl = ix.slice(kind, key, label)
            if sl:
                slices.append(sl)
            return sl

        pct = lambda sl: f"{sl.share:.1%}"  # noqa: E731
        level: RelevanceLevel
        share: float | None
        if sc.level is ScopeLevel.COMPANY:
            name = signal.entity.entity_name or signal.entity.entity_id
            issuer = add("ISSUER", signal.entity.entity_id, ix.names.get(signal.entity.entity_id, name))
            sector = add("SECTOR", sc.sector or "", sc.sector or "") if sc.sector else None
            if issuer:
                level, share = RelevanceLevel.DIRECT, issuer.share
                path = [f"{name}: held, {pct(issuer)} of the book in {issuer.asset_count} positions"]
                summary = (f"The book holds {name} directly: {issuer.asset_count} positions, {pct(issuer)} of its value.")
            elif sector:
                level, share = RelevanceLevel.SECTOR, sector.share
                path = [f"{name}: not held"]
                summary = f"The book does not hold {name}, but {pct(sector)} of it sits in {sc.sector} (read-across only)."
            else:
                level, share = RelevanceLevel.NONE, 0.0
                path = [f"{name}: not held"]
                summary = f"The book has no exposure to {name} or its sector."
            if sector:
                path.append(f"{sc.sector} sector: {pct(sector)} of the book in {sector.asset_count} positions")
        elif sc.level is ScopeLevel.SECTOR:
            sector = add("SECTOR", sc.sector or "", sc.sector or "")
            if sector:
                level, share = RelevanceLevel.SECTOR, sector.share
                path = [f"{sc.sector} sector: {pct(sector)} of the book in {sector.asset_count} positions"]
                summary = (f"No single company is named; the event is about {sc.sector}, which is {pct(sector)} of the book "
                           f"({sector.asset_count} positions).")
            else:
                level, share = RelevanceLevel.NONE, 0.0
                summary = f"The event is about {sc.sector}, which the book does not hold."
        elif sc.level is ScopeLevel.MARKET:
            level, share = RelevanceLevel.MARKET_WIDE, (ix.shockable / ix.total if ix.total else 0.0)
            themes = ", ".join(t.replace("_", " ") for t in sc.themes) or "market-wide"
            summary = f"A market-wide event ({themes}): it reaches the whole book through market-factor shocks, not through one holding."
            if share is not None and share < 0.9999:
                summary = (f"A market-wide event ({themes}): market-factor shocks can move {share:.1%} of the book; the rest is cash or instruments "
                           "EventShock cannot stress.")
        else:
            level, share = RelevanceLevel.UNDETERMINED, None
            summary = ("Nothing about this event could be tied to a company, sector or market theme, so its relevance to the book "
                       "cannot be stated. Market-wide shocks are the only ones that could apply.")
            path = ["Subject not identified"]
        book = add("BOOK", "BOOK", "Whole book")
        if sc.level in (ScopeLevel.MARKET, ScopeLevel.UNRESOLVED) and book:
            path.append(f"Whole book: {book.asset_count} positions via market-wide shocks")
        no_exposure = []
        for r in sc.regions:
            if sc.level is ScopeLevel.COMPANY:
                continue  # the company's country is not a separate claim
            if not add("REGION", r, r):
                no_exposure.append(r)
        if no_exposure:
            path.append(f"Region {', '.join(no_exposure)}: no positions in the book")
        reach = self._reach(signal) if with_reach else None
        return PortfolioRelevance(signal_id=signal.id, scope_level=sc.level.value, level=level, share=share, summary=summary,
                                  path=path, slices=slices, reach=reach, band=self._band(share), portfolio_id=pf.portfolio_id, portfolio_name=pf.name)

    def _reach(self, signal: RiskSignal) -> ScenarioReach | None:
        scn = self._catalog.default_for(signal.event.category)
        sc = signal.scope
        if scn is None or sc is None:
            return None
        known = sc.level is ScopeLevel.COMPANY and not signal.entity.is_unknown
        sector = sc.sector if sc.has_sector else None
        bound = sum(1 for s in scn.shocks if _binds(s.scope, sc.level, known, sector)[0])
        note = ("every shock reaches this event" if bound == len(scn.shocks) else
                "no shock in this scenario reaches this event" if bound == 0 else
                f"{len(scn.shocks) - bound} shock(s) need a company or sector this event does not name")
        return ScenarioReach(scenario_id=scn.id, scenario_name=scn.name, shocks_total=len(scn.shocks), shocks_bound=bound, note=note)
