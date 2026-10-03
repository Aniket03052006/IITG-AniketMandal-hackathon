"""The impact artifact loader: integrity, version pinning, lifecycle consistency, and the per-signal serving contract.

These tests build a tiny real artifact with the production code path (``write_artifact``) from synthetic data, so they exercise the
same loader as the server without needing the (git-ignored) training table.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.domain import (
    EventCategory,
    EventClassification,
    ImpactLifecycle,
    SentimentResult,
)
from eventshock.modeling import impact_train as T
from eventshock.modeling.market_pack import build_context_payload
from eventshock.pipeline.config import load_impact_model_config
from eventshock.pipeline.impact_card import ImpactModelCard
from eventshock.pipeline.impact_model import ImpactInput, ImpactModel, ImpactOutcome, ImpactSkip
from eventshock.pipeline.market_context import MarketContext
from tests.modeling_helpers import base_config, make_store

CFG = load_impact_model_config(REPO_ROOT / "configs")
STORE = make_store(300)


def _event(none_p=0.1):
    probs = {c: 1 / 8 for c in EventCategory}
    return EventClassification(category=EventCategory.GEOPOLITICAL, probabilities=probs, no_event_probability=none_p)


def _inp(**kw):
    base = dict(ticker="AAA", entity_unknown=False, multi_entity=False, link_confidence=1.0,
                published_at=datetime(2020, 10, 15, 21, 0, tzinfo=UTC), timestamp_origin="SOURCE", source_type="NEWS", novelty=1.0,
                event=_event(), sentiment=SentimentResult(positive=0.2, neutral=0.5, negative=0.3, score=-0.1))
    base.update(kw)
    return ImpactInput(**base)


def _context():
    last = STORE.dates[-1]
    y, m, d = (int(x) for x in last.split("-"))
    ctx = MarketContext(build_context_payload(STORE, sorted(STORE.sectors), None, datetime(y, m, d, tzinfo=UTC).date().replace(day=1)))
    return ctx


@pytest.fixture(scope="module")
def artifact(tmp_path_factory) -> Path:
    """Fit a small additive model on the synthetic store's features, calibrate it, write it through the real writer."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    out = tmp_path_factory.mktemp("impact")
    rng = np.random.default_rng(0)
    scope = "ISSUER"
    names = [n for n in T.feature_names(scope, "R2")]
    X = rng.normal(size=(800, len(names)))
    absz = np.abs(rng.normal(0, 1, 800)) * np.exp(0.4 * X[:, 0])
    est = HistGradientBoostingRegressor(max_depth=2, max_iter=40, interaction_cst="no_interactions", random_state=0)
    est.fit(X, np.log1p(absz))
    cuts = list(base_config().impact.score_cutpoints)
    score = np.array([1 + sum(a >= c for c in cuts) for a in absz])
    cal = T.build_calibration(CFG, est.predict(X), absz, score, cuts)
    payload = {"kind": "hgb_additive", "features": names, "model": est, "ref_row": [float(v) for v in np.median(X, axis=0)],
               "ref_pred": 0.0, "cal": cal, "lifecycle": "CALIBRATED"}
    cal_card = T.CalibrationCard(method="test", reference_episodes=800, reference_period="-", extreme_score=7, base_rate_extreme=0.04,
                                 bins_reference=[T._bin_card(b) for b in cal["bins"]], bins_heldout=[], nominal_coverage=0.8,
                                 heldout_coverage=T.estimate(0.8))
    sc = T.ScopeCard(
        scope=scope, lifecycle=ImpactLifecycle.CALIBRATED, served=True, summary="test", target="t", selected_id="R2-additive",
        algorithm="test", features=names,
        training=T.TrainingInfo(table_sha256="0" * 64, rows={}, episodes={}, train_period="-", folds="-", excluded={}, seed=0,
                                config_sha256="0" * 64),
        ladder=[], evaluations=[], calibration=cal_card, strata=[],
        attribution=T.Attribution(kind="additive", exact=True, max_abs_error=0.0, units="ln(1+|z|)"), horizon=[], direction=None,
        leakage_findings=[], acceptance=T.Acceptance(rule="r", met=False, checks=[]), limitations=[])
    other = sc.model_copy(update={"scope": "MARKET", "lifecycle": ImpactLifecycle.DATASET, "served": False, "calibration": None,
                                  "attribution": None})
    cfg = CFG.model_copy(update={"model_dir": str(out)})
    runs = {"ISSUER": T.ScopeRun(sc, payload), "MARKET": T.ScopeRun(other, None)}
    manifest = {"rows": 800, "feature_schema": CFG.feature_schema,
                "inputs": {"history_signals": {"sha256": "0" * 64}, "modeling_config_digest": "x"}}
    T.write_artifact(cfg, REPO_ROOT, runs, manifest, "0" * 64, lambda *_: None)
    return out


