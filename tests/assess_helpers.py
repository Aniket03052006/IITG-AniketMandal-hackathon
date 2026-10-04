"""Builders for assessment tests: the vocabulary, the extractors, the scorer and a signal carrying an exact text."""

from __future__ import annotations

from datetime import timedelta

from eventshock.assessment.config import load_hybrid_config, load_semantics_config
from eventshock.assessment.extractor import SemanticExtractor
from eventshock.assessment.hybrid import HybridScorer
from eventshock.assessment.rules import RuleExtractor
from eventshock.assessment.service import AssessmentService
from eventshock.assessment.vocab import Vocab
from eventshock.config import REPO_ROOT, Settings, load_taxonomy
from eventshock.domain import (
    CorroboratingSource,
    EventCategory,
    EventClassification,
    EventStatus,
    RawDocument,
    SourceType,
)
from eventshock.llm.cache import ExtractionCache
from eventshock.llm.config import load_llm_config
from eventshock.pipeline.scope import ScopeResolver, load_scope_config
from eventshock.store import CombinedSignalRepository, InMemorySignalRepository, LiveSignalStore
from tests.helpers import NOW, make_signal

CONFIG_DIR = REPO_ROOT / "configs"
SCOPE_CFG = load_scope_config(CONFIG_DIR)
SCOPE = ScopeResolver(SCOPE_CFG)
SEM = load_semantics_config(CONFIG_DIR)
HYBRID = load_hybrid_config(CONFIG_DIR)
LLM_CFG = load_llm_config(CONFIG_DIR)
VOCAB = Vocab.build(SEM, SCOPE_CFG, {c.id.value: c.label for c in load_taxonomy(Settings(config_dir=CONFIG_DIR)).categories})
RULES = RuleExtractor(VOCAB, SCOPE)
SCORER = HybridScorer(HYBRID)


def extractor(client=None, *, cache: ExtractionCache | None = None, enabled: bool = True, why: str | None = None) -> SemanticExtractor:
    return SemanticExtractor(VOCAB, RULES, LLM_CFG.model_copy(update={"enabled": enabled}), client=client, cache=cache, unavailable_reason=why)


# ------------------------------------------------------------------------------------------------------------------ service builders


def signal_for(text: str, sid: str = "s1", *, no_event: bool = False, **kw):
    """A signal whose report text is exactly ``text`` (the headline). No company is resolved unless ``entity_id`` is given;
    ``no_event`` makes the trained event model's reading NO_EVENT (a PARTIAL signal), as it is for chatter."""
    kw.setdefault("entity_id", "UNKNOWN_ENTITY")
    if no_event:
        kw["impact"] = None
    s = make_signal(sid, **kw)
    if no_event:
        probs = {c: 0.1 for c in EventCategory}
        probs[EventCategory.MARKET_VALUATION] = 0.3  # the arg-max is only a best guess when the status is NO_EVENT
        ev = EventClassification(category=EventCategory.MARKET_VALUATION, probabilities=probs, status=EventStatus.NO_EVENT, no_event_probability=0.95)
        s = s.model_copy(update={"event": ev})
    doc = RawDocument(id=f"d_{sid}", source="Wire", source_type=SourceType.NEWS, published_at=NOW - timedelta(hours=1), ingested_at=NOW, headline=text)
    return s.model_copy(update={"document": doc})


def with_later_reports(s, n: int):
    """The same signal after ``n`` further outlets reported the story, each AFTER the original report."""
    t0 = s.document.published_at
    extra = [CorroboratingSource(source=f"Later{i}", source_type=SourceType.NEWS, published_at=t0 + timedelta(hours=i + 1), headline=s.document.headline)
             for i in range(n)]
    ev = s.evidence.model_copy(update={"source_count": s.evidence.source_count + n, "unique_domain_count": s.evidence.unique_domain_count + n,
                                       "corroborating": [*s.evidence.corroborating, *extra]})
    return s.model_copy(update={"evidence": ev})


def service(signals, *, client=None, enabled: bool = False, threshold: float = 7.0) -> AssessmentService:
    from eventshock.config import StressConfig

    repo = CombinedSignalRepository(InMemorySignalRepository(list(signals), NOW), LiveSignalStore())
    return AssessmentService(extractor(client, enabled=enabled), SCORER, repo, stress=StressConfig(trigger_threshold=threshold), clock=lambda: NOW)
