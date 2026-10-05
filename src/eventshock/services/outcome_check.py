"""Stage 8 evidence for the UI: does the severity scale rank realised moves, what does the outcome look like around ordinary news, and did retrieval earn a place in the score?

Read-only and built once at start-up from the committed evidence files (``docs/evidence/*.json``). Nothing is computed per request; a missing file is reported with the
command that produces it, never filled in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain.base import ContractModel

FILES = {"audit": ("outcome_audit.json", "make outcome-audit"), "validity": ("severity_validity.json", "make severity-validity"),
         "relevance": ("analogue_relevance.json", "make analogue-relevance"), "floor": ("analogue_floor.json", "make analogue-floor"),
         "value": ("analogue_outcome_value.json", "make analogue-value")}

LABEL_READING = {
    "OUTCOME_VALIDATED": "The severity score ranked realised market moves beyond the volatility regime, better than its own placebo window, on both the 2025 test and the 2026 live data.",
    "DIRECTIONALLY_INFORMATIVE": "The severity score ranked realised moves on both the 2025 test and the 2026 live data, but the regime-neutral checks did not all pass.",
    "HEURISTIC_UNCALIBRATED": ("A transparent triage scale, not an outcome-calibrated one. On company headlines it did not rank realised market moves out of sample, and the data "
                               "available here cannot confirm or refute what it is designed to say (how serious a kind of development usually is and how far it reaches)."),
}


class Interval(ContractModel):
    name: str
    estimate: float | None
    lo: float | None
    hi: float | None


class BandRow(ContractModel):
    band: str
    n: int
    tail_rate: float | None
    lo: float | None
    hi: float | None


class SplitCheck(ContractModel):
    split: str
    n: int
    abstained_share: float | None
    tail_rate: float | None
    metrics: list[Interval]
    bands: list[BandRow]


class AuditSummary(ContractModel):
    quiet_days_sampled: int
    news_episodes: int
    auc: float | None
    auc_lo: float | None
    auc_hi: float | None
    share_move_news: float | None
    share_move_quiet: float | None
    auc_without_earnings: float | None
    auc_without_earnings_lo: float | None
    auc_without_earnings_hi: float | None
    auc_with_earnings: float | None
    effective_sample: float | None
    nominal_sample: int | None
    sigma_decision: str
    sigma_reading: str


class RelevanceRow(ContractModel):
    queries: str
    base_rate: float
    p_at_5_e5: float
    p_at_5_tfidf: float
    delta: float
    delta_lo: float
    delta_hi: float


class ValueRow(ContractModel):
    candidate: str
    split: str
    delta_mae: float | None
    lo: float | None
    hi: float | None


class RetrievalSummary(ContractModel):
    served_retriever: str | None
    relevance: list[RelevanceRow]
    similarity_floor: float | None
    floor_curve: list[dict[str, float | bool | None]]
    value: list[ValueRow]
    decision: str | None


class OutcomeCheck(ContractModel):
    label: str | None
    label_reading: str | None
    preregistration_sha256: str | None
    splits: list[SplitCheck]
    market_scope: list[SplitCheck]
    market_scope_note: str | None
    audit: AuditSummary | None
    retrieval: RetrievalSummary | None
    missing: list[str]
    note: str = ("Written before the results were seen (configs/evidence_v3.yaml). An outcome-check result is a statement about the data available here (large-cap company headlines, "
                 "a sampled news feed, 2014-2026), not about every kind of event.")


def _read(root: Path, key: str) -> dict[str, Any] | None:
    p = root / "docs" / "evidence" / FILES[key][0]
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _splits(by: dict[str, Any]) -> list[SplitCheck]:
    out = []
    for name in ("dev", "test", "live"):
        s = by.get(name)
        if not s or "metrics" not in s:
            continue
        out.append(SplitCheck(
            split=name, n=s["n"], abstained_share=s.get("abstained_share"), tail_rate=s.get("overall_tail_rate"),
            metrics=[Interval(name=k, estimate=v["estimate"], lo=v["lo"], hi=v["hi"]) for k, v in s["metrics"].items()],
            bands=[BandRow(band=b["band"], n=b["n"], tail_rate=b["rate"], lo=b["wilson_lo"], hi=b["wilson_hi"]) for b in s.get("band_table", [])]))
    return out


def build_outcome_check(root: Path) -> OutcomeCheck:
    data = {k: _read(root, k) for k in FILES}
    missing = [f"{FILES[k][0]}: run `{FILES[k][1]}`" for k, v in data.items() if v is None]
    val, aud, rel, flr, vv = data["validity"], data["audit"], data["relevance"], data["floor"], data["value"]
    audit = None
    if aud:
        e, ph = aud["event_vs_quiet"], aud["posthoc_ex_earnings"]
        d = aud["decision"]
        audit = AuditSummary(
            quiet_days_sampled=aud["null_sample"]["n"], news_episodes=aud["inputs"]["episodes_news_issuer"], auc=e["stratified_auc"]["auc"], auc_lo=e["auc_ci95"][0], auc_hi=e["auc_ci95"][1],
            share_move_news=e["p_abs_z_ge_material_events"], share_move_quiet=e["p_abs_z_ge_material_quiet"], auc_without_earnings=ph["news_without_earnings_vs_quiet_without_earnings"]["auc"],
            auc_without_earnings_lo=ph["news_without_earnings_vs_quiet_without_earnings"]["auc_ci95"][0], auc_without_earnings_hi=ph["news_without_earnings_vs_quiet_without_earnings"]["auc_ci95"][1],
            auc_with_earnings=ph["news_with_earnings_in_window_vs_all_quiet"]["auc"], effective_sample=aud["clustering"]["effective_n"], nominal_sample=aud["clustering"]["n"],
            sigma_decision=d["outcome_version"],
            sigma_reading=(f"A volatility estimate that adapts faster (EWMA) removed {100 * d['overall']['reduction']:.0f}% of the calm-versus-turbulent variance gap in the normalised move "
                           "and is used for the analogue layer; the frozen models keep the original definition." if d["adopt_ewma"] else "The original volatility estimate was kept."))
    retrieval = None
    if rel or flr or vv:
        rows = []
        for name, m in (rel["metrics"].items() if rel else []):
            dd = m["delta_p_at_5_e5_minus_tfidf"]
            rows.append(RelevanceRow(queries={"all_queries": "All 280 gold queries", "non_none_queries": "The 149 event queries", "decontaminated_queries": "Without near-duplicates"}.get(name, name),
                                     base_rate=m["base_rate"], p_at_5_e5=m["e5"]["p_at_5"], p_at_5_tfidf=m["tfidf"]["p_at_5"], delta=dd["estimate"], delta_lo=dd["lo"], delta_hi=dd["hi"]))
        value = []
        for cand in ("C_knn", "G_reference_class"):
            for split in ("test", "live"):
                x = (vv or {}).get("results", {}).get(split, {}).get(cand, {}).get("delta_mae_vs_B0")
                if x:
                    value.append(ValueRow(candidate=cand, split=split, delta_mae=x["estimate"], lo=x["lo"], hi=x["hi"]))
        retrieval = RetrievalSummary(served_retriever=(rel or {}).get("decision", {}).get("served_retriever"), relevance=rows, similarity_floor=(flr or {}).get("chosen"),
                                     floor_curve=[{"floor": r["floor"], "precision_lift": r["precision_lift"], "answerable_share": r["answerable_share"], "chosen": r["floor"] == flr.get("chosen")}
                                                  for r in (flr or {}).get("curve", [])], value=value, decision=(vv or {}).get("decision"))
    mk = (val or {}).get("posthoc_market_scope")
    return OutcomeCheck(label=val["label"]["label"] if val else None, label_reading=LABEL_READING.get(val["label"]["label"]) if val else None,
                        preregistration_sha256=val["preregistration_sha256"] if val else None, splits=_splits(val["by_split"]) if val else [],
                        market_scope=_splits(mk["by_split"]) if mk else [], market_scope_note=mk["note"] if mk else None, audit=audit, retrieval=retrieval, missing=missing)
