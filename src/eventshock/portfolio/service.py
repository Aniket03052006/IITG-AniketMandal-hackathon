"""One door for portfolios: the synthetic default plus any saved personal ones.

``None`` or ``"default"`` always means the synthetic wholesale book, unchanged. A personal portfolio is only ever used when a request names it,
so the feature is opt-in and one request without an id is back on the default.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ..domain import Portfolio
from ..ports import PortfolioRepository
from .models import (
    DEFAULT_ID,
    Issue,
    IssueLevel,
    ParseRequest,
    ParseResult,
    PortfolioInput,
    PortfolioListItem,
    PortfolioView,
    ResolvedPortfolio,
    StoredPortfolio,
)
from .resolve import Resolver
from .store import PortfolioNotFound, PortfolioStore


class PortfolioInvalid(ValueError):
    def __init__(self, issues: list[Issue]) -> None:
        super().__init__("; ".join(i.message for i in issues if i.level is IssueLevel.ERROR) or "invalid portfolio")
        self.issues = issues


class PortfolioService:
    def __init__(self, default: PortfolioRepository, store: PortfolioStore, resolver: Resolver,
                 clock: Callable[[], datetime] | None = None, presets: dict[str, Portfolio] | None = None) -> None:
        self._default = default
        self._presets = dict(presets or {})   # committed, read-only synthetic books (Wholesale Book v2), addressed by their own portfolio_id
        self._store = store
        self._resolver = resolver
        self._clock = clock or (lambda: datetime.now(UTC))

    # ----------------------------------------------------------------------------------------------------- identity
    def is_default(self, pid: str | None) -> bool:
        return pid is None or pid == DEFAULT_ID or pid == self._default.get().portfolio_id

    def is_preset(self, pid: str | None) -> bool:
        return pid is not None and pid in self._presets

    def presets(self) -> list[PortfolioListItem]:
        return [PortfolioListItem(id=p.portfolio_id, name=p.name, kind="PRESET", base_currency=p.base_currency, total_value=p.total_value,
                                  holding_count=len(p.assets), description=p.description, updated_at=None) for p in self._presets.values()]

    def _default_item(self) -> PortfolioListItem:
        pf = self._default.get()
        return PortfolioListItem(id=DEFAULT_ID, name=pf.name, kind="DEFAULT", base_currency=pf.base_currency, total_value=pf.total_value,
                                 holding_count=len(pf.assets), description=pf.description, updated_at=None)

    def _item(self, sp: StoredPortfolio, res: ResolvedPortfolio) -> PortfolioListItem:
        return PortfolioListItem(id=sp.id, name=sp.name, kind="USER", base_currency=res.base_currency, total_value=res.total_value or 0.0,
                                 holding_count=len(res.holdings), description=sp.notes or "Your portfolio", updated_at=sp.updated_at)

    def resolve_stored(self, sp: StoredPortfolio) -> ResolvedPortfolio:
        return self._resolver.resolve(sp, portfolio_id=sp.id, as_of=sp.updated_at)

    # -------------------------------------------------------------------------------------------------------- reads
    def list(self) -> list[PortfolioListItem]:
        return [self._default_item(), *(self._item(sp, self.resolve_stored(sp)) for sp in self._store.list())]

    def view(self, pid: str | None) -> PortfolioView:
        if self.is_default(pid):
            return PortfolioView(id=DEFAULT_ID, kind="DEFAULT", list_item=self._default_item())
        if self.is_preset(pid):
            return PortfolioView(id=str(pid), kind="PRESET", list_item=next(i for i in self.presets() if i.id == pid))
        sp = self._store.get(pid)  # type: ignore[arg-type]
        res = self.resolve_stored(sp)
        return PortfolioView(id=sp.id, kind="USER", stored=sp, resolved=res, list_item=self._item(sp, res))

    def get_portfolio(self, pid: str | None) -> Portfolio:
        """The engine's portfolio for an id (None / 'default' -> the synthetic book). A saved portfolio that no longer resolves is refused."""
        if self.is_default(pid):
            return self._default.get()
        if self.is_preset(pid):
            return self._presets[pid]  # type: ignore[index]
        res = self.resolve_stored(self._store.get(pid))  # type: ignore[arg-type]
        if not res.ok or res.portfolio is None:
            raise PortfolioInvalid(res.issues)
        return res.portfolio

    def label(self, pid: str | None) -> tuple[str, str]:
        """(id, kind) a request resolves to."""
        if self.is_default(pid):
            return DEFAULT_ID, "DEFAULT"
        return (str(pid), "PRESET") if self.is_preset(pid) else (str(pid), "USER")

    # ------------------------------------------------------------------------------------------------------- writes
    def validate(self, inp: PortfolioInput) -> ResolvedPortfolio:
        return self._resolver.resolve(inp, portfolio_id="pf_draft", as_of=self._clock())

    def _checked(self, inp: PortfolioInput) -> None:
        res = self.validate(inp)
        if not res.ok:
            raise PortfolioInvalid(res.issues)

    def create(self, inp: PortfolioInput) -> PortfolioView:
        self._checked(inp)
        return self.view(self._store.create(inp).id)

    def update(self, pid: str, inp: PortfolioInput) -> PortfolioView:
        if self.is_default(pid):
            raise PortfolioNotFound("the default portfolio is read-only: duplicate it or create your own")
        self._checked(inp)
        return self.view(self._store.update(pid, inp).id)

    def delete(self, pid: str) -> None:
        if self.is_default(pid):
            raise PortfolioNotFound("the default portfolio cannot be deleted")
        self._store.delete(pid)

    def duplicate(self, pid: str) -> PortfolioView:
        if self.is_default(pid):
            raise PortfolioNotFound("the default portfolio is a wholesale book of loans and derivatives and cannot be copied into a personal portfolio")
        sp = self._store.get(pid)
        data = sp.model_dump(exclude={"id", "created_at", "updated_at"})
        data["name"] = f"{sp.name} (copy)"[:80]
        return self.create(PortfolioInput.model_validate(data))

    def parse(self, req: ParseRequest) -> ParseResult:
        return self._resolver.parse_quick(req.text, name=req.name, base_currency=req.base_currency, as_of=self._clock())
