"""The executive digest: "what should I care about right now?", answered from the monitor's own changes and states.

Nothing is scored. Each section lists the events whose state changed in a particular way, ordered by one documented key (``configs/decision.yaml: digest``):

    1. relevance to the portfolio (materiality tier, CRITICAL first),
    2. severity (higher first),
    3. the size of the change the section is about (exposure share, modeled stress, severity step, evidence tiers),
    4. recency of the change (newer first),
    5. the event id.

Every card returns that key beside its position, so the order can be read and argued with; there is no importance model. A card drills down, in order, to the event, its evidence, its scope,
its portfolio exposure, its propagation, its stress and the attribution of that stress.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from pydantic import Field

from ..decision.config import DecisionConfig
from ..decision.models import ObservationKind, ProvenanceRef
from ..domain import Portfolio
from ..domain.base import ContractModel
from ..propagation.concentration import OverlapItem
from ..propagation.models import OverlapView
from .models import RANK_EVIDENCE, ChangeType, EventState, Mode, RiskChange
from .service import MonitorService

VERSION = "digest-v1"

SECTION_INFO: dict[str, tuple[str, str, list[ChangeType]]] = {
    "NEW_RISKS": ("Top new risks", "Events that reached the tracking floor in this window.", [ChangeType.NEW_EVENT]),
    "ESCALATIONS": ("Escalations", "Events whose severity rose or whose coverage describes them widening or worsening.", [ChangeType.EVENT_ESCALATED]),
    "EXPOSURE_CHANGES": ("Largest changes in portfolio exposure", "Events whose relevance to the book, or the share of it they reach, changed.", [ChangeType.PORTFOLIO_EXPOSURE_CHANGED]),
    "STRESS_CHANGES": ("Largest changes in modeled stress", "Events whose scenario P&L moved. A simulation under an illustrative scenario, not a forecast.", [ChangeType.STRESS_CHANGED]),
    "EVIDENCE_CHANGES": ("Important evidence changes", "Events that gained or lost independent corroboration.", [ChangeType.EVIDENCE_STRENGTHENED, ChangeType.EVIDENCE_WEAKENED]),
    "CONFLICTS": ("Major conflicts", "Events whose reports now contradict each other on a tracked claim.", [ChangeType.CONFLICT_APPEARED]),
    "CONCENTRATION": ("Concentration changes", "Independent events that now share a risk factor and the same holdings.", []),
    "WATCHLISTS": ("Watchlist activity", "What happened to the subjects you watch.", []),
}


class RankPart(ContractModel):
    name: str
    value: str


class DrillStep(ContractModel):
    step: str = Field(description="EVENT | EVIDENCE | SCOPE | EXPOSURE | PROPAGATION | STRESS | ATTRIBUTION")
    signal_id: str


class OverlapSummary(ContractModel):
    risk_factor: str
    risk_factor_label: str
    status: str = Field(description="NEW | GROWN | RESOLVED")
    event_count: int
    previous_event_count: int
    shared_share: float
    sentence: str
    signal_ids: list[str]


class WatchSummary(ContractModel):
    watchlist_id: str
    name: str
    matched_events: int
    new_events: int
    recent_changes: int
    top: list[dict[str, str | float | None]] = Field(description="the watched events that matter most: signal_id, headline, severity, materiality")


class DigestCard(ContractModel):
    kind: str = Field(description="EVENT | OVERLAP | WATCHLIST")
    section: str
    rank: int
    rank_key: list[RankPart]
    event_id: str | None
    signal_id: str | None
    headline: str
    summary: str
    change_types: list[ChangeType]
    change_ids: list[str]
    at: datetime | None
    severity: float | None
    lifecycle: str | None
    evidence_tier: str | None
    conflict: str | None
    materiality: str | None
    exposure_share: float | None
    stress_pnl_pct: float | None
    independent_sources: int | None
    drill: list[DrillStep]
    overlap: OverlapSummary | None = None
    watch: WatchSummary | None = None
    provenance: list[ProvenanceRef]


class DigestSection(ContractModel):
    id: str
    title: str
    blurb: str
    total: int
    truncated: bool
    cards: list[DigestCard]


class Digest(ContractModel):
    version: str = VERSION
    mode: Mode
    availability: str = Field(description="AVAILABLE | UNAVAILABLE")
    reason: str | None = None
    cycle: int | None
    window: int
    as_of: datetime | None
    portfolio_id: str | None
    portfolio_name: str | None
    tracked_events: int
    change_count: int
    sections: list[DigestSection]
    ranking: str = Field(description="the ordering rule, in words")
    labels: list[str]
    limitations: list[str]


RANKING = "Ordered by relevance to the portfolio (materiality tier), then severity, then the size of the change the section is about, then how recent it is, then the event id. No importance score."
LABELS = [
    "Nothing here is scored: the order is a documented key that every card shows.",
    "Severity, lifecycle, evidence and conflicts are EventShock's own assessment; stress is a simulation under an illustrative scenario, not a forecast.",
    "Replay shows the same digest every time; live shows what the live feed changed.",
]
LIMITATIONS = [
    "A change is reported when a configured threshold is crossed (judgement priors, unvalidated); it does not measure how much the change matters.",
    "In the frozen replay each cluster's severity and scenario are fixed, so exposure and stress changes are rare and appear mainly when a cluster joins an event or the portfolio or an adjustment changes.",
    "Events whose report times were assigned by the replay are never placed on a timeline, so they are not here.",
]


def _change_size(c: RiskChange) -> float:
    p, s = c.previous, c.current
    t = c.change_type
    if t is ChangeType.PORTFOLIO_EXPOSURE_CHANGED:
        a = abs((s.exposure_share or 0.0) - ((p.exposure_share or 0.0) if p else 0.0))
        return max(a, 0.001)   # a level move with no change of share still counts a little
    if t is ChangeType.STRESS_CHANGED:
        return abs((s.stress_pnl_pct or 0.0) - ((p.stress_pnl_pct or 0.0) if p else 0.0))
    if t is ChangeType.EVENT_ESCALATED:
        return max((s.severity or 0.0) - ((p.severity or 0.0) if p else 0.0), 0.0)
    if t in (ChangeType.EVIDENCE_STRENGTHENED, ChangeType.EVIDENCE_WEAKENED):
        return float(abs(RANK_EVIDENCE.get(s.evidence_tier, 0) - (RANK_EVIDENCE.get(p.evidence_tier, 0) if p else 0)))
    if t is ChangeType.CONFLICT_APPEARED:
        return 1.0
    return s.severity or 0.0


def _tier(cfg: DecisionConfig, level: str | None) -> int:
    order = cfg.digest.materiality_order
    return order.index(level) if level in order else len(order)


def rank_key(cfg: DecisionConfig, s: EventState, size: float, at: datetime | None) -> tuple:
    """The sort key (ascending = first). Every component is shown on the card."""
    return (_tier(cfg, s.materiality), -(s.severity or 0.0), -round(size, 9), -(at.timestamp() if at else 0.0), s.event_id)


def _parts(s: EventState, size: float, at: datetime | None) -> list[RankPart]:
    return [RankPart(name="materiality", value=s.materiality or "UNDETERMINED"), RankPart(name="severity", value="n/a" if s.severity is None else f"{s.severity:g}"),
            RankPart(name="size of change", value=f"{size:.3g}"), RankPart(name="recency", value=at.isoformat() if at else "n/a"), RankPart(name="id", value=s.event_id)]


def drill(signal_id: str) -> list[DrillStep]:
    return [DrillStep(step=x, signal_id=signal_id) for x in ("EVENT", "EVIDENCE", "SCOPE", "EXPOSURE", "PROPAGATION", "STRESS", "ATTRIBUTION")]


def _event_card(cfg: DecisionConfig, section: str, group: list[RiskChange], mode: Mode) -> tuple[tuple, DigestCard]:
    latest = max(group, key=lambda c: (c.at, c.change_id))
    s = latest.current
    size = max(_change_size(c) for c in group)
    key = rank_key(cfg, s, size, latest.at)
    types = sorted({c.change_type for c in group}, key=lambda t: t.value)
    return key, DigestCard(
        kind="EVENT", section=section, rank=0, rank_key=_parts(s, size, latest.at), event_id=s.event_id, signal_id=s.lead_signal_id, headline=s.headline, summary=latest.summary,
        change_types=types, change_ids=[c.change_id for c in sorted(group, key=lambda c: c.change_id)], at=latest.at, severity=s.severity, lifecycle=s.lifecycle, evidence_tier=s.evidence_tier,
        conflict=s.conflict, materiality=s.materiality, exposure_share=s.exposure_share, stress_pnl_pct=s.stress_pnl_pct, independent_sources=s.independent_sources, drill=drill(s.lead_signal_id),
        provenance=[ProvenanceRef(kind=ObservationKind.EVENTSHOCK_ASSESSMENT, source="monitor.digest", ref_id=s.event_id, as_of=latest.at)])


def build_sections(cfg: DecisionConfig, changes: list[RiskChange], mode: Mode, overlap_cards: list[DigestCard], watch_cards: list[DigestCard]) -> list[DigestSection]:
    out: list[DigestSection] = []
    cap = cfg.digest.per_section
    for sid in cfg.digest.sections:
        title, blurb, types = SECTION_INFO[sid]
        if sid == "CONCENTRATION":
            cards = overlap_cards
        elif sid == "WATCHLISTS":
            cards = watch_cards
        else:
            by_event: dict[str, list[RiskChange]] = {}
            for c in changes:
                if c.change_type in types:
                    by_event.setdefault(c.event_id, []).append(c)
            built = sorted((_event_card(cfg, sid, g, mode) for g in by_event.values()), key=lambda kc: kc[0])
            cards = [c for _, c in built]
        total = len(cards)
        shown = [c.model_copy(update={"rank": i + 1}) for i, c in enumerate(cards[:cap])]
        out.append(DigestSection(id=sid, title=title, blurb=blurb, total=total, truncated=total > cap, cards=shown))
    return out


@dataclass
class Inputs:
    changes: list[RiskChange]
    states: dict[str, EventState]
    as_of: datetime | None
    cycle: int | None
    untracked: int


class DigestService:
    def __init__(self, cfg: DecisionConfig, monitor: MonitorService, *, propagation: Callable[[], object | None], watch_summaries: Callable[..., list[WatchSummary]] | None = None) -> None:
        self.cfg = cfg
        self._monitor = monitor
        self._prop = propagation
        self._watch = watch_summaries

    def digest(self, *, mode: Mode = Mode.REPLAY, cycle: int | None = None, window: int = 4, portfolio: Portfolio | None = None, portfolio_name: str | None = None) -> Digest:
        m = self._monitor
        pf_id = portfolio.portfolio_id if portfolio is not None else None
        if mode is Mode.REPLAY:
            try:
                cyc, states = m.replay_states(cycle, portfolio)
            except LookupError as exc:
                return self._empty(mode, str(exc), cycle, window, portfolio, portfolio_name)
            k = cyc.index
            cs = m.replay_changes(cycle=k, window=window, portfolio=portfolio) if k >= 1 else None
            changes = list(cs.changes) if cs else []
            current, as_of = states.states, cyc.at
            overlap_cards = self._overlap_cards(k, window, portfolio)
        else:
            enabled, _, _ = m._live_status()  # noqa: SLF001
            changes = m.live_changes(portfolio=portfolio).changes
            current, as_of, k = m.live_states(), m._clock(), None  # noqa: SLF001
            overlap_cards = []
            if not enabled and not changes:
                return self._empty(mode, "the live feed is off; REPLAY works without it", None, window, portfolio, portfolio_name)
        watch_cards = self._watch_cards(mode, k, window, portfolio)
        sections = build_sections(self.cfg, changes, mode, overlap_cards, watch_cards)
        return Digest(mode=mode, availability="AVAILABLE", cycle=k, window=window, as_of=as_of, portfolio_id=pf_id, portfolio_name=portfolio_name, tracked_events=len(current), change_count=len(changes),
                      sections=sections, ranking=RANKING, labels=LABELS, limitations=LIMITATIONS)

    def _empty(self, mode: Mode, reason: str, cycle: int | None, window: int, portfolio: Portfolio | None, name: str | None) -> Digest:
        return Digest(mode=mode, availability="UNAVAILABLE", reason=reason, cycle=cycle, window=window, as_of=None, portfolio_id=portfolio.portfolio_id if portfolio else None, portfolio_name=name,
                      tracked_events=0, change_count=0, sections=[], ranking=RANKING, labels=LABELS, limitations=LIMITATIONS)

    # ------------------------------------------------------------------------------------------------------------------------------ overlaps
    def _overlap_view(self, k: int, portfolio: Portfolio | None) -> OverlapView | None:
        prop = self._prop()
        if prop is None:
            return None
        _, states = self._monitor.replay_states(k, portfolio)
        idx = self._monitor._svc().index()  # noqa: SLF001
        items: list[OverlapItem] = []
        for st in states.states.values():
            ev = idx.event(st.event_id)
            if ev is None or st.materiality not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                continue
            lead = next((n.signal for n in ev.nodes if n.signal.id == st.lead_signal_id), ev.anchor.signal)
            items.append(OverlapItem(signal_id=lead.id, event_id=ev.id, headline=st.headline, published_at=st.last_seen, materiality=st.materiality, severity=st.severity,
                                     graph=prop.graph(lead, portfolio)))  # type: ignore[attr-defined]
        return prop.overlaps_of(items, portfolio)  # type: ignore[attr-defined]

    def _overlap_cards(self, k: int, window: int, portfolio: Portfolio | None) -> list[DigestCard]:
        try:
            now = self._overlap_view(k, portfolio)
            prev = self._overlap_view(max(k - window, 0), portfolio) if k - window >= 0 else None
        except (LookupError, ValueError):
            return []
        if now is None:
            return []
        before = {c.risk_factor: c for c in (prev.clusters if prev else [])}
        out: list[tuple[tuple, DigestCard]] = []
        for c in now.clusters:
            b = before.get(c.risk_factor)
            n_now, n_prev = len(c.events), len(b.events) if b else 0
            if b is not None and n_now <= n_prev:
                continue                                               # not new and not larger: nothing changed
            status = "NEW" if b is None else "GROWN"
            sigs = [e.signal_id for e in c.events]
            key = (-n_now, -c.shared_share, c.risk_factor)
            out.append((key, DigestCard(
                kind="OVERLAP", section="CONCENTRATION", rank=0, rank_key=[RankPart(name="events sharing the factor", value=str(n_now)), RankPart(name="shared share of book", value=f"{c.shared_share:.3f}"),
                                                                           RankPart(name="risk factor", value=c.risk_factor)], event_id=None, signal_id=sigs[0] if sigs else None,
                headline=f"{c.risk_factor_label}: {n_now} events now share it", summary=c.sentence, change_types=[], change_ids=[], at=None, severity=None, lifecycle=None, evidence_tier=None, conflict=None,
                materiality=None, exposure_share=c.shared_share, stress_pnl_pct=None, independent_sources=None, drill=drill(sigs[0]) if sigs else [],
                overlap=OverlapSummary(risk_factor=c.risk_factor, risk_factor_label=c.risk_factor_label, status=status, event_count=n_now, previous_event_count=n_prev, shared_share=c.shared_share,
                                       sentence=c.sentence, signal_ids=sigs),
                provenance=[ProvenanceRef(kind=ObservationKind.PRODUCT_RULE, source="propagation.concentration", ref_id=c.risk_factor)])))
        out.sort(key=lambda kc: kc[0])
        return [c for _, c in out]

    # ----------------------------------------------------------------------------------------------------------------------------- watchlists
    def _watch_cards(self, mode: Mode, k: int | None, window: int, portfolio: Portfolio | None) -> list[DigestCard]:
        if self._watch is None:
            return []
        try:
            summaries = self._watch(mode=mode, cycle=k, window=window, portfolio=portfolio)
        except (LookupError, ValueError):
            return []
        out: list[tuple[tuple, DigestCard]] = []
        for w in summaries:
            if w.matched_events == 0 and w.recent_changes == 0:
                continue
            top = w.top[0] if w.top else {}
            out.append(((-w.new_events, -w.recent_changes, -w.matched_events, w.watchlist_id), DigestCard(
                kind="WATCHLIST", section="WATCHLISTS", rank=0, rank_key=[RankPart(name="new events", value=str(w.new_events)), RankPart(name="changes", value=str(w.recent_changes)),
                                                                          RankPart(name="matching events", value=str(w.matched_events)), RankPart(name="id", value=w.watchlist_id)],
                event_id=None, signal_id=str(top.get("signal_id")) if top.get("signal_id") else None, headline=w.name,
                summary=f"{w.matched_events} matching event{'s' if w.matched_events != 1 else ''}, {w.new_events} new, {w.recent_changes} change{'s' if w.recent_changes != 1 else ''} in the window",
                change_types=[], change_ids=[], at=None, severity=None, lifecycle=None, evidence_tier=None, conflict=None, materiality=None, exposure_share=None, stress_pnl_pct=None,
                independent_sources=None, drill=drill(str(top["signal_id"])) if top.get("signal_id") else [], watch=w,
                provenance=[ProvenanceRef(kind=ObservationKind.PRODUCT_RULE, source="watchlist.match", ref_id=w.watchlist_id)])))
        out.sort(key=lambda kc: kc[0])
        return [c for _, c in out]

