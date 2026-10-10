"""Impact target and event-time features from daily prices. Pure standard library, point-in-time by construction.

Target (see ``docs/notes/MODELING_READINESS.md`` for the reasoning and measured evidence)::

    AR_k = r_k - a - b*m_k - c*p_k          market m (^GSPC) and sector-peer p (equal weight, ex-self)
    CAR  = sum of AR over sessions s0 .. s0+W-1
    z    = CAR / (sigma * sqrt(W))          sigma = RMS residual over the sigma_window sessions before s0
    impact score = 1 + #{cut points <= |z|}   fixed cut points from configs/modeling.yaml

``a, b, c`` and ``sigma`` use sessions strictly before ``s0``; no price at or after ``s0`` can reach a feature. The
target itself, of course, is the future relative to the report.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import accumulate
from pathlib import Path
from zoneinfo import ZoneInfo

from ..domain import UNKNOWN_ENTITY
from ..pipeline.market_context import SessionRules, anchor_session
from .config import ImpactConfig
from .corpora import HistoryDoc

NAN = float("nan")


def file_stem(symbol: str) -> str:
    return symbol.replace("^", "_").replace("/", "-").replace("=", "-")


def _read_series(path: Path) -> dict[str, tuple[float, float]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["date"]: (float(r["adj_close"]), float(r["volume"])) for r in csv.DictReader(fh)
                if r["adj_close"] and float(r["adj_close"]) > 0}


@dataclass(frozen=True)
class Fit:
    a: float
    b: float
    c: float  # 0.0 when the market-only model is used
    sigma: float
    n_fit: int
    factor_model: str  # "market+sector" | "market"


@dataclass(frozen=True)
class ImpactTarget:
    z: float  # signed
    abs_z: float
    car: float
    fit: Fit
    score: int


@dataclass(frozen=True)
class MarketTarget:
    """Market-wide severity: the S&P 500's own excess move over the same window, in trailing-sigma units."""

    z: float
    abs_z: float
    car: float
    mu: float
    sigma: float
    score: int


def score_from_abs_z(abs_z: float, cutpoints: Sequence[float]) -> int:
    """1 + number of cut points <= |z| (a value exactly on a cut point takes the higher score)."""
    return 1 + sum(1 for c in cutpoints if abs_z >= c)


