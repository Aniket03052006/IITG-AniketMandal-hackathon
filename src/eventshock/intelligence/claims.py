"""Structured claims and contradiction between reports of one event.

A *claim* is a clause that asserts one pole of a closed axis (confirmed / denied, open / closed, completed / cancelled, running / shut down,
guidance raised / cut, approved / rejected; ``configs/intelligence.yaml``): subject, predicate (the axis), object, polarity (the pole),
timestamp, source and the verbatim clause it was read from. Extraction is rule-based over that closed lexicon, so it never invents a
claim; it also misses paraphrase, and says so. A cue that is negated in the text ("has not confirmed") asserts nothing and is dropped,
and a hedged or second-hand clause ("reportedly", "according to") is marked ``attributed``.

Two claims conflict only when they sit on the same axis, assert opposite poles, come from different reports and share a topic. Within
``conflict_window_hours`` that is a contradiction; further apart it is a change of state over time, reported separately. Sentiment
variance is never evidence of contradiction.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from ..pipeline.normalize import content_tokens, match_form
from .config import ClaimsCfg
from .grouping import GReport
from .model import Claim, ClaimConflict, ConflictState, EvidenceQuote
from .textutil import cue_pattern, find_cues, sentences, words

_PRONOUN_SUBJECTS = {"it", "its", "this", "that", "they", "he", "she", "the company", "the firm", "the group", "the bank", "the lender"}
_AUX = {"is", "are", "was", "were", "has", "have", "had", "will", "would", "to", "also", "now", "then", "just", "that", "and", "but", "as", "which", "who"}
_BACKGROUND = re.compile(r"\b(?:after|following|since|amid|despite|when|once|before|because|as)\b", re.IGNORECASE)
_CLAUSE_END = re.compile(r"[,;:.!?]|\b(?:and|but|while|as|after|before|amid|despite|though|although)\b", re.IGNORECASE)


@dataclass(frozen=True)
class _Claim:
    claim: Claim
    topic: frozenset[str]
    domain: str
    trusted: bool
    time: datetime
    retraction: bool
    pole: str  # "pos" | "neg"


class ClaimExtractor:
    def __init__(self, cfg: ClaimsCfg, authoritative: Iterable[str] = ()) -> None:
        self.cfg = cfg
        self.authoritative = frozenset(authoritative)
        self._cue_map: dict[str, tuple[str, str]] = {}
        cues: list[str] = []
        for aid, ax in cfg.axes.items():
            for pole, lst in (("pos", ax.pos), ("neg", ax.neg)):
                for c in lst:
                    self._cue_map[match_form(c)] = (aid, pole)
                    cues.append(c)
        self._pat = cue_pattern(cues)
        self._neg = cue_pattern(cfg.negators)
        self._hedge = cue_pattern(cfg.hedges)
        self._retract = cue_pattern(cfg.retraction_cues)

    # ----------------------------------------------------------------------------------------------------------------- extract
    def extract(self, report: GReport, entity_id: str | None, entity_name: str | None) -> list[_Claim]:
        full = report.body is not None
        text = f"{report.headline}\n{report.body}" if full else report.headline
        out: list[_Claim] = []
        for off, sent in sentences(text):
            hedged = bool(find_cues(self._hedge, sent))
            retraction = bool(find_cues(self._retract, sent))
            for hit in find_cues(self._pat, sent):
                aid, pole = self._cue_map[match_form(hit.cue)]
                if self._negated(sent[:hit.start]) or self._background(sent[:hit.start]):
                    continue
                ax = self.cfg.axes[aid]
                subject = self._subject(sent[:hit.start], entity_name)
                obj = self._object(sent[hit.end:])
                cue_tokens = content_tokens(hit.cue)
                topic = frozenset(content_tokens(sent) - cue_tokens)
                if entity_id:
                    topic = topic | {f"ent:{entity_id}"}
                claim = Claim(
                    id=f"{report.id}#{len(out)}", report_id=report.id, signal_id=report.signal_id, source=report.source,
                    published_at=report.published_at, axis=aid, predicate=aid, verb=hit.cue,
                    polarity=ax.pos_label if pole == "pos" else ax.neg_label, subject=subject, object=obj, attributed=hedged,
                    evidence_span=EvidenceQuote(quote=sent, start=off, end=off + len(sent)), full_text=full)
                out.append(_Claim(claim, topic, report.domain, report.trusted, report.published_at, retraction, pole))
        return out

    @staticmethod
    def _background(before: str) -> bool:
        """A cue inside a subordinate clause ("after the plant shut down") recounts a past state; it is not what the report asserts."""
        clause = re.split(r"[,;:.!?]", before)[-1]
        return bool(_BACKGROUND.search(clause))

    def _negated(self, before: str) -> bool:
        tail = " ".join(words(before)[-3:])
        return bool(find_cues(self._neg, tail))

    def _subject(self, before: str, entity_name: str | None) -> str | None:
        ws = words(before)[-self.cfg.max_subject_words:]
        while ws and ws[0].lower() in _AUX:
            ws = ws[1:]
        while ws and ws[-1].lower() in _AUX:
            ws = ws[:-1]
        s = " ".join(ws).strip()
        if not s or s.lower() in _PRONOUN_SUBJECTS:
            return entity_name
        return s

    def _object(self, after: str) -> str | None:
        m = _CLAUSE_END.search(after)
        seg = after[:m.start()] if m else after
        ws = words(seg)[: self.cfg.max_object_words]
        return " ".join(ws) or None

    # ------------------------------------------------------------------------------------------------------------------ detect
    def detect(self, claims: list[_Claim]) -> tuple[list[ClaimConflict], list[ClaimConflict]]:
        """(conflicts, sequential changes) among ``claims`` (any order; the result is deterministic)."""
        cfg = self.cfg
        # a report that itself asserts both poles of an axis is recounting a change of state ("back online after the outage"), not taking a side
        both = {(c.claim.report_id, c.claim.axis) for c in claims if any(
            o.claim.report_id == c.claim.report_id and o.claim.axis == c.claim.axis and o.pole != c.pole for o in claims)}
        ordered = sorted((c for c in claims if (c.claim.report_id, c.claim.axis) not in both), key=lambda c: (c.time, c.claim.id))
        conflicts: list[ClaimConflict] = []
        sequential: list[ClaimConflict] = []
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                if a.claim.axis != b.claim.axis or a.pole == b.pole or a.claim.report_id == b.claim.report_id:
                    continue
                shared = a.topic & b.topic
                if not shared:
                    continue
                ax = cfg.axes[a.claim.axis]
                both_trusted = a.trusted and b.trusted
                gap_h = (b.time - a.time).total_seconds() / 3600 if both_trusted else None
                cid = f"cf:{a.claim.id}|{b.claim.id}"
                topic = sorted(t for t in shared if not t.startswith("ent:"))
                if gap_h is not None and gap_h > cfg.conflict_window_hours:
                    sequential.append(ClaimConflict(
                        id=cid, axis=a.claim.axis, axis_label=ax.label, state=ConflictState.NO_CONFLICT, side_a=a.claim, side_b=b.claim,
                        shared_topic=topic, hours_apart=round(gap_h, 2),
                        reason=(f"'{a.claim.polarity}' ({a.claim.source}) and later '{b.claim.polarity}' ({b.claim.source}) are {gap_h:.0f} h apart: "
                                "a change of state over time, not a contradiction.")))
                    continue
                same_source = a.domain == b.domain or a.claim.source == b.claim.source
                n_shared = len(shared)
                reasons: list[str] = []
                if a.claim.attributed or b.claim.attributed:
                    reasons.append("at least one claim is hedged or second-hand")
                if same_source:
                    reasons.append("both come from the same outlet (it may be a correction, not a disagreement)")
                if not both_trusted:
                    reasons.append("a timestamp is not trusted, so the window cannot be checked")
                if n_shared < cfg.min_conflict_tokens:
                    reasons.append(f"only {n_shared} topic word(s) are shared (needs {cfg.min_conflict_tokens})")
                state = ConflictState.POSSIBLE_CONFLICT if reasons else ConflictState.CONFLICTED
                reason = (f"{a.claim.source} reports '{a.claim.polarity}' and {b.claim.source} reports '{b.claim.polarity}' on the same "
                          f"{ax.label.lower()} claim" + (f" ({'; '.join(reasons)})." if reasons else " (explicit, unhedged, different outlets)."))
                resolver = self._resolver(a, b, ordered)
                if resolver is None and b.domain in self.authoritative and a.domain not in self.authoritative:
                    resolver = (b, "an authoritative source states it after a non-authoritative one")
                if resolver is not None:
                    c, why = resolver
                    pole_label = ax.pos_label if c.pole == "pos" else ax.neg_label
                    conflicts.append(ClaimConflict(
                        id=cid, axis=a.claim.axis, axis_label=ax.label, state=ConflictState.RESOLVED_CONFLICT, side_a=a.claim, side_b=b.claim,
                        shared_topic=topic, hours_apart=None if gap_h is None else round(gap_h, 2), reason=reason,
                        resolved_by=c.claim, resolution=f"Later report from {c.claim.source} settles it as '{pole_label}': {why}."))
                    continue
                conflicts.append(ClaimConflict(
                    id=cid, axis=a.claim.axis, axis_label=ax.label, state=state, side_a=a.claim, side_b=b.claim, shared_topic=topic,
                    hours_apart=None if gap_h is None else round(gap_h, 2), reason=reason))
        return conflicts[:12], sequential[:12]

    def _resolver(self, a: _Claim, b: _Claim, ordered: list[_Claim]) -> tuple[_Claim, str] | None:
        """A later claim on the same axis and topic that settles the pair: an authoritative source, the same source reversing itself, or an
        explicit retraction. A later claim from a third, non-authoritative outlet does not (counting outlets is not establishing truth)."""
        last = max(a.time, b.time)
        topic = a.topic | b.topic
        for c in ordered:
            if c.time <= last or c.claim.axis != a.claim.axis or not (c.topic & topic):
                continue
            if c.domain in self.authoritative:
                return c, "an authoritative source"
            for side in (a, b):
                if (c.domain == side.domain or c.claim.source == side.claim.source) and c.pole != side.pole:
                    return c, f"{side.claim.source} reversed its own earlier claim"
            if c.retraction:
                return c, "the report states a correction or retraction"
        return None


def overall_state(conflicts: list[ClaimConflict]) -> ConflictState:
    states = {c.state for c in conflicts}
    if ConflictState.CONFLICTED in states:
        return ConflictState.CONFLICTED
    if ConflictState.POSSIBLE_CONFLICT in states:
        return ConflictState.POSSIBLE_CONFLICT
    if ConflictState.RESOLVED_CONFLICT in states:
        return ConflictState.RESOLVED_CONFLICT
    return ConflictState.NO_CONFLICT
