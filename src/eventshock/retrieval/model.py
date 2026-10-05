"""The analogue contract. A retrieved analogue is RETRIEVED evidence about the past, never evidence about the new report, and its realised outcome is
hindsight: it can be shown, it can never be an input to the severity score (unless the pre-registered test says so; see ``docs/ANALOGUES.md``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OUTCOME_NOTE = ("The realised move is hindsight about a PAST report: the market-model abnormal return over the reaction window after it "
                "(outcome-v3 for a company, the S&P 500's excess move for a market-wide report). It is not a forecast for this report.")


class _Strict(BaseModel):
    # extra="forbid" like the other evidence contracts; defaults are listed as always-present in the OpenAPI response schema (see domain.base.ContractModel)
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class Analogue(_Strict):
    id: str
    origin: Literal["RETRIEVED"] = "RETRIEVED"
    headline: str
    published_at: str
    reaction_session: str = Field(description="the first session whose move counts as the reaction (the report's own session, or the next one for an after-close report)")
    scope: Literal["ISSUER", "MARKET"]
    ticker: str | None = None
    sector: str | None = None
    similarity: float = Field(description="cosine similarity of the two reports' e5 embeddings, 0-1 (e5 similarities are compressed: unrelated texts typically score 0.70-0.80)")
    car_pct: float = Field(description="cumulative abnormal return over the reaction window, in percent (signed)")
    z: float = Field(description="that move in units of the issuer's own trailing volatility (signed)")
    abs_z: float
    vix_level: float | None = Field(default=None, description="^VIX close of the session before the reaction, i.e. the regime the move happened in")
    outcome_version: str
    model_event_type: str | None = Field(default=None, description="the trained event model's label for that old text (noisy; shown for orientation only)")


class AnalogueAggregate(_Strict):
    n_episodes: int = Field(description="distinct past episodes behind the statistics")
    n_stories: int = Field(description="distinct stories after near-duplicate collapse above the similarity floor")
    n_used: int = Field(description="how many of them (the most similar, after diversity caps) the statistics below are computed from: the effective sample size")
    car_pct_q10: float
    car_pct_q50: float
    car_pct_q90: float
    abs_car_pct_median: float
    share_move_ge_2sigma: float = Field(description="share of the analogues whose |z| was at least 2")
    share_lo: float
    share_hi: float
    quiet_day_share: float = Field(description="the same share on ordinary days (random sessions with no earnings reaction): the yardstick")
    lift: float | None = Field(default=None, description="share_move_ge_2sigma / quiet_day_share")
    distinguishable_from_quiet_day: bool = Field(description="True only if the Wilson interval of the share lies entirely above the quiet-day share")
    reading: str


class AnalogueSet(_Strict):
    status: Literal["OK", "NO_RELIABLE_ANALOGUE", "UNAVAILABLE"]
    reason: str
    scope: Literal["ISSUER", "MARKET"] | None = None
    query_date: str | None = None
    similarity_floor: float | None = None
    eligible: int = Field(default=0, description="past episodes allowed by the point-in-time rule")
    above_floor: int = 0
    items: list[Analogue] = []
    aggregate: AnalogueAggregate | None = None
    below_bar: list[Analogue] = Field(default=[], description="nearest eligible reports when the reliability bar is not met: shown for transparency, never as precedent")
    caveats: list[str] = []
    index_version: str | None = None
    outcome_note: str = OUTCOME_NOTE
