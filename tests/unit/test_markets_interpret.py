"""Interpretation: ordered, named rules; descriptive wording that never says the market 'confirms' EventShock; divergence is an observation, not a verdict."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eventshock.markets.interpret import CAVEATS, interpret
from eventshock.markets.models import (
    ExternalMarketObservation,
    Interpretation,
    MarketStatus,
    ProviderCategory,
)
from tests.markets_helpers import MCFG

ICFG = MCFG.interpretation
T = datetime(2026, 9, 25, 12, tzinfo=UTC)


def obs(p=0.60, prev=0.50, oi=2000.0, vol=3000.0, **kw):  # noqa: ANN001, ANN003, ANN201
    change = None if p is None or prev is None else (p - prev) * 100.0
    base = dict(provider="kalshi", category=ProviderCategory.PREDICTION_MARKET, source="kalshi-snapshot", market_id="M", series_id="S", question="q", probability=p, previous_probability=prev,
                probability_change_pp=change, observed_at=T, previous_observed_at=None, market_status=MarketStatus.OPEN, raw_status="active", volume=vol, volume_24h=10.0, open_interest=oi,
                close_time=None, source_url=None, synthetic=False, provenance=[])
    base.update(kw)
    return ExternalMarketObservation(**base)


def run(o, *, orientation="UP", sev=8.0, prev=6.0, mat="HIGH"):  # noqa: ANN001, ANN201
    return interpret(o, orientation=orientation, orientation_basis="test", severity=sev, severity_prev=prev, materiality=mat, cfg=ICFG)


def test_a_material_repricing_toward_risk_while_severity_rose_is_market_repriced():
    r = run(obs(p=0.72, prev=0.48))
    assert r.code is Interpretation.MARKET_REPRICED and r.rule == "R1_REPRICED_WITH_SEVERITY_UP" and r.market_direction == "TOWARD_RISK" and r.eventshock_direction == "UP"
    assert "+24.0 pp toward risk" in r.text and "6 → 8" in r.text and r.eventshock_elevated


def test_a_smaller_move_toward_risk_while_elevated_is_aligned_and_says_directionally():
    r = run(obs(p=0.54, prev=0.50), prev=8.0)                                     # +4 pp: a direction but not a re-pricing; severity unchanged
    assert r.code is Interpretation.ALIGNED and r.rule == "R2_ELEVATED_AND_TOWARD_RISK"
    assert r.text == "External market observation is directionally aligned with EventShock's assessment."
    assert "confirm" not in r.text.lower() and "validat" not in r.text.lower() and "proves" not in r.text.lower()


def test_aligned_also_when_eventshock_is_not_elevated_and_the_market_does_not_move_toward_risk():
    for p in (0.50, 0.40):
        r = run(obs(p=p, prev=0.50), sev=3.0, mat="LOW", prev=3.0)
        assert r.code is Interpretation.ALIGNED and r.rule == "R2_NOT_ELEVATED_AND_NO_RISK_MOVE" and not r.eventshock_elevated


def test_an_elevated_assessment_with_a_flat_or_opposite_market_is_divergent_and_says_it_proves_nothing():
    flat = run(obs(p=0.504, prev=0.50), prev=8.0)
    assert flat.code is Interpretation.DIVERGENT and flat.rule == "R3_ELEVATED_WITHOUT_RISK_MOVE" and "has not materially repriced" in flat.text
    away = run(obs(p=0.42, prev=0.50), prev=8.0)
    assert away.code is Interpretation.DIVERGENT and "moved the other way (−8.0 pp)" in away.text
    for r in (flat, away):
        assert "does not show that either is wrong" in r.text and "observation worth monitoring" in r.text


def test_a_market_moving_toward_risk_while_eventshock_is_not_elevated_is_also_divergent():
    r = run(obs(p=0.70, prev=0.50), sev=3.0, mat="LOW", prev=3.0)
    assert r.code is Interpretation.DIVERGENT and r.rule == "R3_RISK_MOVE_WITHOUT_ELEVATION"


def test_a_thin_or_unpriced_market_is_low_information_whatever_it_did():
    assert run(obs(oi=3.0, vol=5.0)).code is Interpretation.LOW_INFORMATION and run(obs(oi=3.0, vol=5.0)).rule == "R0_LOW_INFORMATION"
    unpriced = run(obs(p=None, prev=None))
    assert unpriced.code is Interpretation.LOW_INFORMATION and "no trade and no usable two-sided quote" in unpriced.reason
    assert run(obs(oi=3.0, vol=5000.0)).code is not Interpretation.LOW_INFORMATION                   # either measure of activity is enough
    assert run(obs(oi=5000.0, vol=1.0)).code is not Interpretation.LOW_INFORMATION


def test_a_neutral_orientation_never_claims_a_direction():
    big = run(obs(p=0.72, prev=0.48), orientation="NEUTRAL")
    assert big.code is Interpretation.MARKET_REPRICED and big.rule == "R1_REPRICED_UNMAPPED" and big.market_direction == "UNMAPPED" and "not mapped" in big.text
    small = run(obs(p=0.52, prev=0.50), orientation="NEUTRAL")
    assert small.code is Interpretation.NOT_ASSESSED and small.rule == "R4_NEUTRAL_ORIENTATION"


def test_a_down_orientation_reads_a_falling_probability_as_toward_risk():
    r = run(obs(p=0.30, prev=0.50), orientation="DOWN", prev=8.0)
    assert r.market_direction == "TOWARD_RISK" and r.code is Interpretation.ALIGNED


def test_without_a_previous_observation_nothing_is_assessed_rather_than_guessed():
    r = run(obs(p=0.60, prev=None))
    assert r.code is Interpretation.NOT_ASSESSED and r.rule == "R4_NO_PREVIOUS" and r.market_direction is None


def test_the_boundaries_of_the_thresholds_are_inclusive():
    just = run(obs(p=0.60, prev=0.50), prev=8.0)                                      # exactly +10 pp, severity unchanged: not a re-pricing (needs severity up)
    assert just.code is Interpretation.ALIGNED
    rep = run(obs(p=0.60, prev=0.50))
    assert rep.code is Interpretation.MARKET_REPRICED                                     # exactly the re-pricing threshold with severity up
    under = run(obs(p=0.519, prev=0.50), prev=8.0)                                        # +1.9 pp: below the aligned threshold: FLAT
    assert under.market_direction == "FLAT" and under.code is Interpretation.DIVERGENT


@pytest.mark.parametrize("sev,mat,elevated", [(7.0, None, True), (6.0, "HIGH", True), (6.0, "CRITICAL", True), (6.0, "MEDIUM", False), (None, None, False)])
def test_elevated_means_severity_at_the_threshold_or_a_high_relevance(sev, mat, elevated):
    assert run(obs(), sev=sev, mat=mat, prev=sev).eventshock_elevated is elevated


def test_every_interpretation_carries_the_caveats_and_never_an_empty_reason():
    for o in (obs(), obs(p=None, prev=None), obs(p=0.9, prev=0.1)):
        r = run(o)
        assert r.reason and r.rule and r.text and r.caveats == CAVEATS and "never an input" in " ".join(r.caveats)
