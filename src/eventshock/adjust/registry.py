"""The whitelist of adjustable settings.

Only what is listed here can be changed by hand: numeric thresholds, switches, the exposure mapping tables and a few vocabularies. Claim and lifecycle cue
lexicons, model files, severity anchors, scenario catalog values and every pinned digest are deliberately not adjustable. A spec's ``pattern`` is a dotted path whose
``*`` segments stand for any key of the shipped defaults at that level. The bounds here are a first guard; the strict config models then validate the whole result.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..domain import LAB_FACTORS, RiskFactor, Scenario, ShockScope
from ..propagation.config import LEVELS, Edge

CONFIGS = ("intelligence", "portfolio", "propagation")
ENGINE_FACTORS = [f.value for f in RiskFactor if f not in LAB_FACTORS]  # the lab-only factors are not part of any adjustable mapping
_USER_EDGE = re.compile(r"^propagation\.risk_factors\.([A-Z_]+)\.transmission\.(user_[a-z0-9_]+)$")
_SHOCK_RANGE = {RiskFactor.EQUITY: (-1.0, 1.0), RiskFactor.RATES_BPS: (-2000.0, 2000.0), RiskFactor.CREDIT_SPREAD_BPS: (-2000.0, 2000.0),
                RiskFactor.PD_MULTIPLIER: (0.0, 20.0), RiskFactor.LGD_ADD: (-1.0, 1.0), RiskFactor.FX_PCT: (-1.0, 1.0), RiskFactor.COMMODITY_PCT: (-1.0, 1.0)}


@dataclass(frozen=True)
class Spec:
    pattern: str
    group: str
    label: str                      # {0}, {1}... are the wildcard values
    kind: str
    lo: float | None = None
    hi: float | None = None
    choices: tuple[str, ...] = ()
    unit: str | None = None
    description: str = ""
    open_key: bool = False          # the last segment may be a key the shipped defaults lack (a new ticker)
    regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        rx = r"\.".join("[^.]+" if seg == "*" else re.escape(seg) for seg in self.pattern.split("."))
        object.__setattr__(self, "regex", re.compile(f"^{rx}$"))


def _n(p: str, g: str, label: str, lo: float, hi: float, unit: str | None = None, desc: str = "", kind: str = "number") -> Spec:
    return Spec(p, g, label, kind, lo, hi, unit=unit, description=desc)


LEVEL_CHOICES = tuple(LEVELS)

SPECS: tuple[Spec, ...] = (
    # ------------------------------------------------------------------------------------------------- scenario generation
    _n("propagation.generation.min_severity", "scenario", "Minimum severity to generate a scenario", 1, 10, "1-10", "A scenario is generated only at or above this severity."),
    Spec("propagation.generation.min_materiality", "scenario", "Minimum relevance to generate a scenario", "choice", choices=LEVEL_CHOICES,
         description="The event must matter to the portfolio at least this much."),
    Spec("propagation.generation.downside_only", "scenario", "Loss scenarios only (refuse favourable events)", "boolean"),
    _n("propagation.generation.propagated_equity_shock", "scenario", "Propagated sector equity shock (before weights)", -0.5, 0.0, "fraction",
       "Added to the scenario's market-wide equity shock for each sector the active risk factors reach."),
    _n("propagation.generation.propagated_spread_bps", "scenario", "Propagated sector credit-spread widening", 0, 500, "bp"),
    _n("propagation.generation.max_propagated_sectors", "scenario", "Most sectors a scenario propagates to", 1, 6, None, kind="integer"),
    _n("propagation.generation.propagation_scale", "scenario", "Scale on every transmission weight", 0, 2),
    Spec("propagation.templates.*.enabled", "scenario", "Template on: {0}", "boolean"),
    _n("propagation.templates.*.propagation_scale", "scenario", "Propagation scale: {0}", 0, 2),
    # ------------------------------------------------------------------------------------------------------ relevance
    _n("portfolio.relevance_bands.high_share", "relevance", "Feed relevance band: HIGH from this share of the book", 0.001, 1.0, "share"),
    _n("portfolio.relevance_bands.medium_share", "relevance", "Feed relevance band: MEDIUM from this share of the book", 0.001, 1.0, "share"),
    _n("propagation.materiality.exposure_bands.medium_share", "relevance", "Exposure row MEDIUM from", 0.001, 0.99, "share of the book reached"),
    _n("propagation.materiality.exposure_bands.high_share", "relevance", "Exposure row HIGH from", 0.001, 0.99, "share of the book reached"),
    _n("propagation.materiality.exposure_bands.very_high_share", "relevance", "Exposure row VERY HIGH from", 0.001, 1.0, "share of the book reached"),
    _n("propagation.materiality.severity_bands.medium", "relevance", "Severity column MEDIUM from", 1, 10, "1-10"),
    _n("propagation.materiality.severity_bands.high", "relevance", "Severity column HIGH from", 1, 10, "1-10"),
    _n("propagation.materiality.severity_bands.critical", "relevance", "Severity column CRITICAL from", 1, 10, "1-10"),
    Spec("propagation.materiality.grid.*.*", "relevance", "Relevance for {0} exposure and {1} severity", "choice", choices=LEVEL_CHOICES,
         description="Must never decrease as exposure or severity rises."),
    _n("propagation.materiality.concentration_bump_top_share", "relevance", "Raise a level when one position is this share of what is reached", 0.05, 1.0, "share"),
    Spec("propagation.materiality.assumption_only_cap", "relevance", "Cap when only assumed edges reach the book", "choice", choices=LEVEL_CHOICES),
    Spec("propagation.materiality.severity_unavailable_cap", "relevance", "Cap when severity was not assessed", "choice", choices=LEVEL_CHOICES),
    _n("propagation.concentration.min_share", "relevance", "Concentration flag: at least this share of the book", 0.01, 1.0, "share"),
    _n("propagation.concentration.equal_weight_multiple", "relevance", "Concentration flag: at least this many times an equal split", 1, 50, "x"),
    _n("propagation.concentration.min_items", "relevance", "Concentration flag: minimum items in a dimension", 2, 50, None, kind="integer"),
    _n("propagation.concentration.hhi_flag", "relevance", "Concentration flag: Herfindahl index of a dimension", 0.01, 1.0),
    _n("propagation.concentration.hhi_equal_weight_multiple", "relevance", "Concentration flag: Herfindahl index vs 1/n of an equal split", 1, 20, "x"),
    _n("propagation.concentration.window_days", "relevance", "Overlapping events: look back", 0.5, 365, "days"),
    _n("propagation.concentration.max_signals", "relevance", "Overlapping events: most signals considered", 2, 1000, None, kind="integer"),
    _n("propagation.concentration.min_events", "relevance", "Overlapping events: minimum independent events", 2, 20, None, kind="integer"),
    _n("propagation.concentration.min_overlap_share", "relevance", "Overlapping events: shared holdings at least this share of the book", 0.001, 1.0, "share"),
    Spec("propagation.concentration.min_materiality", "relevance", "Overlapping events: each event at least this relevant", "choice", choices=LEVEL_CHOICES),
    # ------------------------------------------------------------------------------------------------------ mapping
    _n("propagation.risk_factors.*.transmission.*.weight", "mapping", "{0} / {1}: weight", -1, 1, "x the adverse shock",
       "Positive hurts the target, negative benefits it."),
    Spec("propagation.risk_factors.*.transmission.*.enabled", "mapping", "{0} / {1}: on", "boolean"),
    Spec("propagation.risk_factors.*.transmission.*.shock", "mapping", "{0} / {1}: writes a sector shock", "boolean",
         description="Sector edges only."),
    Spec("propagation.category_risk_factors.*", "mapping", "Risk factors assumed for {0} events", "text_list",
         description="Risk factor ids from the mapping table."),
    # ------------------------------------------------------------------------------------------------ intelligence
    _n("intelligence.scope.industry_min_terms", "intelligence", "Industry terms needed to name an industry", 1, 5, None, kind="integer"),
    Spec("intelligence.scope.ticker_industry.*", "intelligence", "Industry of {0}", "text", open_key=True,
         description="An industry name known to the vocabulary (the industry list is not adjustable)."),
    Spec("intelligence.scope.theme_risk_factors.*", "intelligence", "Engine factors theme '{0}' bears on", "text_list", description="Engine factor names."),
    Spec("intelligence.sources.authoritative_domains", "intelligence", "Authoritative source domains", "text_list"),
    _n("intelligence.grouping.window_hours", "intelligence", "Grouping window", 1, 720, "hours"),
    _n("intelligence.grouping.min_shared_tokens", "intelligence", "Grouping: shared tokens to be a candidate", 1, 10, None, kind="integer"),
    _n("intelligence.grouping.max_posting_length", "intelligence", "Grouping: most events a token may be in", 50, 5000, None, kind="integer"),
    _n("intelligence.grouping.min_cosine", "intelligence", "Grouping: closeness (same issuer)", 0, 1),
    _n("intelligence.grouping.min_shared_facts", "intelligence", "Grouping: shared facts (same issuer)", 0, 10, None, kind="integer"),
    _n("intelligence.grouping.unresolved_min_cosine", "intelligence", "Grouping: closeness (no issuer)", 0, 1),
    _n("intelligence.grouping.unresolved_min_shared_facts", "intelligence", "Grouping: shared facts (no issuer)", 0, 10, None, kind="integer"),
    _n("intelligence.evidence.strong_min_independent", "intelligence", "STRONG evidence: independent sources", 1, 20, None, kind="integer"),
    _n("intelligence.evidence.strong_min_diversity", "intelligence", "STRONG evidence: source diversity", 0, 1),
    _n("intelligence.evidence.moderate_min_independent", "intelligence", "MODERATE evidence: independent sources", 1, 20, None, kind="integer"),
    _n("intelligence.novelty.lookback_days", "intelligence", "Novelty look-back", 1, 365, "days"),
    _n("intelligence.novelty.same_story_min_cosine", "intelligence", "Novelty: same-story closeness", 0, 1),
    _n("intelligence.novelty.recurrence_gap_hours", "intelligence", "Novelty: quiet gap before a recurrence", 1, 2000, "hours"),
    _n("intelligence.novelty.min_new_facts", "intelligence", "Novelty: new facts that make an update", 0, 10, None, kind="integer"),
    _n("intelligence.novelty.max_priors_shown", "intelligence", "Novelty: earlier events shown", 1, 10, None, kind="integer"),
    _n("intelligence.velocity.bucket_minutes", "intelligence", "Velocity bucket", 5, 1440, "minutes", kind="integer"),
    _n("intelligence.velocity.min_reports", "intelligence", "Velocity: minimum reports", 2, 50, None, kind="integer"),
    _n("intelligence.velocity.min_span_hours", "intelligence", "Velocity: minimum span", 0.1, 48, "hours"),
    _n("intelligence.velocity.accel_min_reports", "intelligence", "Velocity: reports for acceleration", 2, 100, None, kind="integer"),
    _n("intelligence.claims.conflict_window_hours", "intelligence", "Contradiction window", 1, 240, "hours"),
    _n("intelligence.claims.min_conflict_tokens", "intelligence", "Contradiction: shared topic words", 1, 10, None, kind="integer"),
    _n("intelligence.lifecycle.confirmed_min_independent", "intelligence", "Lifecycle: sources to confirm", 1, 20, None, kind="integer"),
    _n("intelligence.lifecycle.resolution_min_independent", "intelligence", "Lifecycle: sources to resolve", 1, 20, None, kind="integer"),
    _n("intelligence.lifecycle.stale_after_hours", "intelligence", "Lifecycle: stale after", 1, 720, "hours"),
    _n("intelligence.lifecycle.escalation_hold_hours", "intelligence", "Lifecycle: escalation hold", 1, 240, "hours"),
)


def spec_for(path: str) -> Spec | None:
    return next((s for s in SPECS if s.regex.match(path)), None)


def split_config(path: str) -> tuple[str, str]:
    head, _, rest = path.partition(".")
    return head, rest


def expand(spec: Spec, defaults: Mapping[str, Mapping[str, Any]]) -> Iterator[tuple[str, list[str], Any]]:
    """The concrete paths a spec covers in the shipped defaults, with the wildcard values and the shipped value."""
    cfg, rest = split_config(spec.pattern)
    parts = rest.split(".")
    # re-walk keeping the actual key path
    def go(node: Any, i: int, path: list[str], caps: list[str]) -> Iterator[tuple[list[str], list[str], Any]]:
        if i == len(parts):
            yield path, caps, node
            return
        if not isinstance(node, Mapping):
            return
        seg = parts[i]
        keys = list(node) if seg == "*" else ([seg] if seg in node else [])
        for k in keys:
            yield from go(node[k], i + 1, path + [str(k)], caps + [str(k)] if seg == "*" else caps)
    for path, caps, leaf in go(defaults.get(cfg, {}), 0, [], []):
        yield cfg + "." + ".".join(path), caps, leaf


def default_at(path: str, defaults: Mapping[str, Mapping[str, Any]]) -> tuple[bool, Any]:
    cfg, rest = split_config(path)
    node: Any = defaults.get(cfg, {})
    for seg in rest.split("."):
        if not isinstance(node, Mapping) or seg not in node:
            return False, None
        node = node[seg]
    return True, node


def shock_override_specs(scenarios: list[Scenario], default_by_category: Mapping[Any, str]) -> list[tuple[str, str, float, tuple[float, float], str]]:
    """(path, label, shipped value, bounds, category) of each base shock a template can override, read from the catalog scenario of each class."""
    by_id = {s.id: s for s in scenarios}
    out = []
    for cat, sid in sorted(default_by_category.items(), key=lambda kv: str(kv[0])):
        scn = by_id.get(sid)
        if scn is None:
            continue
        for sh in scn.shocks:
            if sh.sector is not None:
                continue
            key = f"{sh.factor.value}:{sh.scope.value}"
            out.append((f"propagation.templates.{cat.value if hasattr(cat, 'value') else cat}.shock_overrides.{key}",
                        f"{scn.name}: {sh.factor.value} {sh.scope.value.lower()} shock", sh.value, _SHOCK_RANGE[sh.factor], scn.name))
    return out


def validate_value(spec: Spec, value: Any) -> str | None:
    """None when ``value`` fits the spec's type and bounds, else the reason."""
    k = spec.kind
    if k in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return "must be a number"
        if k == "integer" and float(value) != int(value):
            return "must be a whole number"
        if spec.lo is not None and value < spec.lo or spec.hi is not None and value > spec.hi:
            return f"must be between {spec.lo:g} and {spec.hi:g}"
        return None
    if k == "boolean":
        return None if isinstance(value, bool) else "must be true or false"
    if k == "choice":
        return None if value in spec.choices else f"must be one of {', '.join(spec.choices)}"
    if k == "text":
        return None if isinstance(value, str) and 0 < len(value.strip()) <= 120 else "must be a short, non-empty text"
    if k == "text_list":
        ok = isinstance(value, list) and len(value) <= 200 and all(isinstance(v, str) and 0 < len(v.strip()) <= 120 for v in value)
        return None if ok else "must be a list of short, non-empty texts"
    return f"unsupported kind {k}"


def validate_path_value(path: str, value: Any, defaults: Mapping[str, Mapping[str, Any]], shock_paths: Mapping[str, tuple[float, float]]) -> str | None:
    """The reason ``path`` may not take ``value``, or None."""
    if (m := _USER_EDGE.match(path)) is not None:
        if m.group(1) not in defaults.get("propagation", {}).get("risk_factors", {}):
            return f"unknown risk factor {m.group(1)!r}"
        try:
            Edge.model_validate(value)
        except ValueError as exc:
            return f"not a valid transmission edge: {exc}"
        return None
    if path in shock_paths:
        lo, hi = shock_paths[path]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
            return f"must be a number between {lo:g} and {hi:g}"
        return None
    spec = spec_for(path)
    if spec is None:
        return "this setting is not adjustable"
    if not spec.open_key and not default_at(path, defaults)[0]:
        return "no such setting"
    return validate_value(spec, value)


__all__ = ["SPECS", "Spec", "CONFIGS", "ENGINE_FACTORS", "LEVEL_CHOICES", "spec_for", "expand", "default_at", "shock_override_specs", "validate_path_value", "ShockScope"]
