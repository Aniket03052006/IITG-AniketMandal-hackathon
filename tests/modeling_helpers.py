"""Synthetic prices and documents for the modeling tests (small, seeded, hand-checkable)."""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from eventshock.config import REPO_ROOT
from eventshock.modeling.config import ModelingConfig, load_modeling_config
from eventshock.modeling.corpora import HistoryDoc
from eventshock.modeling.market import PriceStore

SECTORS = {"AAA": "Tech", "BBB": "Tech", "CCC": "Tech", "DDD": "Energy"}


def base_config() -> ModelingConfig:
    return load_modeling_config(REPO_ROOT / "configs")


def override(cfg: ModelingConfig, **sections: dict) -> ModelingConfig:
    """Deep-merge dict overrides into the validated config, e.g. ``override(cfg, impact={"window_sessions": 1})``."""
    data = cfg.model_dump(mode="json")
    for k, v in sections.items():
        data[k] = {**data[k], **v}
    return ModelingConfig.model_validate(data)


def business_days(start: date, n: int) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def make_store(n: int = 520, *, seed: int = 7, shock: dict[tuple[str, int], float] | None = None,
               sectors: dict[str, str] | None = None, cfg: ModelingConfig | None = None) -> PriceStore:
    """Market ^GSPC plus issuers whose returns are beta * market + noise. ``shock`` adds (ticker, session) -> extra return."""
    cfg = cfg or base_config()
    rng = random.Random(seed)
    dates = business_days(date(2020, 1, 1), n)
    mret = [rng.gauss(0.0003, 0.01) for _ in range(n)]
    sectors = SECTORS if sectors is None else sectors
    series = {cfg.impact.market_symbol: _cum(mret), cfg.impact.volatility_symbol: [20 + 5 * math.sin(i / 20) for i in range(n)]}
    volume = {s: [1_000_000.0 + 1000 * i for i in range(n)] for s in (*sectors, cfg.impact.market_symbol, cfg.impact.volatility_symbol)}
    for k, t in enumerate(sectors):
        beta = 0.8 + 0.3 * k
        r = [beta * mret[i] + rng.gauss(0, 0.012) for i in range(n)]
        for (tt, i), extra in (shock or {}).items():
            if tt == t:
                r[i] += extra
        series[t] = _cum(r)
    return PriceStore(dates, series, volume, sectors, cfg.impact)


def _cum(r: list[float]) -> list[float]:
    p, out = 100.0, []
    for x in r:
        p *= 1 + x
        out.append(p)
    return out


def make_doc(i: int, *, text: str = "Company announces something", adapter: str = "top-tweets", ticker: str | None = "AAA",
             published_at: datetime | None = None, origin: str = "SOURCE", multi: bool = False, link: float = 1.0,
             rule: str = "CASHTAG", tags: tuple[str, ...] = (), placeholder: str = "MARKET_VALUATION",
             sentiment: float = 0.0) -> HistoryDoc:
    return HistoryDoc(
        id=f"d{i}", adapter=adapter, source_type="SOCIAL", text=text,
        published_at=published_at or datetime(2021, 5, 4, 21, 0, tzinfo=UTC), origin=origin, ticker=ticker,
        entity_id=f"ENT_{ticker}" if ticker else "UNKNOWN_ENTITY", link_confidence=link, multi_entity=multi, er_rule=rule,
        novelty=1.0, dataset_tickers=tags, cluster_id=f"cl{i}", member_count=1, placeholder_event=placeholder,
        placeholder_sentiment=sentiment, gkg_tone=None)


def write_prices(dirpath: Path, store: PriceStore) -> None:
    from eventshock.modeling.market import file_stem

    dirpath.mkdir(parents=True, exist_ok=True)
    for s, closes in store.close.items():
        lines = ["date,open,high,low,close,adj_close,volume"]
        for d, c, v in zip(store.dates, closes, store.volume[s], strict=True):
            lines.append(f"{d},{c},{c},{c},{c},{c},{int(v)}")
        (dirpath / f"{file_stem(s)}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