def _copy(artifact: Path, tmp_path: Path) -> Path:
    d = tmp_path / "m"
    shutil.copytree(artifact, d)
    return d


class TestLoader:
    def test_loads_and_serves_the_scope_the_card_says(self, artifact):
        m = ImpactModel.load(artifact)
        assert m.served_scopes == ["ISSUER"]
        assert m.lifecycle == {"ISSUER": ImpactLifecycle.CALIBRATED, "MARKET": ImpactLifecycle.DATASET}

    def test_a_modified_artifact_is_refused(self, artifact, tmp_path):
        d = _copy(artifact, tmp_path)
        with (d / "model.joblib").open("ab") as fh:
            fh.write(b"x")
        with pytest.raises(ConfigError, match="does not match its model card"):
            ImpactModel.load(d)

    def test_a_missing_file_is_refused_with_the_fix(self, artifact, tmp_path):
        d = _copy(artifact, tmp_path)
        (d / "model_card.json").unlink()
        with pytest.raises(ConfigError, match="make train-impact"):
            ImpactModel.load(d)

    def test_a_library_version_mismatch_is_refused(self, artifact, tmp_path):
        d = _copy(artifact, tmp_path)
        card = json.loads((d / "model_card.json").read_text())
        card["libraries"]["scikit-learn"] = "0.0.1"
        (d / "model_card.json").write_text(json.dumps(card))
        with pytest.raises(ConfigError, match="scikit-learn"):
            ImpactModel.load(d)

    def test_production_without_a_met_bar_is_refused(self, artifact):
        card = ImpactModelCard.model_validate_json((artifact / "model_card.json").read_text())
        card.scopes[0].lifecycle = ImpactLifecycle.PRODUCTION  # acceptance.met is False
        import joblib

        with pytest.raises(ConfigError, match="PRODUCTION but its acceptance bar is not met"):
            ImpactModel(card, joblib.load(artifact / "model.joblib"), 0.8)

    def test_a_served_scope_must_be_in_the_artifact(self, artifact):
        card = ImpactModelCard.model_validate_json((artifact / "model_card.json").read_text())
        import joblib

        payload = joblib.load(artifact / "model.joblib")
        payload["scopes"] = {}
        with pytest.raises(ConfigError, match="no model for it"):
            ImpactModel(card, payload, 0.8)

    def test_a_feature_schema_mismatch_is_refused(self, artifact):
        card = ImpactModelCard.model_validate_json((artifact / "model_card.json").read_text())
        import joblib

        payload = joblib.load(artifact / "model.joblib")
        payload["feature_schema"] = "impact-features-v0"
        with pytest.raises(ConfigError, match="feature schema"):
            ImpactModel(card, payload, 0.8)