class PriceStore:
    """Aligned daily series on the market calendar. Missing sessions are NaN, never filled."""

    def __init__(self, dates: list[str], close: dict[str, list[float]], volume: dict[str, list[float]],
                 sectors: dict[str, str], cfg: ImpactConfig) -> None:
        self.dates, self.close, self.volume, self.sectors, self.cfg = dates, close, volume, sectors, cfg
        self.tz = ZoneInfo(cfg.exchange_timezone)
        self.market = cfg.market_symbol
        if self.market not in close:
            raise ValueError(f"market symbol {self.market} missing from the price store")
        self.ret = {s: self._returns(v) for s, v in close.items()}
        self.peer: dict[str, list[float]] = {}
        self.peer_n: dict[str, int] = {}
        self._pre: dict[str, dict[str, list[float]]] = {}
        for t in close:
            if t in sectors:
                peers = [p for p, sec in sectors.items() if sec == sectors[t] and p != t and p in close]
                self.peer_n[t] = len(peers)
                self.peer[t] = [self._mean_valid([self.ret[p][i] for p in peers]) for i in range(len(dates))] if peers else []

    # ----------------------------------------------------------------------------------- construction
    @classmethod
    def from_dir(cls, prices_dir: Path, symbols: Sequence[str], sectors: dict[str, str], cfg: ImpactConfig) -> PriceStore:
        series = {s: _read_series(prices_dir / f"{file_stem(s)}.csv") for s in symbols}
        dates = sorted(series[cfg.market_symbol])
        close = {s: [series[s].get(d, (NAN, NAN))[0] for d in dates] for s in symbols}
        volume = {s: [series[s].get(d, (NAN, NAN))[1] for d in dates] for s in symbols}
        return cls(dates, close, volume, sectors, cfg)

    def scrambled_from(self, index: int, seed: int = 1) -> PriceStore:
        """A copy whose prices and volumes from session ``index`` on are replaced by deterministic noise.

        Used by the leakage tests: features at ``s0 = index`` must be identical on the original and on this copy.
        """
        def noise(i: int, k: int) -> float:
            return 0.5 + ((i * 2654435761 + k * 40503 + seed * 97) % 1000) / 500.0  # in [0.5, 2.5)

        close = {s: [v if i < index else v * noise(i, k) for i, v in enumerate(vals)]
                 for k, (s, vals) in enumerate(self.close.items())}
        volume = {s: [v if i < index else v * noise(i, k + 7) for i, v in enumerate(vals)]
                  for k, (s, vals) in enumerate(self.volume.items())}
        return PriceStore(self.dates, close, volume, self.sectors, self.cfg)

    @staticmethod
    def _returns(close: list[float]) -> list[float]:
        out = [NAN]
        for i in range(1, len(close)):
            a, b = close[i - 1], close[i]
            out.append(b / a - 1 if (a == a and b == b and a > 0) else NAN)
        return out

    @staticmethod
    def _mean_valid(xs: list[float]) -> float:
        v = [x for x in xs if x == x]
        return sum(v) / len(v) if v else NAN

    # ----------------------------------------------------------------------------------------- anchoring
    def session_rules(self) -> SessionRules:
        return SessionRules(self.cfg.exchange_timezone, self.cfg.session_open, self.cfg.session_close)

    def anchor(self, ts: datetime, origin: str) -> tuple[int | None, str]:
        """(s0, timing). See ``pipeline.market_context.anchor_session`` (the one implementation, shared with serving)."""
        return anchor_session(self.dates, ts, origin, self.session_rules())

    # ----------------------------------------------------------------------------------------- the model
    def _prefix(self, t: str) -> dict[str, list[float]]:
        """Prefix sums of the regression moments for ticker ``t`` (valid rows only)."""
        if t in self._pre:
            return self._pre[t]
        y, m = self.ret[t], self.ret[self.market]
        p = self.peer.get(t) or [NAN] * len(y)
        use_p = self.peer_n.get(t, 0) >= self.cfg.sector_min_peers
        rows = []
        for i in range(len(y)):
            ok = y[i] == y[i] and m[i] == m[i]
            pv = p[i] if (use_p and p[i] == p[i]) else (0.0 if not use_p else None)
            if not ok or pv is None:
                rows.append((0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
            else:
                rows.append((1, m[i], pv, y[i], m[i] * m[i], pv * pv, m[i] * pv, y[i] * m[i], y[i] * pv, y[i] * y[i]))
        names = ("n", "m", "p", "y", "mm", "pp", "mp", "ym", "yp", "yy")
        pre = {nm: [0.0, *accumulate(r[k] for r in rows)] for k, nm in enumerate(names)}
        self._pre[t] = pre
        return pre

    def _sum(self, pre: dict[str, list[float]], key: str, lo: int, hi: int) -> float:
        return pre[key][hi] - pre[key][lo]

    def fit_before(self, t: str, start: int) -> tuple[Fit | None, str]:
        """Fit using sessions [start - beta_window, start - 1]. Returns (fit, reason-if-None)."""
        cfg = self.cfg
        lo = max(1, start - cfg.beta_window)
        if start - lo < cfg.min_history_sessions:
            return None, "INSUFFICIENT_HISTORY"
        pre = self._prefix(t)
        S = {k: self._sum(pre, k, lo, start) for k in pre}
        n = S["n"]
        if n < cfg.min_history_sessions:
            return None, "INSUFFICIENT_HISTORY"
        use_p = self.peer_n.get(t, 0) >= cfg.sector_min_peers
        cmm, cpp, cmp_ = S["mm"] - S["m"] ** 2 / n, S["pp"] - S["p"] ** 2 / n, S["mp"] - S["m"] * S["p"] / n
        cym, cyp = S["ym"] - S["y"] * S["m"] / n, S["yp"] - S["y"] * S["p"] / n
        det = cmm * cpp - cmp_ ** 2
        if use_p and det > 1e-12 * max(cmm * cpp, 1e-30):
            b, c = (cym * cpp - cyp * cmp_) / det, (cyp * cmm - cym * cmp_) / det
            model = "market+sector"
        else:
            if cmm <= 0:
                return None, "DEGENERATE_FIT"
            b, c, model = cym / cmm, 0.0, "market"
        a = (S["y"] - b * S["m"] - c * S["p"]) / n
        slo = max(1, start - cfg.sigma_window)
        W = {k: self._sum(pre, k, slo, start) for k in pre}
        nw = W["n"]
        if nw < cfg.sigma_window * 0.5:
            return None, "INSUFFICIENT_HISTORY"
        ssr = (W["yy"] + nw * a * a + b * b * W["mm"] + c * c * W["pp"] - 2 * a * W["y"] - 2 * b * W["ym"]
               - 2 * c * W["yp"] + 2 * a * b * W["m"] + 2 * a * c * W["p"] + 2 * b * c * W["mp"])
        sigma = math.sqrt(max(ssr, 0.0) / nw)
        if sigma <= 0:
            return None, "DEGENERATE_FIT"
        return Fit(a, b, c, sigma, int(n), model), ""

    def target(self, t: str, start: int) -> tuple[ImpactTarget | None, str]:
        """CAR-z over sessions [start, start + W - 1] using only data before ``start`` for the model."""
        W = self.cfg.window_sessions
        if start + W > len(self.dates):
            return None, "CENSORED"
        fit, why = self.fit_before(t, start)
        if fit is None:
            return None, why
        y, m = self.ret[t], self.ret[self.market]
        p = self.peer.get(t) or [NAN] * len(y)
        car = 0.0
        for k in range(start, start + W):
            pk = p[k] if fit.c != 0.0 else 0.0
            if not (y[k] == y[k] and m[k] == m[k] and pk == pk):
                return None, "MISSING_RETURN"
            car += y[k] - fit.a - fit.b * m[k] - fit.c * pk
        z = car / (fit.sigma * math.sqrt(W))
        return ImpactTarget(z, abs(z), car, fit, score_from_abs_z(abs(z), self.cfg.score_cutpoints)), ""

    # --------------------------------------------------------------------------------- as-of features
    def features_asof(self, t: str, s0: int) -> dict[str, float] | None:
        """Event-time price features. Reads only sessions < s0 (a test scrambles everything from s0 on)."""
        fit, _ = self.fit_before(t, s0)
        if fit is None or s0 < 22:
            return None
        y, m = self.ret[t], self.ret[self.market]
        p = self.peer.get(t) or [NAN] * len(y)

        def cum(r: list[float], k: int) -> float:
            vals = r[s0 - k:s0]
            return math.prod(1 + v for v in vals if v == v) - 1

        def resid_vol_ratio(k: int) -> float:
            """RMS abnormal return of the last ``k`` sessions (< s0) relative to the trailing sigma: is vol heating up?"""
            ar = []
            for i in range(s0 - k, s0):
                pk = p[i] if fit.c != 0.0 else 0.0
                if y[i] == y[i] and m[i] == m[i] and pk == pk:
                    ar.append(y[i] - fit.a - fit.b * m[i] - fit.c * pk)
            return math.sqrt(sum(v * v for v in ar) / len(ar)) / fit.sigma if len(ar) >= max(3, k // 2) else NAN

        vix = self.close.get(self.cfg.volatility_symbol)
        vols = [v for v in self.volume[t][s0 - 21:s0 - 1] if v == v]
        v_prev = self.volume[t][s0 - 1]
        out = {
            "sigma_60": fit.sigma, "beta_market": fit.b, "beta_sector": fit.c,
            "ret_1d": cum(y, 1), "ret_5d": cum(y, 5), "ret_20d": cum(y, 20), "mkt_ret_5d": cum(m, 5),
            "sector_ret_5d": cum(p, 5) if p and fit.c != 0.0 else 0.0,
            "volume_ratio": (v_prev / (sum(vols) / len(vols))) if vols and v_prev == v_prev and sum(vols) > 0 else NAN,
            "resid_vol_5d_ratio": resid_vol_ratio(5), "resid_vol_20d_ratio": resid_vol_ratio(20),
        }
        if vix:
            out["vix_level"] = vix[s0 - 1]
            out["vix_chg_5d"] = vix[s0 - 1] / vix[s0 - 6] - 1 if vix[s0 - 6] == vix[s0 - 6] and vix[s0 - 6] > 0 else NAN
        return out

    # ------------------------------------------------------------------------------- market-wide scope
    def market_fit_before(self, start: int) -> tuple[float, float] | None:
        """(mu, sigma) of the market's daily return from sessions strictly before ``start``; None without enough history."""
        cfg = self.cfg
        m = self.ret[self.market]
        lo = max(1, start - cfg.beta_window)
        if start - lo < cfg.min_history_sessions:
            return None
        win = [v for v in m[lo:start] if v == v]
        if len(win) < cfg.min_history_sessions:
            return None
        mu = sum(win) / len(win)
        slo = max(1, start - cfg.sigma_window)
        sig = [v for v in m[slo:start] if v == v]
        if len(sig) < cfg.sigma_window * 0.5:
            return None
        sigma = math.sqrt(sum((v - mu) ** 2 for v in sig) / len(sig))
        return (mu, sigma) if sigma > 0 else None

    def market_target(self, start: int) -> tuple[MarketTarget | None, str]:
        """Excess S&P 500 move over sessions [start, start + W - 1] in units of trailing sigma (model fitted before ``start``)."""
        W = self.cfg.window_sessions
        if start + W > len(self.dates):
            return None, "CENSORED"
        fit = self.market_fit_before(start)
        if fit is None:
            return None, "INSUFFICIENT_HISTORY"
        mu, sigma = fit
        m = self.ret[self.market]
        car = 0.0
        for k in range(start, start + W):
            if m[k] != m[k]:
                return None, "MISSING_RETURN"
            car += m[k] - mu
        z = car / (sigma * math.sqrt(W))
        return MarketTarget(z, abs(z), car, mu, sigma, score_from_abs_z(abs(z), self.cfg.score_cutpoints)), ""

    def market_features_asof(self, s0: int, rates_symbol: str | None = None) -> dict[str, float] | None:
        """Market-state features at ``s0``: the S&P's own recent move and vol, VIX, 10y yield. Reads only sessions < s0."""
        fit = self.market_fit_before(s0)
        if fit is None or s0 < 22:
            return None
        mu, sigma = fit
        m = self.ret[self.market]

        def cum(k: int) -> float:
            return math.prod(1 + v for v in m[s0 - k:s0] if v == v) - 1

        def dev_ratio(k: int) -> float:
            d = [v - mu for v in m[s0 - k:s0] if v == v]
            return math.sqrt(sum(v * v for v in d) / len(d)) / sigma if len(d) >= max(3, k // 2) else NAN

        out = {"sigma_60": sigma, "ret_1d": cum(1), "ret_5d": cum(5), "ret_20d": cum(20),
               "dev_vol_5d_ratio": dev_ratio(5), "dev_vol_20d_ratio": dev_ratio(20)}
        vix = self.close.get(self.cfg.volatility_symbol)
        if vix:
            base = [v for v in vix[s0 - 61:s0 - 1] if v == v]
            out["vix_level"] = vix[s0 - 1]
            out["vix_chg_5d"] = vix[s0 - 1] / vix[s0 - 6] - 1 if vix[s0 - 6] == vix[s0 - 6] and vix[s0 - 6] > 0 else NAN
            out["vix_rel_60"] = vix[s0 - 1] / (sum(base) / len(base)) if base and vix[s0 - 1] == vix[s0 - 1] else NAN
        rate = self.close.get(rates_symbol) if rates_symbol else None
        if rate:
            out["rate_level"] = rate[s0 - 1]
            out["rate_chg_5d"] = rate[s0 - 1] - rate[s0 - 6] if rate[s0 - 1] == rate[s0 - 1] and rate[s0 - 6] == rate[s0 - 6] else NAN
        return out


# ------------------------------------------------------------------------------------------------ rows
def eligibility_reason(doc: HistoryDoc, store: PriceStore, cfg: ImpactConfig) -> str | None:
    if doc.entity_id == UNKNOWN_ENTITY or not doc.ticker:
        return "NO_ISSUER"
    if cfg.exclude_multi_entity and doc.multi_entity:
        return "MULTI_ENTITY"
    if doc.link_confidence < cfg.min_link_confidence:
        return "LOW_LINK_CONFIDENCE"
    if cfg.require_dataset_ticker_agreement and doc.dataset_tickers and doc.ticker not in doc.dataset_tickers:
        return "DATASET_TICKER_MISMATCH"
    if doc.ticker not in store.close:
        return "NO_PRICES"
    return None


def impact_rows(docs: Iterator[HistoryDoc] | Sequence[HistoryDoc], store: PriceStore, cfg: ImpactConfig
                ) -> tuple[list[dict], dict[str, int]]:
    """One row per eligible document with target, placebo target and event-time features; plus a drop-reason census."""
    rows: list[dict] = []
    drops: dict[str, int] = {}

    def drop(reason: str) -> None:
        drops[reason] = drops.get(reason, 0) + 1

    for doc in docs:
        why = eligibility_reason(doc, store, cfg)
        if why:
            drop(why)
            continue
        assert doc.ticker is not None
        s0, timing = store.anchor(doc.published_at, doc.origin)
        if s0 is None:
            drop("BEYOND_PRICES")
            continue
        tgt, why = store.target(doc.ticker, s0)
        if tgt is None:
            drop(why)
            continue
        feats = store.features_asof(doc.ticker, s0)
        if feats is None:
            drop("INSUFFICIENT_HISTORY")
            continue
        placebo, _ = store.target(doc.ticker, s0 + cfg.placebo_offset_sessions)
        local = doc.published_at.astimezone(store.tz)
        rows.append({
            "id": doc.id, "adapter": doc.adapter, "source_type": doc.source_type, "ticker": doc.ticker,
            "sector": store.sectors.get(doc.ticker), "published_at": doc.published_at.isoformat(),
            "origin": doc.origin, "timing": timing, "s0": s0, "s0_date": store.dates[s0],
            "episode": f"{doc.ticker}|{store.dates[s0]}", "link_confidence": doc.link_confidence,
            "novelty": doc.novelty, "dow": local.weekday(), "local_hour": local.hour + local.minute / 60,
            **{f"f_{k}": v for k, v in feats.items()},
            "z": tgt.z, "abs_z": tgt.abs_z, "car": tgt.car, "score": tgt.score, "factor_model": tgt.fit.factor_model,
            "placebo_abs_z": placebo.abs_z if placebo else None,
            "placeholder_event": doc.placeholder_event,  # audit only; registered as CIRCULAR, never a feature
        })
    sizes: dict[str, int] = {}
    for r in rows:
        sizes[r["episode"]] = sizes.get(r["episode"], 0) + 1
    for r in rows:
        r["episode_size"] = sizes[r["episode"]]
        r["weight"] = 1.0 / sizes[r["episode"]]
    return rows, dict(sorted(drops.items()))


def market_rows(docs: Iterator[HistoryDoc] | Sequence[HistoryDoc], store: PriceStore, cfg: ImpactConfig, rates_symbol: str | None
                ) -> tuple[list[dict], dict[str, int]]:
    """Market-scope rows: documents that name no listed issuer, scored against the S&P 500's own move (its sessions are the episodes)."""
    rows: list[dict] = []
    drops: dict[str, int] = {}

    def drop(reason: str) -> None:
        drops[reason] = drops.get(reason, 0) + 1

    for doc in docs:
        if doc.entity_id != UNKNOWN_ENTITY:
            drop("HAS_ISSUER")
            continue
        s0, timing = store.anchor(doc.published_at, doc.origin)
        if s0 is None:
            drop("BEYOND_PRICES")
            continue
        tgt, why = store.market_target(s0)
        if tgt is None:
            drop(why)
            continue
        feats = store.market_features_asof(s0, rates_symbol)
        if feats is None:
            drop("INSUFFICIENT_HISTORY")
            continue
        placebo, _ = store.market_target(s0 + cfg.placebo_offset_sessions)
        local = doc.published_at.astimezone(store.tz)
        rows.append({
            "id": doc.id, "scope": "MARKET", "adapter": doc.adapter, "source_type": doc.source_type, "ticker": None, "sector": None,
            "published_at": doc.published_at.isoformat(), "origin": doc.origin, "timing": timing, "s0": s0,
            "s0_date": store.dates[s0], "episode": f"MKT|{store.dates[s0]}", "link_confidence": doc.link_confidence,
            "novelty": doc.novelty, "dow": local.weekday(), "local_hour": local.hour + local.minute / 60,
            **{f"m_{k}": v for k, v in feats.items()},
            "z": tgt.z, "abs_z": tgt.abs_z, "car": tgt.car, "score": tgt.score,
            "placebo_abs_z": placebo.abs_z if placebo else None,
            "placeholder_event": doc.placeholder_event,
        })
    sizes: dict[str, int] = {}
    for r in rows:
        sizes[r["episode"]] = sizes.get(r["episode"], 0) + 1
    for r in rows:
        r["episode_size"] = sizes[r["episode"]]
        r["weight"] = 1.0 / sizes[r["episode"]]
    return rows, dict(sorted(drops.items()))
