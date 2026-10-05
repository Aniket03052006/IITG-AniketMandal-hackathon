"""Stage 8: the scenario reality check (read-only; the stress arithmetic is untouched)."""

from __future__ import annotations

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.domain import RiskFactor, ShockScope
from eventshock.stress.history_check import GRID, SCHEMA, ShockHistory, _count_at_least, _summary, _windows


def synthetic() -> ShockHistory:
    """Daily moves 1..1000 (in thousandths): a known distribution so every rank can be computed by hand."""
    vals = [i / 1000.0 for i in range(-500, 500)]
    s = _summary(vals)
    return ShockHistory({"schema": SCHEMA, "grid": GRID, "horizons_sessions": [1], "first_session": "2014-01-02", "last_session": "2026-10-01",
                         "series": {k: {"1": s} for k in ("SP500", "SECTOR_BASKET", "ISSUER", "US10Y_BP")}})


class TestWindows:
    def test_compounded_k_session_returns_and_nan_gaps(self):
        r = _windows([float("nan"), 0.1, 0.1, -0.5, 0.0], 2, compound=True)
        assert r == pytest.approx([1.1 * 1.1 - 1, 1.1 * 0.5 - 1, 0.5 - 1])  # windows touching the NaN are skipped

    def test_yield_changes_are_in_basis_points(self):
        assert _windows([4.00, 4.10, 4.35], 1, compound=False) == pytest.approx([10.0, 25.0])
        assert _windows([4.0, float("nan"), 4.2], 1, compound=False) == []


class TestRank:
    def test_exact_counts_in_the_tail_and_interpolation_in_the_body(self):
        s = _summary([i / 1000.0 for i in range(-500, 500)])
        count, beyond = _count_at_least(s, GRID, -0.45, "down")     # exact tail
        assert not beyond and count == 51
        count, _ = _count_at_least(s, GRID, -0.1, "down")           # body: interpolated on the quantile grid
        assert count == pytest.approx(400, abs=3)
        count, _ = _count_at_least(s, GRID, 0.3, "up")
        assert count == pytest.approx(200, abs=3)

    def test_beyond_history_is_flagged_not_extrapolated(self):
        s = _summary([i / 1000.0 for i in range(-500, 500)])
        assert _count_at_least(s, GRID, -0.9, "down") == (0.0, True)
        assert _count_at_least(s, GRID, 0.9, "up") == (0.0, True)


class TestChecks:
    def test_equity_shock_is_ranked_against_the_matching_series(self):
        c = synthetic().check_shock(RiskFactor.EQUITY, ShockScope.MARKET, -0.25)
        h = c.horizons[0]
        assert c.checkable and h.direction == "down" and h.share_as_extreme == pytest.approx(0.25, abs=0.01) and h.one_in == pytest.approx(4.0, rel=0.05)
        assert "S&P 500" in c.basis and "about 1 window in" in c.reading

    def test_a_shock_larger_than_anything_on_record_says_so(self):
        c = synthetic().check_shock(RiskFactor.RATES_BPS, ShockScope.MARKET, 900.0)
        assert c.horizons[0].beyond_history and c.horizons[0].one_in is None and "larger than any on record" in c.reading

    @pytest.mark.parametrize("factor", [RiskFactor.CREDIT_SPREAD_BPS, RiskFactor.PD_MULTIPLIER, RiskFactor.LGD_ADD])
    def test_credit_factors_are_never_pretended_to_be_checkable(self, factor):
        c = synthetic().check_shock(factor, ShockScope.MARKET, 1.5)
        assert not c.checkable and c.horizons == [] and "unvalidated assumption" in c.reading

    def test_a_bad_artifact_is_refused(self, tmp_path):
        with pytest.raises(ConfigError, match="schema"):
            ShockHistory({"schema": "other"})
        with pytest.raises(ConfigError, match="shock-history"):
            ShockHistory.load(tmp_path)


class TestCommittedArtifact:
    """Pins facts about the real, committed history so a silent change of method or data shows up."""

    h = ShockHistory.load(REPO_ROOT)

    def test_shape_and_provenance(self):
        d = self.h.data
        assert d["first_session"] == "2014-01-02" and d["horizons_sessions"] == [1, 5, 21] and set(d["series"]) == {"SP500", "SECTOR_BASKET", "ISSUER", "US10Y_BP"}
        assert "prices" not in d and d["series"]["SP500"]["1"]["n"] > 3000

    def test_known_market_history(self):
        d = self.h.data["series"]["SP500"]["1"]
        assert d["worst"][0] < -0.10 and d["best"][-1] > 0.08      # March 2020
        c = self.h.check_shock(RiskFactor.EQUITY, ShockScope.MARKET, -0.08)
        assert c.horizons[0].share_as_extreme < 0.002 and not c.horizons[0].beyond_history
        assert c.horizons[2].share_as_extreme > c.horizons[0].share_as_extreme    # the same fall is less rare over 21 sessions than over 1

    def test_the_parallel_plus_100bp_rate_shock_exceeds_the_worst_21_session_move_on_record(self):
        c = self.h.check_shock(RiskFactor.RATES_BPS, ShockScope.MARKET, 100.0)
        assert c.horizons[2].beyond_history or c.horizons[2].one_in > 1000
