"""What the language model is asked to return, as a pydantic model (validation) and a JSON schema (the forced tool call).

The vocabulary lists (event classes, subtypes, sectors, regions, asset classes, indicators) are put into the schema as ``enum`` so the provider
constrains the answer, and they are checked again on our side by ``assessment.grounding``: a provider's constraint is a convenience, not a guarantee.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LLMEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    surface: str = Field(min_length=1, max_length=120)
    kind: str = "OTHER"
    role: str = "mentioned"


class LLMQuote(BaseModel):
    model_config = ConfigDict(extra="ignore")
    quote: str = Field(min_length=1, max_length=400)
    supports: str = "event_type"


class LLMIndicator(BaseModel):
    """A severity indicator the model sees in the report: its id, the verbatim phrase that shows it (if there is one) and why."""

    model_config = ConfigDict(extra="ignore")
    id: str
    quote: str | None = Field(default=None, max_length=300)
    reason: str = Field(default="", max_length=240)


class LLMRubricAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str | int
    reason: str = Field(default="", max_length=300)
    quote: str | None = Field(default=None, max_length=300)


class LLMRubric(BaseModel):
    model_config = ConfigDict(extra="ignore")
    magnitude: LLMRubricAnswer | None = None
    reach: LLMRubricAnswer | None = None
    certainty: LLMRubricAnswer | None = None
    direction: LLMRubricAnswer | None = None


class LLMExtraction(BaseModel):
    """The model's answer. Every field but the required few has a safe default so a thin answer degrades instead of failing."""

    model_config = ConfigDict(extra="ignore")
    event_type: str
    event_subtype: str = "other"
    event_confidence: float = Field(default=0.5, ge=0, le=1)
    sentiment: float = Field(default=0.0, ge=-1, le=1)
    sentiment_intensity: str = "medium"
    sentiment_confidence: float | None = Field(default=None, ge=0, le=1)
    entities: list[LLMEntity] = []
    sectors: list[str] = []
    regions: list[str] = []
    affected_asset_classes: list[str] = []
    severity_indicators: list[LLMIndicator | str] = []
    rubric: LLMRubric | None = None
    uncertainty: float = Field(default=0.5, ge=0, le=1)
    evidence: list[LLMQuote] = []
    rationale: str = Field(default="", max_length=400)


TOOL_NAME = "record_assessment"


def _answer(value: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": {
        "value": value,
        "reason": {"type": "string", "description": "one sentence: why this level, in terms of the event's own scale (not the tone of the wording)"},
        "quote": {"type": ["string", "null"], "description": "optional: a short VERBATIM phrase from the text that supports it"}},
        "required": ["value", "reason"]}


def tool_schema(*, event_types: list[str], subtypes: list[str], sectors: list[str], regions: list[str], asset_classes: list[str],
                indicators: list[str], reach: list[str], certainty: list[str], direction: list[str]) -> dict[str, Any]:
    """The tool's ``input_schema``. A forced tool call is the structured-output mechanism: the reply is JSON, never prose."""

    def enum_list(values: list[str]) -> dict[str, Any]:
        return {"type": "array", "items": {"type": "string", "enum": values}}

    def soft_list(values: list[str], what: str) -> dict[str, Any]:
        """A list the provider does NOT enforce: a value outside the vocabulary would make the provider reject the whole call, which costs a retry and often ends in
        the rules. Grounding checks every value and drops (and reports) any that is not allowed, so the vocabulary is still the only thing that gets through."""
        return {"type": "array", "items": {"type": "string"}, "description": f"{what}; allowed values only: {', '.join(values)}"}

    return {
        "type": "object",
        "properties": {
            "event_type": {"type": "string", "enum": event_types},
            "event_subtype": {"type": "string", "enum": subtypes},
            "event_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "sentiment": {"type": "number", "minimum": -1, "maximum": 1,
                          "description": "tone of the report toward the affected parties: -1 very adverse .. +1 very favourable"},
            "sentiment_intensity": {"type": "string", "enum": ["low", "medium", "high"]},
            "sentiment_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "entities": {"type": "array", "items": {"type": "object", "properties": {
                "surface": {"type": "string", "description": "the name EXACTLY as written in the text"},
                "kind": {"type": "string", "enum": ["COMPANY", "INSTITUTION", "REGULATOR", "GOVERNMENT", "OTHER"]},
                "role": {"type": "string", "enum": ["subject", "counterparty", "mentioned"]}},
                "required": ["surface", "kind", "role"]}},
            "sectors": soft_list(sectors, "sectors the text is about"),
            "regions": soft_list(regions, "geographies the text points to"),
            "affected_asset_classes": soft_list(asset_classes, "asset classes the event touches"),
            "severity_indicators": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string", "enum": indicators},
                "quote": {"type": ["string", "null"], "description": "a short VERBATIM phrase from the text that shows this indicator; omit it if no phrase does"},
                "reason": {"type": "string", "description": "one short sentence on why you see this indicator"}},
                "required": ["id", "reason"]}},
            "rubric": {"type": "object", "properties": {
                "magnitude": _answer({"type": "integer", "enum": [0, 1, 2, 3, 4]}),
                "reach": _answer({"type": "string", "enum": reach}),
                "certainty": _answer({"type": "string", "enum": certainty}),
                "direction": _answer({"type": "string", "enum": direction})},
                "required": ["magnitude", "reach", "certainty", "direction"]},
            "uncertainty": {"type": "number", "minimum": 0, "maximum": 1,
                            "description": "how unsure you are about this reading (0 certain, 1 a guess)"},
            "evidence": {"type": "array", "items": {"type": "object", "properties": {
                "quote": {"type": "string", "description": "a VERBATIM excerpt of the text"},
                "supports": {"type": "string", "description": "one of: event_type, sentiment, entity, sector, region, severity"}},
                "required": ["quote"]}},
            "rationale": {"type": "string", "description": "one sentence, at most 300 characters"},
        },
        # only what the answer cannot do without: the provider rejects a call that misses any required field, which costs a whole retry; every other field has a
        # safe default on our side, and everything returned is validated and grounded by us regardless of what the provider's schema check allows
        # the rubric is required: when it was optional a model (qwen) simply never answered it, so the AI contributed nothing and nothing said so. For a text that is not a market
        # event the prompt asks for a neutral answer (magnitude 0), which costs nothing and keeps the contract simple.
        "required": ["event_type", "rubric"],
    }
