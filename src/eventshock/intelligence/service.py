"""The event-intelligence service: one derived view per signal, assembled from the signal, the events around it and the existing layers.

Nothing here is stored on a ``RiskSignal``. The service reads the signal repository (replay, live and pasted signals alike, so a manual
analysis gets exactly the treatment a live report gets), groups signals into events, and returns an ``EventIntelligence`` whose every
section can abstain with a reason. It reuses, rather than reimplements: the entity resolver's result (``signal.entity``), the pipeline's
scope vocabulary, the assessment layer's reading and severity, the relevance service, and the deterministic stress engine.

Time: every section is computed from reports published at or before ``as_of`` (future-invariance is tested). For a replay signal the
default ``as_of`` is the last report of its event (labelled LAST_REPORT, not the end of the snapshot); for live and pasted signals it is
the clock now.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

from ..assessment.model import RiskAssessment
from ..assessment.vocab import NO_EVENT
from ..domain import (
    UNKNOWN_ENTITY,
    EventCategory,
    EventStatus,
    Portfolio,
    RiskSignal,
    ScopeLevel,
    StressStatus,
)
from ..services.relevance import RelevanceService
from ..services.stress_service import SignalNotFound, StressService, _binds
from ..store import CHANNEL_REPLAY, CombinedSignalRepository
from ..stress.scenarios import ScenarioCatalog
from .claims import ClaimExtractor, _Claim, overall_state
from .config import IntelligenceConfig
from .evidence import build_evidence_profile
from .grouping import Event, EventIndex, GReport, mark_independence
from .lifecycle import LifecycleEngine
from .model import (
    VERSION,
    Abstention,
    AffectedEntity,
    AffectedRiskFactor,
    AffectedSector,
    AffectedView,
    Availability,
    ConflictState,
    ContradictionView,
    EventGroup,
    EventHeadline,
    EventIntelligence,
    EventScope,
    IntelligenceProvenance,
    LifecycleView,
    ReportRef,
    ResolutionStatus,
    ScopeType,
    StressPreview,
)
from .novelty import NoveltyClassifier
from .scope import HierarchicalScopeResolver
from .velocity import build_velocity

LABELS = [
    "Scope: deterministic vocabulary rules (RULES); the confidence is a rule tier, not a probability.",
    "Event grouping, novelty class, velocity, contradiction and lifecycle: rules over reports and timestamps (RULES); every threshold is a judgement prior, unvalidated.",
    "Evidence strength: a tier from countable facts. Model confidence: what a model says of its own output. Never combined.",
    "Affected risk factors: a vocabulary link or a configured scenario shock (ASSUMPTION), never a measured exposure.",
    "Portfolio relevance: the book's own holdings (OBSERVED). Stress: a modeled outcome under an illustrative scenario, not a forecast.",
]

LIMITATIONS = [
    "Claim extraction reads a closed list of cue phrases, so it misses paraphrase and can read a figure of speech as a claim; it never invents one.",
    "Reports folded into a cluster keep their headline only, so claims are read from the first report's full text and from the others' headlines.",
    "Grouping, novelty, lifecycle and evidence thresholds are judgement priors written before any result was seen; none is fitted or validated.",
    "A replay report whose source gave no time has a time the replay assigned: such events are not grouped, and velocity, lifecycle and novelty abstain.",
    "Authoritative sources come from a closed list: a source not on it is 'not known to be authoritative', not 'known not to be'.",
    "Novelty looks back only over the signals EventShock holds (the replay window and the live overlay).",
]


class IntelligenceService:
    def __init__(self, cfg: IntelligenceConfig, signals: CombinedSignalRepository, scope: HierarchicalScopeResolver, *,
                 assessments=None, relevance: RelevanceService | None = None, stress: StressService | None = None,  # noqa: ANN001
                 catalog: ScenarioCatalog | None = None, snapshot_id: str | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.cfg = cfg
        self._signals = signals
        self._scope = scope
        self._assess = assessments
        self._relevance = relevance
        self._stress = stress
        self._catalog = catalog
        self._snapshot_id = snapshot_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._auth = frozenset(cfg.sources.authoritative_domains)
        self._copy = set(cfg.sources.copy_relations)
        self._claims = ClaimExtractor(cfg.claims, self._auth)
        self._life = LifecycleEngine(cfg.lifecycle, self._auth)
        self._novelty = NoveltyClassifier(cfg.novelty)
        self._lock = threading.RLock()
        self._index_key: tuple | None = None
        self._index_obj: EventIndex | None = None
        self._memo: dict[tuple, dict] = {}

    # ------------------------------------------------------------------------------------------------------------------ index
    def index(self) -> EventIndex:
        key = (self._signals.seq, len(self._signals.base._signals))  # noqa: SLF001 (the replay base is immutable; live changes bump seq)
        with self._lock:
            if self._index_obj is None or self._index_key != key:
                self._index_obj = EventIndex(self._signals.list(), self.cfg)
                self._index_key = key
                self._memo.clear()
            return self._index_obj

    # ------------------------------------------------------------------------------------------------------------------ public
    def scope_of(self, signal: RiskSignal) -> EventScope:
        """The hierarchical scope alone (cheap: no grouping): used by the feed row and its filter."""
        with self._lock:
            key = ("scope", signal.id, signal.created_at, signal.document.id)
            hit = self._memo.get(key)
            if hit is None:
                hit = {"scope": self._scope.resolve(signal)}
                self._memo[key] = hit
            return hit["scope"]

    def for_signal(self, signal: RiskSignal, *, as_of: datetime | None = None, portfolio: Portfolio | None = None,
                   include_stress: bool = True) -> EventIntelligence:
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise ValueError("as_of must include a time zone")
        idx = self.index()
        event = idx.event_of(signal.id)
        if event is None:
            raise LookupError(f"signal {signal.id!r} is not in the event index")
        channel = self._signals.channel_of(signal.id)
        all_reports = event.reports()
        last_all = max(r.published_at for r in all_reports)
        if as_of is not None:
            when, basis = as_of.astimezone(UTC), "REQUESTED"
        elif channel == CHANNEL_REPLAY:
            when, basis = last_all, "LAST_REPORT"
        else:
            when, basis = max(self._clock(), last_all), "NOW"
        first_all = min(r.published_at for r in all_reports)
        if when < first_all:
            raise ValueError("as_of precedes the first report of this event")
        key = (signal.id, signal.created_at, signal.evidence.source_count, self._index_key, when.isoformat())
        with self._lock:
            core = self._memo.get(key)
        if core is None:
            core = self._core(signal, event, idx, when)
            with self._lock:
                self._memo[key] = core
        a = self._assess.detail(signal) if self._assess is not None else None
        return self._assemble(signal, event, core, a, when, basis, channel, portfolio, include_stress)

    # -------------------------------------------------------------------------------------------------------------------- core
    def _cut(self, event: Event, when: datetime) -> list[GReport]:
        return mark_independence([r for r in event.reports() if r.published_at <= when], self._copy)

    def _claims_of(self, reports: list[GReport], idx: EventIndex) -> list[_Claim]:
        out: list[_Claim] = []
        for r in reports:
            ent = idx.nodes[r.signal_id].signal.entity if r.signal_id in idx.nodes else None
            known = ent is not None and ent.entity_id != UNKNOWN_ENTITY
            out += self._claims.extract(r, ent.entity_id if known else None, ent.entity_name if known else None)  # type: ignore[union-attr]
        return out

    def _core(self, signal: RiskSignal, event: Event, idx: EventIndex, when: datetime) -> dict:
        reports = self._cut(event, when)
        trusted = event.trusted
        scope = self._scope.resolve(signal)
        claims = self._claims_of(reports, idx)
        conflicts, sequential = self._claims.detect(claims)
        state = overall_state(conflicts)
        method = ("Closed-lexicon claim extraction over each report's clauses; opposite poles of one axis from different reports that share a topic, "
                  f"within {self.cfg.claims.conflict_window_hours:g} h, are a conflict. Sentiment variance is never used.")
        if not claims:
            contradiction = ContradictionView(
                availability=Availability.PARTIAL, state=ConflictState.NO_CONFLICT, claims_extracted=0, conflicts=[], sequential_changes=[], method=method,
                reason="No claim on a tracked axis (confirmed/denied, open/closed, completed/cancelled, running/shut down, guidance raised/cut, approved/rejected) "
                       "was found, so no conflict could be detected. That is absence of evidence, not evidence that the reports agree.")
        else:
            contradiction = ContradictionView(
                availability=Availability.AVAILABLE, state=state, claims_extracted=len(claims), conflicts=conflicts, sequential_changes=sequential, method=method)

        cache: dict[datetime, bool] = {}

        def open_at(t: datetime) -> bool:
            if t not in cache:
                cs, _ = self._claims.detect([c for c in claims if c.time <= t])
                cache[t] = any(c.state is ConflictState.CONFLICTED for c in cs)
            return cache[t]

        if trusted:
            st, since, trans = self._life.run(reports, open_at, when)
            lifecycle = LifecycleView(
                availability=Availability.AVAILABLE, state=st, since=since, first_seen=reports[0].published_at, last_updated=reports[-1].published_at,
                as_of=when, as_of_basis="", transitions=trans)
        else:
            lifecycle = LifecycleView(
                availability=Availability.UNAVAILABLE, reason="The report timestamps were assigned by the replay, not published by the source, so the "
                "event's life cannot be followed.", state=None, since=None, first_seen=None, last_updated=None, as_of=None, as_of_basis="", transitions=[])
        velocity = build_velocity(reports, self.cfg.velocity, trusted=trusted)

        def state_of_prior(p: Event, at: datetime) -> str | None:
            prs = self._cut(p, at)
            if not prs or not p.trusted:
                return None
            s, _, _ = self._life.run(prs, lambda _t: False, at)
            return s.value if s else None

        first_seen = reports[0].published_at
        novelty = self._novelty.classify(signal, event, idx, first_seen, trusted=trusted, state_of_prior=state_of_prior)
        evidence = build_evidence_profile(signal, reports, scope.scope_confidence.tier, state, self.cfg.evidence, self._auth, trusted)
        return {"reports": reports, "scope": scope, "contradiction": contradiction, "lifecycle": lifecycle, "velocity": velocity, "novelty": novelty,
                "evidence": evidence, "trusted": trusted}

    # ----------------------------------------------------------------------------------------------------------------- assemble
    def _assemble(self, signal: RiskSignal, event: Event, core: dict, a: RiskAssessment | None, when: datetime, basis: str, channel: str,
                  portfolio: Portfolio | None, include_stress: bool) -> EventIntelligence:
        reports: list[GReport] = core["reports"]
        t0 = signal.document.published_at
        refs = [ReportRef(id=r.id, signal_id=r.signal_id, source=r.source, source_type=r.source_type, domain=r.domain, url=r.url,
                          published_at=r.published_at, headline=r.headline, relation=r.relation, independent=r.independent, clock_trusted=r.trusted,
                          phase="AT_REPORT" if r.published_at == t0 and r.relation == "CANONICAL" and r.signal_id == signal.id
                          else "AFTER_REPORT" if r.published_at > t0 else "BEFORE_REPORT") for r in reports[:300]]
        group = EventGroup(
            event_id=event.id, anchor_signal_id=event.anchor.signal.id, signal_ids=event.signal_ids, headline=event.anchor.signal.document.headline,
            report_count=len(reports), independent_sources=sum(1 for r in reports if r.independent), first_seen=reports[0].published_at if reports else None,
            last_seen=reports[-1].published_at if reports else None, reports=refs,
            grouping_note=(f"{len(event.nodes)} report cluster(s) grouped into this event by issuer or scope, event class, wording and shared facts within "
                           f"{self.cfg.grouping.window_hours:g} h; each report is kept below." if len(event.nodes) > 1 else
                           "One report cluster: no other cluster met the grouping rules (same subject, class, close wording and shared facts, within the window)."
                           if event.trusted else "This event's report times were assigned by the replay, so it is never grouped with another."))
        lifecycle = core["lifecycle"].model_copy(update={"as_of": when if core["trusted"] else None, "as_of_basis": basis})
        evidence = core["evidence"]
        scope: EventScope = core["scope"]
        prov = signal.provenance
        provenance = IntelligenceProvenance(
            channel=channel, adapter=prov.adapter if prov else str(signal.document.raw_metadata.get("adapter", "unknown")),
            timestamp_origin=prov.timestamp_origin.value if prov else "UNKNOWN", clock_trusted=bool(core["trusted"]),
            content_sha256=prov.content_sha256 if prov else str(signal.document.raw_metadata.get("content_sha256", "")), snapshot_id=prov.snapshot_id if prov else None)

        contradiction = core["contradiction"]
        if a is not None and a.conflict is not None:
            contradiction = contradiction.model_copy(update={"tone_divergence": a.conflict})
        relevance = self._relevance.assess(signal, portfolio=portfolio) if self._relevance is not None else None
        stress = self._stress_preview(signal, a, portfolio) if include_stress else StressPreview(
            availability=Availability.ABSTAINED, reason="not requested")
        affected = self._affected(signal, scope, a)
        headline = EventHeadline(
            headline=signal.document.headline, event_type=a.reading.event_type if a else signal.event.category.value,
            event_label=a.reading.event_label if a else None, event_subtype_label=a.reading.event_subtype_label if a else None,
            event_status=signal.event.status.value, sentiment=a.reading.sentiment if a else signal.sentiment.score,
            sentiment_label=a.reading.sentiment_label if a else None, severity_score=a.severity.score if a and a.severity else None,
            severity_band=a.severity.band if a and a.severity else None, impact_score=signal.impact.score if signal.impact else None,
            impact_origin=(None if signal.impact is None or prov is None else "MODEL" if prov.stage_origins.get("impact") == "MODEL" else "PLACEHOLDER"),
            extraction_mode=a.extraction.mode.value if a else None)
        return EventIntelligence(
            signal_id=signal.id, version=VERSION, as_of=when, as_of_basis=basis, event=headline, group=group, provenance=provenance, scope=scope,
            evidence=evidence, novelty=core["novelty"], velocity=core["velocity"], contradiction=contradiction, lifecycle=lifecycle, affected=affected,
            relevance=relevance, stress=stress, abstentions=self._abstentions(signal, scope, a, core, relevance, stress, lifecycle),
            labels=LABELS, limitations=LIMITATIONS)

    # ---------------------------------------------------------------------------------------------------------------- affected
    def _affected(self, signal: RiskSignal, scope: EventScope, a: RiskAssessment | None) -> AffectedView:
        llm = a is not None and a.extraction.mode.value == "LLM"
        entities: list[AffectedEntity] = []
        if a is not None:
            for e in a.reading.entities:
                entities.append(AffectedEntity(name=e.name, kind=e.kind, role=e.role, resolved=e.resolved, entity_id=e.entity_id, ticker=e.ticker,
                                               origin="AI" if llm else "RULES"))
        elif signal.entity.entity_id != UNKNOWN_ENTITY:
            entities.append(AffectedEntity(name=signal.entity.entity_name or signal.entity.entity_id, kind="COMPANY", role="subject", resolved=True,
                                           entity_id=signal.entity.entity_id, ticker=signal.entity.ticker, origin="DATA"))
        sectors: dict[str, AffectedSector] = {}
        for n in scope.scope_path:
            if n.type is ScopeType.SECTOR:
                sectors[n.value] = AffectedSector(sector=n.value, origin="DATA" if n.basis == "ENTITY_MASTER" else "RULES", basis=f"scope path ({n.basis.lower()})")
        for s in scope.candidates:
            if scope.resolution_status is ResolutionStatus.AMBIGUOUS and s in {x for x in self._sector_names()}:
                sectors.setdefault(s, AffectedSector(sector=s, origin="RULES", basis="tied with another sector: listed, not chosen"))
        if a is not None:
            for s in a.reading.sectors:
                sectors.setdefault(s, AffectedSector(sector=s, origin="AI" if llm else "RULES", basis="read from the text by the assessment layer"))
        regions: list[str] = []
        for n in [*scope.scope_path, *scope.secondary]:
            if n.type is ScopeType.GEOGRAPHY and n.value not in regions:
                regions.append(n.value)
        if a is not None:
            for r in a.reading.regions:
                nm = self._scope.region_name(r)
                if nm not in regions:
                    regions.append(nm)
        factors: dict[str, AffectedRiskFactor] = {}
        themes = list(signal.scope.themes) if signal.scope else []
        for rf, th in self._scope.risk_factors_for(themes):
            factors[rf] = AffectedRiskFactor(factor=rf, origin="VOCABULARY", basis=f"the text uses {th.replace('_', ' ')} vocabulary")
        scn, bound = self._scenario(signal, a)
        if scn is not None and signal.scope is not None:
            sc = signal.scope
            known = sc.level is ScopeLevel.COMPANY and signal.entity.entity_id != UNKNOWN_ENTITY
            sector = sc.sector if sc.has_sector else (a.reading.sectors[0] if a and a.reading.sectors else None)
            for s in scn.shocks:
                if _binds(s.scope, ScopeLevel.SECTOR if (sector and not sc.has_sector) else sc.level, known, sector)[0]:
                    factors.setdefault(s.factor.value, AffectedRiskFactor(
                        factor=s.factor.value, origin="SCENARIO", basis=f"the default scenario ({scn.name}) applies a {s.scope.value.lower()} shock to it: an assumption"))
        note = ("Entities and sectors are what the text names or implies. Risk factors are a vocabulary link or a configured scenario shock: an assumption, "
                "never a measured exposure.")
        return AffectedView(entities=entities, sectors=list(sectors.values()), regions=regions, risk_factors=list(factors.values()), note=note)

    def _sector_names(self) -> list[str]:
        return list(self._scope.resolver.cfg.sectors)

    def _scenario(self, signal: RiskSignal, a: RiskAssessment | None):  # noqa: ANN202
        if self._catalog is None:
            return None, False
        if a is not None:
            if a.reading.event_type == NO_EVENT:
                return None, False
            return self._catalog.default_for(EventCategory(a.reading.event_type)), True
        if signal.event.status is EventStatus.NO_EVENT:
            return None, False
        return self._catalog.default_for(signal.event.category), True

    # ------------------------------------------------------------------------------------------------------------------ stress
    def _stress_preview(self, signal: RiskSignal, a: RiskAssessment | None, portfolio: Portfolio | None) -> StressPreview:
        if self._stress is None:
            return StressPreview(availability=Availability.UNAVAILABLE, status="UNAVAILABLE", reason="the stress engine is not running in this profile")
        try:
            r = self._stress.run(signal.id, portfolio=portfolio)
        except SignalNotFound:
            return StressPreview(availability=Availability.UNAVAILABLE, status="UNAVAILABLE", reason="the signal is not in the repository")
        sev = a.severity.score if a and a.severity else None
        trig = a.threshold.threshold if a and a.threshold else None
        base = dict(status=r.status.value, reason=r.reason, scenario_id=r.scenario.id if r.scenario else None,
                    scenario_name=r.scenario.name if r.scenario else None, severity_score=sev, trigger_threshold=trig, run_id=r.run_id)
        if r.status is StressStatus.COMPLETED and r.summary is not None:
            return StressPreview(availability=Availability.AVAILABLE, baseline_value=r.summary.baseline_value, stressed_value=r.summary.stressed_value,
                                 pnl=r.summary.pnl, pnl_pct=r.summary.pnl_pct, **base)
        avail = Availability.UNAVAILABLE if r.status is StressStatus.UNAVAILABLE else Availability.ABSTAINED
        return StressPreview(availability=avail, **base)

    # ------------------------------------------------------------------------------------------------------------- abstentions
    def _abstentions(self, signal: RiskSignal, scope: EventScope, a: RiskAssessment | None, core: dict, relevance, stress: StressPreview,  # noqa: ANN001
                     lifecycle: LifecycleView) -> list[Abstention]:
        out: list[Abstention] = []
        if signal.entity.entity_id == UNKNOWN_ENTITY:
            out.append(Abstention(field="company", state="UNKNOWN", reason="no listed company was named in the text"))
        if not any(n.type is ScopeType.SECTOR for n in scope.scope_path):
            out.append(Abstention(field="sector", state="UNKNOWN", reason=scope.reason if scope.scope_type is ScopeType.UNRESOLVED else "no sector is named or implied"))
        if scope.scope_type is ScopeType.UNRESOLVED:
            out.append(Abstention(field="scope", state="UNKNOWN", reason=scope.reason))
        if signal.impact is None:
            out.append(Abstention(field="impact", state="UNAVAILABLE", reason=signal.status_reason or "no impact was scored for this signal"))
        if a is not None and a.severity is None:
            out.append(Abstention(field="severity", state="UNAVAILABLE", reason=a.severity_note or "the text does not describe a market event"))
        nv = core["novelty"]
        if nv.availability is not Availability.AVAILABLE:
            out.append(Abstention(field="novelty", state=nv.availability.value, reason=nv.reason or ""))
        vel = core["velocity"]
        if vel.availability in (Availability.UNAVAILABLE, Availability.ABSTAINED):
            out.append(Abstention(field="velocity", state=vel.availability.value, reason=vel.reason or ""))
        if lifecycle.availability is not Availability.AVAILABLE:
            out.append(Abstention(field="lifecycle", state=lifecycle.availability.value, reason=lifecycle.reason or ""))
        if core["contradiction"].availability is not Availability.AVAILABLE:
            out.append(Abstention(field="contradiction", state="ABSTAINED", reason=core["contradiction"].reason or ""))
        if relevance is not None and relevance.level.value == "UNDETERMINED":
            out.append(Abstention(field="portfolio relevance", state="UNKNOWN", reason=relevance.summary))
        if stress.availability is not Availability.AVAILABLE and stress.reason:
            out.append(Abstention(field="portfolio stress", state=stress.status or "UNAVAILABLE", reason=stress.reason))
        return out
