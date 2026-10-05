"""Phase 2 of Stage 8: is the realised outcome a well-normalised, regime-neutral severity? (Audit only: no frozen artifact changes.)

The shipped outcome (``outcome-v2``, ``modeling.market``) is ``z = CAR[s0, s0+1] / (sigma * sqrt(2))`` with ``sigma`` the RMS residual of the 60
sessions before ``s0``. The audit asks, on a *quiet-day null sample* (random (ticker, session) pairs with no corpus episode within two sessions),
whether that normalisation does its job, and measures how much the news episodes differ from quiet days at all. The rule for the one decision it
may take (use an EWMA sigma in the side-car layers) is pre-registered in ``configs/evidence_v3.yaml``; everything else is a diagnostic.

Everything is deterministic (seeded) and reads only the committed-or-rebuildable inputs named in the output. The audit never reads a scorecard
result, so it cannot be tuned toward one.
"""

from __future__ import annotations

import json
import math
import random
import re
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import rankdata

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text, sha256_file
from ..pipeline.config import load_impact_model_config
from .config import load_modeling_config
from .evidence_v3 import load_evidence_v3
from .market import Fit, PriceStore
from .outcome_v3 import ewma_sigma

NAN = float("nan")
SCHEMA = "outcome-audit-v1"
_TOKEN = re.compile(r"[a-z0-9$]{3,}")


