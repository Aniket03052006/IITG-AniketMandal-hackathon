"""Derive the sector spend mix of the synthetic book from the Kaggle Financial Transactions dataset.

Only an aggregate is written (data/replay/sector_mix.json, a few KB); the 1.3 GB source never enters git.
Usage:  python scripts/derive_sector_mix.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "kaggle" / "transactions-fraud-datasets"
OUT = ROOT / "data" / "replay" / "sector_mix.json"


def sector_of(description: str, sectors: dict[str, list[str]]) -> str:
    for sector, words in sectors.items():
        if any(w.lower() in description.lower() for w in words):
            return sector
    return "OTHER"


def main() -> None:
    sectors = yaml.safe_load((ROOT / "configs" / "mcc_sector_map.yaml").read_text(encoding="utf-8"))["sectors"]
    mcc = json.loads((SRC / "mcc_codes.json").read_text(encoding="utf-8"))
    spend: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    rows = used = errors = refunds = 0
    csv.field_size_limit(10_000_000)
    with (SRC / "transactions_data.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows += 1
            if r["errors"]:
                errors += 1
                continue
            amt = float(r["amount"].replace("$", "").replace(",", ""))
            if amt <= 0:
                refunds += 1
                continue
            used += 1
            spend[r["mcc"]] += amt
            count[r["mcc"]] += 1
    table = []
    by_sector: dict[str, float] = defaultdict(float)
    for code, total in sorted(spend.items(), key=lambda kv: -kv[1]):
        desc = mcc.get(code, "unknown")
        sec = sector_of(desc, sectors)
        by_sector[sec] += total
        table.append({"mcc": code, "description": desc, "sector": sec, "spend": round(total, 2), "transactions": count[code]})
    total = sum(spend.values())
    mapped = total - by_sector.get("OTHER", 0.0)
    shares = {s: round(by_sector[s] / mapped, 6) for s in sectors if by_sector.get(s)}
    out = {
        "source": "computingvictor/transactions-fraud-datasets (Kaggle), Apache-2.0; aggregate only",
        "assumption": "Retail card spend by merchant category is used as a crude proxy for the relative economic weight of "
                      "sectors. It tilts the synthetic book's notionals; it does not describe any real bank's exposure.",
        "rows_read": rows, "rows_used": used, "excluded_rows_with_errors": errors, "excluded_non_positive_amounts": refunds,
        "spend_total": round(total, 2), "mapped_share_of_spend": round(mapped / total, 4),
        "sector_share_of_mapped_spend": shares,
        "sector_spend": {s: round(v, 2) for s, v in sorted(by_sector.items())},
        "mcc_assignments": table,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"rows={rows:,} used={used:,} mapped={out['mapped_share_of_spend']:.1%}")
    print(json.dumps(shares, indent=1))
    unmapped = [t for t in table if t["sector"] == "OTHER"][:10]
    print("largest OTHER:", [(t["mcc"], t["description"], round(t["spend"] / total, 4)) for t in unmapped])


if __name__ == "__main__":
    sys.exit(main())
