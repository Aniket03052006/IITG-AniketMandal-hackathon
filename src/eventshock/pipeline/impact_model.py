"""The trained impact model, serving side: load a verified artifact and turn one report into a calibrated, explained estimate.

Training and evaluation live in ``eventshock.modeling.impact_train`` and import *this* module, so the feature assembly, the
prediction, the score mapping and the attribution that are evaluated are the very code that serves (no train/serve skew).
Nothing here fits anything.

What the model says (``assess``):
* it predicts ``log1p(|z|)``: the size of the two-session abnormal move that follows the report, in units of the issuer's own
  trailing volatility (scope ISSUER) or of the S&P 500's (scope MARKET). It uses only what was knowable when the report appeared:
  market state from sessions before the reaction, the timestamp, and the frozen sentiment/event models' reading of the text;
* the 1-10 score is that prediction ranked against the out-of-fold prediction distribution of the training period and read off
  the realised severity distribution at the same percentile, using the target's own fixed cut points (no hand-set thresholds).
  The continuous prediction is kept (``predicted_severity``);
* the uncertainty is empirical, not parametric: what comparable historical events (same score bucket, out of fold) actually realised;
* the drivers are exact: for an additive model, baseline + the per-feature contributions equal the prediction.

Failure policy (nothing is invented): a missing artifact is a non-event at start-up (the labelled heuristic keeps serving) unless
the config says ``require``; a modified or version-mismatched artifact raises ``ConfigError`` always; a report that cannot be scored
(no resolved scope, no market context, synthetic clock) comes back as an ``ImpactSkip`` with the reason, and the caller keeps the
labelled heuristic for that one signal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..domain import (
    EventClassification,
    ImpactAssessment,
    ImpactAudit,
    ImpactDriver,
    ImpactLifecycle,
    ImpactScope,
    SentimentResult,
)
from .event_context import EventCalendar
from .impact_card import ARTIFACT_FILE, CARD_FILE, ImpactModelCard
from .impact_features import (
    ALL_FEATURES,
    FEATURE_SCHEMA,
    ISSUER,
    MARKET,
    SCOPES,
    doc_features,
    state_features,
    text_features,
)
from .impact_features_v2 import ALL_FEATURES_V2, CALENDAR, FEATURE_SCHEMA_V2, feature_group_v2
from .market_context import MarketContext, quantize
from .sentiment_model import _file_sha256

PAYLOAD_SCHEMA = "impact-model-payload-1"
UNRELIABLE_TIMING = {"IN_SESSION", "DATE_ONLY", "FIRST_SEEN"}
TOP_DRIVERS = 8
SERVED = {ImpactLifecycle.TRAINED, ImpactLifecycle.CALIBRATED, ImpactLifecycle.PRODUCTION}


def score_knots(cutpoints: list[float], cap: float) -> tuple[list[float], list[float]]:
    """Severity (|z|) knots and the continuous score value they map to: 0 -> 0, each cut point k -> k, ``cap`` -> 10.

    ``ceil(value)`` (min 1) is the integer score: value in (s-1, s] is score s, exactly the ``ceil(raw * 10)`` convention of
    ``ImpactAssessment.raw``.
    """
    return [0.0, *cutpoints, cap], [float(i) for i in range(len(cutpoints) + 2)]


def interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear, clamped, tolerant of repeated xs (first y wins at ties)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    if xs[hi] == xs[lo]:
        return ys[lo]
    return ys[lo] + (ys[hi] - ys[lo]) * (x - xs[lo]) / (xs[hi] - xs[lo])


def to_score(value: float) -> int:
    return min(10, max(1, math.ceil(round(value, 6))))


def calibrate_value(cal: dict[str, Any], pred_log: float) -> tuple[float, int]:
    """(continuous value in [0, 10], integer score) for one prediction. Shared by serving and by training's evaluation."""
    u = interp(pred_log, cal["pred_q"], cal["grid"])
    z_star = interp(u, cal["grid"], cal["sev_q"])
    kz, kv = score_knots(cal["cut"], cal["cap"])
    value = interp(z_star, kz, kv)
    return value, to_score(value)


def attribute_row(model: Any, ref_row: list[float], x: list[float]) -> tuple[list[float], float, float]:
    """Per-feature contributions (log-severity), baseline prediction, prediction. See ``ImpactModel.attribute``."""
    import numpy as np

    rows = [list(ref_row), list(x)]
    for j, v in enumerate(x):
        r = list(ref_row)
        r[j] = v
        rows.append(r)
    preds = model.predict(np.asarray(rows, dtype=float))
    base, full = float(preds[0]), float(preds[1])
    return [float(v) - base for v in preds[2:]], base, full


