"""Leakage checks. Each returns findings; ``require_clean`` turns any ERROR into an exception.

What is checked, and why (each has an injected-leak test showing it fires):
* group straddle      - a group (episode, near-duplicate component) that appears in two splits
* time order/embargo  - a later split containing a row earlier than an earlier split's last row + embargo
* duplicates          - exact/near-duplicate texts across splits (published TFN valid fails this)
* feature availability- only registered event-time features may reach an impact model
* future invariance   - features must not change when every price from s0 on is replaced by noise
* placebo / metadata  - skill on a window that ends before s0, and the skill of issuer/source/season alone
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from .market import PriceStore
from .text import has_near_duplicate


class LeakageError(RuntimeError):
    """Raised when a leakage check fails. Never caught inside the package."""


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str  # "ERROR" | "WARN" | "INFO"
    detail: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.check}: {self.detail}"


def require_clean(findings: Iterable[Finding]) -> list[Finding]:
    items = list(findings)
    errors = [f for f in items if f.severity == "ERROR"]
    if errors:
        raise LeakageError("; ".join(str(f) for f in errors))
    return items


# ------------------------------------------------------------------------------------------------ groups & time
def group_straddle(rows: Sequence[dict], group_key: str, split_key: str = "split",
                   splits: Sequence[str] = ("train", "val", "test", "live")) -> list[Finding]:
    seen: dict[object, set[str]] = defaultdict(set)
    for r in rows:
        if r[split_key] in splits:
            seen[r[group_key]].add(r[split_key])
    bad = {g: s for g, s in seen.items() if len(s) > 1}
    if not bad:
        return [Finding("group_straddle", "INFO", f"no {group_key} spans two splits ({len(seen)} groups)")]
    ex = next(iter(bad.items()))
    return [Finding("group_straddle", "ERROR", f"{len(bad)} {group_key} groups span several splits, e.g. {ex[0]!r} in {sorted(ex[1])}")]


def time_order(rows: Sequence[dict], dates: list[str], embargo_sessions: int,
               order: Sequence[str] = ("train", "val", "test", "live")) -> list[Finding]:
    """Each split must start at least ``embargo_sessions`` sessions after the previous split's last session."""
    span: dict[str, tuple[int, int]] = {}
    for r in rows:
        if r["split"] in order:
            lo, hi = span.get(r["split"], (r["s0"], r["s0"]))
            span[r["split"]] = (min(lo, r["s0"]), max(hi, r["s0"]))
    out: list[Finding] = []
    present = [s for s in order if s in span]
    for a, b in zip(present, present[1:], strict=False):
        gap = span[b][0] - span[a][1]
        if gap < embargo_sessions:
            out.append(Finding("time_order", "ERROR", f"{b} starts {gap} sessions after {a} ends (< embargo {embargo_sessions}); "
                                                     f"{a} ends {dates[span[a][1]]}, {b} starts {dates[span[b][0]]}"))
    return out or [Finding("time_order", "INFO", "splits are time ordered with the embargo respected: "
                           + ", ".join(f"{s} {dates[span[s][0]]}..{dates[span[s][1]]}" for s in present))]


# ------------------------------------------------------------------------------------------------ duplicates
def duplicate_rate(train_texts: Sequence[str], eval_texts: Sequence[str], threshold: float, name: str,
                   max_rate: float) -> list[Finding]:
    """Share of ``eval_texts`` with an exact or >= threshold near-duplicate in ``train_texts``."""
    if not eval_texts:
        return [Finding("duplicates", "INFO", f"{name}: no evaluation rows")]
    flags = has_near_duplicate(eval_texts, train_texts, threshold)
    rate = sum(flags) / len(flags)
    sev = "ERROR" if rate > max_rate else "INFO"
    return [Finding("duplicates", sev, f"{name}: {sum(flags)}/{len(flags)} = {rate:.1%} of evaluation texts have a duplicate "
                                       f"(Jaccard >= {threshold}) in train (limit {max_rate:.1%})")]


# ------------------------------------------------------------------------------------------ feature availability
AT_EVENT_TIME = "AT_EVENT_TIME"
SHORTCUT = "SHORTCUT"
POST_EVENT = "POST_EVENT"

