"""Turn what a user typed into the engine's ``Portfolio`` - deterministically, with every guess labelled and every defect named.

Rules (all of them deliberate; see ``docs/notes/PORTFOLIOS.md``):
- Reject or label, never guess silently. An ERROR blocks saving; a WARNING is saved and shown; an INFO says what EventShock did.
- WEIGHT mode: weights must sum to 100% (within a small rounding tolerance they are rescaled and the portfolio says so). Weights summing to
  less than 100% need an explicit "treat the remainder as cash"; more than 100% is always an error. Value = weight x total value.
- QUANTITY mode: value = quantity x price. There is no price feed, so a missing price is an error (cash is worth 1 per unit).
- A ticker EventShock does not know is allowed (as an equity at beta 1.0) but flagged: an event about a named company can only reach one of the 34
  issuers; an unknown holding can only be reached by sector and market-wide shocks.
- One base currency. A holding in another currency is valued as entered and flagged "FX not modelled".
"""

from __future__ import annotations

import math
import re
from datetime import datetime

from pydantic import ValidationError

from ..domain import AssetClass, Portfolio, PortfolioAsset
from .catalog import InstrumentCatalog, Reference
from .config import PortfolioConfig
from .models import (
    EntryMode,
    FieldSource,
    HoldingInput,
    Issue,
    IssueLevel,
    ParseResult,
    PortfolioInput,
    ResolvedHolding,
    ResolvedPortfolio,
)

TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=_]*$")
_NUM = r"\d+(?:\.\d+)?"
_PCT = re.compile(rf"^({_NUM})\s*%$")
_QTY_PRICE = re.compile(rf"^({_NUM})\s*(?:shares?|units?|sh)?\s*(?:@|x|×|at)\s*({_NUM})$", re.I)
_BARE = re.compile(rf"^({_NUM})$")
_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9.\-^=_]*)\s*[:,\t=]?\s*(.+?)\s*$")
DEFAULT_DESCRIPTION = "USER-DEFINED portfolio: holdings and any reference data used are listed per position with their source. Not a recommendation."


def _issue(level: IssueLevel, code: str, message: str, holding: int | None = None, field: str | None = None) -> Issue:
    return Issue(level=level, code=code, message=message, holding=holding, field=field)


