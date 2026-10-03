"""The impact model card: what the impact model is, what it was trained on, how it was chosen, how it scored against baselines on
chronologically held-out data, and how far it passed the pre-registered acceptance bar (so, what its lifecycle is).

Written by ``eventshock.modeling.impact_train`` next to the artifact, read by the serving path (integrity check) and returned
unchanged by ``GET /api/models/impact``. Timestamp-free, so retraining reproduces it byte for byte.
One card, two scopes (ISSUER, MARKET): each has its own data, its own evaluation and its own lifecycle.
"""

from __future__ import annotations

from pydantic import Field

from ..domain import ImpactLifecycle
from .sentiment_card import _Card

ARTIFACT_FILE = "model.joblib"
CARD_FILE = "model_card.json"


class Estimate(_Card):
    """A point estimate with a 95% cluster-bootstrap interval (episodes are resampled, never rows)."""

    value: float | None = None
    lo: float | None = None
    hi: float | None = None


class ModelScore(_Card):
    """One ladder step scored on one evaluation set. Errors are on log1p(|z|); lower is better."""

    id: str
    mae: Estimate
    rmse: float | None = None
    spearman: Estimate = Field(description="episode-level rank correlation of the prediction with the realised |z|")
    top_decile_lift: float | None = Field(default=None, description="mean realised |z| of the top 10% of predictions / overall mean")
    placebo_spearman: Estimate = Field(description="same prediction against the window BEFORE the event: skill here is market state, not the event")
    delta_mae_vs_constant: Estimate = Field(description="paired difference (negative = better than the constant)")
    delta_mae_vs_market_state: Estimate = Field(description="paired difference against the market-state-only linear model (negative = better)")


class SetResult(_Card):
    id: str = Field(description="oof | val | test | val+test | live | live_reliable")
    title: str
    role: str
    n_episodes: int
    n_rows: int
    period: str
    models: list[ModelScore]


class LadderEntry(_Card):
    id: str
    family: str
    rung: str | None
    servable: bool
    params: dict[str, str | int | float]
    n_features: int
    oof_mae: Estimate
    oof_spearman: Estimate
    delta_mae_vs_previous_choice: Estimate = Field(description="out-of-fold paired difference to the current choice when it was tried")
    chosen: bool
    verdict: str


class CalibrationBin(_Card):
    score_low: int
    score_high: int
    n_episodes: int
    severity_q10: float
    severity_q50: float
    severity_q90: float
    realised_score_q10: int
    realised_score_q90: int
    p_extreme: Estimate


class CalibrationCard(_Card):
    method: str
    reference_episodes: int
    reference_period: str
    extreme_score: int
    base_rate_extreme: float = Field(description="share of reference episodes that realised score >= extreme_score")
    bins_reference: list[CalibrationBin] = Field(description="out-of-fold training period: the table the server reads")
    bins_heldout: list[CalibrationBin] = Field(description="val+test, same bin edges: the independent check")
    nominal_coverage: float
    heldout_coverage: Estimate = Field(description="share of held-out episodes whose realised score fell in the served [low, high]")
    monotonicity_spearman: float | None = Field(default=None, description="bucket order vs realised mean |z| on val+test")
    extreme_brier: float | None = None
    extreme_brier_base_rate: float | None = None


class Stratum(_Card):
    dimension: str
    value: str
    n_episodes: int
    spearman: Estimate
    mae_model: float | None
    mae_constant: float | None


class AcceptanceCheck(_Card):
    id: str
    label: str
    passed: bool | None = Field(description="null = could not be evaluated (too little data): never counts as a pass")
    value: str
    detail: str


class Acceptance(_Card):
    rule: str = Field(description="the bar, fixed in configs/impact_model.yaml before the first held-out run")
    met: bool
    checks: list[AcceptanceCheck]


class Attribution(_Card):
    kind: str = Field(description="additive | linear | sensitivity")
    exact: bool = Field(description="contributions plus the baseline add up to the prediction exactly")
    max_abs_error: float | None = Field(description="largest |sum - prediction| over held-out rows (log-severity units)")
    units: str


class TrainingInfo(_Card):
    table_sha256: str
    rows: dict[str, int]
    episodes: dict[str, int]
    train_period: str
    folds: str
    excluded: dict[str, int]
    seed: int
    config_sha256: str


class HorizonCheck(_Card):
    window_sessions: int
    spearman: Estimate


class DirectionCheck(_Card):
    n: int
    hit_rate: Estimate = Field(description="share of confident, non-neutral sentiment calls whose sign matched the realised abnormal return")
    note: str


class ScopeCard(_Card):
    scope: str
    lifecycle: ImpactLifecycle
    served: bool = Field(description="the artifact contains a model for this scope that the server uses")
    summary: str
    target: str
    selected_id: str | None
    algorithm: str
    features: list[str]
    training: TrainingInfo
    ladder: list[LadderEntry]
    evaluations: list[SetResult]
    calibration: CalibrationCard | None
    strata: list[Stratum]
    attribution: Attribution | None
    horizon: list[HorizonCheck]
    direction: DirectionCheck | None
    leakage_findings: list[str]
    acceptance: Acceptance
    limitations: list[str]


class PreviousComparison(_Card):
    """The new model against the one it would replace, on the same held-out episodes (paired; negative = the new model has the lower error)."""

    scope: str
    previous_id: str
    set_id: str
    n_episodes: int
    delta_mae: Estimate
    spearman_new: Estimate
    spearman_previous: Estimate


class ImpactModelCard(_Card):
    id: str
    version: str
    feature_schema: str
    output_definition: str
    artifact_file: str
    artifact_sha256: str = Field(min_length=64, max_length=64)
    artifact_bytes: int
    libraries: dict[str, str]
    dataset: dict[str, str | int | dict[str, int] | dict[str, str]] = Field(description="hashes and counts of the table the model was fitted from")
    selection_rule: str
    scopes: list[ScopeCard]
    vs_previous: list[PreviousComparison] = Field(default_factory=list, description="paired comparison with the model this one would replace")

    def scope(self, name: str) -> ScopeCard | None:
        return next((s for s in self.scopes if s.scope == name), None)
