"""Evidence about an event: how well it is corroborated. Kept strictly apart from how sure a model is of its own output.

``evidence_strength`` is a tier from explicit, named rules over countable facts (independent sources, source diversity, authoritative
sources, an open contradiction). ``model_confidence`` lists, per model stage, what that stage says about itself. The two answer different
questions ("did this happen, according to whom?" versus "is the classifier sure of its label?") and are never merged into one number.
"""

from __future__ import annotations

from ..domain import UNKNOWN_ENTITY, EventStatus, RiskSignal
from .config import EvidenceCfg
from .grouping import GReport
from .model import (
    Availability,
    ConfidenceTier,
    ConflictState,
    EvidenceProfile,
    EvidenceStrength,
    ModelConfidenceItem,
)

_TIER_ORDER = ["INSUFFICIENT", "WEAK", "MODERATE", "STRONG"]


def model_confidence(signal: RiskSignal) -> list[ModelConfidenceItem]:
    ev, prov = signal.event, signal.provenance
    event_trained = bool(prov and prov.event)
    out = [ModelConfidenceItem(
        stage="event", value=round(ev.confidence, 4),
        basis=(f"calibrated P of the top class among all nine classes ({prov.event.model_id})" if event_trained and prov and prov.event
               else "the placeholder rule's top-class share: not a calibrated probability"),
        status={EventStatus.CLASSIFIED: "classified: the model committed to a class", EventStatus.UNCERTAIN: "uncertain: no class is asserted",
                EventStatus.NO_EVENT: "not a market event"}[ev.status])]
    s = signal.sentiment
    sent_conf = prov.sentiment.confidence if prov and prov.sentiment else max(s.positive, s.neutral, s.negative)
    out.append(ModelConfidenceItem(
        stage="sentiment", value=round(sent_conf, 4),
        basis=("largest calibrated class probability of the trained sentiment model" if prov and prov.sentiment else "largest class share"),
        status="trained model (experimental)" if prov and prov.sentiment else "placeholder or source label"))
    imp = signal.impact
    if imp is None:
        out.append(ModelConfidenceItem(stage="impact", value=None, basis="no impact was scored for this signal", status="unavailable"))
    else:
        lifecycle = prov.impact.lifecycle.value if prov and prov.impact else None
        rng = f"; comparable history spans {imp.score_low}-{imp.score_high}" if imp.score_low is not None else ""
        out.append(ModelConfidenceItem(
            stage="impact", value=None, basis=f"a 1-10 market-response proxy, not a probability{rng}",
            status=(f"trained impact model, lifecycle {lifecycle} (experimental)" if lifecycle else "placeholder rule")))
    return out


def build_evidence_profile(signal: RiskSignal, reports: list[GReport], scope_tier: ConfidenceTier, disagreement: ConflictState,
                           cfg: EvidenceCfg, authoritative: frozenset[str], trusted: bool) -> EvidenceProfile:
    mc = model_confidence(signal)
    ent = signal.entity
    entity_conf = None if ent.entity_id == UNKNOWN_ENTITY else ent.link_confidence
    audit = signal.provenance.entity_audit if signal.provenance else None
    entity_basis = ("no company was resolved" if entity_conf is None else
                    f"rule {audit.rule}" + (f", matched {audit.matched_text!r}" if audit and audit.matched_text else "") if audit else "entity resolver")
    n = len(reports)
    ind = [r for r in reports if r.independent]
    n_ind = len(ind)
    domains = {r.domain for r in reports}
    copies = sum(1 for r in reports if not r.independent)
    auth_domains = sorted({r.domain for r in ind if r.domain in authoritative})
    firsts = [r.published_at for r in reports]
    diversity = round(n_ind / n, 4) if n else None
    disagree = {ConflictState.NO_CONFLICT: "NONE", ConflictState.POSSIBLE_CONFLICT: "POSSIBLE", ConflictState.CONFLICTED: "CONFLICTED",
                ConflictState.RESOLVED_CONFLICT: "RESOLVED"}[disagreement]

    reasons: list[str] = []
    if n_ind >= cfg.strong_min_independent and (diversity or 0) >= cfg.strong_min_diversity:
        tier, rule = "STRONG", "STRONG_INDEPENDENT"
        reasons.append(f"{n_ind} independent sources (≥{cfg.strong_min_independent}) and diversity {diversity:.2f} (≥{cfg.strong_min_diversity:g})")
    elif n_ind >= cfg.moderate_min_independent:
        tier, rule = "MODERATE", "MODERATE_INDEPENDENT"
        reasons.append(f"{n_ind} independent sources (≥{cfg.moderate_min_independent})")
        if n_ind >= cfg.strong_min_independent:
            reasons.append(f"but diversity {diversity:.2f} is below {cfg.strong_min_diversity:g}: most reports are copies")
    elif n_ind == 1 and auth_domains:
        tier, rule = "WEAK", "SINGLE_AUTHORITATIVE"
        reasons.append(f"one independent source, and it is on the authoritative list ({auth_domains[0]})")
    elif n_ind == 1:
        tier, rule = "INSUFFICIENT", "SINGLE_SOURCE"
        reasons.append("one independent source that is not known to be authoritative: nothing corroborates it")
    else:
        tier, rule = "INSUFFICIENT", "NO_REPORTS"
        reasons.append("no report is available at the requested time")
    if disagreement is ConflictState.CONFLICTED and _TIER_ORDER.index(tier) > _TIER_ORDER.index(cfg.conflict_caps_at):
        reasons.append(f"capped at {cfg.conflict_caps_at}: reports contradict each other and the conflict is unresolved")
        tier, rule = cfg.conflict_caps_at, rule + "+CONFLICT_CAP"
    if not trusted:
        reasons.append("timestamps were assigned by the replay, so how far apart the reports are is not known")
    comps = {"reports": n, "independent_sources": n_ind, "unique_domains": len(domains), "source_diversity": diversity,
             "authoritative_sources": len(auth_domains), "syndicated_or_copied": copies, "source_disagreement": disagree}
    return EvidenceProfile(
        availability=Availability.AVAILABLE if n else Availability.UNAVAILABLE, reason=None if n else "no report at or before the requested time",
        source_count=n, independent_sources=n_ind, unique_domains=len(domains), source_diversity=diversity, syndicated_copies=copies,
        authoritative_sources=len(auth_domains), authoritative_supported=bool(auth_domains), authoritative_domains=auth_domains,
        first_observed=min(firsts) if firsts else None, latest_observed=max(firsts) if firsts else None, entity_confidence=entity_conf,
        entity_basis=entity_basis, scope_confidence=scope_tier, model_confidence=mc, source_disagreement=disagree,
        evidence_strength=EvidenceStrength(tier=tier, rule=rule, reasons=reasons, components=comps))
