"""Novelty class: is this event NEW, a CONTINUATION or UPDATE of an earlier one, or a RECURRING one?

Compares the event with *earlier events of the same subject* (the same issuer, else the same vocabulary scope) inside a look-back window.
It is a classification by explicit rules over similarity, event class, key facts and elapsed time, not a model. The pipeline's own
``novelty_score`` (a smooth count-based number the impact model was trained on) is reported unchanged beside it; the label never feeds
back into it, and neither feeds the severity score here.

Rules, first match wins:

1. an untrusted clock, or no subject to compare within, gives UNKNOWN (an abstention);
2. no earlier event of the subject in the look-back gives NEW;
3. the nearest earlier event is not the same narrative (a different class, or wording too different) gives NEW;
4. the same narrative, and the earlier event was RESOLVED / STALE or went quiet for ``recurrence_gap_hours`` or this text says "another",
   "again", "fresh"... gives RECURRING;
5. the same narrative with numbers or names the earlier event did not carry (or an update cue) gives UPDATE;
6. otherwise CONTINUATION (same narrative, nothing new).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ..domain import RiskSignal
from .config import NoveltyCfg
from .grouping import Event, EventIndex, scope_key_of
from .model import Availability, NoveltyAssessment, PriorEvent
from .textutil import cue_pattern, find_cues


class NoveltyClassifier:
    def __init__(self, cfg: NoveltyCfg) -> None:
        self.cfg = cfg
        self._rec = cue_pattern(cfg.recurrence_cues)
        self._upd = cue_pattern(cfg.update_cues)

    def classify(self, signal: RiskSignal, event: Event, index: EventIndex, first_seen: datetime, *, trusted: bool,
                 state_of_prior: Callable[[Event, datetime], str | None]) -> NoveltyAssessment:
        cfg = self.cfg
        ev = signal.evidence
        base = dict(novelty_score=ev.novelty_score, novelty_measured=ev.novelty_measured)

        def out(label: str, rule: str, *, avail: Availability = Availability.AVAILABLE, reason: str | None = None, priors=None, match=None,
                new=None, cont=None, rec=None) -> NoveltyAssessment:
            return NoveltyAssessment(availability=avail, reason=reason, label=label, rule=rule, nearest_prior=priors or [], narrative_match=match,
                                     new_information=new or [], continuation_indicators=cont or [], recurrence_cues=rec or [], **base)

        if not trusted:
            return out("UNKNOWN", "UNTRUSTED_CLOCK", avail=Availability.UNAVAILABLE,
                       reason="The report times were assigned by the replay, so earlier and later cannot be told apart.")
        key = scope_key_of(event.anchor)
        if key is None:
            return out("UNKNOWN", "NO_SUBJECT", avail=Availability.ABSTAINED,
                       reason="No company, sector, theme or region could be identified, so there is no earlier event to compare this with.")
        priors = index.priors(event, key, first_seen, cfg.lookback_days * 24)
        if not priors:
            return out("NEW", "NO_PRIOR", reason=None,
                       cont=[f"no earlier event of this subject in the {cfg.lookback_days:g}-day look-back (within the data held)"])

        cur_bag = frozenset().union(*(n.bag for n in event.nodes))
        cur_facts = frozenset().union(*(n.facts for n in event.nodes))
        text = f"{event.anchor.signal.document.headline}. {event.anchor.signal.document.body}"
        scored = []
        for p in priors:
            bag = frozenset().union(*(n.bag for n in p.nodes))
            scored.append((index.idf.cosine(cur_bag, bag), p))
        scored.sort(key=lambda sp: (-sp[0], sp[1].id))
        shown = []
        for sim, p in scored[: cfg.max_priors_shown]:
            last = max(r.published_at for r in p.reports())
            same_class = p.anchor.classified == event.anchor.classified
            shown.append(PriorEvent(event_id=p.id, signal_id=p.anchor.signal.id, headline=p.anchor.signal.document.headline,
                                    first_seen=min(n.time for n in p.nodes), last_seen=last, similarity=round(sim, 4),
                                    same_event_class=same_class, lifecycle_then=state_of_prior(p, first_seen)))
        sim, best = scored[0]
        same_class = best.anchor.classified == event.anchor.classified
        narrative = sim >= cfg.same_story_min_cosine and same_class
        if not narrative:
            why = ("a different event class" if not same_class else f"wording too different (cosine {sim:.2f} < {cfg.same_story_min_cosine:g})")
            return out("NEW", "DIFFERENT_NARRATIVE", priors=shown, match=False,
                       cont=[f"the nearest earlier event of this subject is not the same narrative: {why}"])
        prior_facts = frozenset().union(*(n.facts for n in best.nodes))
        new_facts = sorted(cur_facts - prior_facts)[:8]
        rec_cues = sorted({h.cue.lower() for h in find_cues(self._rec, text)})
        upd_cues = sorted({h.cue.lower() for h in find_cues(self._upd, text)})
        last = max(r.published_at for r in best.reports())
        gap_h = (first_seen - last).total_seconds() / 3600
        then = shown[0].lifecycle_then if shown and shown[0].event_id == best.id else state_of_prior(best, first_seen)
        indicators = [f"same event class ({event.anchor.classified or 'unclassified'})", f"similar wording (cosine {sim:.2f})",
                      f"the earlier event's last report was {gap_h:.0f} h before this one"]
        if then:
            indicators.append(f"the earlier event was {then} when this one began")
        if then in ("RESOLVED", "STALE") or gap_h >= cfg.recurrence_gap_hours or rec_cues:
            why = ("it was " + then.lower()) if then in ("RESOLVED", "STALE") else (f"it had been quiet {gap_h:.0f} h" if gap_h >= cfg.recurrence_gap_hours
                                                                                    else f"the text says {', '.join(rec_cues)}")
            return out("RECURRING", "RECURRENCE", priors=shown, match=True, new=new_facts, cont=indicators + [f"treated as a recurrence because {why}"], rec=rec_cues)
        if len(new_facts) >= cfg.min_new_facts or upd_cues:
            return out("UPDATE", "NEW_FACTS", priors=shown, match=True, new=new_facts, cont=indicators + ([f"update wording: {', '.join(upd_cues)}"] if upd_cues else []))
        return out("CONTINUATION", "NO_NEW_FACTS", priors=shown, match=True, new=[], cont=indicators + ["no numbers or names beyond the earlier event's"])