CAL_NAMES = frozenset(n for names in CALENDAR.values() for n in names)


def _next_weekday(iso: str) -> str:
    from datetime import date, timedelta

    d = date.fromisoformat(iso) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def reaction_dates(context: MarketContext, key: str) -> tuple[str, str]:
    """ISO dates of the reaction session s0 and the session after it, as the training table has them.

    Inside the frozen calendar both are real sessions. For a report after the last known close (``NEXT``) or on the last session, the unknown dates are the next
    weekdays: a holiday could make that off by a day, which can only move a scheduled-FOMC flag (stated in docs/notes/EVIDENCE_V2.md).
    """
    from bisect import bisect_left

    from .market_context import NEXT

    if key == NEXT:
        d0 = _next_weekday(context.last_session)
        return d0, _next_weekday(d0)
    i = bisect_left(context.dates, key)
    return key, (context.dates[i + 1] if i + 1 < len(context.dates) else _next_weekday(key))


@dataclass(frozen=True)
class ImpactInput:
    """Everything the impact stage needs from one signal (all knowable at event time; novelty is past-only)."""

    ticker: str | None
    entity_unknown: bool
    multi_entity: bool
    link_confidence: float
    published_at: datetime
    timestamp_origin: str
    source_type: str
    novelty: float
    event: EventClassification
    sentiment: SentimentResult


@dataclass(frozen=True)
class ImpactOutcome:
    assessment: ImpactAssessment
    audit: ImpactAudit


@dataclass(frozen=True)
class ImpactSkip:
    reason: str