# ------------------------------------------------------------------------------------------------ small statistics
def moments(z: Sequence[float]) -> dict[str, float | int]:
    """n, mean, variance, excess kurtosis and the two tail rates of a sample of z-scores (population moments)."""
    a = np.asarray([v for v in z if v == v], dtype=float)
    if a.size < 4:
        return {"n": int(a.size), "mean": NAN, "var": NAN, "excess_kurtosis": NAN, "p_abs_gt_2": NAN, "p_abs_gt_3": NAN}
    m, v = float(a.mean()), float(a.var())
    k = float(((a - m) ** 4).mean() / v ** 2 - 3) if v > 0 else NAN
    return {"n": int(a.size), "mean": m, "var": v, "excess_kurtosis": k,
            "p_abs_gt_2": float((np.abs(a) > 2).mean()), "p_abs_gt_3": float((np.abs(a) > 3).mean())}


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(pos > neg) + 0.5 P(tie), via mid-ranks. NaN if either sample is empty."""
    if pos.size == 0 or neg.size == 0:
        return NAN
    r = rankdata(np.concatenate([pos, neg]))
    return float((r[: pos.size].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def regime_gap(z: Sequence[float], regime: Sequence[int]) -> float:
    """|ln(Var(z | top regime tercile) / Var(z | bottom tercile))|: 0 for a normalisation that is regime-neutral."""
    z_arr, r_arr = np.asarray(z, dtype=float), np.asarray(regime)
    lo, hi = z_arr[(r_arr == 0) & np.isfinite(z_arr)], z_arr[(r_arr == 2) & np.isfinite(z_arr)]
    if lo.size < 30 or hi.size < 30 or lo.var() <= 0 or hi.var() <= 0:
        return NAN
    return float(abs(math.log(hi.var() / lo.var())))


def tercile_cuts(values: Sequence[float]) -> tuple[float, float]:
    a = np.asarray([v for v in values if v == v], dtype=float)
    if a.size < 100:
        raise ConfigError("too few VIX observations to cut terciles")
    q = np.quantile(a, [1 / 3, 2 / 3])
    return float(q[0]), float(q[1])


def regime_cutpoints(store: PriceStore, pre: dict[str, Any]) -> tuple[float, float]:
    """VIX tercile cut points fixed on the early period named in the pre-registration, then applied to every period."""
    span = pre["outcome_audit"]["regime"]["tercile_cutpoints_from"]
    vix = store.close[store.cfg.volatility_symbol]
    return tercile_cuts([v for d, v in zip(store.dates, vix, strict=True) if span["first"] <= d <= span["last"]])


def tercile_of(v: float, cuts: tuple[float, float]) -> int:
    return 0 if v < cuts[0] else (1 if v < cuts[1] else 2)


def icc_design_effect(values: Sequence[float], groups: Sequence[str]) -> dict[str, float | int]:
    """One-way ANOVA intraclass correlation of ``values`` within ``groups`` (here: issuer episodes sharing a reaction date).

    ``design_effect = 1 + (m_bar - 1) * icc`` with ``m_bar`` the size-weighted mean group size; ``effective_n = n / design_effect``.
    """
    by: dict[str, list[float]] = defaultdict(list)
    for v, g in zip(values, groups, strict=True):
        if v == v:
            by[g].append(float(v))
    n = sum(len(x) for x in by.values())
    k = len(by)
    if k < 2 or n <= k:
        return {"n": n, "groups": k, "icc": NAN, "design_effect": NAN, "effective_n": NAN, "date_fixed_effect_r2": NAN}
    grand = sum(sum(x) for x in by.values()) / n
    ssb = sum(len(x) * (sum(x) / len(x) - grand) ** 2 for x in by.values())
    ssw = sum(sum((v - sum(x) / len(x)) ** 2 for v in x) for x in by.values())
    msb, msw = ssb / (k - 1), ssw / (n - k)
    m0 = (n - sum(len(x) ** 2 for x in by.values()) / n) / (k - 1)
    icc = max(0.0, (msb - msw) / (msb + (m0 - 1) * msw)) if msb + (m0 - 1) * msw > 0 else 0.0
    m_bar = sum(len(x) ** 2 for x in by.values()) / n
    de = 1 + (m_bar - 1) * icc
    return {"n": n, "groups": k, "icc": icc, "design_effect": de, "effective_n": n / de,
            "date_fixed_effect_r2": ssb / (ssb + ssw) if ssb + ssw > 0 else NAN}


def sibling_share(episodes: Sequence[dict[str, Any]], *, jaccard: float, within_sessions: int) -> dict[str, float | int]:
    """Share of episodes with a same-ticker sibling within ``within_sessions`` whose token Jaccard is at least ``jaccard`` (story duplication)."""
    by: dict[str, list[tuple[int, set[str], dict[str, Any]]]] = defaultdict(list)
    for e in episodes:
        by[e["ticker"]].append((e["s0"], set(_TOKEN.findall(str(e.get("text", "")).lower())), e))
    straddle = 0
    flagged: set[int] = set()
    for rows in by.values():
        rows.sort(key=lambda r: r[0])
        for i, (s, toks, e) in enumerate(rows):
            j = i + 1
            while j < len(rows) and rows[j][0] - s <= within_sessions:
                t2 = rows[j][1]
                if toks and t2 and len(toks & t2) / len(toks | t2) >= jaccard:
                    flagged.add(id(e))
                    flagged.add(id(rows[j][2]))
                    if e.get("split") != rows[j][2].get("split"):
                        straddle += 1
                j += 1
    has = len(flagged)
    return {"episodes": len(episodes), "with_sibling": has, "share": has / len(episodes) if episodes else NAN, "split_straddling_pairs": straddle}


# ------------------------------------------------------------------------------------------------ prices-side helpers
def clean(o: Any) -> Any:
    """Recursively replace NaN/inf by None so the evidence file is strict JSON."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


def prices_digest(prices_dir: Path) -> str:
    """One digest over every price file (name + sha256), so the evidence says exactly which (non-redistributable) prices it used."""
    import hashlib

    h = hashlib.sha256()
    for p in sorted(prices_dir.glob("*.csv")):
        h.update(p.name.encode() + b"\0" + sha256_file(p).encode() + b"\n")
    return h.hexdigest()


def vix_prev(store: PriceStore, s0: int) -> float:
    """^VIX close of the latest valid session before ``s0`` (looks back at most five sessions)."""
    vix = store.close[store.cfg.volatility_symbol]
    for k in range(1, 6):
        if s0 - k >= 0 and vix[s0 - k] == vix[s0 - k]:
            return vix[s0 - k]
    return NAN


