"""Event x portfolio relevance: LOW / MEDIUM / HIGH / CRITICAL by an explicit lookup, never a weighted score.

The share of the book the event reaches picks a row, the event's severity picks a column, and the grid in ``configs/propagation.yaml`` names the level. Then, in
this order, one bump (the reached part is concentrated in one position) and two caps (only assumed edges reach the book; severity was not assessed) may apply.
Every input, the grid cell and every rule that fired are returned, so "why is this relevant?" is answered by the numbers themselves.
"""

from __future__ import annotations

from collections import defaultdict

from ..adjust.models import AdjustmentNotice
from ..intelligence.model import Availability
from .config import EXPOSURE_ROWS, LEVELS, PropagationConfig, level_rank
from .models import (
    MappingBasis,
    MaterialityComponent,
    MaterialityRule,
    PortfolioMateriality,
    PropagationGraph,
)

LABELS = [
    "Relevance to your holdings only: how much of the book the event reaches and how severe it is. It is not a forecast of loss.",
    "Severity is a transparent, uncalibrated triage score; the transmission edges that extend the reach are assumptions.",
]
BASIS_WORDS = {
    MappingBasis.DIRECT_FACT: "the book holds the named issuer (a fact)",
    MappingBasis.EVIDENCED_SCOPE: "a sector, industry or region the text names, or a holding's structural sensitivity to a factor the text is about",
    MappingBasis.ASSUMPTION_ONLY: "only assumed transmission edges reach the book",
    MappingBasis.NONE: "nothing reaches the book",
}


def _min_level(a: str, b: str) -> str:
    return a if level_rank(a) <= level_rank(b) else b


