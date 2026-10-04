"""The one door to semantic extraction: cache -> language model -> grounding, with the rule extractor as the labelled fallback.

Every path returns a reading and an ``ExtractionInfo`` that says which path produced it. A provider problem (no key, timeout, rate limit, rejected
key, malformed answer) is never an exception to the caller: it becomes ``fallback_reason`` on the result and the rule extractor serves.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..domain import EventCategory
from ..llm.cache import ExtractionCache, cache_key
from ..llm.client import LLMBadOutput, LLMClient, LLMError, LLMRateLimited
from ..llm.config import LLMConfig
from ..llm.prompt import PROMPT_VERSION, SYSTEM, user_message
from ..llm.schema import TOOL_NAME, LLMExtraction, tool_schema
from .grounding import ground
from .model import ExtractionInfo, ExtractionMode, SemanticReading
from .reference import Reference
from .rules import RuleExtractor
from .vocab import NO_EVENT, Vocab

log = logging.getLogger("eventshock")


@dataclass
class ExtractorStats:
    llm_calls: int = 0
    cache_hits: int = 0
    fallbacks: int = 0
    last_fallback_reason: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self, name: str, reason: str | None = None) -> None:
        with self._lock:
            setattr(self, name, getattr(self, name) + 1)
            if reason:
                self.last_fallback_reason = reason


class SemanticExtractor:
    def __init__(self, vocab: Vocab, rules: RuleExtractor, cfg: LLMConfig, *, client: LLMClient | None = None,
                 cache: ExtractionCache | None = None, unavailable_reason: str | None = None) -> None:
        self.vocab, self._rules, self._cfg = vocab, rules, cfg
        self._client, self._cache = client, cache
        self._unavailable = unavailable_reason  # why an enabled LLM has no client (e.g. no key)
        self.stats = ExtractorStats()
        self._calls: deque[float] = deque()  # monotonic times of recent provider calls (the local cost guard)
        self._clock = time.monotonic
        self._guard = threading.Lock()
        subtypes = sorted({s.id for subs in vocab.cfg.subtypes.values() for s in subs} | {"other"})
        self._schema = tool_schema(
            event_types=[*(c.value for c in EventCategory), NO_EVENT], subtypes=subtypes, sectors=list(vocab.sectors),
            regions=list(vocab.regions), asset_classes=list(vocab.cfg.asset_classes), indicators=list(vocab.cfg.indicators))

    # ------------------------------------------------------------------------------------------------------------------ status
    @property
    def llm_ready(self) -> bool:
        return self._client is not None

    def status(self) -> dict[str, object]:
        mode = "LLM" if self.llm_ready else "RULES"
        return {"mode": mode, "enabled": self._cfg.enabled, "model": self._client.model_id if self._client else None,
                "reason": None if self.llm_ready else (self._unavailable or "the language model is switched off (rule-based demo mode)"),
                "llm_calls": self.stats.llm_calls, "cache_hits": self.stats.cache_hits, "fallbacks": self.stats.fallbacks,
                "last_fallback_reason": self.stats.last_fallback_reason}

    def _allow_call(self) -> bool:
        """A sliding one-minute window over provider calls: a demo left open cannot run up a bill, and the rules serve meanwhile."""
        now = self._clock()
        with self._guard:
            while self._calls and now - self._calls[0] > 60.0:
                self._calls.popleft()
            if len(self._calls) >= self._cfg.max_calls_per_minute:
                return False
            self._calls.append(now)
            return True

    # ---------------------------------------------------------------------------------------------------------------------- run
    def extract(self, text: str, ref: Reference, *, use_llm: bool = True) -> tuple[SemanticReading, ExtractionInfo]:
        if not use_llm or self._client is None:
            reading, info = self._rules.extract(text, ref)
            if use_llm and self._unavailable and self._cfg.enabled:
                info = info.model_copy(update={"fallback_reason": self._unavailable})
            return reading, info
        sent = text[: self._cfg.max_chars_sent]
        key = cache_key(sent, self._client.model_id, PROMPT_VERSION, self.vocab.cfg.version)
        cached = self._cache.get(key) if self._cache is not None else None
        try:
            if cached is not None:
                raw = LLMExtraction.model_validate(cached)
                self.stats.bump("cache_hits")
            else:
                if not self._allow_call():
                    raise LLMRateLimited(f"local limit of {self._cfg.max_calls_per_minute} calls per minute reached")
                answer = self._client.extract(system=SYSTEM, user=user_message(sent), tool_name=TOOL_NAME, tool_schema=self._schema)
                self.stats.bump("llm_calls")
                try:
                    raw = LLMExtraction.model_validate(answer)
                except ValidationError as exc:
                    raise LLMBadOutput(f"schema check failed: {exc.errors()[0]['loc']}") from exc
            reading, notes = ground(raw, text, ref, self.vocab, self._cfg.grounding)
        except (LLMError, ValidationError) as exc:
            reason = exc.reason if isinstance(exc, LLMError) else LLMBadOutput.reason
            detail = f"{reason} ({exc})" if str(exc) else reason
            log.warning("llm extraction fell back to rules: %s", detail)
            self.stats.bump("fallbacks", detail)
            reading, info = self._rules.extract(text, ref)
            return reading, info.model_copy(update={"fallback_reason": detail})
        if cached is None and self._cache is not None:
            self._cache.put(key, raw.model_dump())
        info = ExtractionInfo(
            mode=ExtractionMode.LLM, model_id=self._client.model_id, vocabulary_version=self.vocab.cfg.version,
            prompt_version=PROMPT_VERSION, cached=cached is not None, notes=notes,
            basis=("A language model filled a closed schema from the text alone; every entity and quote was checked against the text. "
                   "It does not score severity: that is computed separately from explicit weights."))
        return reading, info