def residuals(store: PriceStore, ticker: str, fit: Fit, lo: int, hi: int) -> list[tuple[int, float]]:
    """(session, abnormal return) for valid sessions in [lo, hi), under ``fit``. Same arithmetic as ``PriceStore.target``."""
    y, m = store.ret[ticker], store.ret[store.market]
    p = store.peer.get(ticker) or [NAN] * len(y)
    out = []
    for i in range(lo, hi):
        pk = p[i] if fit.c != 0.0 else 0.0
        if y[i] == y[i] and m[i] == m[i] and pk == pk:
            out.append((i, y[i] - fit.a - fit.b * m[i] - fit.c * pk))
    return out


def sigma_ex(res: Sequence[tuple[int, float]], drop: set[int], min_obs: int = 30) -> float | None:
    kept = [r for i, r in res if i not in drop]
    return math.sqrt(sum(r * r for r in kept) / len(kept)) if len(kept) >= min_obs else None


def earnings_sessions(store: PriceStore, filings_path: Path) -> dict[str, list[int]]:
    """Per ticker, the reaction sessions of 8-K item 2.02 filings (exact acceptance time, so after-close filings react the next session)."""
    out: dict[str, set[int]] = defaultdict(set)
    with filings_path.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("form") != "8-K" or "2.02" not in (r.get("items") or []):
                continue
            ts = datetime.fromisoformat(str(r["acceptance_utc"]).replace("Z", "+00:00"))
            s, _ = store.anchor(ts, "SOURCE")
            if s is not None:
                out[r["ticker"]].add(s)
    return {t: sorted(v) for t, v in out.items()}


def has_session_in(sorted_sessions: Sequence[int], lo: int, hi: int) -> bool:
    """True if any session in the sorted list lies in [lo, hi]."""
    i = bisect_left(sorted_sessions, lo)
    return i < len(sorted_sessions) and sorted_sessions[i] <= hi


def sample_quiet(store: PriceStore, taken: dict[str, set[int]], earn: dict[str, list[int]], *, n: int, first_idx: int, seed: int,
                 lam: float, exclude_within: int) -> list[dict[str, Any]]:
    """Random (ticker, session) pairs with no corpus episode of that ticker within ``exclude_within`` sessions; three z's per pair."""
    rng = random.Random(seed)
    tickers = sorted(t for t in store.sectors if t in store.close)
    window = store.cfg.window_sessions
    last = len(store.dates) - window - 1
    blocked = {t: {s + d for s in ss for d in range(-exclude_within, exclude_within + 1)} for t, ss in taken.items()}
    out: list[dict[str, Any]] = []
    tries = 0
    while len(out) < n and tries < 40 * n:
        tries += 1
        t = tickers[rng.randrange(len(tickers))]
        s0 = rng.randrange(first_idx, last + 1)
        if s0 in blocked.get(t, ()):
            continue
        tgt, _ = store.target(t, s0)
        if tgt is None:
            continue
        vix = vix_prev(store, s0)
        if vix != vix:
            continue
        sw = store.cfg.sigma_window
        res = residuals(store, t, tgt.fit, s0 - sw, s0)
        if len(res) < sw // 2:
            continue
        s_ew = ewma_sigma(tgt.fit.sigma, [r for _, r in res], lam)
        es = earn.get(t, [])
        k = bisect_left(es, s0 - sw)
        in_window = [e for e in es[k:] if e < s0]
        in_target = has_session_in(es, s0, s0 + window - 1)
        z_ex = None
        ratio = None
        if in_window:
            drop = {e for e in in_window} | {e + 1 for e in in_window}
            s_ex = sigma_ex(res, drop)
            if s_ex:
                z_ex = tgt.car / (s_ex * math.sqrt(window))
                ratio = tgt.fit.sigma / s_ex
        out.append({"ticker": t, "s0": s0, "date": store.dates[s0], "year": int(store.dates[s0][:4]), "vix": vix,
                    "z60": tgt.z, "z_ewma": tgt.car / (s_ew * math.sqrt(window)), "earn_in_window": bool(in_window),
                    "z_ex": z_ex, "sigma_ratio": ratio, "earn_in_target": in_target})
    if len(out) < n:
        raise ConfigError(f"quiet-day sampler produced only {len(out)} of {n} pairs")
    return out