class MaterialityAssessor:
    def __init__(self, cfg: PropagationConfig) -> None:
        self.cfg = cfg

    def assess(self, graph: PropagationGraph, severity: float | None, adjustments: AdjustmentNotice | None = None) -> PortfolioMateriality:
        m = self.cfg.materiality
        common = dict(signal_id=graph.signal_id, portfolio_id=graph.portfolio_id, portfolio_name=graph.portfolio_name, labels=LABELS,
                      mapping_basis=graph.mapping_basis, reached_share=graph.reached_share, adjustments=adjustments)
        if graph.availability is Availability.ABSTAINED:
            return PortfolioMateriality(
                availability=Availability.ABSTAINED, reason=graph.reason, level="UNDETERMINED", level_from_grid=None, exposure_row=None, severity_column=None,
                components=[], rules=[], why=[graph.reason or "No defensible mapping."], summary="Relevance cannot be stated: " + (graph.reason or "no defensible mapping."),
                **common)  # type: ignore[arg-type]
        sev_comp = MaterialityComponent(
            id="severity", label="Event severity", display="not assessed" if severity is None else f"{severity:g} of 10",
            value=severity, band=None if severity is None else self.cfg.severity_column(severity),
            detail="the transparent severity scorecard (uncalibrated)" if severity is not None else "the text does not describe a scored market event")
        if graph.reached_share <= 0:
            comps = [sev_comp, MaterialityComponent(id="reach", label="Share of the book reached", display="0.0%", value=0.0, band="NONE",
                                                    detail=graph.reason or "the book holds nothing the event reaches")]
            return PortfolioMateriality(
                availability=Availability.AVAILABLE, reason=graph.reason, level="NONE", level_from_grid=None, exposure_row=None, severity_column=None,
                components=comps, rules=[], why=["The event can be mapped, but you hold nothing it reaches, so it is not relevant to this portfolio."]
                + [f"Not reached: {x}" for x in graph.not_reached[:4]],
                summary="Not relevant to this portfolio: the book holds nothing the event reaches.", **common)  # type: ignore[arg-type]

        row_all = self.cfg.exposure_row(graph.reached_share)
        row_ev = self.cfg.exposure_row(graph.evidenced_share)
        # reach that rests only on assumed edges can lift the exposure row by at most one step above what the evidence alone supports
        limit = EXPOSURE_ROWS[min(EXPOSURE_ROWS.index(row_ev) + 1, len(EXPOSURE_ROWS) - 1)]
        limited = EXPOSURE_ROWS.index(row_all) > EXPOSURE_ROWS.index(limit)
        row = limit if limited else row_all
        col = "MEDIUM" if severity is None else self.cfg.severity_column(severity)
        base = m.grid[row][col]
        level = base
        rules = [MaterialityRule(kind="GRID", id=f"grid.{row}.{col}", fired=True,
                                 effect=f"{row.replace('_', ' ').lower()} exposure with {col.lower()} severity{' (assumed: not assessed)' if severity is None else ''} gives {base}"),
                 MaterialityRule(kind="CAP", id="assumed_reach_limit", fired=limited, effect=(
                     f"the whole reach ({graph.reached_share:.1%}) is a {row_all.replace('_', ' ').lower()} exposure row, but only {graph.evidenced_share:.1%} of it is evidenced "
                     f"({row_ev.replace('_', ' ').lower()}): assumed reach can lift the row one step at most, so the row is {row.replace('_', ' ').lower()}" if limited else
                     f"the evidenced reach ({graph.evidenced_share:.1%}) supports the row: assumed edges do not lift it more than one step"))]
        # concentration inside the reached part of the book
        by_issuer: dict[str, float] = defaultdict(float)
        for h in graph.reached:
            by_issuer[h.entity_id] += h.market_value
        top = max((h.market_value for h in graph.reached), default=0.0)
        top_share = top / graph.reached_value if graph.reached_value else 0.0
        hhi = sum((v / graph.reached_value) ** 2 for v in by_issuer.values()) if graph.reached_value else 0.0
        bump = top_share >= m.concentration_bump_top_share and row != "LOW" and level != LEVELS[-1]
        if bump:
            level = LEVELS[level_rank(level) + 1]
        rules.append(MaterialityRule(kind="BUMP", id="concentration_bump", fired=bump, effect=(
            f"one position is {top_share:.0%} of what is reached (threshold {m.concentration_bump_top_share:.0%}): the level goes up one step to {level}" if bump else
            f"the largest position is {top_share:.0%} of what is reached, below the {m.concentration_bump_top_share:.0%} bump threshold")))
        assumed_only = graph.evidenced_share <= 0
        capped = assumed_only and level_rank(level) > level_rank(m.assumption_only_cap)
        if capped:
            level = _min_level(level, m.assumption_only_cap)
        rules.append(MaterialityRule(kind="CAP", id="assumption_only_cap", fired=capped, effect=(
            f"only assumed transmission edges reach the book, so the level cannot exceed {m.assumption_only_cap}" if capped else
            "applies only when no part of the reach is evidenced; here " + ("it is capped already or not needed" if assumed_only else "part of it is evidenced"))))
        no_sev = severity is None
        capped2 = no_sev and level_rank(level) > level_rank(m.severity_unavailable_cap)
        if capped2:
            level = _min_level(level, m.severity_unavailable_cap)
        rules.append(MaterialityRule(kind="CAP", id="severity_unavailable_cap", fired=capped2, effect=(
            f"severity was not assessed, so the level cannot exceed {m.severity_unavailable_cap}" if capped2 else
            "applies only when severity is not assessed" if not no_sev else "severity is not assessed; the level is already within the cap")))

        comps = [
            sev_comp,
            MaterialityComponent(id="reach", label="Share of the book reached (counted once)", display=f"{graph.reached_share:.1%}", value=graph.reached_share, band=row_all,
                                 detail=f"{len(graph.reached)} positions, {graph.reached_value:,.0f} of the book"),
            MaterialityComponent(id="direct", label="Direct exposure (the named issuer)", display=f"{graph.direct_share:.1%}", value=graph.direct_share,
                                 detail="positions in the issuer the event names" if graph.direct_share else "the event names no issuer you hold"),
            MaterialityComponent(id="indirect", label="Indirect exposure (sector, industry, region, risk factor)", display=f"{graph.indirect_share:.1%}", value=graph.indirect_share,
                                 detail="reached through what the event is about, not through the issuer itself"),
            MaterialityComponent(id="evidenced", label="Reach that is evidenced", display=f"{graph.evidenced_share:.1%}", value=graph.evidenced_share,
                                 detail="named in the text, in the entity master, or a structural sensitivity to a factor the text is about"),
            MaterialityComponent(id="assumed", label="Reach that is only assumed", display=f"{graph.assumed_share:.1%}", value=graph.assumed_share,
                                 detail="reached only by configured transmission edges (judgement priors)"),
            MaterialityComponent(id="concentration", label="Concentration of the reached part", display=f"top position {top_share:.0%}", value=top_share,
                                 band="CONCENTRATED" if bump else None, detail=f"Herfindahl index across issuers {hhi:.2f}"),
            MaterialityComponent(id="basis", label="Mapping basis", display=graph.mapping_basis.value.replace("_", " ").lower(), value=graph.mapping_basis.value,
                                 detail=BASIS_WORDS[graph.mapping_basis]),
        ]
        why = []
        if graph.direct_share > 0:
            why.append(f"The event names an issuer you hold: {graph.direct_share:.1%} of the book.")
        if graph.indirect_share > 0:
            why.append(f"It also reaches {graph.indirect_share:.1%} of the book through its sector, industry, region or risk factors.")
        why.append(f"Together it reaches {graph.reached_share:.1%} of the book ({len(graph.reached)} positions): {graph.evidenced_share:.1%} evidenced, {graph.assumed_share:.1%} only assumed.")
        if limited:
            why.append(f"Only the evidenced part supports a {row_ev.replace('_', ' ').lower()} exposure row; assumed reach lifts it one step at most, to {row.replace('_', ' ').lower()}.")
        why.append(f"Severity is {'not assessed' if severity is None else f'{severity:g} of 10'}, read from the {col.lower()} column: the grid says {base}.")
        why += [r.effect for r in rules[1:] if r.fired and r.id != 'assumed_reach_limit']
        summary = (f"{level}: reaches {graph.reached_share:.1%} of the book ({graph.evidenced_share:.1%} evidenced, {graph.assumed_share:.1%} only assumed); "
                   f"strongest basis: {BASIS_WORDS[graph.mapping_basis]}.")
        return PortfolioMateriality(
            availability=Availability.AVAILABLE, reason=None, level=level, level_from_grid=base, exposure_row=row, severity_column=None if severity is None else col,
            components=comps, rules=rules, why=why, summary=summary, **common)  # type: ignore[arg-type]
