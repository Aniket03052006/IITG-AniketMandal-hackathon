"""The severity rubric: four anchored ordinal answers about an event, derived deterministically and then (optionally) adjusted by the AI within a bound.

magnitude (0-4) · reach (firm / sector / market / global) · certainty (confirmed / proposed / speculative) · direction (adverse / mixed / neutral / favourable)

``RubricDeriver.baseline`` answers all four from the text with rules only (cue phrases, indicator levels, a monetary amount, the sector vocabulary): crude but
reproducible and available with no model. ``apply_ai`` then lets a language model's answer replace a baseline answer under an explicit bound:

* an answer needs a stated reason, or it is ignored;
* it may move at most ``free_steps`` (one) step from the baseline;
* one exception, for a baseline the rules had NO evidence for (only a default: an unknown phrasing is not a reason to cap the AI): there a verbatim quote lets its answer stand.
  (Letting a quote lift the bound where the rules *do* have evidence scored worse on the recorded answers, so that is not allowed: docs/evidence/severity_ai_bound_ablation.json.)

So the AI's contribution is structured (four ordinal answers, each with a reason), bounded, inspectable (baseline, proposal and outcome are all shown) and reproducible
(the answers are cached; the rest is arithmetic). It never produces the score.
"""

from __future__ import annotations

import re

from ..pipeline.scope import ScopeResolver
from .config import CERTAINTY_ORDER, DIRECTION_ORDER, REACH_ORDER, SeverityConfig
from .cues import find_cue
from .model import AIRubric, Origin, RubricField, RubricProposal, SemanticReading
from .vocab import NO_EVENT, Vocab

