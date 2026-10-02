"""The sentiment model card: a typed, validated record of what the model is, how it was chosen and how it scored.

Written by ``eventshock.modeling.sentiment_train`` next to the artifact, read by the serving path (integrity check) and
returned unchanged by ``GET /api/models/sentiment``. Deliberately timestamp-free so retraining reproduces it byte for byte.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Card(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class ClassMetrics(_Card):
    precision: float
    recall: float
    f1: float
    support: float


class LabelScores(_Card):
    """Accuracy and macro-F1 of one way of turning the output into a label."""

    accuracy: float
    macro_f1: float


class ReliabilityBin(_Card):
    lo: float
    hi: float
    n: int
    confidence: float
    accuracy: float


class EvalMetrics(_Card):
    n: int
    weighted: bool = Field(description="rows carry inclusion weights (stratified gold sample)")
    labels: list[str] = Field(description="row/column order of the confusion matrix: truth (rows) x predicted (columns)")
    accuracy: float
    macro_f1: float
    macro_f1_ci95: tuple[float, float] | None = Field(default=None, description="bootstrap over rows")
    per_class: dict[str, ClassMetrics]
    confusion: list[list[float]]
    log_loss: float | None = None
    brier: float | None = None
    ece: float | None = Field(default=None, description="expected calibration error of the top-label probability")
    spearman_score_vs_label: float | None = Field(default=None, description="rank correlation of the score with -1/0/+1 labels")
    mean_score_by_class: dict[str, float] | None = None
    product_rule: LabelScores | None = Field(default=None, description="label from the UI's score cut (|score| >= 0.15) instead of arg-max")


class EvalSet(_Card):
    id: str
    title: str
    role: str = Field(description="in_domain | external | indicative")
    description: str
    status: str = Field(description="ok | skipped")
    note: str = ""
    model: EvalMetrics | None = None
    baselines: dict[str, LabelScores] = Field(default_factory=dict)


class CalibrationInfo(_Card):
    method: str
    temperature: float
    fitted_on: str
    ece_test_before: float
    ece_test_after: float
    reliability_test: list[ReliabilityBin]


class Candidate(_Card):
    preprocessing: str
    C: float
    class_weight: str | None
    temperature: float
    valid_log_loss: float
    valid_macro_f1: float
    selected: bool


class TrainingInfo(_Card):
    dataset: str
    licence: str
    table: str
    table_sha256: str
    rows: dict[str, int]
    label_distribution: dict[str, int]
    split_note: str
    seed: int
    config_digest: str


class ConfidentError(_Card):
    eval_set: str
    text: str
    truth: str
    predicted: str
    confidence: float
    score: float


class SentimentModelCard(_Card):
    id: str
    version: str
    algorithm: str
    preprocessing: str
    classes: list[str]
    score_definition: str
    artifact_file: str
    artifact_sha256: str = Field(min_length=64, max_length=64)
    artifact_bytes: int
    libraries: dict[str, str] = Field(description="versions the artifact was built with; scikit-learn must match at load time")
    training: TrainingInfo
    selection_rule: str
    candidates: list[Candidate]
    calibration: CalibrationInfo
    evaluations: list[EvalSet]
    confident_errors: list[ConfidentError]
    limitations: list[str]
