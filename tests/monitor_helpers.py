"""Builders for the monitor tests: event states with a correct fingerprint, fake assessment / propagation layers with chosen answers, and a monitor over real intelligence."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from eventshock.config import REPO_ROOT
from eventshock.decision.config import DecisionConfig, load_decision_config
from eventshock.domain import RiskSignal
from eventshock.intelligence.model import Availability
from eventshock.intelligence.service import IntelligenceService
from eventshock.monitor.models import EventState, fingerprint_of
from eventshock.monitor.service import MonitorService
from eventshock.monitor.state import StateBuilder
from eventshock.monitor.store import ChangeLog, StateStore
from eventshock.store import CombinedSignalRepository, InMemorySignalRepository, LiveSignalStore
from tests.intel_helpers import BASE, CFG, scope_resolver

T0 = BASE


def dcfg(**monitor) -> DecisionConfig:  # noqa: ANN003
    return load_decision_config(REPO_ROOT / "configs", {f"monitor.{k}": v for k, v in monitor.items()} or None)


def state(**kw) -> EventState:  # noqa: ANN003
    """A tracked event state with sensible defaults; ``fingerprint`` is always recomputed from the fields, as the builder does."""
    base = dict(event_id="evt_1", anchor_signal_id="a", lead_signal_id="a", headline="JPMorgan fined", as_of=T0, tracked=True, member_count=1, report_count=1,
                independent_sources=1, first_seen=T0, last_seen=T0, event_type="REGULATORY_LEGAL", scope_type="COMPANY", scope_value="JPMorgan Chase", severity=6.0,
                severity_band="high", lifecycle="DEVELOPING", evidence_tier="WEAK", conflict="NO_CONFLICT", velocity_per_hour=None, portfolio_id="pf_test",
                materiality="MEDIUM", exposure_share=0.20, stress_status="ABSTAINED", stress_pnl_pct=None, stress_run_id=None, clock_trusted=True)
    base.update(kw)
    base["fingerprint"] = fingerprint_of(base)
    return EventState(**base)


class FakeAssess:
    """assess(signal) -> the little of RiskAssessment the monitor reads."""

    def __init__(self, severity: dict[str, float | None] | None = None, default: float | None = 6.0, event_type: str = "REGULATORY_LEGAL") -> None:
        self.severity, self.default, self.event_type = severity or {}, default, event_type

    def assess(self, signal: RiskSignal):  # noqa: ANN201
        sev = self.severity.get(signal.id, self.default)
        s = None if sev is None else SimpleNamespace(score=int(sev), band="high")
        return SimpleNamespace(severity=s, reading=SimpleNamespace(event_type=self.event_type))

    def detail(self, signal: RiskSignal):  # noqa: ANN201
        a = self.assess(signal)
        a.conflict = None
        return a


class FakeProp:
    """materiality / scenario / portfolio_stress with chosen answers per signal id."""

    def __init__(self, level: dict[str, str] | None = None, share: dict[str, float] | None = None, pnl: dict[str, float] | None = None) -> None:
        self.level, self.share, self.pnl = level or {}, share or {}, pnl or {}

    def materiality(self, signal, pf=None):  # noqa: ANN001, ANN201
        return SimpleNamespace(level=self.level.get(signal.id, "LOW"), reached_share=self.share.get(signal.id, 0.1), portfolio_id="pf_test")

    def scenario(self, signal, pf=None):  # noqa: ANN001, ANN201
        has = signal.id in self.pnl
        return SimpleNamespace(scenario=object() if has else None, availability=Availability.AVAILABLE if has else Availability.ABSTAINED)

    def portfolio_stress(self, signal, pf=None, store=True):  # noqa: ANN001, ANN201
        return SimpleNamespace(run=SimpleNamespace(summary=SimpleNamespace(pnl_pct=self.pnl[signal.id]), run_id=f"run_{signal.id}"))


def monitor(base: list[RiskSignal] | None = None, *, assess: FakeAssess | None = None, prop: FakeProp | None = None, as_of: datetime | None = None, tmp: Path | None = None,
            step_hours: float = 24.0, **monitor_cfg) -> tuple[MonitorService, CombinedSignalRepository, IntelligenceService]:  # noqa: ANN003
    repo = CombinedSignalRepository(InMemorySignalRepository(base or [], as_of or (BASE + timedelta(days=3))), LiveSignalStore())
    intel = IntelligenceService(CFG, repo, scope_resolver(), clock=lambda: BASE + timedelta(days=1))
    cfg = dcfg(replay_step_hours=step_hours, **monitor_cfg)
    builder = StateBuilder(cfg.monitor, intelligence=lambda: intel, propagation=lambda: prop or FakeProp(), assessments=assess or FakeAssess())
    log = ChangeLog(tmp / "changes.jsonl" if tmp else None, cfg.monitor.store_max_changes)
    states = StateStore(tmp / "state.json" if tmp else None)
    return MonitorService(cfg, signals=repo, intelligence=lambda: intel, builder=builder, changelog=log, states=states, clock=lambda: BASE + timedelta(days=1)), repo, intel


def watch_service(base: list[RiskSignal], tmp: Path, *, assess: FakeAssess | None = None, prop: FakeProp | None = None, **monitor_cfg):  # noqa: ANN003, ANN201
    """A WatchlistService over real grouping/scope and the fake assessment/propagation answers; returns (service, monitor, repo)."""
    from eventshock.config import Settings, load_taxonomy
    from eventshock.domain import Entity
    from eventshock.watchlist.service import WatchlistService
    from eventshock.watchlist.store import WatchlistStore
    from eventshock.watchlist.vocabulary import build_vocabulary
    from tests.prop_helpers import book

    mon, repo, intel = monitor(base, assess=assess, prop=prop, tmp=tmp / "m", **monitor_cfg)
    entities = [Entity(entity_id="ENT_JPM", name="JPMorgan Chase", ticker="JPM", sector="Financials", country="US"),
                Entity(entity_id="ENT_XOM", name="Exxon Mobil", ticker="XOM", sector="Energy", country="US"),
                Entity(entity_id="ENT_GS", name="Goldman Sachs", ticker="GS", sector="Financials", country="US"),
                Entity(entity_id="ENT_KO", name="Coca-Cola", ticker="KO", sector="Consumer", country="US")]   # in the master, not in the test book
    cfg = mon.cfg.watchlist
    pf = book()
    taxonomy = load_taxonomy(Settings())
    vocab = lambda: build_vocabulary(CFG, ["Financials", "Energy", "Technology"], taxonomy, entities, cfg)  # noqa: E731
    fake_prop = prop or FakeProp()
    svc = WatchlistService(cfg, WatchlistStore(tmp / "w", max_watchlists=cfg.max_watchlists, clock=lambda: BASE), mon, vocabulary=vocab, intelligence=lambda: intel,
                           propagation=lambda: fake_prop, assessments=assess or FakeAssess(), portfolio=lambda p: p or pf, clock=lambda: BASE + timedelta(days=2))
    return svc, mon, repo
