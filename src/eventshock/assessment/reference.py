"""What the trained pipeline already said about a report: the *reference* the extractors compare against and fall back on.

It is a plain value object so the extractors can be tested on text alone (``Reference()`` = "no trained reading available").
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import EntityAudit, EntityMention, EventStatus, RiskSignal, SignalScope


@dataclass(frozen=True)
class Reference:
    event_category: str | None = None
    event_status: str | None = None
    event_confidence: float | None = None  # calibrated P(top class), when the trained model reports one
    sentiment: float | None = None
    sentiment_confidence: float | None = None
    entity: EntityMention | None = None
    entity_audit: EntityAudit | None = None
    scope: SignalScope | None = None

    @property
    def event_is_finding(self) -> bool:
        return self.event_category is not None and self.event_status == EventStatus.CLASSIFIED.value

    @classmethod
    def from_signal(cls, s: RiskSignal) -> Reference:
        prov = s.provenance
        conf = prov.event.confidence if prov and prov.event else None
        return cls(
            event_category=s.event.category.value, event_status=s.event.status.value,
            event_confidence=conf if conf is not None else s.event.confidence,
            sentiment=s.sentiment.score, sentiment_confidence=prov.sentiment.confidence if prov and prov.sentiment else None,
            entity=s.entity, entity_audit=prov.entity_audit if prov else None, scope=s.scope)


def analysed_text(headline: str, body: str) -> str:
    """The one string every extractor reads and every evidence offset indexes into."""
    return headline if not body.strip() else f"{headline}\n{body}"
