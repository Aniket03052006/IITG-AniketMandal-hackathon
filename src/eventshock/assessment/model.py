"""The risk assessment contract: what a report means, how serious it is and why, and what was known when.

An assessment is a *side-car* to ``RiskSignal`` (it is never stored on it, so the frozen replay output and its digests are untouched). Four kinds of
content are kept apart on purpose and each field says which it is:

* source text and quotes taken from it (``EvidenceSpan``, ``source``),
* the extraction of that text (an LLM or the deterministic rule extractor: ``ExtractionInfo.mode`` says which),
* the severity score (a transparent scorecard of four anchored answers plus two bounded data adjustments: ``SeverityAssessment``), and
* scenario assumptions (owned by the scenario catalogue, only referenced here).

Nothing here is a forecast. ``labels`` and ``limitations`` carry that statement on every response.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from ..domain.base import ContractModel


class ExtractionMode(StrEnum):
    LLM = "LLM"  # a language model filled the closed schema; every claim was checked against the text
    RULES = "RULES"  # deterministic cue-phrase rules over the trained models' readings (demo / fallback mode)


class Kind(StrEnum):
    """What sort of statement a number or phrase is. The UI shows these as separate badges and never blends them."""

    SOURCE = "SOURCE"  # taken from the report text
    EXTRACTION = "EXTRACTION"  # an LLM / rule reading of the text
    JUDGEMENT_PRIOR = "JUDGEMENT_PRIOR"  # a configured weight or prior (documented, not fitted)
    MARKET_STATE = "MARKET_STATE"  # a historical observation available at the report's time
    MODEL_REFERENCE = "MODEL_REFERENCE"  # a trained model's output, experimental
    SCENARIO_ASSUMPTION = "SCENARIO_ASSUMPTION"  # a configured shock
    REALISED = "REALISED"  # what happened afterwards: display only, never an input
    RETRIEVED = "RETRIEVED"  # a past report found by similarity, with its realised outcome: evidence about OTHER events, never about this one


class Origin(StrEnum):
    """Where a number or reading comes from. The UI never calls a whole result "AI-generated": each part says which of these it is."""

    AI = "AI"  # a language model's (or a trained classifier's) reading of the text
    DATA = "DATA"  # an observation: market data, timestamps, source metadata
    RULES = "RULES"  # deterministic logic: cue phrases, comparison with earlier reports, exposure, scenario mapping, portfolio arithmetic
    HYBRID = "HYBRID"  # combines more than one of the above (e.g. a rules baseline moved by a bounded AI adjustment)
    ASSUMPTION = "ASSUMPTION"  # a configured judgement: a matrix anchor, a multiplier, a scenario shock
    RETRIEVED = "RETRIEVED"  # a past report retrieved by semantic similarity (with its realised outcome): precedent, not a reading of this report


class IndicatorBasis(StrEnum):
    QUOTED = "QUOTED"  # the report contains a phrase that shows it, and that phrase is cited verbatim
    KEYWORD = "KEYWORD"  # a configured cue phrase for this indicator appears in the report
    INFERRED = "INFERRED"  # the AI judged it present with no matching phrase: an inference, never shown as a quote


class Phase(StrEnum):
    BEFORE_REPORT = "BEFORE_REPORT"
    AT_REPORT = "AT_REPORT"
    AFTER_REPORT = "AFTER_REPORT"


# ---------------------------------------------------------------------------------------------------------------------- extraction
class AssessedEntity(ContractModel):
    name: str = Field(description="exactly as written in the text")
    kind: str = Field(description="COMPANY | INSTITUTION | REGULATOR | GOVERNMENT | OTHER")
    role: str = Field(description="subject | counterparty | mentioned")
    resolved: bool = Field(description="true only when the name matched the entity master (a listed issuer EventShock holds data for)")
    entity_id: str | None = None
    ticker: str | None = None
    sector: str | None = None


class PrimaryIssuer(ContractModel):
    """The one issuer the signal is about, or ``UNKNOWN_ENTITY``: a name in the text that is not in the entity master never becomes an issuer."""

    entity_id: str
    name: str | None = None
    ticker: str | None = None
    resolved: bool
    note: str = ""


class EvidenceSpan(ContractModel):
    quote: str = Field(description="a verbatim excerpt of the analysed text")
    start: int = Field(ge=0, description="character offset into `SemanticReading.text`")
    end: int = Field(ge=0)
    supports: str = Field(description="event_type | sentiment | entity | sector | region | severity")


class IndicatorHit(ContractModel):
    id: str
    label: str
    level: int = Field(ge=0, le=4, description="the configured typical materiality level of this kind of development (a judgement prior)")
    polarity: str = Field(description="adverse | favourable | neutral")
    basis: IndicatorBasis
    quote: str | None = Field(default=None, description="the phrase in the report that shows it; null for an inference")
    reason: str | None = Field(default=None, description="the AI's one-line reason when the indicator is an inference")


class RubricProposal(ContractModel):
    """One answer the AI gave to a rubric question, with its reason and (when it gave one) the verbatim phrase it rests on."""

    value: str
    reason: str
    quote: str | None = None
    quote_verified: bool = False


class AIRubric(ContractModel):
    magnitude: RubricProposal | None = None
    reach: RubricProposal | None = None
    certainty: RubricProposal | None = None
    direction: RubricProposal | None = None


class SemanticReading(ContractModel):
    text: str = Field(description="the text that was analysed; evidence offsets index into it")
    event_type: str = Field(description="an EventCategory id, or NO_EVENT when the text is not a market event")
    event_label: str
    event_subtype: str
    event_subtype_label: str
    event_confidence: float | None = Field(
        default=None, ge=0, le=1,
        description="LLM: its stated confidence. Rules: the trained event model's calibrated probability for this class, when it has one")
    sentiment: float = Field(ge=-1, le=1)
    sentiment_label: str = Field(description="negative | neutral | positive")
    sentiment_intensity: str = Field(description="low | medium | high")
    sentiment_confidence: float | None = Field(default=None, ge=0, le=1)
    entities: list[AssessedEntity]
    primary_issuer: PrimaryIssuer
    sectors: list[str]
    regions: list[str]
    asset_classes: list[str]
    severity_indicators: list[IndicatorHit]
    uncertainty: float | None = Field(default=None, ge=0, le=1, description="how unsure the reading is; null when it cannot say")
    ai_rubric: AIRubric | None = Field(default=None, description="the language model's answers to the severity rubric; null in rule mode")
    evidence: list[EvidenceSpan]
    rationale: str | None = Field(default=None, description="the model's one-line reason (LLM mode only); an explanation, not evidence")


class ExtractionInfo(ContractModel):
    mode: ExtractionMode
    model_id: str | None = Field(description="the LLM (LLM mode) or the vocabulary version (rules mode)")
    vocabulary_version: str
    prompt_version: str | None = None
    cached: bool = Field(default=False, description="served from the local cache: no call was made")
    fallback_reason: str | None = Field(
        default=None, description="why the rule extractor served although an LLM was configured (timeout, rate limit, bad output, no key)")
    notes: list[str] = Field(default_factory=list, description="what was dropped or corrected by the checks (ungrounded entity, unknown id, ...)")
    basis: str = Field(description="one plain sentence on how this reading was produced")


class Agreement(ContractModel):
    """The extraction against what the trained pipeline already said about the same text. Shown, not hidden."""

    reference_event_type: str | None
    reference_event_status: str | None
    reference_event_confidence: float | None
    event_type_agrees: bool | None
    reference_sentiment: float | None
    sentiment_direction_agrees: bool | None
    note: str


# ------------------------------------------------------------------------------------------------------------------------ severity
class RubricField(ContractModel):
    """One of the four rubric answers: what the deterministic rules said, what the AI proposed, what was used, and why."""

    id: str = Field(description="magnitude | reach | certainty | direction")
    label: str
    baseline: str = Field(description="the rules' answer (a level id)")
    baseline_label: str
    baseline_basis: list[str] = Field(description="the deterministic reasons for the baseline, in words")
    baseline_informed: bool = Field(default=True, description="false when the rules found no evidence and the baseline is only a default: the AI is then less tightly bound")
    ai: str | None = Field(default=None, description="the AI's proposed answer, if one was made")
    ai_label: str | None = None
    ai_reason: str | None = None
    ai_quote: str | None = Field(default=None, description="the verbatim phrase the AI cited, when it cited one that is in the report")
    final: str = Field(description="the answer used in the score")
    final_label: str
    final_says: str
    origin: Origin
    adjustment: str = Field(description="NONE | AI_WITHIN_BOUND | AI_QUOTE_BACKED | AI_CLAMPED | AI_IGNORED: what became of the AI's answer")
    note: str = ""


class ScoreStep(ContractModel):
    """One line of the build-up: starts from the matrix and shows every change on the way to the final score."""

    id: str
    label: str
    origin: Origin
    value: str = Field(description="the input in words")
    effect_points: float = Field(description="change in points (the first step is the starting point)")
    running: float = Field(description="the score after this step")
    detail: str


class OmittedFactor(ContractModel):
    id: str
    label: str
    reason: str


class MarketUse(ContractModel):
    """Whether market data entered the score, and exactly how fresh it was."""

    used: bool
    vix: float | None = None
    as_of: str | None = Field(default=None, description="the session the market state is from (ISO date)")
    report_session: str | None = Field(default=None, description="the last completed session before the report (ISO date)")
    sessions_behind: int | None = Field(default=None, description="how many sessions the data lags that session by")
    max_sessions_behind: int
    reason: str


class Reliability(ContractModel):
    level: str = Field(description="high | moderate | low")
    score: float
    basis: str
    note: str = "Reliability says how far to trust the report. It does not change the severity: severity is how large the event would be if the report is accurate."


class SeverityAssessment(ContractModel):
    score: int = Field(ge=1, le=10)
    points: float = Field(ge=1, le=10, description="before rounding")
    band: str = Field(description="negligible | low | moderate | high | extreme")
    band_label: str
    band_says: str
    low: int = Field(ge=1, le=10)
    high: int = Field(ge=1, le=10)
    range_basis: str
    basis: str = "SCORECARD"
    version: str
    rubric: list[RubricField]
    steps: list[ScoreStep]
    baseline_score: int = Field(ge=1, le=10, description="the score with the AI's adjustments removed (rules only)")
    ai_effect: int = Field(description="score minus baseline_score: what the AI's bounded adjustments changed")
    omitted: list[OmittedFactor]
    market: MarketUse
    reliability: Reliability
    uncertainty: float | None = Field(default=None, ge=0, le=1, description="the reading's own uncertainty, when it states one; it widens the range, never lowers the score")
    formula: str


class ThresholdState(ContractModel):
    threshold: float
    score: int
    crosses: bool
    status: str = Field(description="ABOVE_TRIGGER | BELOW_TRIGGER")
    message: str
    can_run_what_if: bool = True


class ReferenceReading(ContractModel):
    """The trained market-reaction model's own output, kept next to the severity score as a labelled reference. It is not used by the trigger."""

    available: bool
    model_id: str | None = None
    lifecycle: str | None = None
    origin: str | None = Field(default=None, description="MODEL | PLACEHOLDER")
    score: int | None = None
    score_low: int | None = None
    score_high: int | None = None
    note: str


