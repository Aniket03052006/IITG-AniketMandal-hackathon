"""The impact model's input schema: which numbers it may see, and how each is assembled from a report.

One definition for training and serving (the dataset builder, the trainer and ``ImpactModel`` all import it), so a feature
cannot exist in one and not the other. Every name here must also be registered ``AT_EVENT_TIME`` in
``modeling.leakage.FEATURE_REGISTRY``; the trainer refuses to run otherwise, and a test pins the two lists together.
"""

from __future__ import annotations

from datetime import datetime

from ..domain import EventCategory
from .market_context import SessionRules, doc_time_features, quantize, timing_flags

FEATURE_SCHEMA = "impact-features-v1"
ISSUER = "ISSUER"
MARKET = "MARKET"
SCOPES = (ISSUER, MARKET)

# Price-derived state at event time (sessions strictly before s0). ``f_`` = issuer scope, ``m_`` = market scope.
ISSUER_STATE = ["f_sigma_60", "f_beta_market", "f_beta_sector", "f_ret_1d", "f_ret_5d", "f_ret_20d", "f_mkt_ret_5d",
                "f_sector_ret_5d", "f_volume_ratio", "f_resid_vol_5d_ratio", "f_resid_vol_20d_ratio", "f_vix_level",
                "f_vix_chg_5d"]
MARKET_STATE = ["m_sigma_60", "m_ret_1d", "m_ret_5d", "m_ret_20d", "m_dev_vol_5d_ratio", "m_dev_vol_20d_ratio", "m_vix_level",
                "m_vix_chg_5d", "m_vix_rel_60", "m_rate_level", "m_rate_chg_5d"]
STATE = {ISSUER: ISSUER_STATE, MARKET: MARKET_STATE}

# What the report itself and its timestamp tell us.
TIMING = ["t_pre_open", "t_in_session", "t_date_only", "t_first_seen"]
DOC = {ISSUER: ["link_confidence", "novelty", "dow", "local_hour", "is_news", *TIMING],
       MARKET: ["novelty", "dow", "local_hour", "is_news", *TIMING]}

# What the frozen sentiment and event models say about the text (never the placeholder rules, never the ticker/source).
EVENT_P = [f"ev_p_{c.value.lower()}" for c in EventCategory]
TEXT = [*EVENT_P, "ev_p_none", "sent_pos", "sent_neg", "sent_abs"]

# Feature sets by rung of the evaluation ladder (R2 = market state + timing, no text; R3 = R2 + text-model outputs).
RUNGS = ("R2", "R3")


def feature_names(scope: str, rung: str) -> list[str]:
    if rung == "R2":
        return [*STATE[scope], *DOC[scope]]
    if rung == "R3":
        return [*STATE[scope], *DOC[scope], *TEXT]
    raise ValueError(f"unknown rung {rung!r}")


ALL_FEATURES = sorted({n for sc in SCOPES for n in feature_names(sc, "R3")})


def text_features(event_probabilities: dict[EventCategory, float], no_event_probability: float, sent_pos: float,
                  sent_neg: float) -> dict[str, float]:
    """From exactly the fields a served signal carries (so training on ``decide_many`` output equals serving)."""
    out = {f"ev_p_{c.value.lower()}": float(event_probabilities[c]) for c in EventCategory}
    out["ev_p_none"] = float(no_event_probability)
    out["sent_pos"], out["sent_neg"], out["sent_abs"] = float(sent_pos), float(sent_neg), abs(float(sent_pos) - float(sent_neg))
    return out


def doc_features(scope: str, published_at: datetime, timing: str, rules: SessionRules, source_type: str, novelty: float,
                 link_confidence: float) -> dict[str, float]:
    dow, hour = doc_time_features(published_at, rules)
    out = {"novelty": float(novelty), "dow": float(dow), "local_hour": quantize(hour) or 0.0,
           "is_news": 1.0 if source_type == "NEWS" else 0.0, **timing_flags(timing)}
    if scope == ISSUER:
        out["link_confidence"] = float(link_confidence)
    return out


def state_features(scope: str, raw: dict[str, float]) -> dict[str, float]:
    """Prefix the price-store keys (``sigma_60`` -> ``f_sigma_60`` / ``m_sigma_60``) and keep only the schema's names."""
    prefix = "f_" if scope == ISSUER else "m_"
    out = {f"{prefix}{k}": v for k, v in raw.items()}
    return {k: out.get(k, float("nan")) for k in STATE[scope]}


def feature_group(name: str) -> str:
    """A human label for the family a feature belongs to (what the UI groups the drivers by)."""
    if name in ("novelty",):
        return "novelty of the report"
    if name in ("link_confidence",):
        return "entity-link confidence"
    if name in ("dow", "local_hour", "is_news") or name in TIMING:
        return "timing and source"
    if name in EVENT_P or name == "ev_p_none":
        return "event type (text model)"
    if name.startswith("sent_"):
        return "sentiment (text model)"
    if name.endswith(("sigma_60", "resid_vol_5d_ratio", "resid_vol_20d_ratio", "vol_5d_ratio", "vol_20d_ratio", "volume_ratio")):
        return "volatility regime"
    if "vix" in name or "rate" in name:
        return "market conditions"
    if "ret_" in name:
        return "recent price move"
    if "beta" in name:
        return "market sensitivity"
    return "market state"
