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


class LLMExtraction(BaseModel):
    """The model's answer. Every field but the required few has a safe default so a thin answer degrades instead of failing."""

    model_config = ConfigDict(extra="ignore")
    event_type: str
    event_subtype: str = "other"
    event_confidence: float = Field(ge=0, le=1)
    sentiment: float = Field(ge=-1, le=1)
    sentiment_intensity: str = "medium"
    sentiment_confidence: float | None = Field(default=None, ge=0, le=1)
    entities: list[LLMEntity] = []
    sectors: list[str] = []
    regions: list[str] = []
    affected_asset_classes: list[str] = []
    severity_indicators: list[str] = []
    uncertainty: float = Field(default=0.5, ge=0, le=1)
    evidence: list[LLMQuote] = []
    rationale: str = Field(default="", max_length=400)


TOOL_NAME = "record_assessment"


def tool_schema(*, event_types: list[str], subtypes: list[str], sectors: list[str], regions: list[str], asset_classes: list[str],
                indicators: list[str]) -> dict[str, Any]:
    """The tool's ``input_schema``. A forced tool call is the structured-output mechanism: the reply is JSON, never prose."""

    def enum_list(values: list[str]) -> dict[str, Any]:
        return {"type": "array", "items": {"type": "string", "enum": values}}

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
            "sectors": enum_list(sectors),
            "regions": enum_list(regions),
            "affected_asset_classes": enum_list(asset_classes),
            "severity_indicators": enum_list(indicators),
            "uncertainty": {"type": "number", "minimum": 0, "maximum": 1,
                            "description": "how unsure you are about this reading (0 certain, 1 a guess)"},
            "evidence": {"type": "array", "items": {"type": "object", "properties": {
                "quote": {"type": "string", "description": "a VERBATIM excerpt of the text"},
                "supports": {"type": "string",
                             "enum": ["event_type", "sentiment", "entity", "sector", "region", "severity"]}},
                "required": ["quote", "supports"]}},
            "rationale": {"type": "string", "description": "one sentence, at most 300 characters"},
        },
        "required": ["event_type", "event_subtype", "event_confidence", "sentiment", "uncertainty", "evidence"],
    }