class Conflict(ContractModel):
    signal_id: str
    headline: str
    sentiment: float
    hours_apart: float
    note: str


# ------------------------------------------------------------------------------------------------------------------------- assessment
class ProvenanceLine(ContractModel):
    """Where one part of the result comes from, in plain words. The UI shows these as small origin chips."""

    part: str
    origin: Origin
    detail: str


class RiskAssessment(ContractModel):
    signal_id: str
    headline: str
    source: str
    source_type: str
    published_at: datetime
    ingested_at: datetime
    analysed_at: datetime
    timestamp_origin: str
    summary: str = Field(description="what happened, in one sentence assembled from the reading (no free-text generation)")
    extraction: ExtractionInfo
    reading: SemanticReading
    agreement: Agreement
    severity: SeverityAssessment | None = Field(
        description="null when the text is not a market event: nothing is scored for it")
    severity_note: str | None = None
    threshold: ThresholdState | None
    reference: ReferenceReading
    conflict: Conflict | None = None
    corroborating_at_event_time: int = Field(ge=0, description="independent reports that already existed when this one appeared")
    later_reports_excluded: int = Field(ge=0, description="reports about the same story that appeared afterwards: shown, never scored")
    provenance: list[ProvenanceLine] = Field(default_factory=list, description="which parts are AI, data, rules, hybrid or assumption")
    labels: list[str]
    limitations: list[str]


