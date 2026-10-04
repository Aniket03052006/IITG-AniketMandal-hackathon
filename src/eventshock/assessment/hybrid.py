"""The transparent severity score: explicit factors, explicit weights, no fitted parameters.

``points = 1 + 9 * sum_i(w_i' * f_i) * (1 - discount * uncertainty)`` on [1, 10], where each factor ``f_i`` is on [0, 1] and ``w_i'`` is the configured weight
renormalised over the factors that are actually available. A factor that cannot be computed from event-time information is *omitted and listed*,
never guessed. The score is a triage of how serious this kind of development usually is, not a forecast: see ``configs/impact_hybrid.yaml``.

Pure and deterministic. It reads the extraction, the report's own metadata and the market state recorded at event time; later coverage, later
filings and realised moves are not inputs (``tests/unit/test_assessment_temporal.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..domain import EventCategory
from .config import HybridConfig
from .model import Kind, OmittedFactor, RiskDriver, SemanticReading, SeverityAssessment, SeverityFactor
from .vocab import NO_EVENT

FACTOR_ORDER = ["category_prior", "severity_indicators", "tone", "novelty", "breadth", "source_credibility", "market_regime"]
LABELS = {
    "category_prior": "Event class",
    "severity_indicators": "Severity indicators in the text",
    "tone": "Tone",
    "novelty": "Novelty",
    "breadth": "Breadth of reach",
    "source_credibility": "Source credibility",
    "market_regime": "Market regime",
}
KINDS = {
    "category_prior": Kind.JUDGEMENT_PRIOR, "severity_indicators": Kind.EXTRACTION, "tone": Kind.EXTRACTION, "novelty": Kind.SOURCE,
    "breadth": Kind.EXTRACTION, "source_credibility": Kind.SOURCE, "market_regime": Kind.MARKET_STATE,
}
_MARKET_CATEGORIES = {EventCategory.MACROECONOMIC.value, EventCategory.GEOPOLITICAL.value}


@dataclass(frozen=True)
class HybridInputs:
    reading: SemanticReading
    source_type: str  # NEWS | SOCIAL
    novelty: float | None  # None when no issuer was resolved to compare against earlier reports
    corroborating_at_event_time: int  # independent reports published at or before this one
    vix_level: float | None  # the market state recorded at event time, when there was one
    market_as_of: str | None = None  # the session that state is from (ISO date)
    market_age_days: int | None = None  # calendar days between that session and the report


def assessed_scope(r: SemanticReading) -> str | None:
    """COMPANY | SECTOR | MARKET from the extraction, or None when nothing says what the event is about."""
    if r.primary_issuer.resolved or any(e.role == "subject" and e.kind == "COMPANY" for e in r.entities):
        return "COMPANY"
    if r.sectors:
        return "SECTOR"
    if r.event_type in _MARKET_CATEGORIES or r.regions:
        return "MARKET"
    return None


def _interp(points: list[tuple[float, float]], x: float) -> float:
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


class HybridScorer:
    def __init__(self, cfg: HybridConfig) -> None:
        self.cfg = cfg
        self.version = cfg.version

    # ------------------------------------------------------------------------------------------------------------------ factors
    def _factors(self, i: HybridInputs) -> dict[str, tuple[float | None, str]]:
        """factor id -> (value on [0, 1] or None when unavailable, the computed value in words / the reason it is missing)."""
        c, r = self.cfg, i.reading
        out: dict[str, tuple[float | None, str]] = {}
        prior = c.category_prior[EventCategory(r.event_type)]
        out["category_prior"] = (prior, f"{r.event_label}: configured prior {prior:.2f}")

        keep = 1.0
        for h in r.severity_indicators:
            keep *= 1.0 - h.weight
        ind = 1.0 - keep
        names = ", ".join(f"{h.label.lower()} ({h.weight:.2f})" for h in r.severity_indicators)
        out["severity_indicators"] = (ind, f"{len(r.severity_indicators)} found: {names} -> {ind:.2f}" if names else "none found in the text -> 0.00")

        adverse, favourable = max(-r.sentiment, 0.0), max(r.sentiment, 0.0) * c.tone.favourable_weight
        conf = r.sentiment_confidence if r.sentiment_confidence is not None else 1.0
        tone = min(1.0, (adverse + favourable) * conf)
        out["tone"] = (tone, f"tone {r.sentiment:+.2f} ({r.sentiment_label}) x confidence {conf:.2f} -> {tone:.2f}")

        out["novelty"] = ((i.novelty, f"{i.novelty:.2f} against earlier reports of the same issuer") if i.novelty is not None
                          else (None, "no issuer was resolved, so there is nothing to compare against"))

        level = assessed_scope(r)
        if level is None:
            out["breadth"] = (None, "the text does not say what the event is about")
        else:
            b = c.breadth
            extra = sum(max(0, n - b.items_free) for n in (len(r.sectors), len(r.regions), len(r.asset_classes)))
            val = min(1.0, b.scope_base[level] + b.per_extra_item * extra)
            out["breadth"] = (val, f"{level.lower()} level ({b.scope_base[level]:.2f}) + {extra} extra item(s) -> {val:.2f}")

        sc = c.source_credibility
        corro = min(1.0, i.corroborating_at_event_time / sc.corroboration_cap)
        cred = sc.type_share * sc.type_prior[i.source_type] + (1 - sc.type_share) * corro
        out["source_credibility"] = (cred, f"{i.source_type.lower()} source ({sc.type_prior[i.source_type]:.2f}), "
                                           f"{i.corroborating_at_event_time} independent report(s) at the time -> {cred:.2f}")

        if i.vix_level is None:
            out["market_regime"] = (None, "no market data at the report's time (the pipeline recorded none)")
        elif i.market_age_days is not None and i.market_age_days > c.market_regime.max_staleness_days:
            out["market_regime"] = (None, f"the market data held ends {i.market_as_of}, {i.market_age_days} days before this report "
                                          f"(limit {c.market_regime.max_staleness_days}): not the market at the time")
        else:
            val = _interp(c.market_regime.vix_points, i.vix_level)
            when = f" as of {i.market_as_of}" + (f" ({i.market_age_days} day(s) before the report)" if i.market_age_days else "") if i.market_as_of else ""
            out["market_regime"] = (val, f"VIX {i.vix_level:.1f}{when} -> {val:.2f}")
        return out

    # --------------------------------------------------------------------------------------------------------------------- score
    def _points(self, factors: dict[str, tuple[float | None, str]], weights: dict[str, float], unc: float) -> tuple[float, dict[str, float], float]:
        avail = {k: w for k, w in weights.items() if factors[k][0] is not None and w > 0}
        total = sum(avail.values())
        norm = {k: (w / total if total else 0.0) for k, w in avail.items()}
        raw = sum(norm[k] * factors[k][0] for k in norm)  # type: ignore[operator]
        keep = 1.0 - self.cfg.uncertainty_discount * unc
        return 1.0 + 9.0 * raw * keep, norm, raw

    def score(self, i: HybridInputs) -> SeverityAssessment | None:
        r = i.reading
        if r.event_type == NO_EVENT:
            return None
        c = self.cfg
        factors = self._factors(i)
        base_w = c.weights.model_dump()
        unc = r.uncertainty if r.uncertainty is not None else c.unknown_uncertainty
        points, norm, raw = self._points(factors, base_w, unc)
        keep = 1.0 - c.uncertainty_discount * unc

        out_f: list[SeverityFactor] = []
        omitted: list[OmittedFactor] = []
        for fid in FACTOR_ORDER:
            val, detail = factors[fid]
            ok = val is not None and fid in norm
            out_f.append(SeverityFactor(
                id=fid, label=LABELS[fid], kind=KINDS[fid], available=ok, value=None if val is None else round(val, 4),
                raw_weight=base_w[fid], weight=round(norm.get(fid, 0.0), 4),
                contribution_points=round(9.0 * norm[fid] * val * keep, 4) if ok and val is not None else 0.0, detail=detail))
            if not ok:
                omitted.append(OmittedFactor(id=fid, label=LABELS[fid], reason=detail if val is None else "its configured weight is zero"))

        # sensitivity: each weight off by +-delta in turn, renormalised
        scores = [_round_score(points)]
        for fid in norm:
            for sign in (-1.0, 1.0):
                w2 = dict(base_w)
                w2[fid] = base_w[fid] * (1.0 + sign * c.sensitivity.delta)
                p, _, _ = self._points(factors, w2, unc)
                scores.append(_round_score(p))
        low, high = min(scores), max(scores)
        removed = 9.0 * raw * (1.0 - keep)
        return SeverityAssessment(
            score=_round_score(points), points=round(points, 3), low=low, high=high,
            range_basis=(f"Assumption sensitivity, not a statistical interval: the lowest and highest score when any single weight is "
                         f"changed by {int(c.sensitivity.delta * 100)}% (all other weights unchanged)."),
            version=self.version, factors=out_f, omitted=omitted, drivers=self._drivers(out_f, i), uncertainty=round(unc, 4),
            uncertainty_stated=r.uncertainty is not None,
            uncertainty_points_removed=round(removed, 4),
            formula=(f"severity = 1 + 9 x sum(weight x factor) x (1 - {c.uncertainty_discount:g} x uncertainty) "
                     f"= 1 + 9 x {raw:.3f} x {keep:.3f} = {points:.2f}"))

    # -------------------------------------------------------------------------------------------------------------------- drivers
    def _drivers(self, factors: list[SeverityFactor], i: HybridInputs) -> list[RiskDriver]:
        out: list[RiskDriver] = []
        for f in factors:
            if not f.available or f.value is None:
                continue
            v = f.value
            text, direction = _driver_text(f.id, v, i)
            out.append(RiskDriver(factor_id=f.id, text=text, direction=direction, points=f.contribution_points))
        return sorted(out, key=lambda d: -d.points)


def _round_score(points: float) -> int:
    return int(min(10, max(1, math.floor(points + 0.5))))


def _where(r: SemanticReading) -> str:
    if r.sectors:
        return f" affecting {', '.join(r.sectors)}"
    if r.regions:
        return f" in {', '.join(r.regions)}"
    return ""


def _driver_text(fid: str, v: float, i: HybridInputs) -> tuple[str, str]:
    r = i.reading
    d = "UP" if v >= 0.6 else "DOWN" if v <= 0.3 else "NEUTRAL"
    if fid == "category_prior":
        d = "UP" if v >= 0.6 else "DOWN" if v < 0.5 else "NEUTRAL"
        tail = {"UP": " (a class that usually reaches widely)", "DOWN": " (a class that tends to stay contained)", "NEUTRAL": ""}[d]
        return f"{r.event_label} event{_where(r)}{tail}", d
    if fid == "severity_indicators":
        if not r.severity_indicators:
            return "No explicit severity markers in the text", "DOWN"
        return "Markers of seriousness: " + ", ".join(h.label.lower() for h in r.severity_indicators if h.id != "large_scale" or len(r.severity_indicators) == 1), d
    if fid == "tone":
        d = "UP" if v >= 0.5 else "DOWN" if v <= 0.15 else "NEUTRAL"
        words = {"UP": "Adverse tone raises the signal", "DOWN": f"{r.sentiment_label.capitalize()} tone reduces the immediate severity signal",
                 "NEUTRAL": "Mildly adverse tone"}
        return words[d], d
    if fid == "novelty":
        d = "UP" if v >= 0.8 else "DOWN" if v <= 0.3 else "NEUTRAL"
        return ("High novelty: little earlier coverage of this issuer" if d == "UP" else
                "Low novelty: largely repeats earlier reports" if d == "DOWN" else "Moderate novelty"), d
    if fid == "breadth":
        lvl = assessed_scope(r) or "unknown"
        d = "UP" if v >= 0.6 else "DOWN" if v <= 0.3 else "NEUTRAL"
        return {"MARKET": "Market-wide reach", "SECTOR": "Sector-level reach", "COMPANY": "Reach limited to one company"}.get(lvl, "Reach unclear"), d
    if fid == "source_credibility":
        d = "UP" if v >= 0.7 else "DOWN" if v <= 0.5 else "NEUTRAL"
        if i.corroborating_at_event_time == 0:
            return "Limited corroboration: a single source at the time", "DOWN" if v <= 0.5 else "NEUTRAL"
        return f"{i.corroborating_at_event_time} independent report(s) already existed", d
    if fid == "market_regime":
        d = "UP" if v >= 0.6 else "DOWN" if v <= 0.2 else "NEUTRAL"
        return ("Elevated volatility regime" if d == "UP" else "Calm market backdrop" if d == "DOWN" else "Moderate market volatility"), d
    return fid, d
