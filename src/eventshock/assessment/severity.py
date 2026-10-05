"""The severity scorecard: a deterministic function of four rubric answers, two bounded data adjustments and a fixed matrix. No fitted parameters.

    raw      = anchor[magnitude] + offset[reach]                       the severity matrix
    scaled   = 1 + (raw - 1) * certainty_factor * direction_factor     (only when raw > 1)
    points   = scaled + regime_adjustment + novelty_adjustment         each omitted, with its reason, when its input is missing or stale
    score    = clamp(round(points), 1, 10)

Why not a weighted average of bounded factors (the previous formula): an average regresses to the middle (a score of 9 needs every factor near 1), several factors
barely varied (class prior 0.40-0.75, a constant source-credibility term) and one measured wording rather than scale, so scores clustered at 4-7 and nothing reached
the extremes. Here the five magnitude anchors are the middles of the five semantic bands, so every band is reachable by construction, and what the score is made of
is readable line by line.

Pure and deterministic. Inputs are the rubric (rules baseline, AI proposal, outcome), the market state *as of the report* (already checked for freshness), and the
novelty/corroboration that existed at the report's time. Later coverage, later filings and realised moves are not inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import SeverityConfig
from .model import (
    MarketUse,
    OmittedFactor,
    Origin,
    Reliability,
    RubricField,
    ScoreStep,
    SemanticReading,
    SeverityAssessment,
)
from .vocab import NO_EVENT


@dataclass(frozen=True)
class SeverityInputs:
    reading: SemanticReading
    rubric: list[RubricField]
    market: MarketUse
    novelty: float | None  # None when no issuer was resolved to compare against
    source_type: str  # NEWS | SOCIAL
    corroborating_at_event_time: int  # independent reports published at or before this one


def _interp(points: list[tuple[float, float]], x: float) -> float:
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _round(points: float) -> int:
    return int(min(10, max(1, int(points + 0.5))))


class SeverityScorer:
    def __init__(self, cfg: SeverityConfig) -> None:
        self.cfg = cfg
        self.version = cfg.version

    # -------------------------------------------------------------------------------------------------------- the maths
    def _points(self, mag: str, reach: str, cert: str, dirn: str, regime: float, novelty: float, *, anchor_shift: float = 0.0,
                factor_delta: float = 0.0) -> float:
        c = self.cfg
        raw = c.magnitude[int(mag)].anchor + anchor_shift + c.reach[reach].offset
        cf, df = c.certainty[cert].factor, c.direction[dirn].factor
        cf, df = min(1.0, max(0.05, cf + factor_delta)), min(1.0, max(0.05, df + factor_delta))
        scaled = 1.0 + (raw - 1.0) * cf * df if raw > 1.0 else raw
        return scaled + regime + novelty

    def _adjustments(self, i: SeverityInputs) -> tuple[float, float, list[OmittedFactor]]:
        c, omitted = self.cfg, []
        regime = 0.0
        if i.market.used and i.market.vix is not None:
            regime = _interp(c.regime.vix_points, i.market.vix)
        else:
            omitted.append(OmittedFactor(id="regime", label="Market regime", reason=i.market.reason))
        nov = 0.0
        if i.novelty is not None:
            nov = (i.novelty - c.novelty.neutral_point) * c.novelty.strength
        else:
            omitted.append(OmittedFactor(id="novelty", label="Novelty", reason="No issuer was resolved, so there is no earlier report of the same issuer to compare with."))
        return regime, nov, omitted

    # ----------------------------------------------------------------------------------------------------------- score
    def score(self, i: SeverityInputs) -> SeverityAssessment | None:
        if i.reading.event_type == NO_EVENT:
            return None
        c = self.cfg
        f = {r.id: r for r in i.rubric}
        mag, reach, cert, dirn = f["magnitude"].final, f["reach"].final, f["certainty"].final, f["direction"].final
        regime, nov, omitted = self._adjustments(i)
        pts = self._points(mag, reach, cert, dirn, regime, nov)
        score = _round(pts)

        # what the AI's bounded adjustments changed: the same arithmetic on the rules-only answers
        bmag, breach, bcert, bdirn = (f[k].baseline for k in ("magnitude", "reach", "certainty", "direction"))
        base_pts = self._points(bmag, breach, bcert, bdirn, regime, nov)
        base_score = _round(base_pts)

        # sensitivity: each judgement parameter in turn, plus the rules-only score
        u = i.reading.uncertainty or 0.0
        s = c.sensitivity
        shift = s.anchor_shift * (1.0 + u)
        variants = [base_pts, self._points(mag, reach, cert, dirn, regime, nov, anchor_shift=shift),
                    self._points(mag, reach, cert, dirn, regime, nov, anchor_shift=-shift),
                    self._points(mag, reach, cert, dirn, regime, nov, factor_delta=s.factor_delta),
                    self._points(mag, reach, cert, dirn, regime, nov, factor_delta=-s.factor_delta)]
        for k in s.adjustment_scales:
            variants.append(self._points(mag, reach, cert, dirn, regime * k, nov * k))
        scores = [score, *(_round(v) for v in variants)]
        low, high = min(scores), max(scores)

        steps = self._steps(i, f, regime, nov, pts)
        band = c.band_of(score)
        return SeverityAssessment(
            score=score, points=round(min(10.0, max(1.0, pts)), 3), band=band.id, band_label=band.label, band_says=band.says, low=low, high=high,
            range_basis=(f"Assumption sensitivity, not a statistical interval: the lowest and highest score when each judgement parameter is changed in turn "
                         f"(matrix anchors by {shift:.2f} points, certainty and direction factors by {s.factor_delta:g}, the data adjustments removed or scaled "
                         f"by {max(s.adjustment_scales):g}), and with the AI's adjustments removed."),
            version=self.version, rubric=i.rubric, steps=steps, baseline_score=base_score, ai_effect=score - base_score, omitted=omitted,
            market=i.market, reliability=self.reliability(i.source_type, i.corroborating_at_event_time), uncertainty=i.reading.uncertainty,
            formula=(f"raw = anchor[{c.magnitude[int(mag)].label}] {c.magnitude[int(mag)].anchor:g} + offset[{c.reach[reach].label}] {c.reach[reach].offset:+g}; "
                     f"1 + (raw - 1) x {c.certainty[cert].factor:g} x {c.direction[dirn].factor:g}; {regime:+.2f} regime; {nov:+.2f} novelty; "
                     f"= {pts:.2f} -> {score}"))

    def _steps(self, i: SeverityInputs, f: dict[str, RubricField], regime: float, nov: float, final_pts: float) -> list[ScoreStep]:
        c = self.cfg
        mag, reach, cert, dirn = f["magnitude"], f["reach"], f["certainty"], f["direction"]
        raw = c.magnitude[int(mag.final)].anchor + c.reach[reach.final].offset
        steps = [ScoreStep(
            id="matrix", label="Severity matrix", origin=Origin.HYBRID if Origin.HYBRID in (mag.origin, reach.origin) else Origin.RULES, value=f"{mag.final_label} × {reach.final_label.lower()}", effect_points=round(raw, 3), running=round(raw, 3),
            detail=(f"Magnitude '{mag.final_label}' starts at {c.magnitude[int(mag.final)].anchor:g} (the middle of its band); reach '{reach.final_label.lower()}' "
                    f"moves it {c.reach[reach.final].offset:+g}. Both answers start from deterministic rules" + (" and the AI moved at least one of them." if Origin.HYBRID in (mag.origin, reach.origin) else ".")))]
        run = raw
        for fld, table, label in ((cert, c.certainty, "Certainty"), (dirn, c.direction, "Direction")):
            fac = table[fld.final].factor
            after = 1.0 + (run - 1.0) * fac if run > 1.0 else run
            steps.append(ScoreStep(
                id=fld.id, label=label, origin=fld.origin, value=fld.final_label, effect_points=round(after - run, 3), running=round(after, 3),
                detail=f"{fld.final_says.capitalize()}. Scales the distance above 1 by {fac:g}." + (f" {fld.note}" if fld.note else "")))
            run = after
        if i.market.used and i.market.vix is not None:
            run += regime
            steps.append(ScoreStep(id="regime", label="Market regime", origin=Origin.DATA, value=f"VIX {i.market.vix:.1f}", effect_points=round(regime, 3),
                                   running=round(run, 3), detail=i.market.reason))
        if i.novelty is not None:
            run += nov
            steps.append(ScoreStep(id="novelty", label="Novelty", origin=Origin.RULES, value=f"{i.novelty:.2f}", effect_points=round(nov, 3), running=round(run, 3),
                                   detail="Compared with earlier reports of the same issuer: new information moves markets more than a restatement."))
        clamped = min(10.0, max(1.0, final_pts))
        if abs(clamped - final_pts) > 1e-9:
            steps.append(ScoreStep(id="clamp", label="Scale limits", origin=Origin.RULES, value="1 to 10", effect_points=round(clamped - final_pts, 3),
                                   running=round(clamped, 3), detail="The score is held to the 1-10 scale."))
        return steps

    # ------------------------------------------------------------------------------------------------------ reliability
    def reliability(self, source_type: str, corroborating: int) -> Reliability:
        r = self.cfg.reliability
        corro = min(1.0, corroborating / r.corroboration_cap)
        sc = r.type_share * r.type_prior[source_type] + (1 - r.type_share) * corro
        level = "high" if sc >= r.high_from else "moderate" if sc >= r.moderate_from else "low"
        return Reliability(
            level=level, score=round(sc, 3),
            basis=f"{source_type.lower()} source ({r.type_prior[source_type]:.2f}) and {corroborating} independent report(s) that already existed at the time")
