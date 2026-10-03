"""One feature schema for training and serving, every name registered as event-time, none of the banned ones."""

from __future__ import annotations

import pytest

from eventshock.modeling.leakage import (
    AT_EVENT_TIME,
    FEATURE_REGISTRY,
    LeakageError,
    check_features,
    require_clean,
)
from eventshock.pipeline import impact_features as F


def test_every_model_feature_is_registered_as_event_time():
    bad = [n for n in F.ALL_FEATURES if FEATURE_REGISTRY.get(n, ("UNREGISTERED", ""))[0] != AT_EVENT_TIME]
    assert bad == []
    require_clean(check_features(F.ALL_FEATURES))


@pytest.mark.parametrize("banned", ["unique_domains", "source_count", "coverage_velocity", "episode_size", "ticker", "adapter",
                                    "year", "placeholder_event", "abs_z", "z", "score", "same_day_return"])
def test_banned_features_cannot_be_added_to_the_schema(banned):
    assert banned not in F.ALL_FEATURES
    with pytest.raises(LeakageError):
        require_clean(check_features([*F.ALL_FEATURES, banned]))


def test_unregistered_features_are_refused():
    with pytest.raises(LeakageError):
        require_clean(check_features(["f_some_new_thing"]))


def test_rungs_are_nested_and_scoped():
    for scope in F.SCOPES:
        r2, r3 = F.feature_names(scope, "R2"), F.feature_names(scope, "R3")
        assert set(r2) < set(r3) and len(r2) == len(set(r2))
    assert all(n.startswith(("f_", "t_")) or n in F.DOC[F.ISSUER] for n in F.feature_names(F.ISSUER, "R2"))
    assert not any(n.startswith("f_") for n in F.feature_names(F.MARKET, "R3"))
    assert "link_confidence" not in F.feature_names(F.MARKET, "R3")


def test_text_features_come_only_from_model_outputs():
    from eventshock.domain import EventCategory

    probs = {c: 0.1 for c in EventCategory}
    out = F.text_features(probs, 0.2, 0.6, 0.1)
    assert set(out) == set(F.TEXT)
    assert out["sent_abs"] == pytest.approx(0.5) and out["ev_p_none"] == 0.2


def test_state_features_prefix_and_fill_missing_with_nan():
    out = F.state_features(F.ISSUER, {"sigma_60": 0.01, "ret_1d": 0.002})
    assert list(out) == F.ISSUER_STATE and out["f_sigma_60"] == 0.01
    assert out["f_vix_level"] != out["f_vix_level"]  # NaN: absent stays absent, never imputed here
