"""The evidence bundle: one typed, read-only summary of *how much the system's numbers can be trusted*, served by ``GET /api/evidence``.

Built (``services.evidence``) from the loaded model cards and from evidence files that the study commands write and the repository commits
(``docs/evidence/impact_study.json``, ``representation_bakeoff.json``, ``data/events/manifest.json``, ``data/gold_v2/agreement.json``). Nothing here is computed at
request time and nothing is invented: a section whose evidence file does not exist says so (``available = False`` and the command that produces it).
Timestamp-free, so the same inputs give byte-identical output.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .impact_card import Estimate


class _E(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class SourceFile(_E):
    file: str
    sha256: str | None = None


class CheckRow(_E):
    id: str
    label: str
    value: str
    passed: bool | None
    detail: str = ""


class StageStatus(_E):
    """What one pipeline stage is, in the product's three words: placeholder rule, experimental model, validated model."""

    stage: str = Field(description="sentiment | event | impact")
    model_id: str | None
    kind: str = Field(description="placeholder | experimental | validated")
    summary: str
    passed: list[str] = []
    failed: list[str] = []
    not_evaluable: list[str] = []
    artifact_sha256: str | None = None


class SourceRow(_E):
    name: str
    kind: str = Field(description="news | social | filing | calendar | prices | labels")
    period: str
    records: int | None
    timestamps: str
    note: str = ""


class YearCount(_E):
    year: str
    issuer: int = 0
    market: int = 0
    filing_events: int = 0


class GoldSummary(_E):
    name: str
    rows: int
    labelled_by: str
    agreement: float | None = None
    kappa: float | None = None
    agreed_rows: int | None = None
    human_reviewed: int = 0
    note: str = ""


class DataFoundation(_E):
    available: bool
    sources: list[SourceRow] = []
    episodes_by_year: list[YearCount] = []
    held_out: dict[str, dict[str, int]] = Field(default_factory=dict, description="protocol -> scope/split -> episodes")
    calendar_filings: int | None = None
    calendar_fomc: int | None = None
    gold: list[GoldSummary] = []
    exclusions: dict[str, dict[str, int]] = Field(default_factory=dict)
    known_gaps: list[str] = []
    command: str = ""


class FeatureRow(_E):
    name: str
    group: str
    availability: str = Field(description="a known before the event | b published at event time | c only after (refused) | shortcut | circular")
    allowed: bool
    used_by: list[str] = Field(default_factory=list, description="rungs that include it")
    why: str


class Increment(_E):
    block: str
    family: str
    where: str
    delta_mae: Estimate = Field(description="paired log-severity MAE difference; negative = the block helps")
    verdict: str = Field(description="helps | no measurable effect | hurts")


class BatteryRow(_E):
    model: str
    role: str
    set: str
    neutral_skill: Estimate
    within_issuer_skill: float | None = None
    placebo_gap: float | None = None


class AblationRow(_E):
    block: str
    method: str
    spearman_lost: float
    mae_added: float
    mae_added_lo: float | None = None
    mae_added_hi: float | None = None


class ProtocolRun(_E):
    protocol: str
    scope: str
    status: str
    episodes: dict[str, int] = {}
    selected: str | None = None
    best_state: str | None = None
    best_block: str | None = None
    checks: list[CheckRow] = []
    increments: list[Increment] = []
    years_helpful: str | None = None
    battery: list[BatteryRow] = []
    ablation: list[AblationRow] = []
    verdict: str = ""


class ContrastRow(_E):
    label: str
    pairs: int
    lift: Estimate
    auc: float | None


class TrackF(_E):
    available: bool
    pairs: int = 0
    headline: ContrastRow | None = None
    by_item: list[ContrastRow] = []
    earnings_by_year: list[ContrastRow] = []
    non_earnings_by_year: list[ContrastRow] = []
    item_code_increment: list[Increment] = []
    note: str = ""


class StudyView(_E):
    available: bool
    preregistration: SourceFile | None = None
    p1_regression: str = ""
    runs: list[ProtocolRun] = []
    track_f: TrackF = TrackF(available=False)
    command: str = ""


class CandidateRow(_E):
    id: str
    family: str
    detail: str
    pooled_delta_f1: Estimate
    checks_passed: list[str] = []
    checks_failed: list[str] = []
    adopt: bool


class CostRow(_E):
    model: str
    kind: str
    parameters_m: float | None = None
    ms_per_text_batch1: float | None = None
    ms_per_text_batch32: float | None = None
    peak_rss_mb: int | None = None
    controlled: bool = False
    deterministic: bool | None = None


class ProbeRow(_E):
    channel: str
    pairs: int
    share_correct: float
    lo: float
    hi: float


class RepresentationView(_E):
    available: bool
    decision: str = ""
    baseline: str = ""
    sets: dict[str, int] = {}
    baseline_pooled_f1: float | None = None
    candidates: list[CandidateRow] = []
    cost: list[CostRow] = []
    probe: list[ProbeRow] = []
    command: str = ""


class EvidenceBundle(_E):
    schema_version: int = 1
    generated_from: list[SourceFile]
    stages: list[StageStatus]
    data: DataFoundation
    features: list[FeatureRow]
    study: StudyView
    representation: RepresentationView
    limitations: list[str]
