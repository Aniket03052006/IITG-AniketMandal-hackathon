"""When is an event worth a person's look? Named rules over fields the monitor already holds; no model, no score, no new number."""

from __future__ import annotations

from datetime import datetime

from ..decision.config import ReviewCfg
from ..monitor.models import EventState, fingerprint_of
from .models import ReasonCode, ReviewReason, RuleInfo

# What identifies an event's own evidence. The portfolio-dependent fields (materiality, exposure, stress) are left out on purpose: a decision made on one
# book must not look "changed" when the same event is read against another.
INTRINSIC = ("member_count", "report_count", "independent_sources", "severity", "lifecycle", "evidence_tier", "conflict", "lead_signal_id")

LABELS: dict[ReasonCode, str] = {
    ReasonCode.CONFLICTED_CLAIMS: "Sources disagree",
    ReasonCode.UNRESOLVED_HIGH_SEVERITY: "High severity, subject unresolved",
    ReasonCode.SINGLE_SOURCE_HIGH_SEVERITY: "High severity, one source",
    ReasonCode.MATERIAL_TO_BOOK: "Material to the book",
    ReasonCode.LARGE_STRESS_LOSS: "Large modeled loss",
    ReasonCode.ESCALATING: "Escalating",
    ReasonCode.CHANGED_SINCE_REVIEW: "Changed since reviewed",
}


def intrinsic_fingerprint(state: EventState) -> str:
    return fingerprint_of({k: getattr(state, k) for k in INTRINSIC})


def evaluate(state: EventState, cfg: ReviewCfg) -> list[ReviewReason]:
    """Every rule that fires for this event, in a fixed order, each with the values that fired it."""
    out: list[ReviewReason] = []
    sev = state.severity

    def add(code: ReasonCode, detail: str) -> None:
        out.append(ReviewReason(code=code, label=LABELS[code], detail=detail))

    if state.conflict in ("CONFLICTED", "POSSIBLE_CONFLICT"):
        add(ReasonCode.CONFLICTED_CLAIMS, f"claims conflict ({state.conflict.lower().replace('_', ' ')}); evidence is {state.evidence_tier.lower()}")
    if sev is not None and state.scope_type == "UNRESOLVED" and sev >= cfg.unresolved_min_severity:
        add(ReasonCode.UNRESOLVED_HIGH_SEVERITY, f"severity {sev:g} (at least {cfg.unresolved_min_severity:g}) and the text names no company, sector or market")
    if sev is not None and state.independent_sources <= 1 and sev >= cfg.single_source_min_severity:
        add(ReasonCode.SINGLE_SOURCE_HIGH_SEVERITY, f"severity {sev:g} (at least {cfg.single_source_min_severity:g}) reported by {state.independent_sources} independent source")
    if state.materiality in cfg.material_levels:
        share = f", reaching {state.exposure_share:.1%} of the book" if state.exposure_share is not None else ""
        add(ReasonCode.MATERIAL_TO_BOOK, f"relevance to the book is {state.materiality}{share}")
    if state.stress_pnl_pct is not None and state.stress_pnl_pct <= cfg.stress_loss_floor:
        add(ReasonCode.LARGE_STRESS_LOSS, f"the generated scenario models {state.stress_pnl_pct:+.2%} of the book (floor {cfg.stress_loss_floor:+.0%}); a simulation, not a forecast")
    if state.lifecycle == "ESCALATING":
        add(ReasonCode.ESCALATING, "its lifecycle is ESCALATING")
    return out


def rule_catalogue(cfg: ReviewCfg) -> list[RuleInfo]:
    r = ReasonCode
    return [
        RuleInfo(code=r.CONFLICTED_CLAIMS, label=LABELS[r.CONFLICTED_CLAIMS], rule="the event's claims contradict each other (conflict is CONFLICTED or POSSIBLE_CONFLICT); never inferred from tone"),
        RuleInfo(code=r.UNRESOLVED_HIGH_SEVERITY, label=LABELS[r.UNRESOLVED_HIGH_SEVERITY], rule=f"scope is UNRESOLVED and severity >= {cfg.unresolved_min_severity:g}"),
        RuleInfo(code=r.SINGLE_SOURCE_HIGH_SEVERITY, label=LABELS[r.SINGLE_SOURCE_HIGH_SEVERITY], rule=f"at most one independent source and severity >= {cfg.single_source_min_severity:g}"),
        RuleInfo(code=r.MATERIAL_TO_BOOK, label=LABELS[r.MATERIAL_TO_BOOK], rule=f"relevance to the book is {' or '.join(cfg.material_levels)} (read against the book selected)"),
        RuleInfo(code=r.LARGE_STRESS_LOSS, label=LABELS[r.LARGE_STRESS_LOSS], rule=f"the generated scenario's modeled change is {cfg.stress_loss_floor:+.0%} of the book or worse (a simulation)"),
        RuleInfo(code=r.ESCALATING, label=LABELS[r.ESCALATING], rule="the event's lifecycle is ESCALATING"),
        RuleInfo(code=r.CHANGED_SINCE_REVIEW, label=LABELS[r.CHANGED_SINCE_REVIEW], rule="reviewed or dismissed earlier, and the event's own evidence has changed since (reports, sources, severity, lifecycle, evidence tier or conflict)"),
    ]


def changed_reason(status: str, at: datetime) -> ReviewReason:
    return ReviewReason(code=ReasonCode.CHANGED_SINCE_REVIEW, label=LABELS[ReasonCode.CHANGED_SINCE_REVIEW], detail=f"it was {status.lower()} on {at:%d %b %Y, %H:%M} UTC and its evidence has changed since")