class ImpactModel:
    def __init__(self, card: ImpactModelCard, payload: dict[str, Any], min_link_confidence: float,
                 calendar: EventCalendar | None = None) -> None:
        self.card = card
        if payload.get("schema") != PAYLOAD_SCHEMA:
            raise ConfigError(f"impact artifact has payload schema {payload.get('schema')!r}, expected {PAYLOAD_SCHEMA!r}")
        if payload["feature_schema"] not in (FEATURE_SCHEMA, FEATURE_SCHEMA_V2) or card.feature_schema != payload["feature_schema"]:
            raise ConfigError(f"impact artifact was built for feature schema {payload['feature_schema']!r} (card {card.feature_schema!r}), code knows "
                              f"{FEATURE_SCHEMA!r} and {FEATURE_SCHEMA_V2!r}; retrain it")
        self.feature_schema: str = payload["feature_schema"]
        known = set(ALL_FEATURES_V2) if self.feature_schema == FEATURE_SCHEMA_V2 else set(ALL_FEATURES)
        self.calendar = calendar
        self.min_link_confidence = min_link_confidence
        self.model_id = card.id
        self.model_version = card.version
        self.artifact_sha256 = card.artifact_sha256
        self._scopes: dict[str, dict[str, Any]] = {}
        for sc in card.scopes:
            if sc.scope not in SCOPES:
                raise ConfigError(f"impact card has unknown scope {sc.scope!r}")
            if sc.lifecycle is ImpactLifecycle.PRODUCTION and not sc.acceptance.met:
                raise ConfigError(f"impact card scope {sc.scope} is PRODUCTION but its acceptance bar is not met")
            if sc.lifecycle in (ImpactLifecycle.CALIBRATED, ImpactLifecycle.PRODUCTION) and sc.calibration is None:
                raise ConfigError(f"impact card scope {sc.scope} is {sc.lifecycle.value} without a calibration")
            if sc.served:
                if sc.lifecycle not in SERVED:
                    raise ConfigError(f"impact card scope {sc.scope} is served at lifecycle {sc.lifecycle.value}")
                p = payload["scopes"].get(sc.scope)
                if not p:
                    raise ConfigError(f"impact card says scope {sc.scope} is served but the artifact has no model for it")
                for f in p["features"]:
                    if f not in known:
                        raise ConfigError(f"impact artifact uses unknown feature {f!r}")
                self._scopes[sc.scope] = p
        self.lifecycle: dict[str, ImpactLifecycle] = {sc.scope: sc.lifecycle for sc in card.scopes}
        self.needs_calendar = any(f in CAL_NAMES for p in self._scopes.values() for f in p["features"])
        if self.needs_calendar:
            if calendar is None:
                raise ConfigError("this impact model reads the event calendar (earnings dates, 8-K filings, FOMC) but none was supplied")
            pinned = card.dataset.get("calendar") if isinstance(card.dataset.get("calendar"), dict) else None
            if pinned and any(calendar.digests.get(k) != v for k, v in pinned.items()):
                raise ConfigError("the event calendar files do not match the hashes pinned in the impact model card: they were modified, "
                                  "or the model must be retrained")

    @classmethod
    def load(cls, model_dir: Path, min_link_confidence: float = 0.8, calendar: EventCalendar | None = None) -> ImpactModel:
        hint = "run `make train-impact` to rebuild it (needs data/modeling/impact_table.jsonl via `make impact-table`, see docs/notes/IMPACT_MODEL.md)"
        card_path, art_path = model_dir / CARD_FILE, model_dir / ARTIFACT_FILE
        for p in (card_path, art_path):
            if not p.is_file():
                raise ConfigError(f"impact model file missing: {p}; {hint}")
        try:
            card = ImpactModelCard.model_validate_json(card_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConfigError(f"invalid impact model card {card_path}: {exc}") from exc
        actual = _file_sha256(art_path)
        if actual != card.artifact_sha256:
            raise ConfigError(f"impact artifact {art_path} does not match its model card (sha256 {actual[:12]} != "
                              f"{card.artifact_sha256[:12]}): the file was modified or replaced; {hint}")
        installed = metadata.version("scikit-learn")
        built = card.libraries.get("scikit-learn")
        if installed != built:
            raise ConfigError(f"impact artifact was built with scikit-learn {built}, installed is {installed}; "
                              f"install the pinned version from requirements.txt or {hint}")
        import joblib  # sha256 verified above, so the pickle is exactly the committed artifact

        return cls(card, joblib.load(art_path), min_link_confidence, calendar)

    # ------------------------------------------------------------------------------------------------- introspection
    @property
    def served_scopes(self) -> list[str]:
        return sorted(self._scopes)

    def serves(self, scope: str) -> bool:
        return scope in self._scopes

    def features(self, scope: str) -> list[str]:
        return list(self._scopes[scope]["features"])

    def scope_of(self, inp: ImpactInput) -> str | None:
        if inp.entity_unknown:
            return MARKET
        if inp.ticker and not inp.multi_entity and inp.link_confidence >= self.min_link_confidence:
            return ISSUER
        return None

    # ------------------------------------------------------------------------------------------------- the model
    def vector(self, scope: str, feats: dict[str, float]) -> list[float]:
        return [float(feats.get(f, float("nan"))) for f in self._scopes[scope]["features"]]

    def predict_log(self, scope: str, rows: list[list[float]]) -> list[float]:
        import numpy as np

        return [float(v) for v in self._scopes[scope]["model"].predict(np.asarray(rows, dtype=float))]

    def calibrate(self, scope: str, pred_log: float) -> tuple[float, int, dict[str, Any] | None]:
        """(continuous value in [0, 10], integer score, the reference bucket it falls in)."""
        cal = self._scopes[scope]["cal"]
        value, score = calibrate_value(cal, pred_log)
        bucket = next((b for b in cal["bins"] if b["score_low"] <= score <= b["score_high"]), None)
        return value, score, bucket

    def attribute(self, scope: str, x: list[float]) -> tuple[list[float], float, float]:
        """Per-feature contributions in log-severity, the baseline prediction, and the prediction itself.

        Ceteris-paribus substitution against a reference row (training medians). For an additive model (gradient boosting with
        one feature per interaction group, or a linear model) baseline + sum(contributions) equals the prediction exactly.
        """
        p = self._scopes[scope]
        return attribute_row(p["model"], p["ref_row"], x)

    # ------------------------------------------------------------------------------------------------- one signal
    def assess(self, inp: ImpactInput, context: MarketContext) -> ImpactOutcome | ImpactSkip:
        scope = self.scope_of(inp)
        if scope is None:
            return ImpactSkip("not a single, confidently resolved issuer and not market-wide: the impact model has no scope for it")
        if scope not in self._scopes:
            return ImpactSkip(f"no served impact model for scope {scope} (lifecycle {self.lifecycle.get(scope, ImpactLifecycle.NOT_AVAILABLE).value})")
        if inp.timestamp_origin == "SYNTHETIC_REPLAY_CLOCK":
            return ImpactSkip("the document has no real timestamp (replay assigned one): there is no event time to measure from")
        if inp.event.no_event_probability is None:
            return ImpactSkip("the event model's output is missing: the impact model reads it")
        key, timing, why = context.anchor(inp.published_at, inp.timestamp_origin)
        if key is None:
            return ImpactSkip(f"no market context for this report: {why}")
        if scope == ISSUER:
            raw = context.issuer_features(inp.ticker or "", key)
            if raw is None:
                return ImpactSkip(f"no market context for {inp.ticker} at session {key} (too little price history, or not covered)")
        else:
            raw = context.market_features(key)
            if raw is None:
                return ImpactSkip(f"no market context for the market at session {key}")
        feats = {
            **state_features(scope, raw),
            **doc_features(scope, inp.published_at, timing, context.rules, inp.source_type, inp.novelty, inp.link_confidence),
            **text_features(inp.event.probabilities, inp.event.no_event_probability, inp.sentiment.positive, inp.sentiment.negative),
        }
        if self.needs_calendar and self.calendar is not None:
            d0, d1 = reaction_dates(context, key)
            cal = (self.calendar.issuer_features(inp.ticker or "", inp.published_at, d0, d1) if scope == ISSUER
                   else self.calendar.market_features(d0, d1))
            feats.update({k: quantize(v) for k, v in cal.items()})
        names = self._scopes[scope]["features"]
        x = self.vector(scope, feats)
        contrib, base, pred_log = self.attribute(scope, x)
        value, score, bucket = self.calibrate(scope, pred_log)
        pred_sev = max(0.0, math.expm1(pred_log))
        sc = self.card.scope(scope)
        assert sc is not None
        lifecycle = sc.lifecycle
        kind = sc.attribution.kind if sc.attribution else "additive"
        exact = bool(sc.attribution and sc.attribution.exact)
        order = sorted(range(len(names)), key=lambda j: -abs(contrib[j]))
        drivers = [ImpactDriver(feature="baseline", contribution=round(base, 4), note="the model's output for a typical event (training medians)")]
        for j in order[:TOP_DRIVERS]:
            v = x[j]
            drivers.append(ImpactDriver(feature=names[j], contribution=round(contrib[j], 4), note=feature_group_v2(names[j]),
                                        value=None if v != v else round(v, 6)))
        rest = order[TOP_DRIVERS:]
        if rest:
            drivers.append(ImpactDriver(feature=f"{len(rest)} other features", contribution=round(sum(contrib[j] for j in rest), 4),
                                        note="the remaining inputs, summed"))
        basis = ("log-severity, ln(1 + |z|): baseline + contributions = the model's prediction" if exact else
                 "log-severity, ln(1 + |z|): each feature moved alone from its typical value (does not sum to the prediction)")
        assessment = ImpactAssessment(
            score=score, raw=round(min(1.0, max(0.0, value / 10)), 4), drivers=drivers,
            quantisation=f"ceil(raw * 10), min 1; raw = rank-calibrated severity ({kind} model {self.model_id})",
            scope=scope, predicted_severity=round(pred_sev, 4),
            comparable_events=bucket["n_episodes"] if bucket else None,
            score_low=bucket["realised_score_q10"] if bucket else None, score_high=bucket["realised_score_q90"] if bucket else None,
            realised_severity_low=bucket["severity_q10"] if bucket else None,
            realised_severity_median=bucket["severity_q50"] if bucket else None,
            realised_severity_high=bucket["severity_q90"] if bucket else None,
            p_extreme=bucket["p_extreme"] if bucket else None, driver_basis=basis)
        finite = {f: round(v, 6) for f, v in zip(names, x, strict=True) if v == v}
        audit = ImpactAudit(
            model_id=self.model_id, model_version=self.model_version, artifact_sha256=self.artifact_sha256, lifecycle=lifecycle,
            scope=ImpactScope(scope), feature_schema=self.feature_schema, calibrated=True, session=key, timing=timing,
            timing_reliable=timing not in UNRELIABLE_TIMING, market_context_as_of=context.last_session, inputs=finite,
            missing_inputs=[f for f, v in zip(names, x, strict=True) if v != v])
        return ImpactOutcome(assessment, audit)


__all__ = ["ImpactInput", "ImpactModel", "ImpactOutcome", "ImpactSkip", "attribute_row", "calibrate_value", "interp", "score_knots", "to_score"]
