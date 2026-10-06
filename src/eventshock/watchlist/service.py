"""``WatchlistService``: validation, CRUD and what each watched item currently shows.

Everything an item shows is read from the monitor's event state (severity, lifecycle, novelty, velocity, evidence tier, conflict, portfolio relevance, modeled stress, recent
changes); nothing is inferred again here. A disabled list is inert (inspectable, never matching). Replay is deterministic: activity at a replay cycle is a pure function of the
frozen signals, the cycle and the portfolio.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ..decision.config import WatchlistCfg
from ..decision.models import ObservationKind, ProvenanceRef
from ..domain import AssetClass, Portfolio
from ..intelligence.grouping import Event
from ..intelligence.model import ScopeType
from ..monitor.digest import WatchSummary
from ..monitor.models import RANK_MATERIALITY, ChangeType, EventState, Mode
from ..monitor.service import MonitorService
from ..store import CHANNEL_REPLAY
from .match import (
    Match,
    match_company,
    match_event_type,
    match_scope_level,
    match_theme,
)
from .models import (
    ItemActivity,
    ItemRollup,
    VocabEntry,
    WatchedEvent,
    WatchItem,
    WatchKind,
    Watchlist,
    WatchlistActivity,
    WatchlistInput,
    WatchVocabulary,
)
from .store import WatchlistStore

LABELS = [
    "Matching reads the scope EventShock already resolved for each event. An event with no resolved company never matches a company; an unresolved event matches nothing.",
    "Severity, lifecycle, novelty, velocity, evidence and conflicts are EventShock's own assessment; stress is a simulation under an illustrative scenario, not a forecast.",
    "A disabled watchlist is kept but inert.",
]
KIND_NAME = {"COMPANY": "company", "SECTOR": "sector", "INDUSTRY": "industry", "GEOGRAPHY": "region", "EVENT_TYPE": "event type", "RISK_THEME": "risk theme", "PORTFOLIO_EXPOSURE": "portfolio exposure"}
LIMITATIONS = [
    "Events whose report times were assigned by the replay (social posts) are never placed on a timeline, so they are not listed.",
    "Matching reads vocabulary and the entity master: an event that is about a watched subject in words the vocabulary does not hold is not matched.",
]


class WatchlistInvalid(ValueError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


class WatchlistService:
    def __init__(self, cfg: WatchlistCfg, store: WatchlistStore, monitor: MonitorService, *, vocabulary: Callable[[], WatchVocabulary],
                 intelligence: Callable[[], object | None], propagation: Callable[[], object | None], assessments: object | None,
                 portfolio: Callable[[Portfolio | None], Portfolio], clock: Callable[[], datetime] | None = None) -> None:
        self.cfg = cfg
        self._store = store
        self._monitor = monitor
        self._vocab = vocabulary
        self._intel = intelligence
        self._prop = propagation
        self._assess = assessments
        self._book = portfolio
        self._clock = clock or (lambda: datetime.now(UTC))

    # ------------------------------------------------------------------------------------------------------------------------------ vocabulary
    def vocabulary(self) -> WatchVocabulary:
        return self._vocab()

    def _normalise(self, inp: WatchlistInput) -> WatchlistInput:
        v = self._vocab()
        issues: list[str] = []
        name = inp.name.strip()
        if not name:
            issues.append("a watchlist needs a name")
        if len(name) > self.cfg.name_max_chars:
            issues.append(f"the name is longer than {self.cfg.name_max_chars} characters")
        if len(inp.items) > self.cfg.max_items:
            issues.append(f"a watchlist holds at most {self.cfg.max_items} items")
        def table(entries: list[VocabEntry]) -> dict[str, VocabEntry]:
            """value and (for a company) ticker, case-insensitively; the 'top:N' template is not itself a value."""
            out: dict[str, VocabEntry] = {}
            for e in entries:
                if e.value == "top:N":
                    continue
                out[e.value.lower()] = e
                if e.detail:
                    out.setdefault(e.detail.lower(), e)
            return out

        by_kind: dict[WatchKind, dict[str, VocabEntry]] = {
            WatchKind.COMPANY: table(v.companies), WatchKind.SECTOR: table(v.sectors), WatchKind.INDUSTRY: {e.value.lower(): e for e in v.industries},
            WatchKind.GEOGRAPHY: table(v.geographies), WatchKind.EVENT_TYPE: {e.value.lower(): e for e in v.event_types}, WatchKind.RISK_THEME: table(v.risk_themes),
            WatchKind.PORTFOLIO_EXPOSURE: table(v.portfolio_exposure),
        }
        items: list[WatchItem] = []
        seen: set[tuple[str, str]] = set()
        for it in inp.items:
            raw = it.value.strip()
            if it.kind is WatchKind.PORTFOLIO_EXPOSURE and raw.lower().startswith("top:"):
                try:
                    n = int(raw[4:])
                except ValueError:
                    issues.append(f"{raw!r}: 'top:N' needs a whole number")
                    continue
                if not 1 <= n <= self.cfg.top_holdings_max:
                    issues.append(f"{raw!r}: N must be between 1 and {self.cfg.top_holdings_max}")
                    continue
                canon, label = f"top:{n}", f"Top {n} holding{'s' if n != 1 else ''} by value"
            else:
                hit = by_kind[it.kind].get(raw.lower())
                if hit is None:
                    what = {WatchKind.COMPANY: "a company in the entity master (an entity id or a ticker)", WatchKind.SECTOR: "a sector", WatchKind.INDUSTRY: "an industry",
                            WatchKind.GEOGRAPHY: "a region code", WatchKind.EVENT_TYPE: "an event category", WatchKind.RISK_THEME: "a risk theme",
                            WatchKind.PORTFOLIO_EXPOSURE: "'top:N' or a company in the entity master"}[it.kind]
                    issues.append(f"{it.kind.value} {raw!r} is not {what}: free text is never turned into a company or a sector")
                    continue
                canon, label = hit.value, hit.label
            key = (it.kind.value, canon)
            if key in seen:
                continue
            seen.add(key)
            items.append(WatchItem(kind=it.kind, value=canon, label=label))
        if issues:
            raise WatchlistInvalid(issues)
        return WatchlistInput(name=name, enabled=inp.enabled, items=items)

    # ------------------------------------------------------------------------------------------------------------------------------------ CRUD
    def list(self) -> list[Watchlist]:
        return self._store.list()

    def get(self, wid: str) -> Watchlist:
        return self._store.get(wid)

    def create(self, inp: WatchlistInput) -> Watchlist:
        return self._store.create(self._normalise(inp))

    def update(self, wid: str, inp: WatchlistInput) -> Watchlist:
        return self._store.update(wid, self._normalise(inp))

    def delete(self, wid: str) -> None:
        self._store.delete(wid)

    # --------------------------------------------------------------------------------------------------------------------------------- activity
    def _targets(self, item: WatchItem, pf: Portfolio) -> tuple[set[str], str | None]:
        """The held entity ids a PORTFOLIO_EXPOSURE item names in this portfolio, and why it is empty when it is."""
        held: dict[str, float] = {}
        for a in pf.assets:
            if a.asset_type in (AssetClass.CASH, AssetClass.OTHER):
                continue
            held[a.entity_id] = held.get(a.entity_id, 0.0) + a.market_value
        if item.value.startswith("top:"):
            n = int(item.value[4:])
            top = [e for e, _ in sorted(held.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]
            return set(top), (None if top else "this portfolio holds nothing to rank")
        if item.value in held:
            return {item.value}, None
        return set(), f"{item.label or item.value} is not held in this portfolio"

    def activity(self, w: Watchlist, *, mode: Mode = Mode.REPLAY, cycle: int | None = None, window: int = 1, portfolio: Portfolio | None = None) -> WatchlistActivity:
        pf = self._book(portfolio)
        base = dict(watchlist=w, mode=mode.value, window=window, portfolio_id=pf.portfolio_id, labels=LABELS, limitations=LIMITATIONS)
        prov = [ProvenanceRef(kind=ObservationKind.EVENTSHOCK_ASSESSMENT, source="watchlist.match", ref_id=w.id)]
        intel = self._intel()
        if intel is None:
            return WatchlistActivity(cycle=None, as_of=None, status="UNAVAILABLE", reason="event intelligence is not running in this profile", items=[], recent_changes=0,
                                     provenance=prov, **base)  # type: ignore[arg-type]
        if mode is Mode.REPLAY:
            try:
                cyc, states = self._monitor.replay_states(cycle, portfolio)
            except (LookupError, ValueError) as exc:
                return WatchlistActivity(cycle=cycle, as_of=None, status="UNAVAILABLE", reason=str(exc), items=[], recent_changes=0, provenance=prov, **base)  # type: ignore[arg-type]
            cycles = self._monitor.cycles()
            from_at = cycles[max(cyc.index - max(window, 1), 0)].at
            as_of, k = cyc.at, cyc.index
            tracked = states.states
            changes = self._monitor.replay_changes(cycle=k, window=window, portfolio=portfolio).changes if k >= 1 else []
            by_event: dict[str, list[ChangeType]] = {}
            for c in changes:
                by_event.setdefault(c.event_id, []).append(c.change_type)
        else:
            as_of, k, from_at = self._clock(), None, None
            tracked = self._monitor.live_states()
            by_event = {}
            for c in self._monitor.logged_changes():
                by_event.setdefault(c.event_id, []).append(c.change_type)
        if not w.enabled:
            items = [ItemActivity(item=i, status="DISABLED", reason="this watchlist is switched off", matched_events=0, new_events=0, scanned=0, truncated=False, events=[], rollup=None)
                     for i in w.items]
            return WatchlistActivity(cycle=k, as_of=as_of, status="DISABLED", reason="this watchlist is switched off: nothing is matched", items=items, recent_changes=0,
                                     provenance=prov, **base)  # type: ignore[arg-type]
        items = [self._item(i, mode, as_of, from_at, k, tracked, by_event, pf, portfolio) for i in w.items]
        return WatchlistActivity(cycle=k, as_of=as_of, status="OK", items=items, recent_changes=sum(len(v) for v in by_event.values()), provenance=prov, **base)  # type: ignore[arg-type]

    def digest_summaries(self, *, mode: Mode, cycle: int | None, window: int, portfolio: Portfolio | None = None) -> list[WatchSummary]:
        """One summary per enabled watchlist for the executive digest: how many events match, how many are new and how many changes they had in the window."""
        out: list[WatchSummary] = []
        for w in self._store.list():
            if not w.enabled or not w.items:
                continue
            a = self.activity(w, mode=mode, cycle=cycle, window=window, portfolio=portfolio)
            if a.status != "OK":
                continue
            matched: dict[str, WatchedEvent] = {}
            new: set[str] = set()
            changes = 0
            for it in a.items:
                for e in it.events:
                    matched.setdefault(e.event_id, e)
                    if e.is_new:
                        new.add(e.event_id)
                changes += sum(len(e.recent_changes) for e in it.events)
            total = sum(it.matched_events for it in a.items)
            ranked = sorted(matched.values(), key=lambda e: (-RANK_MATERIALITY.get(e.materiality or "UNDETERMINED", -1), -(e.severity or 0.0), e.event_id))[:3]
            out.append(WatchSummary(watchlist_id=w.id, name=w.name, matched_events=total, new_events=len(new), recent_changes=changes,
                                    top=[{"signal_id": e.lead_signal_id, "headline": e.headline, "severity": e.severity, "materiality": e.materiality} for e in ranked]))
        return out

    # ------------------------------------------------------------------------------------------------------------------------------------ item
    def _candidates(self, item: WatchItem, mode: Mode, as_of: datetime, tracked: dict[str, EventState], pf: Portfolio) -> tuple[list[tuple[Event, Match]], str | None]:
        intel = self._intel()
        idx = intel.index()  # type: ignore[attr-defined]
        out: list[tuple[Event, Match]] = []
        if item.kind is WatchKind.PORTFOLIO_EXPOSURE:
            targets, why = self._targets(item, pf)
            prop = self._prop()
            if not targets or prop is None:
                return [], why or "event-to-portfolio propagation is not running"
            for eid in sorted(tracked):
                ev = idx.event(eid)
                if ev is None:
                    continue
                st = tracked[eid]
                lead = next((n.signal for n in ev.nodes if n.signal.id == st.lead_signal_id), ev.anchor.signal)
                reached = {h.entity_id for h in prop.graph(lead, pf if pf is not self._book(None) else None).reached}  # type: ignore[attr-defined]
                hit = sorted(reached & targets)
                if hit:
                    out.append((ev, Match(f"propagation reaches {len(hit)} of the watched holding(s)")))
            return out, None
        for ev in idx.events:
            if not ev.trusted:
                continue
            live = any(self._monitor._signals.channel_of(n.signal.id) != CHANNEL_REPLAY for n in ev.nodes)  # noqa: SLF001
            if live != (mode is Mode.LIVE):      # REPLAY looks at the frozen replay only, LIVE only at events the live overlay holds
                continue
            if min(n.time for n in ev.nodes) > as_of:
                continue
            m = self._match_scoped(item, ev)
            if m is not None:
                out.append((ev, m))
        return out, None

    def _match_scoped(self, item: WatchItem, ev: Event) -> Match | None:
        """Does this (non-exposure) item match this event? Reads the resolved scope and the signals' own facts only."""
        intel = self._intel()
        label = item.label or item.value
        if item.kind is WatchKind.COMPANY:
            return match_company(ev, item.value, label)
        if item.kind is WatchKind.EVENT_TYPE:
            a = self._assess.assess(ev.anchor.signal) if self._assess is not None else None  # type: ignore[attr-defined]
            return match_event_type(ev.anchor.signal, a.reading.event_type if a is not None else None, item.value, label)
        scope = intel.scope_of(ev.anchor.signal)  # type: ignore[attr-defined]
        if scope.scope_type is ScopeType.UNRESOLVED:
            return None
        if item.kind is WatchKind.SECTOR:
            return match_scope_level(scope, ScopeType.SECTOR, item.value, label)
        if item.kind is WatchKind.INDUSTRY:
            return match_scope_level(scope, ScopeType.INDUSTRY, item.value, label)
        if item.kind is WatchKind.GEOGRAPHY:
            return match_scope_level(scope, ScopeType.GEOGRAPHY, self._region_name(item.value), label)
        if item.kind is WatchKind.RISK_THEME:
            return match_theme(ev, scope, item.value, label)
        return None

    def event_hits(self, ev: Event, as_of: datetime, mode: Mode, portfolio: Portfolio | None = None) -> list[str]:
        """The enabled watchlist items this event matches, as 'list: kind subject' (for "why am I seeing this?")."""
        pf = self._book(portfolio)
        hits: list[str] = []
        prop = self._prop()
        for w in self._store.list():
            if not w.enabled:
                continue
            for item in w.items:
                m: Match | None
                if item.kind is WatchKind.PORTFOLIO_EXPOSURE:
                    targets, _ = self._targets(item, pf)
                    if not targets or prop is None:
                        continue
                    nodes = [n for n in ev.nodes if n.time <= as_of]
                    if not nodes:
                        continue
                    lead = self._monitor.builder.lead(nodes, portfolio)[0].signal
                    reached = {h.entity_id for h in prop.graph(lead, portfolio).reached}  # type: ignore[attr-defined]
                    m = Match("propagation reaches a watched holding") if reached & targets else None
                else:
                    m = self._match_scoped(item, ev)
                if m is not None:
                    hits.append(f"{w.name}: {KIND_NAME.get(item.kind.value, item.kind.value)} {item.label or item.value}")
        return hits

    def _region_name(self, code: str) -> str:
        for e in self._vocab().geographies:
            if e.value == code:
                return e.label
        return code

    def _item(self, item: WatchItem, mode: Mode, as_of: datetime, from_at: datetime | None, cycle: int | None, tracked: dict[str, EventState],
              by_event: dict[str, list[ChangeType]], pf: Portfolio, portfolio: Portfolio | None) -> ItemActivity:
        cands, why = self._candidates(item, mode, as_of, tracked, pf)
        if not cands:
            return ItemActivity(item=item, status="NO_MATCH", reason=why or "no event in view matches this subject", matched_events=0, new_events=0, scanned=0, truncated=False,
                                events=[], rollup=None)
        cands.sort(key=lambda c: (-max(n.time for n in c[0].nodes if n.time <= as_of).timestamp(), c[0].id))
        cap = self.cfg.max_scan_events
        scanned = cands[:cap]
        events: list[WatchedEvent] = []
        new_events = 0
        for ev, m in scanned:
            b = self._monitor.builder.build(ev, as_of, portfolio, force_full=True)
            if b is None:
                continue
            st, intel = b.state, b.intel
            first = st.first_seen
            is_new = first is not None and from_at is not None and first > from_at
            new_events += 1 if is_new else 0
            events.append(WatchedEvent(
                event_id=ev.id, lead_signal_id=st.lead_signal_id, headline=st.headline, match_reason=m.reason, first_seen=st.first_seen, last_seen=st.last_seen, is_new=is_new,
                severity=st.severity, lifecycle=st.lifecycle, novelty=intel.novelty.label if intel is not None else None, velocity_per_hour=st.velocity_per_hour,
                evidence_tier=st.evidence_tier, conflict=st.conflict, materiality=st.materiality, exposure_share=st.exposure_share, stress_pnl_pct=st.stress_pnl_pct,
                recent_changes=sorted(set(by_event.get(ev.id, [])), key=lambda c: c.value), clock_trusted=st.clock_trusted))
        shown = events[: self.cfg.max_events_per_item]
        return ItemActivity(item=item, status="MATCHED", reason=None, matched_events=len(cands), new_events=new_events, scanned=len(scanned), truncated=len(cands) > cap,
                            events=shown, rollup=_rollup(events))


def _rollup(events: list[WatchedEvent]) -> ItemRollup:
    def count(vals: list[str | None]) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in vals:
            if v:
                out[v] = out.get(v, 0) + 1
        return dict(sorted(out.items()))
    sev = [e.severity for e in events if e.severity is not None]
    stress = [e.stress_pnl_pct for e in events if e.stress_pnl_pct is not None]
    vel = [e.velocity_per_hour for e in events if e.velocity_per_hour is not None]
    mats = [e.materiality for e in events if e.materiality]
    return ItemRollup(
        max_severity=max(sev) if sev else None, lifecycle_counts=count([e.lifecycle for e in events]), evidence_counts=count([e.evidence_tier for e in events]),
        conflicts_open=sum(1 for e in events if e.conflict in ("POSSIBLE_CONFLICT", "CONFLICTED")),
        max_materiality=max(mats, key=lambda m: RANK_MATERIALITY.get(m, -1)) if mats else None, worst_stress_pnl_pct=min(stress) if stress else None,
        novelty_counts=count([e.novelty for e in events]), fastest_velocity_per_hour=max(vel) if vel else None)

