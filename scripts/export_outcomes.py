"""Export the realised market moves that followed the replay reports, as a small committed file (data/outcomes/replay_outcomes.json).

Why this exists: the UI's timeline separates what EventShock knew at the time from what the market did afterwards. The realised moves live
in the local, git-ignored impact table (data/modeling/impact_table_v2.jsonl); this script keeps only the rows the replay signals refer to,
as derived statistics (no prices, no text): one row per (scope, issuer, reaction session) that at least one model-scored replay signal uses.
Every such row that exists is exported, not a selection. Deterministic: sorted rows, no timestamps.

The file is read by GET /api/signals/{id}/context only. It is never attached to a RiskSignal and never reaches a model.
Run: make outcomes   (needs data/modeling/impact_table_v2.jsonl: `make impact-table-v2`)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from eventshock.api.deps import build_container  # noqa: E402
from eventshock.config import Settings  # noqa: E402
from eventshock.services.signal_context import OUTCOMES_SCHEMA  # noqa: E402

TABLE = REPO / "data" / "modeling" / "impact_table_v2.jsonl"
OUT = REPO / "data" / "outcomes" / "replay_outcomes.json"
WINDOW_SESSIONS = 2
DEFINITION = (
    "Realised move = the abnormal return over the two sessions starting at the reaction session, in units of the issuer's own trailing volatility "
    "(for MARKET scope, the S&P 500's move against its trailing volatility): the model's own target, observed after the fact."
)


def main() -> int:
    if not TABLE.is_file():
        print(f"missing {TABLE}: run `make impact-table-v2` first", file=sys.stderr)
        return 2
    c = build_container(Settings())
    wanted: set[tuple[str, str, str]] = set()
    for s in c.signals.list():
        a = s.provenance.impact if s.provenance else None
        if a is None or a.session == "NEXT":
            continue
        wanted.add((a.scope.value, (s.entity.ticker or "") if a.scope.value == "ISSUER" else "", a.session))
    rows = {}
    with TABLE.open(encoding="utf-8") as f:
        for line in f:
            if '"live"' not in line:
                continue
            r = json.loads(line)
            if r.get("split") != "live" or r.get("z") is None:
                continue
            key = (r["scope"], r["ticker"] if r["scope"] == "ISSUER" else "", r["s0_date"])
            if key in wanted:
                rows[key] = {"scope": key[0], "ticker": key[1], "session": key[2], "abs_z": round(abs(r["z"]), 6), "z": round(r["z"], 6), "score": int(r["score"])}
    missing = sorted(wanted - rows.keys())
    doc = {"schema": OUTCOMES_SCHEMA, "window_sessions": WINDOW_SESSIONS, "definition": DEFINITION,
           "source": "data/modeling/impact_table_v2.jsonl (local, git-ignored), split=live",
           "keys_wanted": len(wanted), "keys_exported": len(rows), "keys_without_outcome": len(missing),
           "rows": [rows[k] for k in sorted(rows)]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(REPO)}: {len(rows)} of {len(wanted)} (scope, issuer, session) keys exported; "
          f"{len(missing)} without a recorded outcome (reaction window not complete): {missing[:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