# ------------------------------------------------------------------------------------------------ the pre-registered decision
def decide_ewma(sample: Sequence[dict[str, Any]], cuts: tuple[float, float], rule: dict[str, Any]) -> dict[str, Any]:
    """Apply ``adopt_ewma_if`` from the pre-registration to the quiet-day sample. Returns every number the rule used."""
    def gap(rows: Sequence[dict[str, Any]], key: str) -> float:
        return regime_gap([r[key] for r in rows], [tercile_of(r["vix"], cuts) for r in rows])

    halves = []
    for first, last in rule["must_hold_in_both_halves"]:
        rows = [r for r in sample if first <= r["date"] <= last]
        g60, ge = gap(rows, "z60"), gap(rows, "z_ewma")
        red = 1 - ge / g60 if g60 == g60 and ge == ge and g60 > 0 else NAN
        halves.append({"first": first, "last": last, "n": len(rows), "gap_sigma60": g60, "gap_ewma": ge, "reduction": red})
    g60, ge = gap(sample, "z60"), gap(sample, "z_ewma")
    var_e = moments([r["z_ewma"] for r in sample])["var"]
    lo, hi = rule["overall_null_variance_within"]
    thr = rule["regime_log_variance_gap_reduction_at_least"]
    checks = {
        "reduction_in_every_half": all(h["reduction"] == h["reduction"] and h["reduction"] >= thr for h in halves),
        "overall_ewma_variance_in_range": bool(var_e == var_e and lo <= var_e <= hi),
    }
    return {"threshold": thr, "variance_range": [lo, hi], "overall": {"gap_sigma60": g60, "gap_ewma": ge,
            "reduction": (1 - ge / g60) if g60 and g60 == g60 and ge == ge else NAN, "ewma_variance": var_e},
            "halves": halves, "checks": checks, "adopt_ewma": all(checks.values()),
            "outcome_version": "outcome-v3" if all(checks.values()) else "outcome-v2"}


# ------------------------------------------------------------------------------------------------ episodes from the v2 table
def load_issuer_episodes(table: Path) -> tuple[list[dict[str, Any]], dict[str, set[int]]]:
    """(news episodes, every issuer episode's (ticker -> sessions)). One news episode per ticker-session, text = its earliest news report."""
    taken: dict[str, set[int]] = defaultdict(set)
    best: dict[str, dict[str, Any]] = {}
    with table.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("scope") != "ISSUER":
                continue
            taken[r["ticker"]].add(int(r["s0"]))
            if r.get("is_news") != 1.0:
                continue
            cur = best.get(r["episode"])
            if cur is None or r["published_at"] < cur["published_at"]:
                best[r["episode"]] = {k: r.get(k) for k in ("episode", "ticker", "s0", "s0_date", "z", "abs_z", "placebo_abs_z", "timing", "origin",
                                                          "published_at", "text", "event_top", "adapter", "f_vix_level", "f_sigma_60",
                                                          "f_resid_vol_5d_ratio", "f_resid_vol_20d_ratio", "split_P2_extended")}
                best[r["episode"]]["split"] = r.get("split_P2_extended")
    return sorted(best.values(), key=lambda e: (e["s0"], e["ticker"])), taken


def stratified_auc(events: Sequence[dict[str, Any]], null: Sequence[dict[str, Any]], *, min_events: int = 5, min_null: int = 20) -> dict[str, Any]:
    """AUC of |z| (event > quiet) within (ticker, year) strata, averaged with event-count weights: composition cannot drive it."""
    nul: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in null:
        nul[(r["ticker"], r["year"])].append(abs(r["z60"]))
    ev: dict[tuple[str, int], list[float]] = defaultdict(list)
    for e in events:
        ev[(e["ticker"], int(e["s0_date"][:4]))].append(float(e["abs_z"]))
    num = den = 0.0
    used = 0
    for key, pos in ev.items():
        neg = nul.get(key, [])
        if len(pos) < min_events or len(neg) < min_null:
            continue
        a = auc(np.asarray(pos), np.asarray(neg))
        num += a * len(pos)
        den += len(pos)
        used += len(pos)
    return {"auc": num / den if den else NAN, "events_used": used, "events_total": len(events)}


