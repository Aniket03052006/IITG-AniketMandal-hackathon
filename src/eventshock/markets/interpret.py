"""Transparent, descriptive interpretation of a matched market against EventShock's own assessment. Four observations and one honest fallback, by ordered rules, with the rule named.

They are observations, not verdicts: "directionally aligned" does not mean the market confirms EventShock, and divergence is not evidence that either side is wrong. Nothing in the market
(probability, change, volume, liquidity) is ever fed back into an EventShock number.
"""

from __future__ import annotations

from .config import InterpretationCfg
from .models import ExternalMarketObservation, Interpretation, InterpretationView

CAVEATS = [
    "An external market observation is an independent source's price. It is not ground truth and it is never an input to EventShock's risk signal, severity, classification, mapping or stress.",
    "A prediction market's probability is thin and can be moved by a few participants; volume and open interest are shown so that can be judged.",
    "The market's question is about its own outcome and horizon, which need not be the event's: the match is a curated mapping from a theme, not an identity.",
]


def _fmt_pp(x: float | None) -> str:
    return "n/a" if x is None else f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.1f} pp"


def interpret(o: ExternalMarketObservation, *, orientation: str, orientation_basis: str, severity: float | None, severity_prev: float | None, materiality: str | None,
              cfg: InterpretationCfg) -> InterpretationView:
    elevated = (severity is not None and severity >= cfg.elevated_severity) or (materiality in cfg.elevated_materiality)
    es_dir = None
    if severity is not None and severity_prev is not None:
        es_dir = "UP" if severity > severity_prev else "DOWN" if severity < severity_prev else "FLAT"
    dp = None if o.probability_change_pp is None else round(o.probability_change_pp, 6)    # so exactly 10 pp is 10 pp, not 9.999999999999998
    sign = {"UP": 1.0, "DOWN": -1.0}.get(orientation)
    if dp is None:
        m_dir = None
    elif sign is None:
        m_dir = "UNMAPPED"
    else:
        r = dp * sign
        m_dir = "TOWARD_RISK" if r >= cfg.aligned_pp else "AWAY_FROM_RISK" if r <= -cfg.aligned_pp else "FLAT"
    es_txt = (f"severity {severity:g}" if severity is not None else "no severity") + (f", relevance {materiality}" if materiality else "")
    base = dict(eventshock_elevated=elevated, eventshock_direction=es_dir, market_direction=m_dir, orientation=orientation, caveats=CAVEATS)

    # R0: a market that is unpriced or thinly traded supports no reading
    thin = (o.open_interest or 0.0) < cfg.min_open_interest and (o.volume or 0.0) < cfg.min_volume
    if o.probability is None or thin:
        why = "no trade and no usable two-sided quote" if o.probability is None else f"only {o.volume or 0:g} contracts traded and {o.open_interest or 0:g} open (limits {cfg.min_volume:g} and {cfg.min_open_interest:g})"
        return InterpretationView(code=Interpretation.LOW_INFORMATION, text="A market exists, but it is too thinly traded or unpriced to support an interpretation.", reason=why, rule="R0_LOW_INFORMATION", **base)

    # R1: a material re-pricing toward risk while EventShock's severity rose
    if sign is not None and dp is not None and abs(dp) >= cfg.repriced_pp and m_dir == "TOWARD_RISK" and es_dir == "UP":
        return InterpretationView(code=Interpretation.MARKET_REPRICED, text=f"The matched market repriced {_fmt_pp(dp)} toward risk while EventShock's severity rose ({severity_prev:g} → {severity:g}).",
                                  reason=f"a move of at least {cfg.repriced_pp:g} pp toward risk ({orientation_basis}) with a higher severity", rule="R1_REPRICED_WITH_SEVERITY_UP", **base)
    if sign is None and dp is not None and abs(dp) >= cfg.repriced_pp:
        return InterpretationView(code=Interpretation.MARKET_REPRICED, text=f"The matched market repriced {_fmt_pp(dp)}. Whether that is toward or away from risk is not mapped for this market.",
                                  reason=f"a move of at least {cfg.repriced_pp:g} pp; no direction is claimed ({orientation_basis})", rule="R1_REPRICED_UNMAPPED", **base)
    if sign is None:
        return InterpretationView(code=Interpretation.NOT_ASSESSED, text="No interpretation: the market has not moved materially and no direction relative to risk is defined for it.",
                                  reason=f"the orientation is neutral ({orientation_basis}), so aligned or divergent cannot be said", rule="R4_NEUTRAL_ORIENTATION", **base)
    if dp is None:
        return InterpretationView(code=Interpretation.NOT_ASSESSED, text="No interpretation: there is no earlier observation to compare the market's probability with.",
                                  reason="the previous probability is not available", rule="R4_NO_PREVIOUS", **base)

    # R2 / R3: direction against EventShock's elevated or not
    if elevated and m_dir == "TOWARD_RISK":
        return InterpretationView(code=Interpretation.ALIGNED, text="External market observation is directionally aligned with EventShock's assessment.",
                                  reason=f"EventShock is elevated ({es_txt}) and the market moved {_fmt_pp(dp)} toward risk ({orientation_basis})", rule="R2_ELEVATED_AND_TOWARD_RISK", **base)
    if not elevated and m_dir in ("FLAT", "AWAY_FROM_RISK"):
        return InterpretationView(code=Interpretation.ALIGNED, text="External market observation is directionally aligned with EventShock's assessment.",
                                  reason=f"EventShock is not elevated ({es_txt}) and the market did not move toward risk ({_fmt_pp(dp)})", rule="R2_NOT_ELEVATED_AND_NO_RISK_MOVE", **base)
    if elevated:
        moved = "has not materially repriced" if m_dir == "FLAT" else f"has moved the other way ({_fmt_pp(dp)})"
        return InterpretationView(code=Interpretation.DIVERGENT, text=f"EventShock identifies elevated risk ({es_txt}), while the matched market {moved}. This is an observation worth monitoring; it does not show that either is wrong.",
                                  reason=f"EventShock is elevated and the market's direction is {m_dir.lower().replace('_', ' ')} ({orientation_basis})", rule="R3_ELEVATED_WITHOUT_RISK_MOVE", **base)
    return InterpretationView(code=Interpretation.DIVERGENT, text=f"The matched market moved {_fmt_pp(dp)} toward risk while EventShock is not elevated ({es_txt}). This is an observation worth monitoring; it does not show that either is wrong.",
                              reason="the market moved toward risk and EventShock is not elevated", rule="R3_RISK_MOVE_WITHOUT_ELEVATION", **base)