_AMOUNT = re.compile(r"[$€£]\s?(\d+(?:[.,]\d+)?)\s?(trillion|billion|million|tn|bn|mn|m|b)\b", re.IGNORECASE)
_UNIT = {"trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6}
_NAMES = {"magnitude": "Event intensity", "reach": "Reach", "certainty": "Certainty", "direction": "Direction"}
ORDERS: dict[str, tuple[str, ...]] = {
    "magnitude": ("0", "1", "2", "3", "4"), "reach": REACH_ORDER, "certainty": CERTAINTY_ORDER, "direction": DIRECTION_ORDER,
}


def largest_amount_usd(text: str) -> float | None:
    """The largest "$N million|billion|trillion" figure in the text (currencies are treated alike: it is a scale proxy, not a conversion)."""
    best = None
    for m in _AMOUNT.finditer(text):
        try:
            v = float(m.group(1).replace(",", ".")) * _UNIT[m.group(2).lower()]
        except (ValueError, KeyError):
            continue
        best = v if best is None or v > best else best
    return best


def _has(text: str, cue: str) -> bool:
    if cue == "may":  # "May" is a month: only the lower-case modal counts
        return re.search(r"(?<![A-Za-z])may(?![A-Za-z])", text) is not None
    return find_cue(text, cue) is not None


class RubricDeriver:
    def __init__(self, vocab: Vocab, scope: ScopeResolver, cfg: SeverityConfig) -> None:
        self.v, self._scope, self.cfg = vocab, scope, cfg
        self._firm = re.compile(vocab.cfg.reach.generic_firm_pattern, re.IGNORECASE)

    # ------------------------------------------------------------------------------------------------------------- labels
    def label(self, field: str, value: str) -> str:
        c = self.cfg
        if field == "magnitude":
            return c.magnitude[int(value)].label
        return {"reach": c.reach, "certainty": c.certainty, "direction": c.direction}[field][value].label  # type: ignore[index]

    def says(self, field: str, value: str) -> str:
        c = self.cfg
        if field == "magnitude":
            return c.magnitude[int(value)].says
        return {"reach": c.reach, "certainty": c.certainty, "direction": c.direction}[field][value].says  # type: ignore[index]

    # ------------------------------------------------------------------------------------------------------------ baseline
    def baseline(self, text: str, rules: SemanticReading) -> dict[str, tuple[str, list[str], bool]]:
        """field -> (level id, the deterministic reasons, informed). ``rules`` is the rule extractor's reading of ``text``. ``informed`` is False when the rules found no evidence
        for the answer and it is only a default."""
        mag = self._magnitude(text, rules)
        return {"magnitude": mag, "reach": self._reach(text, rules, int(mag[0])), "certainty": self._certainty(text), "direction": self._direction(rules)}

    def _magnitude(self, text: str, r: SemanticReading) -> tuple[str, list[str], bool]:
        b, why = self.cfg.baseline, []
        level = 0
        hits = [h for h in r.severity_indicators]
        if hits:
            top = max(hits, key=lambda h: h.level)
            level = top.level
            why.append(f"strongest indicator: {top.label.lower()} (typical level {top.level})")
        elif r.event_type != NO_EVENT:
            level = b.event_without_indicator_level
            why.append(f"a market event with no severity marker: at least level {level}")
        amount = largest_amount_usd(text)
        if amount is not None:
            for floor in sorted(self.v.cfg.amount_floor, key=lambda f: f.min_usd):
                if amount >= floor.min_usd and level < floor.level:
                    level = floor.level
                    why.append(f"an amount of about ${amount:,.0f} sets a floor of level {floor.level}")
        serious = {h.id for h in hits if h.level >= b.compounding.min_level}
        if len(serious) >= b.compounding.min_indicators:
            level += b.compounding.steps
            why.append(f"{len(serious)} distinct serious indicators together: +{b.compounding.steps}")
        ups = [c for c in self.v.cfg.scale_up if _has(text, c)]
        downs = [c for c in self.v.cfg.scale_down if _has(text, c)]
        if ups and not downs:
            level += b.scale_step
            why.append(f"escalating wording ({', '.join(ups[:3])}): +{b.scale_step}")
        elif downs and not ups:
            level -= b.scale_step
            why.append(f"de-escalating wording ({', '.join(downs[:3])}): -{b.scale_step}")
        return str(min(4, max(0, level))), why or ["no event or severity marker found"], bool(hits or amount is not None or ups or downs)

    def _reach(self, text: str, r: SemanticReading, magnitude: int) -> tuple[str, list[str], bool]:
        rc = self.v.cfg.reach
        glob = [c for c in rc.global_cues if _has(text, c)]
        if glob or len(r.regions) >= 3:
            return "global", [f"global wording ({', '.join(glob[:3])})" if glob else f"{len(r.regions)} regions named"], True
        market = [c for c in rc.market_cues if _has(text, c)]
        inst = [e.name for e in r.entities if e.kind == "INSTITUTION"]
        if market or inst:
            return "market", [f"market-wide wording ({', '.join((market + inst)[:3])})"], True
        if magnitude >= 4:  # a systemic event is not confined to one issuer or one sector: that is what systemic means
            return "market", ["a systemic-magnitude event reaches at least a whole market"], True
        if r.primary_issuer.resolved or any(e.kind == "COMPANY" and e.role == "subject" for e in r.entities):
            return "firm", ["a named company is the subject"], True
        terms = {t for ts in self._scope.sector_hits(text).values() for t in ts}
        plural = sorted(t for t in terms if t.endswith("s"))
        if plural and not self._firm.match(text.strip()):
            return "sector", [f"sector-wide terms ({', '.join(plural[:3])})"], True
        if self._firm.match(text.strip()):
            return "firm", ["one unnamed company is described"], True
        return "firm", ["nothing broader can be established, so one issuer is assumed (conservative)"], False

    def _certainty(self, text: str) -> tuple[str, list[str], bool]:
        cv = self.v.cfg.certainty
        spec = [c for c in cv.speculative_cues if _has(text, c)]
        if spec:
            return "speculative", [f"hedged or unconfirmed wording ({', '.join(spec[:3])})"], True
        prop = [c for c in cv.proposed_cues if _has(text, c)]
        if prop:
            return "proposed", [f"proposal or plan wording ({', '.join(prop[:3])})"], True
        return "confirmed", ["stated as having happened or been decided (no hedge or proposal wording found)"], False

    @staticmethod
    def _direction(r: SemanticReading) -> tuple[str, list[str], bool]:
        adv = [h for h in r.severity_indicators if h.polarity == "adverse"]
        fav = [h for h in r.severity_indicators if h.polarity == "favourable"]
        if adv and fav:
            return "mixed", ["both adverse and favourable indicators"], True
        if adv:
            return "adverse", [f"adverse indicators ({', '.join(h.label.lower() for h in adv[:2])})"], True
        if fav:
            return "favourable", [f"favourable indicators ({', '.join(h.label.lower() for h in fav[:2])})"], True
        if r.sentiment <= -0.15:
            return "adverse", [f"no indicator; the tone reading is negative ({r.sentiment:+.2f})"], True
        if r.sentiment >= 0.15:
            return "favourable", [f"no indicator; the tone reading is positive ({r.sentiment:+.2f})"], True
        return "neutral", ["no directional indicator and a neutral tone reading"], False

    # ----------------------------------------------------------------------------------------------------- AI adjustment
    def combine(self, text: str, rules: SemanticReading, ai: AIRubric | None) -> list[RubricField]:
        base = self.baseline(text, rules)
        out = []
        for fid in ("magnitude", "reach", "certainty", "direction"):
            proposal = getattr(ai, fid) if ai is not None else None
            out.append(self.apply_ai(fid, base[fid], proposal))
        return out

    def apply_ai(self, fid: str, base: tuple, proposal: RubricProposal | None) -> RubricField:
        order, rule = ORDERS[fid], self.cfg.ai_adjustment
        bval, bwhy = base[0], base[1]
        informed = base[2] if len(base) > 2 else True
        final, adj, note = bval, "NONE", ""
        ai_val = proposal.value if proposal is not None and proposal.value in order else None
        if proposal is not None and ai_val is not None:
            if rule.require_reason and len((proposal.reason or "").strip()) < rule.min_reason_chars:
                adj, note = "AI_IGNORED", "The AI gave no reason for this answer, so it was ignored."
            else:
                dist = order.index(ai_val) - order.index(bval)
                if dist == 0:
                    adj, note = "NONE", "The AI agrees with the rules."
                elif abs(dist) <= rule.free_steps:
                    final, adj = ai_val, "AI_WITHIN_BOUND"
                    note = f"The AI moved this {abs(dist)} step{'s' if abs(dist) > 1 else ''} {'up' if dist > 0 else 'down'} from the rules, with a stated reason."
                elif (not informed and rule.uninformed_baseline_accepts_quoted_answer) and proposal.quote and proposal.quote_verified:
                    final, adj = ai_val, "AI_QUOTE_BACKED"
                    note = (f"The rules found no evidence for this answer (their baseline is only a default), and the AI is {abs(dist)} steps away but quotes the report verbatim, "
                            "so its answer stands.")
                else:
                    step = rule.free_steps if dist > 0 else -rule.free_steps
                    final, adj = order[order.index(bval) + step], "AI_CLAMPED"
                    note = f"The AI is {abs(dist)} steps from the rules; it may move an answer at most {rule.free_steps} step, so it is held there."
        elif proposal is not None:
            adj, note = "AI_IGNORED", f"The AI's answer {proposal.value!r} is not one of the allowed levels, so it was ignored."
        return RubricField(
            id=fid, label=_NAMES[fid], baseline=bval, baseline_label=self.label(fid, bval), baseline_basis=bwhy, baseline_informed=informed,
            ai=ai_val, ai_label=self.label(fid, ai_val) if ai_val else None, ai_reason=proposal.reason if proposal else None,
            ai_quote=proposal.quote if proposal and proposal.quote_verified else None, final=final, final_label=self.label(fid, final),
            final_says=self.says(fid, final), origin=Origin.HYBRID if proposal is not None else Origin.RULES, adjustment=adj, note=note)