def bootstrap_stratified_auc(events: Sequence[dict[str, Any]], null: Sequence[dict[str, Any]], *, resamples: int, seed: int) -> tuple[float, float]:
    """95% interval of the stratified AUC, resampling reaction dates (episodes of one day move together)."""
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_date[e["s0_date"]].append(e)
    dates = sorted(by_date)
    rng = random.Random(seed)
    vals = []
    for _ in range(resamples):
        picked = [d for d in (dates[rng.randrange(len(dates))] for _ in dates)]
        sample = [e for d in picked for e in by_date[d]]
        a = stratified_auc(sample, null)["auc"]
        if a == a:
            vals.append(a)
    vals.sort()
    if len(vals) < 20:
        return NAN, NAN
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


# ------------------------------------------------------------------------------------------------ the audit
def build_store(repo_root: Path, config_dir: Path) -> PriceStore:
    mcfg = load_modeling_config(config_dir)
    icfg = load_impact_model_config(config_dir)
    ents = repo_root / "data" / "history_v2" / "entities.json"
    if not ents.is_file():
        ents = repo_root / "data" / "history" / "entities.json"
    if not ents.is_file():
        raise ConfigError("missing entities.json: see docs/EVIDENCE_V2.md (`make history-v2`)")
    sectors = {e["ticker"]: e["sector"] for e in json.loads(ents.read_text(encoding="utf-8")) if e.get("ticker")}
    symbols = [*sectors, mcfg.impact.market_symbol, mcfg.impact.volatility_symbol, icfg.rates_symbol]
    return PriceStore.from_dir(repo_root / "data" / "raw" / "prices", symbols, sectors, mcfg.impact)


