"""Episode-level rows for the Stage 4 study: one row per (issuer, reaction session), or per session for the market scope.

Documents of an episode share one realised outcome, so the unit of evidence is the episode. Features are averaged over its documents (NaN-aware:
a calendar feature that is unknown for every document stays unknown); categorical context takes the mode; the episode counts as a publisher-time
(``SOURCE``) episode only if every one of its documents does. No information from any later document enters: the table's features are all event-time
features of their own document, and the mean is over documents of the same session.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np

CARRY = ("scope", "episode", "s0", "s0_date", "ticker", "sector", "z", "abs_z", "score", "placebo_abs_z", "abs_z_w1", "abs_z_w3", "factor_model")


def _mode(values: Sequence[str]) -> str:
    return sorted(Counter(values).items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def aggregate(rows: Sequence[dict[str, Any]], features: Sequence[str], split_keys: Sequence[str]) -> list[dict[str, Any]]:
    """Group a document-level table into episodes. ``split_keys`` columns are constant within an episode (the builder guarantees it)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["scope"], r["episode"])].append(r)
    out = []
    for (_scope, _ep), g in groups.items():
        first = g[0]
        row: dict[str, Any] = {k: first.get(k) for k in CARRY}
        for k in split_keys:
            if len({r[k] for r in g}) != 1:
                raise ValueError(f"episode {first['episode']} has documents in different {k}: the builder must keep episodes whole")
            row[k] = first[k]
        for f in features:
            vals = np.array([np.nan if r.get(f) is None else float(r[f]) for r in g], dtype=float)
            row[f] = float("nan") if np.isnan(vals).all() else float(np.nanmean(vals))
        row["n_docs"] = len(g)
        row["adapter"] = _mode([r["adapter"] for r in g])
        row["timing"] = _mode([r["timing"] for r in g])
        row["event_top"] = _mode([r["event_top"] for r in g])
        row["event_status"] = _mode([r["event_status"] for r in g])
        row["origin"] = "SOURCE" if all(r["origin"] == "SOURCE" for r in g) else _mode([r["origin"] for r in g if r["origin"] != "SOURCE"])
        row["source_type"] = _mode([r["source_type"] for r in g])
        row["text"] = first.get("text", "")
        row["weight"] = 1.0
        out.append(row)
    out.sort(key=lambda r: (r["scope"], r["s0"], r["episode"]))
    return out