class Resolver:
    def __init__(self, catalog: InstrumentCatalog, cfg: PortfolioConfig) -> None:
        self._cat = catalog
        self._cfg = cfg
        self._cash = {t.upper() for t in cfg.cash_tickers}

    # ------------------------------------------------------------------------------------------------ normalisers
    def _sector(self, raw: str | None) -> tuple[str | None, bool]:
        """(label, known). Known = one of the event vocabulary's sectors (or the explicit 'Other')."""
        if not raw or not raw.strip():
            return None, True
        key = raw.strip().lower()
        if key == "other":
            return "Other", True
        canon = self._cfg.sector_aliases.get(key)
        return (canon, True) if canon else (raw.strip().title() if raw.strip().islower() else raw.strip(), False)

    def _region(self, raw: str | None) -> tuple[str | None, bool]:
        if not raw or not raw.strip():
            return None, True
        key = raw.strip().lower()
        canon = self._cfg.region_aliases.get(key)
        return (canon, True) if canon else (raw.strip().upper(), False)

    # ----------------------------------------------------------------------------------------------------- resolve
    def resolve(self, inp: PortfolioInput, *, portfolio_id: str, as_of: datetime) -> ResolvedPortfolio:
        cfg = self._cfg
        issues: list[Issue] = []
        add = issues.append
        name = inp.name.strip()
        base = inp.base_currency.strip().upper()
        if not name:
            add(_issue(IssueLevel.ERROR, "NAME_REQUIRED", "Give the portfolio a name.", field="name"))
        elif len(name) > cfg.limits.max_name_length:
            add(_issue(IssueLevel.ERROR, "NAME_TOO_LONG", f"The name is longer than {cfg.limits.max_name_length} characters.", field="name"))
        if not base.isalpha():
            add(_issue(IssueLevel.ERROR, "BAD_CURRENCY", f"'{inp.base_currency}' is not a currency code (use three letters, e.g. USD, INR).", field="base_currency"))
        holdings = inp.holdings
        if not holdings:
            add(_issue(IssueLevel.ERROR, "NO_HOLDINGS", "Add at least one holding."))
        if len(holdings) > cfg.limits.max_holdings:
            add(_issue(IssueLevel.ERROR, "TOO_MANY_HOLDINGS", f"A portfolio holds at most {cfg.limits.max_holdings} positions."))
            holdings = holdings[: cfg.limits.max_holdings]

        # ---- identity: ticker syntax and duplicates
        tickers: list[str] = []
        seen: dict[str, int] = {}
        for i, h in enumerate(holdings):
            t = h.ticker.strip().upper()
            tickers.append(t)
            if not TICKER_RE.match(t):
                add(_issue(IssueLevel.ERROR, "INVALID_TICKER", f"'{h.ticker}' is not a valid identifier (letters, digits, . - ^ = _).", i, "ticker"))
            if t in seen:
                add(_issue(IssueLevel.ERROR, "DUPLICATE_TICKER", f"{t} appears twice (rows {seen[t] + 1} and {i + 1}): merge them into one holding.", i, "ticker"))
            seen.setdefault(t, i)

        # ---- values
        values: list[float | None] = [None] * len(holdings)
        extra_cash: float | None = None
        total: float | None = None
        mode = inp.mode
        if mode is EntryMode.WEIGHT:
            total = inp.total_value
            if total is None:
                total = cfg.limits.default_total_value
                add(_issue(IssueLevel.INFO, "TOTAL_DEFAULT", f"No total value given: weights are applied to {total:,.0f} {base}.", field="total_value"))
            elif not math.isfinite(total) or total <= 0:
                add(_issue(IssueLevel.ERROR, "BAD_TOTAL", "The total value must be a positive number.", field="total_value"))
                total = None
            weights: list[float | None] = []
            for i, h in enumerate(holdings):
                w = h.weight_pct
                if w is None:
                    add(_issue(IssueLevel.ERROR, "MISSING_WEIGHT", f"{tickers[i]}: enter a weight (percent of the portfolio).", i, "weight_pct"))
                elif not math.isfinite(w) or w <= 0 or w > 100:
                    add(_issue(IssueLevel.ERROR, "INVALID_WEIGHT", f"{tickers[i]}: a weight must be above 0% and at most 100% (short positions are not supported).", i, "weight_pct"))
                    w = None
                weights.append(w)
            if all(w is not None for w in weights) and holdings:
                s = sum(w for w in weights if w is not None)
                tol = cfg.weights.sum_tolerance_pp
                if s > 100 + tol:
                    add(_issue(IssueLevel.ERROR, "WEIGHTS_SUM", f"The weights add up to {s:.2f}%, more than 100%: reduce them.", field="weight_pct"))
                elif s < 100 - tol:
                    if inp.remainder_as_cash:
                        extra_cash = 100 - s
                        add(_issue(IssueLevel.INFO, "REMAINDER_CASH", f"The weights add up to {s:.2f}%: the other {extra_cash:.2f}% is held as cash.", field="weight_pct"))
                    else:
                        add(_issue(IssueLevel.ERROR, "WEIGHTS_SUM", f"The weights add up to {s:.2f}%, not 100%: add the rest (for example as cash) or tick 'treat the remainder as cash'.", field="weight_pct"))
                elif abs(s - 100) > 1e-9:
                    add(_issue(IssueLevel.INFO, "WEIGHTS_RESCALED", f"The weights added up to {s:.2f}%, within rounding of 100%: they were rescaled to 100%.", field="weight_pct"))
                    weights = [w * 100 / s if w is not None else None for w in weights]
                if total is not None:
                    values = [w / 100 * total if w is not None else None for w in weights]
                    if extra_cash is not None:
                        extra_cash = extra_cash / 100 * total
            if any(h.quantity is not None or h.price is not None for h in holdings):
                add(_issue(IssueLevel.INFO, "QTY_IGNORED", "Quantities and prices are ignored in WEIGHT mode (value = weight x total).", field="quantity"))
        else:
            for i, h in enumerate(holdings):
                is_cash = tickers[i] in self._cash or h.asset_class == "CASH"
                q, p = h.quantity, h.price
                if p is None and is_cash:
                    p = 1.0
                if q is None or not math.isfinite(q) or q <= 0:
                    add(_issue(IssueLevel.ERROR, "INVALID_QUANTITY", f"{tickers[i]}: quantity must be a positive number (short positions are not supported).", i, "quantity"))
                elif p is None:
                    add(_issue(IssueLevel.ERROR, "MISSING_PRICE", f"{tickers[i]}: enter its current price - EventShock has no price feed to look it up.", i, "price"))
                elif not math.isfinite(p) or p <= 0:
                    add(_issue(IssueLevel.ERROR, "INVALID_PRICE", f"{tickers[i]}: price must be a positive number.", i, "price"))
                else:
                    values[i] = q * p
            total = sum(v for v in values if v is not None) if all(v is not None for v in values) and holdings else None
            if any(h.weight_pct is not None for h in holdings):
                add(_issue(IssueLevel.INFO, "WEIGHT_IGNORED", "Weights are ignored in QUANTITY mode: they are derived from quantity x price.", field="weight_pct"))

        # ---- per-holding reference data
        resolved: list[ResolvedHolding] = []
        order = [(i, h) for i, h in enumerate(holdings)]
        for i, h in order:
            r = self._resolve_one(i, h, tickers[i], base, values[i], mode, issues)
            if r is not None:
                resolved.append(r)
        if extra_cash:  # the remainder is its own cash holding (or joins an existing one)
            cash = next((r for r in resolved if r.asset_class is AssetClass.CASH and r.currency == base), None)
            if cash is not None:
                cash.value += extra_cash
            else:
                resolved.append(ResolvedHolding(
                    index=len(holdings), asset_id=f"H{len(holdings) + 1:03d}-CASH", ticker="CASH", name="Cash (remainder)", asset_class=AssetClass.CASH,
                    sector="Cash", region="OTHER", currency=base, value=extra_cash, weight=0.0, in_universe=False,
                    sources={"value": FieldSource.DERIVED, "asset_class": FieldSource.DERIVED}, basis=["the part of the weights that was not assigned"]))
        grand = sum(r.value for r in resolved)
        for r in resolved:
            r.weight = r.value / grand if grand else 0.0
            if r.quantity is not None and r.price is not None and r.cost_basis is not None:
                r.unrealised_pnl = (r.price - r.cost_basis) * r.quantity
        if mode is EntryMode.QUANTITY:
            total = grand if resolved and len(resolved) == len(holdings) else total

        ok = not any(i.level is IssueLevel.ERROR for i in issues)
        portfolio = self._engine_portfolio(resolved, portfolio_id, name, base, as_of, issues) if ok else None
        ok = ok and portfolio is not None
        return ResolvedPortfolio(ok=ok, mode=mode, total_value=total if total is not None else (grand or None), base_currency=base,
                                 holdings=resolved, issues=issues, portfolio=portfolio)

    # ----------------------------------------------------------------------------------------------------- one holding
    def _resolve_one(self, i: int, h: HoldingInput, ticker: str, base: str, value: float | None, mode: EntryMode,
                     issues: list[Issue]) -> ResolvedHolding | None:
        def say(level: IssueLevel, code: str, msg: str, field: str | None = None) -> None:
            issues.append(_issue(level, code, msg, i, field))

        src: dict[str, FieldSource] = {}
        basis: list[str] = []
        is_cash = ticker in self._cash
        ref: Reference | None = None if is_cash else self._cat.lookup(ticker)

        # asset class
        if h.asset_class is not None:
            cls = AssetClass(h.asset_class)
            src["asset_class"] = FieldSource.USER
            if ref and ref.asset_class != h.asset_class:
                say(IssueLevel.INFO, "CLASS_OVERRIDE", f"{ticker}: treated as {h.asset_class} as you entered (reference data says {ref.asset_class}).", "asset_class")
        elif is_cash:
            cls, src["asset_class"] = AssetClass.CASH, FieldSource.REFERENCE
        elif ref:
            cls, src["asset_class"] = AssetClass(ref.asset_class), FieldSource.REFERENCE
        else:
            cls, src["asset_class"] = AssetClass.EQUITY, FieldSource.DEFAULT_ASSUMPTION
            say(IssueLevel.WARNING, "UNKNOWN_TICKER",
                f"{ticker} is not one of the 34 issuers or a known fund: it is treated as an equity at beta 1.0 unless you set otherwise, and only sector "
                "and market-wide events can reach it (an event about a named company cannot).", "ticker")
        if cls is AssetClass.OTHER:
            say(IssueLevel.WARNING, "NOT_STRESSED", f"{ticker}: EventShock has no revaluation rule for this class, so it is held at its value and listed as not stressed (not as safe).", "asset_class")
        if cls is AssetClass.CASH and ref is not None and not is_cash:
            ref = None

        # name, sector, region, currency
        nm = (h.name or "").strip() or (ref.name if ref else ticker)
        src["name"] = FieldSource.USER if h.name else (FieldSource.REFERENCE if ref else FieldSource.DEFAULT_ASSUMPTION)

        sector, known = self._sector(h.sector)
        if sector is not None:
            src["sector"] = FieldSource.USER
            if not known:
                say(IssueLevel.WARNING, "UNKNOWN_SECTOR",
                    f"'{h.sector}' is not a sector the event vocabulary uses (Financials, Technology, Energy, Healthcare, Industrials, Consumer): "
                    "it is kept as typed, and sector-level events will not reach it.", "sector")
        elif cls is AssetClass.CASH:
            sector, src["sector"] = "Cash", FieldSource.REFERENCE
        elif ref:
            sector, src["sector"] = ref.sector, FieldSource.REFERENCE
        else:
            sector, src["sector"] = "Other", FieldSource.DEFAULT_ASSUMPTION

        region, rknown = self._region(h.region)
        if region is not None:
            src["region"] = FieldSource.USER
            if not rknown:
                say(IssueLevel.WARNING, "UNKNOWN_REGION", f"'{h.region}' is not a region the event vocabulary names (US, GB, EU, CN, JP, IN, MIDEAST, RU_UA): kept as typed.", "region")
        elif ref:
            region, src["region"] = ref.region, FieldSource.REFERENCE
        else:
            region, src["region"] = "OTHER", FieldSource.DEFAULT_ASSUMPTION

        currency = (h.currency or base).upper()
        src["currency"] = FieldSource.USER if h.currency else FieldSource.DEFAULT_ASSUMPTION
        if currency != base:
            say(IssueLevel.WARNING, "FX_NOT_MODELLED", f"{ticker} is in {currency} but the portfolio is in {base}: it is valued as entered. No event scenario moves currencies; the scenario lab can shock {currency} against {base}.", "currency")

        # beta (equities), duration and spread sensitivity (bonds)
        beta = duration = spread = None
        if cls is AssetClass.EQUITY:
            if h.beta is not None:
                if not -1 <= h.beta <= 3:
                    say(IssueLevel.ERROR, "BETA_RANGE", f"{ticker}: beta must be between -1 and 3.", "beta")
                beta, src["beta"] = h.beta, FieldSource.USER
            elif ref and ref.beta is not None:
                beta, src["beta"] = ref.beta, FieldSource.REFERENCE
                basis.append(ref.basis)
            else:
                beta, src["beta"] = 1.0, FieldSource.DEFAULT_ASSUMPTION
                basis.append("no beta on file: the market average, 1.0, is assumed")
        elif cls is AssetClass.BOND:
            if h.duration is not None:
                if not 0 <= h.duration <= 30:
                    say(IssueLevel.ERROR, "DURATION_RANGE", f"{ticker}: duration must be between 0 and 30 years.", "duration")
                duration, src["duration"] = h.duration, FieldSource.USER
            elif ref and ref.duration is not None:
                duration, src["duration"] = ref.duration, FieldSource.REFERENCE
                basis.append(ref.basis)
            else:
                say(IssueLevel.ERROR, "MISSING_DURATION", f"{ticker}: enter the bond's modified duration in years - a bond's rate sensitivity cannot be guessed.", "duration")
            if ref and ref.spread_sensitivity is not None:
                spread, src["spread_sensitivity"] = ref.spread_sensitivity, FieldSource.REFERENCE
            else:
                spread, src["spread_sensitivity"] = 1.0, FieldSource.DEFAULT_ASSUMPTION
                basis.append("treated as corporate credit: it takes the full credit-spread shock")
        elif ref and ref.basis:
            basis.append(ref.basis)

        # cost basis (informational)
        if h.cost_basis is not None and (not math.isfinite(h.cost_basis) or h.cost_basis <= 0):
            say(IssueLevel.ERROR, "INVALID_COST", f"{ticker}: cost basis must be a positive number.", "cost_basis")
        if value is None:
            return None
        qty = h.quantity if mode is EntryMode.QUANTITY else None
        price = (h.price if h.price is not None else (1.0 if cls is AssetClass.CASH else None)) if mode is EntryMode.QUANTITY else None
        src["value"] = FieldSource.DERIVED
        return ResolvedHolding(
            index=i, asset_id=f"H{i + 1:03d}-{ticker}", ticker=ticker, name=nm, asset_class=cls, sector=sector, region=region, currency=currency,
            value=value, weight=0.0, quantity=qty, price=price, cost_basis=h.cost_basis if h.cost_basis and h.cost_basis > 0 else None,
            beta=beta, duration=duration, spread_sensitivity=spread, in_universe=bool(ref and ref.kind == "ISSUER"), sources=src, basis=basis)

    # --------------------------------------------------------------------------------------------------- engine book
    def _engine_portfolio(self, rows: list[ResolvedHolding], portfolio_id: str, name: str, base: str, as_of: datetime,
                          issues: list[Issue]) -> Portfolio | None:
        assets = []
        for r in rows:
            ref = self._cat.lookup(r.ticker) if r.asset_class is not AssetClass.CASH else None
            entity = ref.entity_id if ref and ref.entity_id else f"USER_{r.ticker}"
            try:
                assets.append(PortfolioAsset(
                    asset_id=r.asset_id, asset_type=r.asset_class, entity_id=entity, name=r.name, sector=r.sector, geography=r.region,
                    notional=r.value, market_value=r.value, beta=r.beta if r.beta is not None else 1.0, duration=r.duration,
                    spread_sensitivity=r.spread_sensitivity if r.spread_sensitivity is not None else 1.0,
                    currency=r.currency if r.currency != base else None))  # a holding in another currency carries its exchange-rate exposure (only the scenario lab shocks it)
            except ValidationError as exc:
                issues.append(_issue(IssueLevel.ERROR, "INVALID_HOLDING", f"{r.ticker}: {exc.errors()[0]['msg']}", r.index))
                return None
        if not assets:
            return None
        try:
            return Portfolio(portfolio_id=portfolio_id, name=name, as_of=as_of, base_currency=base, description=DEFAULT_DESCRIPTION, assets=assets)
        except ValidationError as exc:
            issues.append(_issue(IssueLevel.ERROR, "INVALID_PORTFOLIO", exc.errors()[0]["msg"]))
            return None

    # ------------------------------------------------------------------------------------------------- quick entry
    def parse_quick(self, text: str, *, name: str, base_currency: str, as_of: datetime) -> ParseResult:
        """Parse ``AAPL 20%`` / ``AAPL 100 @ 190`` / ``Cash 25%`` lines into a draft. Never saves; the draft is resolved so issues show at once."""
        issues: list[Issue] = []
        rows: list[tuple[int, str, tuple[str, float, float | None]]] = []
        cleaned = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)  # 1,000 -> 1000
        cleaned = re.sub(r"[$₹€£]", "", cleaned)
        n_line = 0
        for raw in cleaned.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            n_line += 1
            m = _LINE.match(line)
            if not m:
                issues.append(_issue(IssueLevel.ERROR, "UNREADABLE_LINE", f"Line {n_line}: '{raw.strip()}' - write a ticker and then a weight (AAPL 20%) or a quantity and price (AAPL 100 @ 190).", n_line - 1))
                continue
            ticker, rest = m.group(1).upper(), m.group(2)
            if (pm := _PCT.match(rest)):
                rows.append((n_line - 1, ticker, ("W", float(pm.group(1)), None)))
            elif (qm := _QTY_PRICE.match(rest)):
                rows.append((n_line - 1, ticker, ("Q", float(qm.group(1)), float(qm.group(2)))))
            elif (bm := _BARE.match(rest)) and ticker in self._cash:
                rows.append((n_line - 1, ticker, ("Q", float(bm.group(1)), 1.0)))
            else:
                issues.append(_issue(IssueLevel.ERROR, "UNREADABLE_LINE", f"Line {n_line}: '{raw.strip()}' - add a percent (20%) or a quantity and price (100 @ 190).", n_line - 1))
        kinds = {k for _, _, (k, _, _) in rows}
        if len(kinds) > 1:
            issues.append(_issue(IssueLevel.ERROR, "MIXED_MODES", "Use weights (%) on every line or quantity @ price on every line - not both."))
        if not rows and not issues:
            issues.append(_issue(IssueLevel.ERROR, "NO_HOLDINGS", "Nothing to read: enter one holding per line, e.g. AAPL 20%."))
        if any(i.level is IssueLevel.ERROR for i in issues):
            return ParseResult(draft=None, issues=issues)
        mode = EntryMode.WEIGHT if kinds == {"W"} else EntryMode.QUANTITY
        holdings = [HoldingInput(ticker=t, weight_pct=v if k == "W" else None, quantity=v if k == "Q" else None, price=p) for _, t, (k, v, p) in rows]
        draft = PortfolioInput(name=name, base_currency=base_currency, mode=mode, holdings=holdings)
        res = self.resolve(draft, portfolio_id="pf_draft", as_of=as_of)
        return ParseResult(draft=draft, issues=issues, resolved=res)