def run_audit(repo_root: Path, config_dir: Path, out_path: Path, *, log=print) -> dict[str, Any]:
    pre, pre_sha = load_evidence_v3(config_dir)
    audit = pre["outcome_audit"]
    table = repo_root / pre["data"]["impact_table"]
    for p in (table, repo_root / pre["data"]["filings"]):
        if not p.is_file():
            raise ConfigError(f"missing input {p}: `make impact-table-v2 events-calendar` (docs/EVIDENCE_V2.md)")
    store = build_store(repo_root, config_dir)
    window = store.cfg.window_sessions
    lam = 0.94

    log("loading episodes ...")
    episodes, taken = load_issuer_episodes(table)
    earn = earnings_sessions(store, repo_root / pre["data"]["filings"])

    first = audit["null_sample"]["first_session_date"]
    first_idx = bisect_left(store.dates, first)
    cuts = regime_cutpoints(store, pre)
    c0, c1 = audit["regime"]["tercile_cutpoints_from"]["first"], audit["regime"]["tercile_cutpoints_from"]["last"]

    log(f"sampling {audit['null_sample']['n']} quiet (ticker, session) pairs ...")
    null = sample_quiet(store, taken, earn, n=int(audit["null_sample"]["n"]), first_idx=first_idx, seed=int(pre["seed"]), lam=lam,
                        exclude_within=int(audit["null_sample"]["exclude_within_sessions"]))
    regime = [tercile_of(r["vix"], cuts) for r in null]

    # --- identity check: the table's z equals the live target (so CAR = z * sigma * sqrt(W) is recoverable from the table)
    ident_z = ident_sigma = 0.0
    checked = 0
    with table.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("scope") != "ISSUER":
                continue
            tgt, _ = store.target(r["ticker"], int(r["s0"]))
            if tgt is not None:
                ident_z = max(ident_z, abs(tgt.z - r["z"]))
                ident_sigma = max(ident_sigma, abs(tgt.fit.sigma - r["f_sigma_60"]))
                checked += 1
            if checked >= 3000:
                break

    # --- normalisation: both estimators, overall and by regime
    norm = {}
    for key, label in (("z60", "sigma60"), ("z_ewma", "ewma094")):
        norm[label] = {"overall": moments([r[key] for r in null]),
                       "by_vix_tercile": {str(t): moments([r[key] for r, g in zip(null, regime, strict=True) if g == t]) for t in (0, 1, 2)},
                       "regime_log_variance_gap": regime_gap([r[key] for r in null], regime)}
    decision = decide_ewma(null, cuts, audit["adopt_ewma_if"])

    # --- event vs quiet
    boot = pre["bootstrap"]
    ev_all = stratified_auc(episodes, null)
    lo, hi = bootstrap_stratified_auc(episodes, null, resamples=min(int(boot["resamples"]), 300), seed=int(pre["seed"]))
    by_year = {}
    for y in sorted({int(e["s0_date"][:4]) for e in episodes}):
        sub = [e for e in episodes if int(e["s0_date"][:4]) == y]
        by_year[str(y)] = {**stratified_auc(sub, null), "episodes": len(sub),
                           "p_abs_z_ge_2": float(np.mean([e["abs_z"] >= 2 for e in sub])),
                           "null_p_abs_z_ge_2": float(np.mean([abs(r["z60"]) >= 2 for r in null if r["year"] == y])) if any(r["year"] == y for r in null) else NAN}
    by_class = {}
    for cls in sorted({str(e.get("event_top")) for e in episodes}):
        sub = [e for e in episodes if str(e.get("event_top")) == cls]
        by_class[cls] = {**stratified_auc(sub, null), "episodes": len(sub)}

    # --- clock quality
    timing = {}
    for tm in sorted({e["timing"] for e in episodes}):
        sub = [e for e in episodes if e["timing"] == tm]
        real = np.mean([math.log1p(e["abs_z"]) for e in sub])
        plc = np.mean([math.log1p(e["placebo_abs_z"]) for e in sub if e["placebo_abs_z"] is not None])
        timing[tm] = {"episodes": len(sub), "median_abs_z": float(np.median([e["abs_z"] for e in sub])), "mean_log1p_real": float(real),
                      "mean_log1p_placebo": float(plc), "placebo_over_real": float(plc / real) if real else NAN, **stratified_auc(sub, null)}

    # --- clustering of reaction dates
    clustering = icc_design_effect([math.log1p(e["abs_z"]) for e in episodes], [e["s0_date"] for e in episodes])
    wide = 0
    for e in episodes:
        mt, _ = store.market_target(int(e["s0"]))
        wide += int(mt is not None and mt.abs_z >= float(audit["material_move_abs_z"]))
    clustering["share_on_market_wide_move_days"] = wide / len(episodes) if episodes else NAN

    # --- estimation-window contamination (on the quiet sample, where it varies)
    cont = [r for r in null if r["earn_in_window"]]
    no_earn = [r for r in null if not r["earn_in_window"]]
    contamination = {"share_with_earnings_in_sigma_window": len(cont) / len(null),
                     "var_z60_contaminated": moments([r["z60"] for r in cont])["var"],
                     "var_z60_clean": moments([r["z60"] for r in no_earn])["var"],
                     "mean_sigma_inflation_vs_ex_earnings": float(np.mean([r["sigma_ratio"] for r in cont if r["sigma_ratio"]])) if cont else NAN,
                     "var_z_if_earnings_excluded": moments([r["z_ex"] for r in cont if r["z_ex"] is not None])["var"],
                     "note": "diagnostic only: no remedy is applied in this round (see configs/evidence_v3.yaml)"}

    # POST-HOC (added after the first run showed the pre-registered null still contains earnings sessions; disclosed in the journal):
    # the same lift against a null whose own target window contains no earnings reaction, for episodes whose window contains none either.
    null_ex = [r for r in null if not r["earn_in_target"]]
    for e in episodes:
        e["earn_in_target"] = has_session_in(earn.get(e["ticker"], []), int(e["s0"]), int(e["s0"]) + window - 1)
    ev_ne = [e for e in episodes if not e["earn_in_target"]]
    ev_e = [e for e in episodes if e["earn_in_target"]]
    lo_ne, hi_ne = bootstrap_stratified_auc(ev_ne, null_ex, resamples=min(int(boot["resamples"]), 300), seed=int(pre["seed"]))
    posthoc = {
        "note": "post-hoc, not in the pre-registration; the adoption decision above uses only the pre-registered null",
        "null_share_with_earnings_in_target_window": 1 - len(null_ex) / len(null),
        "episodes_share_with_earnings_in_target_window": len(ev_e) / len(episodes) if episodes else NAN,
        "news_without_earnings_vs_quiet_without_earnings": {**stratified_auc(ev_ne, null_ex), "auc_ci95": [lo_ne, hi_ne], "episodes": len(ev_ne),
                                                           "p_abs_z_ge_material_events": float(np.mean([e["abs_z"] >= float(audit["material_move_abs_z"]) for e in ev_ne])),
                                                           "p_abs_z_ge_material_quiet": float(np.mean([abs(r["z60"]) >= float(audit["material_move_abs_z"]) for r in null_ex]))},
        "news_with_earnings_in_window_vs_all_quiet": {**stratified_auc(ev_e, null), "episodes": len(ev_e)},
        "normalisation_quiet_ex_earnings": {"sigma60": moments([r["z60"] for r in null_ex]), "ewma094": moments([r["z_ewma"] for r in null_ex])},
    }

    # market-scope yardstick for the analogue layer: how often the S&P 500's own excess move exceeds the material threshold on an ordinary session
    mz = []
    for s_idx in range(first_idx, len(store.dates) - window):
        mt, _ = store.market_target(s_idx)
        if mt is not None:
            mz.append(mt.z)
    market_baseline = {**moments(mz), "definition": "every session since the first null session; the S&P 500's excess move over the reaction window in trailing-sigma units"}

    material = float(audit["material_move_abs_z"])
    out = {
        "schema": SCHEMA, "evidence_version": pre["version"], "preregistration_sha256": pre_sha, "seed": int(pre["seed"]),
        "inputs": {"impact_table_sha256": sha256_file(table), "episodes_news_issuer": len(episodes),
                   "prices_sha256": prices_digest(repo_root / pre["data"]["prices_dir"]),
                   "price_sessions": len(store.dates), "price_first": store.dates[0], "price_last": store.dates[-1]},
        "vix_tercile_cutpoints": {"from": [c0, c1], "cuts": list(cuts)},
        "identity_check": {"rows_checked": checked, "max_abs_diff_z": ident_z, "max_abs_diff_sigma": ident_sigma, "note": "table z and sigma vs PriceStore.target; CAR = z*sigma*sqrt(W)"},
        "window_sessions": window, "null_sample": {"n": len(null), "by_year": {str(y): sum(1 for r in null if r["year"] == y) for y in sorted({r["year"] for r in null})}},
        "normalisation": norm, "decision": decision,
        "event_vs_quiet": {"stratified_auc": ev_all, "auc_ci95": [lo, hi], "by_year": by_year, "by_event_class": by_class,
                           "p_abs_z_ge_material_events": float(np.mean([e["abs_z"] >= material for e in episodes])),
                           "p_abs_z_ge_material_quiet": float(np.mean([abs(r["z60"]) >= material for r in null]))},
        "clock_quality": timing, "clustering": clustering, "estimation_window_contamination": contamination,
        "story_duplication": sibling_share(episodes, jaccard=0.5, within_sessions=10),
        "posthoc_ex_earnings": posthoc, "market_session_baseline": market_baseline,
    }
    atomic_write_text(out_path, json.dumps(clean(out), indent=2, sort_keys=True, allow_nan=False) + "\n")
    log(f"wrote {out_path}")
    return out
