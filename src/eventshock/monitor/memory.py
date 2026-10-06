"""Event memory: an event is an evolving narrative, not a pile of articles.

Every report that reaches an event is classified against the reports before it, by explicit rules and never by a model:

* the first report of the event is NEW_EVENT;
* a report that the lifecycle engine cited when it moved the event (an escalation, an easing, a resolution cue) is ESCALATION / DE_ESCALATION / RESOLUTION, and the
  classification names the lifecycle rule and the quoted cue;
* a copy of an earlier report (syndicated, near duplicate) is CONTINUATION: it never creates a risk of its own;
* a report that carries numbers or names the earlier reports lacked is an UPDATE;
* anything else is a CONTINUATION.

Because it works on the already-grouped reports, a new article about an existing event can only ever be an update of that event.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..decision.config import MemoryCfg
from ..intelligence.grouping import GReport
from ..intelligence.model import LifecycleTransition
from ..intelligence.textutil import key_facts
from .models import UpdateKind


@dataclass(frozen=True)
class Classified:
    report: GReport
    kind: UpdateKind
    rule: str
    detail: str


def classify_reports(reports: Iterable[GReport], transitions: list[LifecycleTransition], cfg: MemoryCfg, copy_relations: set[str] | frozenset[str]) -> list[Classified]:
    """Classify every report, oldest first. ``reports`` must be cut at the moment of interest; the result for a report never depends on later ones."""
    out: list[Classified] = []
    cited: dict[str, LifecycleTransition] = {}
    for t in transitions:
        for rid in t.evidence_report_ids:
            cited.setdefault(rid, t)
    seen_facts: set[str] = set()
    for i, r in enumerate(sorted(reports, key=lambda r: (r.published_at, r.id))):
        facts = key_facts(f"{r.headline}. {r.body or ''}")
        fresh = sorted(f for f in facts if f not in seen_facts)
        t = cited.get(r.id)
        if i == 0:
            kind, rule, detail = UpdateKind.NEW_EVENT, "FIRST_REPORT", "The first report of the event."
        elif t is not None and t.rule in cfg.resolution_rules:
            kind, rule, detail = UpdateKind.RESOLUTION, f"LIFECYCLE:{t.rule}", t.rule_text + (f' Cue: "{t.evidence_quote}".' if t.evidence_quote else "")
        elif t is not None and t.rule in cfg.escalation_rules:
            kind, rule, detail = UpdateKind.ESCALATION, f"LIFECYCLE:{t.rule}", t.rule_text + (f' Cue: "{t.evidence_quote}".' if t.evidence_quote else "")
        elif t is not None and t.rule in cfg.de_escalation_rules:
            kind, rule, detail = UpdateKind.DE_ESCALATION, f"LIFECYCLE:{t.rule}", t.rule_text + (f' Cue: "{t.evidence_quote}".' if t.evidence_quote else "")
        elif r.relation in copy_relations:
            kind, rule, detail = UpdateKind.CONTINUATION, f"COPY:{r.relation}", f"A {r.relation.lower().replace('_', ' ')} of an earlier report: it adds no coverage of its own."
        elif len(fresh) >= cfg.update_min_new_facts:
            kind, rule, detail = UpdateKind.UPDATE, f"NEW_FACTS:{len(fresh)}", "Adds details the earlier reports did not carry: " + ", ".join(fresh[:5]) + "."
        else:
            kind, rule, detail = UpdateKind.CONTINUATION, "SAME_COVERAGE", "More coverage of what the earlier reports already said."
        seen_facts |= facts
        out.append(Classified(r, kind, rule, detail))
    return out
