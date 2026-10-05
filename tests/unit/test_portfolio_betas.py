"""Single-factor trailing betas: the regression, the shrinkage, the window, and the committed artifact."""

from __future__ import annotations

import json
import math
import random
from types import SimpleNamespace

import pytest

from eventshock.portfolio.betas import PATH, IssuerBetas, build_betas, ols_beta, vasicek
from eventshock.portfolio.config import BetaRules
from tests.portfolio_helpers import ROOT

RULES = BetaRules(window_sessions=250, min_observations=200, prior_mean=1.0, prior_variance_floor=0.01, floor=0.0, cap=3.0)


def store(n=400, seed=1):
    rng = random.Random(seed)
    mkt = [float("nan")] + [rng.gauss(0, 0.01) for _ in range(n - 1)]
    ret = {"^GSPC": mkt}
    ret["TWO"] = [float("nan")] + [2 * m + rng.gauss(0, 0.002) for m in mkt[1:]]
    ret["NEG"] = [float("nan")] + [-1 * m + rng.gauss(0, 0.002) for m in mkt[1:]]
    ret["NOISE"] = [float("nan")] + [rng.gauss(0, 0.02) for _ in mkt[1:]]
    ret["SHORT"] = [float("nan")] * (n - 50) + [rng.gauss(0, 0.01) for _ in range(50)]
    return SimpleNamespace(ret=ret, dates=[f"d{i}" for i in range(n)], market="^GSPC")


def test_ols_recovers_a_known_slope() -> None:
    m = [0.01 * math.sin(i) for i in range(300)]
    b, r2, n, se = ols_beta([2 * x for x in m], m, 200)
    assert b == pytest.approx(2.0) and r2 == pytest.approx(1.0) and n == 300 and se == pytest.approx(0, abs=1e-9)


def test_ols_needs_enough_pairs_and_market_variance() -> None:
    assert ols_beta([0.01] * 10, [0.01, -0.01] * 5, 200) is None
    assert ols_beta([0.01, 0.02] * 150, [0.0] * 300, 200) is None
    nan = float("nan")
    assert ols_beta([nan] * 300, [0.01, -0.01] * 150, 200) is None


def test_vasicek_moves_noisy_estimates_further_toward_the_prior() -> None:
    assert vasicek(2.0, 0.0, 1.0, 0.5) == 2.0                      # exact estimate: kept
    assert vasicek(2.0, 1.0, 1.0, 0.5) == pytest.approx(1 + 0.5 / 1.5)  # noisy: a third of the way back
    assert vasicek(2.0, 0.1, 1.0, 0.5) > vasicek(2.0, 0.5, 1.0, 0.5)


def test_build_betas_over_the_trailing_window(tmp_path) -> None:
    st = store()
    out = build_betas(st, RULES, ["TWO", "NEG", "NOISE", "SHORT", "MISSING"], tmp_path / "b.json")
    assert set(out["betas"]) == {"TWO", "NEG", "NOISE"}                # too few observations / not in the store: no entry, not a guess
    assert out["betas"]["TWO"]["beta_ols"] == pytest.approx(2.0, abs=0.1) and out["betas"]["NEG"]["beta_ols"] == pytest.approx(-1.0, abs=0.1)
    assert out["as_of"] == "d399" and out["betas"]["TWO"]["n"] == 250
    assert abs(out["betas"]["NOISE"]["beta"] - 1.0) < abs(out["betas"]["NOISE"]["beta_ols"] - 1.0) + 1e-9  # noise shrinks toward 1
    again = build_betas(st, RULES, ["TWO", "NEG", "NOISE"], tmp_path / "c.json")
    assert (tmp_path / "b.json").read_text() == (tmp_path / "c.json").read_text() and again["betas"] == out["betas"]


def test_nothing_before_the_window_changes_the_fit() -> None:
    a = store()
    b = store()
    b.ret["TWO"][:100] = [0.5] * 100                                   # distant history rewritten
    assert build_betas(a, RULES, ["TWO"])["betas"] == build_betas(b, RULES, ["TWO"])["betas"]


def test_the_loader_refuses_a_foreign_schema() -> None:
    with pytest.raises(Exception, match="schema"):
        IssuerBetas({"schema": "nope", "as_of": "x", "betas": {}})


def test_the_committed_artifact_is_complete_and_finite() -> None:
    b = IssuerBetas.load(ROOT)
    assert b is not None and b.as_of == "2026-10-01"
    entities = json.loads((ROOT / "data" / "replay" / "entities.json").read_text(encoding="utf-8"))
    for e in entities:
        fit = b.get(e["ticker"])
        assert fit is not None, e["ticker"]
        assert math.isfinite(fit["beta"]) and math.isfinite(fit["se"]) and fit["n"] >= 200 and 0 <= fit["r2"] <= 1
    assert (ROOT / PATH).is_file() and not {"close", "prices", "volume"} & set(b.data)  # derived statistics only
