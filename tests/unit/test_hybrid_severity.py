"""The transparent severity score: explicit factors and weights, renormalised over what is available, with nothing guessed."""

from __future__ import annotations

import math

import pytest

from eventshock.assessment.config import HybridConfig
from eventshock.assessment.hybrid import HybridInputs, assessed_scope
from eventshock.assessment.model import SemanticReading
from eventshock.config import ConfigError
from tests.assess_helpers import CONFIG_DIR, HYBRID, RULES, SCORER
from tests.fakes import CASES, EARNINGS, REGULATORY


def reading(text: str, **upd) -> SemanticReading:
    r, _ = RULES.extract(text)
    return r.model_copy(update=upd) if upd else r


def inputs(r: SemanticReading, **kw) -> HybridInputs:
    base = dict(reading=r, source_type="NEWS", novelty=None, corroborating_at_event_time=0, vix_level=None)
    return HybridInputs(**{**base, **kw})


def test_the_score_is_one_plus_the_listed_contributions() -> None:
    sev = SCORER.score(inputs(reading(REGULATORY, sentiment=-0.4), novelty=0.8, vix_level=22.0, market_as_of="2026-10-01", market_age_days=1))
    assert sev is not None
    assert math.isclose(1 + sum(f.contribution_points for f in sev.factors), sev.points, abs_tol=2e-3)
    assert math.isclose(sum(f.weight for f in sev.factors if f.available), 1.0, abs_tol=2e-3)
    assert 1 <= sev.low <= sev.score <= sev.high <= 10
    assert "x" in sev.formula and f"{sev.points:.2f}" in sev.formula


def test_an_unavailable_factor_is_omitted_listed_and_the_rest_renormalised() -> None:
    sev = SCORER.score(inputs(reading(REGULATORY)))  # no novelty (no issuer), no market data
    assert sev is not None
    omitted = {o.id: o.reason for o in sev.omitted}
    assert set(omitted) == {"novelty", "market_regime"}
    assert "no issuer" in omitted["novelty"] and "no market data" in omitted["market_regime"]
    unavailable = [f for f in sev.factors if not f.available]
    assert all(f.weight == 0 and f.contribution_points == 0 and f.value is None for f in unavailable)
    assert math.isclose(sum(f.weight for f in sev.factors), 1.0, abs_tol=2e-3)


def test_stale_market_data_is_refused_not_used() -> None:
    r = reading(REGULATORY)
    fresh = SCORER.score(inputs(r, vix_level=30.0, market_as_of="2026-10-01", market_age_days=2))
    stale = SCORER.score(inputs(r, vix_level=30.0, market_as_of="2026-01-01", market_age_days=200))
    assert next(f for f in fresh.factors if f.id == "market_regime").available
    f = next(f for f in stale.factors if f.id == "market_regime")
    assert not f.available and "not the market at the time" in next(o.reason for o in stale.omitted if o.id == "market_regime")


def test_a_harsher_text_never_scores_lower() -> None:
    r = reading(EARNINGS, sentiment=-0.2)
    base = SCORER.score(inputs(r))
    worse_tone = SCORER.score(inputs(r.model_copy(update={"sentiment": -0.9, "sentiment_label": "negative"})))
    more_markers = SCORER.score(inputs(reading(EARNINGS + " The firm also warned of default and bankruptcy.", sentiment=-0.2)))
    assert worse_tone.points > base.points
    assert more_markers.points > base.points


def test_neutral_tone_lowers_the_signal_and_the_driver_says_so() -> None:
    sev = SCORER.score(inputs(reading(REGULATORY, sentiment=0.0, sentiment_label="neutral")))
    tone = next(d for d in sev.drivers if d.factor_id == "tone")
    assert tone.direction == "DOWN" and "neutral" in tone.text.lower()


def test_drivers_state_the_computed_facts() -> None:
    sev = SCORER.score(inputs(reading(REGULATORY, sentiment=-0.5), corroborating_at_event_time=0))
    texts = " | ".join(d.text for d in sev.drivers)
    assert "Regulatory / Legal event affecting Financials" in texts
    assert "Limited corroboration" in texts
    assert "capital requirement" in texts.lower()
    assert [d.points for d in sev.drivers] == sorted((d.points for d in sev.drivers), reverse=True)


def test_a_non_event_is_not_scored() -> None:
    r, _ = RULES.extract("Lovely weather in the city this weekend, enjoy the sunshine everyone")
    assert SCORER.score(inputs(r)) is None


def test_uncertainty_removes_points_and_the_amount_is_reported() -> None:
    r = reading(REGULATORY, sentiment=-0.5)
    sure = SCORER.score(inputs(r.model_copy(update={"uncertainty": 0.0})))
    unsure = SCORER.score(inputs(r.model_copy(update={"uncertainty": 1.0})))
    assert sure.uncertainty_points_removed == 0 and unsure.uncertainty_points_removed > 0
    assert unsure.points < sure.points


def test_the_sensitivity_range_is_labelled_as_assumption_sensitivity() -> None:
    sev = SCORER.score(inputs(reading(REGULATORY, sentiment=-0.5)))
    assert "not a statistical interval" in sev.range_basis and "30%" in sev.range_basis


@pytest.mark.parametrize("name,scope", [("regulatory", "SECTOR"), ("monetary", "MARKET"), ("geopolitical", "SECTOR"), ("unknown", "COMPANY")])
def test_breadth_follows_what_the_text_is_about(name: str, scope: str) -> None:
    assert assessed_scope(reading(CASES[name]["text"])) == scope


def test_the_config_rejects_typos_and_missing_priors() -> None:
    import yaml

    raw = yaml.safe_load((CONFIG_DIR / "impact_hybrid.yaml").read_text())
    HybridConfig.model_validate(raw)  # the shipped file is valid
    with pytest.raises(ValueError):
        HybridConfig.model_validate({**raw, "wieghts": raw["weights"]})  # extra key
    bad = {**raw, "category_prior": {k: v for k, v in raw["category_prior"].items() if k != "GEOPOLITICAL"}}
    with pytest.raises(ValueError):
        HybridConfig.model_validate(bad)
    with pytest.raises(ValueError):
        HybridConfig.model_validate({**raw, "weights": {k: 0 for k in raw["weights"]}})


def test_loading_a_broken_config_fails_loudly(tmp_path) -> None:
    from eventshock.assessment.config import load_hybrid_config

    (tmp_path / "impact_hybrid.yaml").write_text("version: x\n")
    with pytest.raises(ConfigError):
        load_hybrid_config(tmp_path)


def test_every_weight_is_documented_in_the_config() -> None:
    text = (CONFIG_DIR / "impact_hybrid.yaml").read_text()
    for k in HYBRID.weights.model_dump():
        assert k in text
    assert "NOT a forecast" in text
