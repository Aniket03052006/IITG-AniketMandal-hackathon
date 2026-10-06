"""Event-to-market matching. NOT keyword overlap: an event reaches a market only through a curated theme, and every gate is explicit, recorded and shown.

Event-side gates (all must pass for a theme to apply):
  EVENT_CLASS  the event's assessed class is one the theme concerns;
  SCOPE        the event's resolved scope is one the theme concerns (an UNRESOLVED event is never matched);
  SUBJECT      the event carries evidence of the theme's subject: a resolved scope theme, or closed-vocabulary phrases in its own text (STRONG with a scope theme or two distinct phrases, WEAK with one);
  GEOGRAPHY    a US theme is not applied to an event about another place (no stated place passes, and says so).
Market-side gates (per candidate): OPEN (not closed or settled at the moment), HORIZON (resolves after the moment and within the configured horizon), FRESH (observed recently enough).
MATCHED needs a STRONG subject; a WEAK one is LOW_CONFIDENCE_MATCH. Nothing here compares an event's words with a market's title.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..intelligence.textutil import cue_pattern, find_cues
from .config import MarketsConfig, ThemeCfg
from .models import Candidate, ExternalMarketObservation, Gate, MarketMatch, MarketStatus, MatchStatus


@dataclass
class EventFeatures:
    event_class: str | None
    scope_type: str
    scope_themes: set[str]
    regions: set[str]
    text: str


@dataclass
class ThemeHit:
    theme: ThemeCfg
    gates: list[Gate]
    evidence: list[str] = field(default_factory=list)
    strong: bool = False

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)


def _gate(gid: str, label: str, ok: bool, detail: str) -> Gate:
    return Gate(id=gid, label=label, passed=ok, detail=detail)


def evaluate_theme(theme: ThemeCfg, f: EventFeatures) -> ThemeHit:
    w = theme.when
    gates = [
        _gate("EVENT_CLASS", "Event class", f.event_class in w.event_classes, f"the event is read as {f.event_class or 'no market event'}; this theme concerns {', '.join(w.event_classes)}"),
        _gate("SCOPE", "Resolved scope", f.scope_type in w.scope_types and f.scope_type != "UNRESOLVED", f"the event's scope is {f.scope_type.lower()}; this theme concerns {', '.join(s.lower() for s in w.scope_types)}"),
    ]
    themes = sorted(set(w.themes_any) & f.scope_themes)
    pat = cue_pattern(w.terms_any) if w.terms_any else None
    terms = sorted({h.cue.lower() for h in find_cues(pat, f.text)}) if pat is not None else []
    evidence = [f"scope theme: {t.replace('_', ' ')}" for t in themes] + [f'phrase in the text: "{t}"' for t in terms]
    strong = bool(themes) or len(terms) >= 2
    gates.append(_gate("SUBJECT", "Evidence of the subject", bool(evidence), "; ".join(evidence) if evidence else f"no scope theme ({', '.join(w.themes_any) or 'none'}) and none of the theme's phrases appear in the text"))
    if w.regions_any:
        if f.regions:
            ok = bool(f.regions & set(w.regions_any))
            gates.append(_gate("GEOGRAPHY", "Place", ok, f"the event concerns {', '.join(sorted(f.regions))}; this theme concerns {', '.join(w.regions_any)}"))
        else:
            gates.append(_gate("GEOGRAPHY", "Place", True, f"no place is stated; the theme concerns {', '.join(w.regions_any)} (not a conflict)"))
    return ThemeHit(theme=theme, gates=gates, evidence=evidence, strong=strong)


def market_gates(o: ExternalMarketObservation, now: datetime, cfg: MarketsConfig) -> list[Gate]:
    m = cfg.matching
    gates = [_gate("OPEN", "Market open", o.market_status is MarketStatus.OPEN, f"status {o.raw_status or o.market_status.value.lower()}")]
    if o.close_time is None:
        gates.append(_gate("HORIZON", "Horizon", True, "no close time reported"))
    else:
        days = (o.close_time - now).total_seconds() / 86400.0
        gates.append(_gate("HORIZON", "Horizon", 0 < days <= m.horizon_max_days, f"resolves in {days:.0f} days (limit {m.horizon_max_days:.0f})"))
    age = (now - o.observed_at).total_seconds() / 86400.0
    gates.append(_gate("FRESH", "Observation fresh", 0 <= age <= m.staleness_days, f"observed {age:.1f} days before this moment (limit {m.staleness_days:g})"))
    return gates


def best_market(cands: list[tuple[ExternalMarketObservation, list[Gate]]]) -> int | None:
    ok = [i for i, (_, g) in enumerate(cands) if all(x.passed for x in g)]
    if not ok:
        return None
    return min(ok, key=lambda i: (-(cands[i][0].open_interest or 0.0), -(cands[i][0].volume or 0.0), cands[i][0].close_time or datetime.max.replace(tzinfo=cands[i][0].observed_at.tzinfo), cands[i][0].market_id))


def build_match(hit: ThemeHit | None, near: ThemeHit | None, cands: list[tuple[ExternalMarketObservation, list[Gate]]], chosen: int | None, cfg: MarketsConfig, *, empty_reason: str | None = None) -> MarketMatch:
    top = cfg.matching.top_candidates
    if hit is None:
        why = "no curated theme applies: " + (f"the closest, {near.theme.label}, fails " + ", ".join(g.label.lower() for g in near.gates if not g.passed) if near else "none was considered")
        return MarketMatch(status=MatchStatus.NO_MATCH, reason=why, theme_id=near.theme.id if near else None, theme_label=near.theme.label if near else None,
                           event_gates=near.gates if near else [], market=None, candidates=[], evidence=near.evidence if near else [])
    cl = [Candidate(market_id=o.market_id, question=o.question, series_id=o.series_id, probability=o.probability, open_interest=o.open_interest, volume=o.volume, close_time=o.close_time,
                    gates=g, chosen=i == chosen) for i, (o, g) in enumerate(cands)]
    cl = sorted(cl, key=lambda c: (not c.chosen, -(c.open_interest or 0.0), c.market_id))[:top]
    if chosen is None:
        why = empty_reason or (f"the theme {hit.theme.label} applies, but none of its {len(cands)} candidate market(s) is open, near enough and fresh at this moment" if cands
                               else f"the theme {hit.theme.label} applies, but no market of its series is available at this moment")
        return MarketMatch(status=MatchStatus.NO_MATCH, reason=why, theme_id=hit.theme.id, theme_label=hit.theme.label, event_gates=hit.gates, market=None, candidates=cl, evidence=hit.evidence)
    o = cands[chosen][0]
    status = MatchStatus.MATCHED if hit.strong else MatchStatus.LOW_CONFIDENCE_MATCH
    why = (f"{hit.theme.label}: the event's class, resolved scope and {'scope theme' if any('scope theme' in e for e in hit.evidence) else 'phrases in its text'} all fit; the market is open, resolves "
           f"{'soon enough' if o.close_time else 'at an unreported date'} and was observed recently. " + ("" if hit.strong else "The subject evidence is a single phrase, so the match is low confidence."))
    return MarketMatch(status=status, reason=why.strip(), theme_id=hit.theme.id, theme_label=hit.theme.label, event_gates=hit.gates, market=o, candidates=cl, evidence=hit.evidence)


def orientation_of(theme: ThemeCfg, question: str) -> tuple[str, str]:
    """(UP | DOWN | NEUTRAL, how it was read): which way a higher probability moves the world relative to risk."""
    o = theme.orientation
    if o.mode in ("UP", "DOWN"):
        return o.mode, f"configured for the theme ({theme.label})"
    if o.mode == "NEUTRAL":
        return "NEUTRAL", "no direction is claimed for this theme's markets"
    q = question.lower()
    up = [c for c in o.up if cue_pattern([c]).search(q)] if o.up else []
    down = [c for c in o.down if cue_pattern([c]).search(q)] if o.down else []
    if up and not down:
        return "UP", f'read from the question ("{up[0]}")'
    if down and not up:
        return "DOWN", f'read from the question ("{down[0]}")'
    return "NEUTRAL", "the question does not state a direction, or states both"