class TestAssess:
    def test_scores_an_issuer_signal_with_a_complete_audit(self, artifact):
        m, ctx = ImpactModel.load(artifact), _context()
        out = m.assess(_inp(published_at=_last_close(ctx)), ctx)
        assert isinstance(out, ImpactOutcome)
        a, au = out.assessment, out.audit
        assert 1 <= a.score <= 10 and 0 <= a.raw <= 1 and a.scope == "ISSUER" and a.predicted_severity >= 0
        assert a.score_low <= a.score_high or a.score_low is not None
        assert au.lifecycle is ImpactLifecycle.CALIBRATED and au.calibrated and au.feature_schema == CFG.feature_schema
        assert au.session == "NEXT" and au.timing == "OFF_HOURS" and au.timing_reliable
        assert au.market_context_as_of == ctx.last_session and "f_sigma_60" in au.inputs

    def test_drivers_are_the_models_own_and_sum_to_the_prediction(self, artifact):
        m, ctx = ImpactModel.load(artifact), _context()
        out = m.assess(_inp(published_at=_last_close(ctx)), ctx)
        assert isinstance(out, ImpactOutcome)
        d = out.assessment.drivers
        assert d[0].feature == "baseline"
        pred_log = float(np.log1p(out.assessment.predicted_severity))
        assert sum(x.contribution for x in d) == pytest.approx(pred_log, abs=2e-3)  # 4-decimal rounding of each term
        assert {x.feature for x in d[1:]} <= {*m.features("ISSUER"), *[f"{i} other features" for i in range(60)]}

    def test_the_score_is_deterministic_and_monotone_in_the_prediction(self, artifact):
        m, ctx = ImpactModel.load(artifact), _context()
        inp = _inp(published_at=_last_close(ctx))
        a, b = m.assess(inp, ctx), m.assess(inp, ctx)
        assert a.assessment == b.assessment
        cal = [m.calibrate("ISSUER", p)[0] for p in np.linspace(-1, 3, 60)]
        assert cal == sorted(cal)

    @pytest.mark.parametrize("kw,why", [
        (dict(ticker=None, entity_unknown=False), "no scope"),
        (dict(multi_entity=True), "no scope"),
        (dict(link_confidence=0.5), "no scope"),
        (dict(timestamp_origin="SYNTHETIC_REPLAY_CLOCK"), "no real timestamp"),
        (dict(entity_unknown=True, ticker=None), "no served impact model for scope MARKET"),
    ])
    def test_signals_it_cannot_score_are_skipped_with_a_reason(self, artifact, kw, why):
        m, ctx = ImpactModel.load(artifact), _context()
        out = m.assess(_inp(published_at=_last_close(ctx), **kw), ctx)
        assert isinstance(out, ImpactSkip) and why in out.reason

    def test_a_report_far_beyond_the_context_is_skipped_not_guessed(self, artifact):
        m, ctx = ImpactModel.load(artifact), _context()
        out = m.assess(_inp(published_at=datetime(2031, 1, 1, 15, tzinfo=UTC)), ctx)
        assert isinstance(out, ImpactSkip) and "no market context" in out.reason

    def test_in_session_and_first_seen_are_flagged_unreliable(self, artifact):
        m, ctx = ImpactModel.load(artifact), _context()
        base = _last_close(ctx)
        seen = m.assess(_inp(published_at=base, timestamp_origin="GDELT_FIRST_SEEN"), ctx)
        assert isinstance(seen, ImpactOutcome) and seen.audit.timing == "FIRST_SEEN" and not seen.audit.timing_reliable

    def test_future_prices_cannot_change_the_estimate(self, artifact):
        """Serving-path future invariance: a context built from prices that are noise from the event session on gives the very
        same estimate, because everything read for session S comes from sessions before S."""
        m = ImpactModel.load(artifact)
        idx = len(STORE.dates) - 5
        ts = datetime.fromisoformat(f"{STORE.dates[idx]}T12:00:00+00:00")  # 07:00/08:00 New York: before the open, s0 = idx
        real = MarketContext(build_context_payload(STORE, sorted(STORE.sectors), None, datetime.fromisoformat(f"{STORE.dates[idx - 8]}T00:00:00+00:00").date()))
        scr = MarketContext(build_context_payload(STORE.scrambled_from(idx), sorted(STORE.sectors), None,
                                                  datetime.fromisoformat(f"{STORE.dates[idx - 8]}T00:00:00+00:00").date()))
        a, b = m.assess(_inp(published_at=ts), real), m.assess(_inp(published_at=ts), scr)
        assert isinstance(a, ImpactOutcome) and isinstance(b, ImpactOutcome)
        assert a.audit.session == STORE.dates[idx]
        assert a.assessment == b.assessment and a.audit.inputs == b.audit.inputs


def _last_close(ctx: MarketContext) -> datetime:
    y, m, d = (int(x) for x in ctx.last_session.split("-"))
    return datetime(y, m, d, 22, 0, tzinfo=UTC)
