"""Build the frozen market-context pack the server reads (derived statistics only; no prices are written).

The pack holds, for every session from a few days before the replay window up to the unknown *next* session, the event-time
features of each issuer and of the market itself, computed by the very functions that built the training table
(``PriceStore.features_asof`` / ``market_features_asof``) and rounded by the same ``quantize``. See ``pipeline.market_context``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..pipeline.market_context import NEXT, PACK_SCHEMA, pack_digest, quantize_features
from .config import ImpactConfig
from .market import NAN, PriceStore, file_stem

FEATURE_SCHEMA = "impact-features-v1"


def _clean(feats: dict[str, float]) -> dict[str, float | None]:
    return {k: (None if v != v else v) for k, v in quantize_features(feats).items()}


def build_context_payload(store: PriceStore, tickers: list[str], rates_symbol: str | None, window_start: date,
                          prices_dir: Path | None = None) -> dict[str, Any]:
    """``window_start``: the first calendar day of the replay window. Sessions from 7 days earlier are included so the
    anchoring of a report on the first window day (e.g. a Sunday) can see the preceding Friday."""
    n = len(store.dates)
    lo = max(0, next((i for i, d in enumerate(store.dates) if d >= (window_start - timedelta(days=7)).isoformat()), n))
    issuer: dict[str, dict[str, dict]] = {t: {} for t in sorted(tickers)}
    market: dict[str, dict] = {}
    for i in range(lo, n + 1):
        key = store.dates[i] if i < n else NEXT
        mf = store.market_features_asof(i, rates_symbol)
        if mf is not None:
            market[key] = _clean(mf)
        for t in issuer:
            f = store.features_asof(t, i) if t in store.close else None
            if f is not None:
                issuer[t][key] = _clean(f)
    cfg: ImpactConfig = store.cfg
    built_from: dict[str, Any] = {
        "price_calendar": [store.dates[0], store.dates[-1], n],
        "market_symbol": cfg.market_symbol, "volatility_symbol": cfg.volatility_symbol, "rates_symbol": rates_symbol,
        "window_sessions": cfg.window_sessions, "beta_window": cfg.beta_window, "sigma_window": cfg.sigma_window,
        "note": "derived statistics (trailing vol, betas, returns, VIX/yield context); no prices or volumes",
    }
    if prices_dir is not None:
        built_from["price_files_sha256"] = {
            s: hashlib.sha256((prices_dir / f"{file_stem(s)}.csv").read_bytes()).hexdigest()
            for s in sorted({*tickers, cfg.market_symbol, cfg.volatility_symbol, *([rates_symbol] if rates_symbol else [])})}
    payload = {
        "schema_version": PACK_SCHEMA, "feature_schema": FEATURE_SCHEMA,
        "session_rules": {"timezone": cfg.exchange_timezone, "open": cfg.session_open.isoformat(timespec="minutes"),
                          "close": cfg.session_close.isoformat(timespec="minutes")},
        "calendar": store.dates[lo:], "last_session": store.dates[-1],
        "issuer": {t: v for t, v in issuer.items() if v}, "market": market, "built_from": built_from,
    }
    payload["digest"] = pack_digest(payload)
    return payload


def write_context(path: Path, payload: dict[str, Any]) -> str:
    from ..ingestion.snapshot import atomic_write_text, sha256_file

    atomic_write_text(path, json.dumps(payload, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n")
    return sha256_file(path)


__all__ = ["FEATURE_SCHEMA", "NAN", "build_context_payload", "write_context"]