# -------------------------------------------------------------------------------------------------------------- evidence + timeline
class SourceReport(ContractModel):
    source: str
    source_type: str
    published_at: datetime
    headline: str
    url: str | None = None
    relation: str
    phase: Phase
    used_in_score: bool


class SourceEvidence(ContractModel):
    headline: str
    text: str
    spans: list[EvidenceSpan]
    reports: list[SourceReport]
    entity_match: str | None = Field(description="how the entity master matched a company, if one did")
    note: str


class InferenceLine(ContractModel):
    label: str
    value: str
    kind: Kind
    detail: str = ""


class ModelInference(ContractModel):
    lines: list[InferenceLine]
    agreement: Agreement
    note: str


class ScenarioAssumptions(ContractModel):
    scenario_id: str | None
    scenario_name: str | None
    illustrative: bool = True
    reference_impact: float | None
    shocks: list[str]
    trigger_threshold: float
    severity_scaling: str
    note: str


class EvidenceView(ContractModel):
    signal_id: str
    source_evidence: SourceEvidence
    model_inference: ModelInference
    scenario_assumptions: ScenarioAssumptions


class TimelineItem(ContractModel):
    at: datetime | None
    label: str
    detail: str
    kind: str = Field(description="REPORT | INGESTED | ASSESSED | MARKET_STATE | FILING | CORROBORATION | OUTCOME")
    phase: Phase
    known_at_assessment: bool
    used_in_severity: bool
    used_by_reference_model: bool
    number_kind: Kind


class TimelineView(ContractModel):
    signal_id: str
    report_time: datetime
    assessed_at: datetime
    timestamp_origin: str
    items: list[TimelineItem]
    excluded: list[str] = Field(description="things that exist but are deliberately not inputs to the severity score")
    note: str
