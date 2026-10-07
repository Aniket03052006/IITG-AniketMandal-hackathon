"""Write Wholesale Book v2 for the replay profile: the replay default book (data/replay/portfolio.json) with the Stage 13 mechanics filled in.

    python scripts/build_book_v2.py        # or: make book-v2   (deterministic: fixed seed; the replay pack itself is never touched)

The demo-profile twin (data/fixtures/portfolio_v2.json) is written by scripts/generate_fixtures.py. Everything is SYNTHETIC; see eventshock.portfolio.book_v2.
"""

from __future__ import annotations

import json
from pathlib import Path

from eventshock.domain import Portfolio
from eventshock.portfolio.book_v2 import build_book_v2

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261002


def main() -> None:
    base = Portfolio.model_validate(json.loads((ROOT / "data" / "replay" / "portfolio.json").read_text(encoding="utf-8")))
    book = build_book_v2(base, seed=SEED)
    out = ROOT / "data" / "portfolio" / "book_v2_replay.json"
    out.write_text(json.dumps(book.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{out.relative_to(ROOT)}: {len(base.assets)} base positions -> {len(book.assets)}, value {base.total_value:,.0f} -> {book.total_value:,.0f}")


if __name__ == "__main__":
    main()
