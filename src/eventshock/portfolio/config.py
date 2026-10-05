"""``configs/portfolio.yaml``: limits, tolerances, alias maps and display bands (no market assumption lives here)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..config import ConfigError, _read_yaml


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Limits(_Cfg):
    max_portfolios: int = Field(gt=0)
    max_holdings: int = Field(gt=0)
    max_name_length: int = Field(gt=0)
    default_total_value: float = Field(gt=0)


class WeightRules(_Cfg):
    sum_tolerance_pp: float = Field(ge=0, le=5)


class BetaRules(_Cfg):
    window_sessions: int = Field(gt=20)
    min_observations: int = Field(gt=10)
    prior_mean: float
    prior_variance_floor: float = Field(gt=0)
    floor: float = Field(ge=-1, le=3)
    cap: float = Field(ge=-1, le=3)


class RelevanceBands(_Cfg):
    high_share: float = Field(gt=0, le=1)
    medium_share: float = Field(gt=0, le=1)


class PortfolioConfig(_Cfg):
    version: str
    limits: Limits
    weights: WeightRules
    betas: BetaRules
    relevance_bands: RelevanceBands
    sector_aliases: dict[str, str]
    region_aliases: dict[str, str]
    cash_tickers: list[str]

    def band(self, share: float | None) -> str:
        """LOW / MEDIUM / HIGH from the share of the book an event reaches (display bands, see the config)."""
        if share is None:
            return "UNDETERMINED"
        if share <= 0:
            return "NONE"
        if share >= self.relevance_bands.high_share:
            return "HIGH"
        return "MEDIUM" if share >= self.relevance_bands.medium_share else "LOW"


def load_portfolio_config(config_dir: Path) -> PortfolioConfig:
    cfg = PortfolioConfig.model_validate(_read_yaml(config_dir / "portfolio.yaml"))
    if cfg.relevance_bands.medium_share >= cfg.relevance_bands.high_share:
        raise ConfigError("portfolio.yaml: relevance_bands.medium_share must be below high_share")
    return cfg
