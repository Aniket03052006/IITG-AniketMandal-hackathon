"""Historical analogues for one signal: embeds its text, searches the point-in-time index, and says what the market regime was then and now.

Read-only and additive, like ``signal_context``: nothing here is stored on ``RiskSignal`` (so replay digests are untouched) and nothing here feeds the severity
score or the stress trigger. Unavailable inputs (no index, no encoder for a new text) are reported as ``UNAVAILABLE`` with the reason, never as an empty answer
that looks like "no analogue".
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable

from ..domain import RiskSignal
from ..domain.scope import ScopeLevel
from ..pipeline.embeddings import EmbeddingSource, EmbeddingUnavailable
from ..retrieval.index import AnalogueIndex
from ..retrieval.model import AnalogueSet
from ..retrieval.search import SearchParams, search

MEMO = 256


def retrieval_scope(level: ScopeLevel) -> str:
    """The corpus a report is compared with: company reports for a company or a sector, market-wide reports for a market-wide one."""
    return "MARKET" if level is ScopeLevel.MARKET else "ISSUER"


def route(signal: RiskSignal) -> tuple[str, str | None, str | None]:
    """(corpus scope, sector filter, reason to refuse).

    UNRESOLVED reports are refused on purpose: the market-wide corpus pairs documents that name no listed company with the S&P 500's move, and for a report that could
    not be tied to a company, a sector or a market-wide theme that outcome would mean nothing. A sector report is compared with company reports of that sector only.
    """
    level = signal.scope.level
    if level is ScopeLevel.UNRESOLVED:
        return "MARKET", None, ("This report could not be tied to a company, a sector or a market-wide theme, so there is no market reaction it could be compared with. "
                                "Nothing is retrieved rather than something misleading.")
    if level is ScopeLevel.SECTOR:
        return "ISSUER", signal.scope.sector, None
    return retrieval_scope(level), None, None


class AnalogueService:
    def __init__(self, index: AnalogueIndex | None, params: SearchParams, embeddings: EmbeddingSource | None, *, unavailable_reason: str | None = None,
                 vix_now: Callable[[RiskSignal], tuple[float | None, str | None]] | None = None) -> None:
        self.index, self.params, self.embeddings = index, params, embeddings
        self._why = unavailable_reason or "no analogue index is loaded"
        self._vix_now = vix_now
        self._memo: OrderedDict[tuple[str, str], AnalogueSet] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.index is not None

    def _unavailable(self, reason: str, scope: str | None = None) -> AnalogueSet:
        return AnalogueSet(status="UNAVAILABLE", reason=reason, scope=scope, index_version=self.index.version if self.index else None)  # type: ignore[arg-type]

    def for_signal(self, signal: RiskSignal) -> AnalogueSet:
        doc = signal.document
        scope, sector, refuse = route(signal)
        if self.index is None:
            return self._unavailable(self._why, scope)
        if refuse is not None:
            return AnalogueSet(status="NO_RELIABLE_ANALOGUE", reason=refuse, scope=scope, query_date=doc.published_at.date().isoformat(),  # type: ignore[arg-type]
                               similarity_floor=self.params.similarity_floor, index_version=self.index.version)
        key = (signal.id, f"{doc.headline}|{doc.body}|{sector}")
        with self._lock:
            hit = self._memo.get(key)
            if hit is not None:
                self._memo.move_to_end(key)
                return hit
        if self.embeddings is None:
            return self._unavailable("Analogue search needs a sentence encoder for this text and none is configured.", scope)
        text = f"{doc.headline} {doc.body}".strip()
        try:
            vec = self.embeddings.embed([text])[0]
        except EmbeddingUnavailable as exc:
            return self._unavailable(f"Analogue search needs the sentence encoder for text it has not seen (pip install -r requirements-embed.txt): {exc}", scope)
        result = search(self.index, vec, query_date=doc.published_at.date().isoformat(), scope=scope, params=self.params, sector=sector, exclude_ids=frozenset({doc.id}))
        result = self._with_regime(signal, result)
        with self._lock:
            self._memo[key] = result
            while len(self._memo) > MEMO:
                self._memo.popitem(last=False)
        return result

    def _with_regime(self, signal: RiskSignal, result: AnalogueSet) -> AnalogueSet:
        """Adds the regime the report arrives in, next to the regimes of the analogues (their ``vix_level``), under the same freshness limits as severity."""
        if result.status != "OK" or self._vix_now is None:
            return result
        vix, as_of = self._vix_now(signal)
        then = [i.vix_level for i in result.items if i.vix_level is not None]
        if vix is None:
            note = "The market state at the time of this report is not available, so the regimes cannot be compared."
        else:
            note = f"VIX was {vix:.1f} at the last session before this report ({as_of})."
            if then:
                note += f" It was {min(then):.1f}-{max(then):.1f} around the analogues."
        return result.model_copy(update={"caveats": [*result.caveats, note]})