FEATURE_REGISTRY: dict[str, tuple[str, str]] = {
    # name: (availability, why)
    "text": (AT_EVENT_TIME, "the report itself"),
    "sentiment_text": (AT_EVENT_TIME, "the report's own wording: the only input of the sentiment model"),
    "source_type": (AT_EVENT_TIME, "NEWS vs SOCIAL"),
    "link_confidence": (AT_EVENT_TIME, "entity-resolution output for this report"),
    "novelty": (AT_EVENT_TIME, "count of strictly earlier same-issuer clusters in 72h (pipeline._apply_novelty)"),
    "dow": (AT_EVENT_TIME, "weekday of publication"),
    "local_hour": (AT_EVENT_TIME, "exchange-local hour of publication"),
    "sector": (AT_EVENT_TIME, "issuer sector from the entity master"),
    "f_sigma_60": (AT_EVENT_TIME, "trailing residual vol, sessions < s0"),
    "f_beta_market": (AT_EVENT_TIME, "trailing fit, sessions < s0"),
    "f_beta_sector": (AT_EVENT_TIME, "trailing fit, sessions < s0"),
    "f_ret_1d": (AT_EVENT_TIME, "return of session s0-1"),
    "f_ret_5d": (AT_EVENT_TIME, "sessions < s0"),
    "f_ret_20d": (AT_EVENT_TIME, "sessions < s0"),
    "f_mkt_ret_5d": (AT_EVENT_TIME, "sessions < s0"),
    "f_sector_ret_5d": (AT_EVENT_TIME, "sessions < s0"),
    "f_volume_ratio": (AT_EVENT_TIME, "volume of s0-1 vs the 20 sessions before it"),
    "f_vix_level": (AT_EVENT_TIME, "VIX close of s0-1"),
    "f_vix_chg_5d": (AT_EVENT_TIME, "sessions < s0"),
    # banned
    "source_count": (POST_EVENT, "cluster size includes reports up to 72h after the first report"),
    "unique_domain_count": (POST_EVENT, "cluster-level, includes later reports"),
    "coverage_velocity": (POST_EVENT, "spans the whole cluster, including later reports"),
    "recent_mention_count": (POST_EVENT, "measured against the replay clock, not the event time"),
    "episode_size": (POST_EVENT, "number of same-issuer reports in the session, known only afterwards"),
    "same_day_volume": (POST_EVENT, "volume of the reaction session"),
    "same_day_return": (POST_EVENT, "return of the reaction session (it is the target)"),
    "ticker": (SHORTCUT, "issuer identity: the model must learn severity, not 'TSLA moves a lot'"),
    "year": (SHORTCUT, "period identity; source and period are confounded"),
    "adapter": (SHORTCUT, "source identity is perfectly confounded with period"),
    "placeholder_event": ("CIRCULAR", "placeholder-v0 keyword class; impact.score is derived from it"),
    "z": (POST_EVENT, "the target"), "abs_z": (POST_EVENT, "the target"), "score": (POST_EVENT, "the target"),
}


def check_features(names: Iterable[str]) -> list[Finding]:
    """Every feature must be registered AT_EVENT_TIME. Unknown names are errors (register them deliberately)."""
    out = []
    for n in names:
        kind, why = FEATURE_REGISTRY.get(n, ("UNREGISTERED", "add it to FEATURE_REGISTRY with the reason it is known at event time"))
        if kind != AT_EVENT_TIME:
            out.append(Finding("feature_availability", "ERROR", f"feature {n!r} is {kind}: {why}"))
    return out or [Finding("feature_availability", "INFO", "all features are registered event-time features")]


# ------------------------------------------------------------------------------------------ future invariance
def future_invariance(store: PriceStore, events: Sequence[tuple[str, int]], *, seed: int = 1) -> list[Finding]:
    """Features at (ticker, s0) must be bit-identical when every price/volume from s0 on is scrambled."""
    bad = []
    for t, s0 in events:
        base = store.features_asof(t, s0)
        scr = store.scrambled_from(s0, seed).features_asof(t, s0)
        if base is None or scr is None:
            continue
        for k in base:
            a, b = base[k], scr[k]
            if not (a == b or (a != a and b != b)):
                bad.append(f"{t}@{store.dates[s0]}:{k}")
    n = len(events)
    return ([Finding("future_invariance", "ERROR", f"{len(bad)} features changed when the future was scrambled: {bad[:3]}")]
            if bad else [Finding("future_invariance", "INFO", f"{n} events: features unchanged when all prices from s0 on are noise")])


# ----------------------------------------------------------------------------------- metadata & placebo skill
def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    def ranks(v: Sequence[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    if len(x) < 3:
        return float("nan")
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def metadata_baseline(train: Sequence[dict], test: Sequence[dict], target: str,
                      keys: Sequence[Callable[[dict], object]], weights: str | None = "weight") -> dict[str, float]:
    """Additive group-mean model on identity keys only (e.g. issuer, source, calendar month): no text, no prices.

    Returns Spearman between its prediction and the target on ``test`` (and the number of test rows). If this is
    clearly above zero, issuer/source/season shortcuts exist that a real model could exploit without reading the news.
    """
    tr = [r for r in train if r.get(target) is not None]
    te = [r for r in test if r.get(target) is not None]
    if len(tr) < 10 or len(te) < 10:
        return {"spearman": float("nan"), "n_test": float(len(te))}
    w = (lambda r: r[weights]) if weights else (lambda r: 1.0)
    gm = sum(r[target] * w(r) for r in tr) / sum(w(r) for r in tr)
    effects: list[dict[object, float]] = []
    for key in keys:
        s: dict[object, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for r in tr:
            a = s[key(r)]
            a[0] += (r[target] - gm) * w(r)
            a[1] += w(r)
        effects.append({k: v[0] / (v[1] + 5.0) for k, v in s.items()})  # shrunk towards the global mean
    pred = [gm + sum(e.get(key(r), 0.0) for e, key in zip(effects, keys, strict=True)) for r in te]
    return {"spearman": spearman(pred, [r[target] for r in te]), "n_test": float(len(te))}


def bootstrap_ci(x: Sequence[float], y: Sequence[float], *, n: int = 200, seed: int = 0) -> tuple[float, float]:
    """95% bootstrap interval for the Spearman correlation (resampling rows)."""
    rng = random.Random(seed)
    idx = range(len(x))
    vals = []
    for _ in range(n):
        s = [rng.choice(idx) for _ in idx]
        vals.append(spearman([x[i] for i in s], [y[i] for i in s]))
    vals = sorted(v for v in vals if v == v)
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]) if vals else (float("nan"), float("nan"))
