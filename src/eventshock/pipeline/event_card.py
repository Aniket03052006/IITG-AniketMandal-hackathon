"""The event model card: a typed, validated record of what the event classifier is, what it was trained on, how it was chosen
and how it scored, including where it is *not* trustworthy.

Written by ``eventshock.modeling.event_train`` next to the artifact, read by the serving path (integrity check) and returned
unchanged by ``GET /api/models/event``. Deliberately timestamp-free so retraining reproduces it byte for byte.
"""

from __future__ import annotations

from pydantic import Field

from .sentiment_card import ClassMetrics, ReliabilityBin, _Card


class EventDetection(_Card):
    """Event vs not-an-event, at the served decision (anything but NO_EVENT counts as 'an event')."""

    precision: float
    recall: float
    f1: float


class ServedDecision(_Card):
    """What the product shows, scored against the truth: CLASSIFIED -> its class, NO_EVENT -> NONE, UNCERTAIN -> no class."""

    macro_f1: float = Field(description="9-class macro-F1 of the served label; UNCERTAIN is always wrong")
    accuracy: float
    coverage: float = Field(description="share of rows the model commits to a class or to NONE (not UNCERTAIN)")
    accuracy_when_decided: float
    classified_precision: float | None = Field(default=None, description="of CLASSIFIED rows, the share whose class equals the truth")
    status_mix: dict[str, float] = Field(description="share of rows per status")
    detection: EventDetection


class EventEvalMetrics(_Card):
    n: int
    weighted: bool
    labels: list[str] = Field(description="row/column order of the confusion matrix: truth (rows) x arg-max class (columns)")
    accuracy: float
    macro_f1: float = Field(description="9-class macro-F1 of the arg-max, over classes that occur in the truth")
    macro_f1_ci95: tuple[float, float] | None = None
    event_macro_f1: float = Field(description="macro-F1 over the 8 event classes only (rows whose truth is NONE do not count as a class)")
    per_class: dict[str, ClassMetrics]
    confusion: list[list[float]]
    log_loss: float | None = None
    brier: float | None = None
    ece: float | None = None
    served: ServedDecision
    served_f1_ci95: tuple[float, float] | None = None


class BaselineScores(_Card):
    accuracy: float
    macro_f1: float
    detection_f1: float | None = Field(default=None, description="event vs not-an-event F1 (a baseline that never says NONE gets recall 1)")


class EventEvalSet(_Card):
    id: str
    title: str
    role: str = Field(description="in_domain | indicative | secondary")
    description: str
    status: str = Field(description="ok | skipped")
    note: str = ""
    model: EventEvalMetrics | None = None
    baselines: dict[str, BaselineScores] = Field(default_factory=dict)


class EventCandidate(_Card):
    preprocessing: str
    C: float
    class_weight: str | None
    temperature: float
    dev_log_loss: float
    dev_macro_f1: float
    selected: bool


class ClassReliability(_Card):
    label: str
    train_examples: int
    annotated_train: int
    dev_support: int
    dev_f1: float | None
    status: str = Field(description="ok | unreliable | unmeasured")
    reason: str


class EventCalibration(_Card):
    method: str
    temperature: float
    fitted_on: str
    ece_dev_population_before: float
    ece_dev_population_after: float
    reliability_dev_population: list[ReliabilityBin]


class EventAbstention(_Card):
    commit_threshold: float = Field(description="the arg-max of the 9-class posterior is committed only at or above this probability")
    rationale: str
    dev_population_n: int
    dev_coverage: float = Field(description="share of weighted dev rows the model commits to (not UNCERTAIN)")
    dev_classified_share: float
    dev_classified_precision: float | None
    dev_no_event_precision: float | None
    route_unreliable_to_uncertain: bool
    unreliable_classes: list[str]


class ConsistencyInfo(_Card):
    n: int
    agreement: float | None
    kappa: float | None
    share_none_first_pass: float | None = None
    note: str = ""


class EventTrainingInfo(_Card):
    labels_file: str
    labels_sha256: str
    table: str
    table_sha256: str
    annotator: str
    rows: dict[str, int] = Field(description="rows per split and kind, e.g. train/annotated, train/silver, dev, replay_check")
    label_distribution_train: dict[str, int]
    label_distribution_dev: dict[str, int]
    silver_note: str
    consistency: ConsistencyInfo
    seed: int
    config_digest: str


class AcceptanceCheck(_Card):
    name: str
    model: float | None
    baseline: float | None
    detail: str
    passed: bool


class Acceptance(_Card):
    rule: str = Field(description="the bar, fixed before the gold set was scored")
    met: bool
    checks: list[AcceptanceCheck]


class EventConfidentError(_Card):
    eval_set: str
    text: str
    truth: str
    served: str = Field(description="CLASSIFIED:<class> | NO_EVENT | UNCERTAIN:<best guess>")
    top_class: str
    p_none: float
    confidence: float


class EventModelCard(_Card):
    id: str
    version: str
    algorithm: str
    preprocessing: str
    classes: list[str] = Field(description="the 9 classes the model scores: the 8 event categories and NONE")
    output_definition: str
    artifact_file: str
    artifact_sha256: str = Field(min_length=64, max_length=64)
    artifact_bytes: int
    libraries: dict[str, str]
    training: EventTrainingInfo
    selection_rule: str
    ablation: dict[str, float] = Field(default_factory=dict, description="dev log-loss with and without the TFN silver rows")
    candidates: list[EventCandidate]
    calibration: EventCalibration
    abstention: EventAbstention
    class_reliability: list[ClassReliability]
    evaluations: list[EventEvalSet]
    acceptance: Acceptance
    confident_errors: list[EventConfidentError]
    limitations: list[str]
