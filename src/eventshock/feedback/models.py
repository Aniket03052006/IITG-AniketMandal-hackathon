"""Contracts of the analyst-feedback side-car."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from ..domain.base import ContractModel

VERSION = "feedback-v1"
LABEL = "ANALYST FEEDBACK — not ground truth, and not used to train or change any model"


class FeedbackType(StrEnum):
    RELEVANCE = "RELEVANCE"
    SCOPE = "SCOPE"
    EVENT = "EVENT"


class FeedbackValue(StrEnum):
    RELEVANT = "RELEVANT"
    PARTIALLY_RELEVANT = "PARTIALLY_RELEVANT"
    IRRELEVANT = "IRRELEVANT"
    CORRECT = "CORRECT"
    INCORRECT = "INCORRECT"


ALLOWED = {
    FeedbackType.RELEVANCE: (FeedbackValue.RELEVANT, FeedbackValue.PARTIALLY_RELEVANT, FeedbackValue.IRRELEVANT),
    FeedbackType.SCOPE: (FeedbackValue.CORRECT, FeedbackValue.INCORRECT),
    FeedbackType.EVENT: (FeedbackValue.CORRECT, FeedbackValue.INCORRECT),
}
NEGATIVE = (FeedbackValue.IRRELEVANT, FeedbackValue.INCORRECT)


class FeedbackInput(ContractModel):
    event_id: str = Field(min_length=1, max_length=64, description="an event id (evt_...) or the id of any signal in it")
    type: FeedbackType
    value: FeedbackValue
    comment: str | None = Field(default=None, max_length=5000)
    analyst_id: str | None = Field(default=None, max_length=64, description="who is giving it; the X-Analyst-Id header is used when this is empty; 'anonymous' otherwise")
    cycle: int | None = Field(default=None, ge=0, description="the replay cycle the analyst was looking at, when there was one")

    @model_validator(mode="after")
    def _pair(self) -> FeedbackInput:
        if self.value not in ALLOWED[self.type]:
            raise ValueError(f"{self.value.value} is not a {self.type.value} answer: use {', '.join(v.value for v in ALLOWED[self.type])}")
        return self


class Feedback(ContractModel):
    feedback_id: str
    event_id: str
    signal_id: str | None
    analyst_id: str
    type: FeedbackType
    value: FeedbackValue
    comment: str | None
    created_at: datetime
    portfolio_id: str | None = None
    cycle: int | None = None
    label: str = LABEL


class TypeStats(ContractModel):
    type: FeedbackType
    total: int
    by_value: dict[str, int]
    agreement: float | None = Field(description="CORRECT / all for SCOPE and EVENT; RELEVANT / all for RELEVANCE; null with no feedback")
    at_least_partly_relevant: float | None = Field(default=None, description="RELEVANCE only: (RELEVANT + PARTIALLY_RELEVANT) / all")


class FeedbackStats(ContractModel):
    version: str = VERSION
    label: str = LABEL
    volume: int
    events: int
    analysts: int
    relevance: TypeStats
    scope: TypeStats
    event: TypeStats
    needs_review: int = Field(description="event/type pairs whose latest answer from at least one analyst is negative (IRRELEVANT or INCORRECT)")
    disagreements: int = Field(description="event/type pairs where analysts' latest answers point both ways")
    first_at: datetime | None
    last_at: datetime | None
    note: str
    limitations: list[str]


class FeedbackList(ContractModel):
    label: str = LABEL
    total: int
    items: list[Feedback]
