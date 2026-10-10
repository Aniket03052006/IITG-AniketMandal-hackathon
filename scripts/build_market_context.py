"""Freeze the event-time market context for the replay window into data/replay/market/context.json (deterministic).

Input  (git-ignored): data/raw/prices/*.csv   (`make fetch-prices`)
Output (committed, derived statistics only): data/replay/market/context.json, hash-pinned in data/replay/manifest.json

The server reads this file instead of prices: Yahoo data is licensed for personal/research use and is not redistributed,
while trailing volatility, betas and returns computed from it are derived statistics (see docs/notes/DATA_LICENSES.md).
Usage:  python scripts/build_market_context.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eventshock.config import ConfigError  # noqa: E402
from eventshock.ingestion.snapshot import atomic_write_text, load_snapshot, sha256_file  # noqa: E402
from eventshock.modeling.config import load_modeling_config  # noqa: E402
from eventshock.modeling.market import PriceStore  # noqa: E402
from eventshock.modeling.market_pack import build_context_payload, write_context  # noqa: E402
from eventshock.pipeline.config import load_impact_model_config  # noqa: E402

REPLAY = ROOT / "data" / "replay"


def main() -> None:
    cfg = load_modeling_config(ROOT / "configs")
    icfg = load_impact_model_config(ROOT / "configs")
    prices = ROOT / "data" / "raw" / "prices"
    if not (prices / "_GSPC.csv").is_file():
        raise ConfigError(f"missing {prices}: run `make fetch-prices` first")
    entities = json.loads((REPLAY / "entities.json").read_text(encoding="utf-8"))
    sectors = {e["ticker"]: e["sector"] for e in entities if e.get("ticker")}
    symbols = [*sectors, cfg.impact.market_symbol, cfg.impact.volatility_symbol, icfg.rates_symbol]
    store = PriceStore.from_dir(prices, symbols, sectors, cfg.impact)
    manifest_path = REPLAY / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window_start = __import__("datetime").datetime.fromisoformat(manifest["window_start"].replace("Z", "+00:00")).date()
    payload = build_context_payload(store, sorted(sectors), icfg.rates_symbol, window_start, prices)
    sha = write_context(REPLAY / "market" / "context.json", payload)
    manifest["market_context"] = {"file": "market/context.json", "sha256": sha}
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    load_snapshot(REPLAY)  # the pack must verify after the edit
    n_iss = sum(len(v) for v in payload["issuer"].values())
    print(f"market context: {len(payload['calendar'])} sessions + NEXT, {len(payload['issuer'])} issuers ({n_iss} issuer-sessions), "
          f"{len(payload['market'])} market-sessions, sha256 {sha[:12]}, {sha256_file(REPLAY / 'market' / 'context.json') == sha}")


if __name__ == "__main__":
    main()
