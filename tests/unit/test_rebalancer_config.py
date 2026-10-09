"""configs/rebalancer.yaml is strict: a misspelt key, an index outside 10-20 stocks or bounds that cannot hold a fully invested index are errors at load time."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.rebalancer.config import load_rebalancer_config

SHIPPED = yaml.safe_load((REPO_ROOT / "configs" / "rebalancer.yaml").read_text(encoding="utf-8"))


def write(tmp_path: Path, raw: dict) -> Path:
    (tmp_path / "rebalancer.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return tmp_path


def edit(**path_values) -> dict:
    import copy
    raw = copy.deepcopy(SHIPPED)
    for path, v in path_values.items():
        node = raw
        *head, last = path.split("__")
        for k in head:
            node = node[k]
        node[last] = v
    return raw


def test_the_shipped_config_loads_and_is_a_fully_invested_band():
    cfg = load_rebalancer_config(REPO_ROOT / "configs")
    lo, hi = cfg.limits()
    assert 10 <= cfg.n <= 20 and lo < cfg.benchmark_weight < hi
    assert lo * cfg.n <= 1 <= hi * cfg.n


def test_the_config_says_every_number_is_a_judgement_prior():
    assert "JUDGEMENT PRIOR" in (REPO_ROOT / "configs" / "rebalancer.yaml").read_text(encoding="utf-8")


def test_a_misspelt_key_is_an_error_not_ignored(tmp_path):
    with pytest.raises(ConfigError, match="half_life_hour"):
        load_rebalancer_config(write(tmp_path, edit(evidence__half_life_hour=36)))


@pytest.mark.parametrize("n", [9, 21])
def test_the_index_holds_ten_to_twenty_stocks(tmp_path, n):
    tickers = [f"T{i}" for i in range(n)]
    with pytest.raises(ConfigError, match="10-20"):
        load_rebalancer_config(write(tmp_path, edit(universe__tickers=tickers)))


def test_a_duplicate_or_lower_case_ticker_is_an_error(tmp_path):
    t = SHIPPED["universe"]["tickers"]
    with pytest.raises(ConfigError, match="twice"):
        load_rebalancer_config(write(tmp_path, edit(universe__tickers=t[:-1] + [t[0]])))
    with pytest.raises(ConfigError, match="upper-case"):
        load_rebalancer_config(write(tmp_path, edit(universe__tickers=t[:-1] + ["aapl"])))


def test_bounds_that_exclude_the_benchmark_are_an_error(tmp_path):
    with pytest.raises(ConfigError, match="benchmark weight"):
        load_rebalancer_config(write(tmp_path, edit(bounds__floor=0.5, bounds__cap=0.6)))
    with pytest.raises(ConfigError, match="benchmark weight"):
        load_rebalancer_config(write(tmp_path, edit(bounds__cap=0.06)))


def test_a_tilt_or_turnover_above_its_limit_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="strength_max"):
        load_rebalancer_config(write(tmp_path, edit(tilt__strength=99)))
    with pytest.raises(ConfigError, match="max_per_cycle_limit"):
        load_rebalancer_config(write(tmp_path, edit(turnover__max_per_cycle=0.5)))
    with pytest.raises(ConfigError, match="min_trade"):
        load_rebalancer_config(write(tmp_path, edit(turnover__min_trade=0.05)))


def test_a_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="missing"):
        load_rebalancer_config(tmp_path)


# ------------------------------------------------------------------------------------------------------------------ strategies, risk, impact, explain
def test_the_baseline_strategy_is_required_and_is_the_unconstrained_sentiment_rule(tmp_path):
    cfg = load_rebalancer_config(REPO_ROOT / "configs")
    base = cfg.strategies["sentiment"]
    assert (base.score, base.sector_cap, base.vol_limit, base.liquidity_floor) == ("sentiment", False, False, False)
    assert set(cfg.strategies) == {"sentiment", "sentiment_risk", "sentiment_impact"}
    raw = edit()
    del raw["strategies"]["sentiment"]
    with pytest.raises(ConfigError, match="baseline"):
        load_rebalancer_config(write(tmp_path, raw))


def test_the_baseline_cannot_be_given_a_constraint_or_the_impact_score(tmp_path):
    raw = edit()
    raw["strategies"]["sentiment"]["sector_cap"] = True
    with pytest.raises(ConfigError, match="baseline"):
        load_rebalancer_config(write(tmp_path, raw))
    raw = edit()
    raw["strategies"]["sentiment"]["score"] = "sentiment_impact"
    with pytest.raises(ConfigError, match="baseline"):
        load_rebalancer_config(write(tmp_path, raw))


def test_a_strategy_with_an_unknown_score_source_or_a_misspelt_flag_is_an_error(tmp_path):
    raw = edit()
    raw["strategies"]["sentiment_risk"]["score"] = "vibes"
    with pytest.raises(ConfigError):
        load_rebalancer_config(write(tmp_path, raw))
    raw = edit()
    raw["strategies"]["sentiment_risk"]["sector_capp"] = True
    with pytest.raises(ConfigError, match="sector_capp"):
        load_rebalancer_config(write(tmp_path, raw))


@pytest.mark.parametrize("path,value", [("risk__sector_cap__ratio", 0), ("risk__vol_aware__gamma", 0), ("risk__vol_aware__reference", "mean"), ("risk__liquidity__min_adv_usd", -1),
                                        ("risk__liquidity__max_participation", 0), ("impact__floor", 0), ("impact__floor", 1.5), ("explain__conflict_min_share", 0.6),
                                        ("explain__stale_after_half_lives", 0)])
def test_risk_impact_and_explain_values_are_validated(tmp_path, path, value):
    with pytest.raises(ConfigError):
        load_rebalancer_config(write(tmp_path, edit(**{path: value})))


def test_dotted_overrides_reach_the_new_sections():
    cfg = load_rebalancer_config(REPO_ROOT / "configs", {"risk.sector_cap.ratio": 0.5, "impact.floor": 0.25})
    assert cfg.risk.sector_cap.ratio == 0.5 and cfg.impact.floor == 0.25
