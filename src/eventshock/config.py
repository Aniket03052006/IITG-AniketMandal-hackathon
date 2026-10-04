"""Settings and validated YAML loaders. Configuration lives outside code (CLAUDE.md rule 8)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .domain import EventCategory, RunMode, Scenario

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """Raised for missing or invalid configuration; never swallowed."""


class StressConfig(BaseModel):
    trigger_threshold: float = Field(default=7, ge=1, le=10)
    severity_scale_min: float = Field(default=0.5, gt=0)
    severity_scale_max: float = Field(default=1.5, gt=0)
    top_n_positions: int = Field(default=8, ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> StressConfig:
        if self.severity_scale_min > self.severity_scale_max:
            raise ValueError("severity_scale_min must be <= severity_scale_max")
        return self


class DataConfig(BaseModel):
    # replay: real-source pack through the pipeline; demo: Stage-1 fixtures
    profile: Literal["replay", "demo"] = "replay"
    fixtures_dir: str = "data/fixtures"
    replay_dir: str = "data/replay"


class AppConfig(BaseModel):
    mode: RunMode = RunMode.REPLAY
    base_currency: str = "USD"
    stress: StressConfig = StressConfig()
    data: DataConfig = DataConfig()


class Settings(BaseSettings):
    """Environment overrides (``EVENTSHOCK_*``). See ``.env.example``."""

    model_config = SettingsConfigDict(env_prefix="EVENTSHOCK_", env_file=".env", extra="ignore", populate_by_name=True)

    config_dir: Path = REPO_ROOT / "configs"
    fixtures_dir: Path | None = None
    replay_dir: Path | None = None
    sentiment_model_dir: Path | None = None  # overrides model_dir in configs/sentiment_model.yaml
    event_model_dir: Path | None = None  # overrides model_dir in configs/event_model.yaml
    impact_model_dir: Path | None = None  # overrides model_dir in configs/impact_model.yaml
    profile: Literal["replay", "demo"] | None = None
    web_dist_dir: Path = REPO_ROOT / "web" / "dist"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    trigger_threshold: float | None = None
    journal_path: Path | None = None  # overrides configs/live.yaml: journal (tests point it at a temp file)
    capture_path: Path | None = None  # overrides configs/live.yaml: source.capture.path
    live_source: Literal["gdelt", "capture"] | None = None  # EVENTSHOCK_LIVE_SOURCE=capture replays the capture file instead of calling GDELT
    live: bool | None = None  # EVENTSHOCK_LIVE=1 turns the live feed on (overrides configs/live.yaml: enabled)
    llm: bool | None = None  # EVENTSHOCK_LLM=1 lets a language model read new text (needs a key); overrides configs/llm.yaml: enabled
    llm_model: str | None = None  # EVENTSHOCK_LLM_MODEL overrides configs/llm.yaml: model
    llm_cache_path: Path | None = None  # EVENTSHOCK_LLM_CACHE_PATH overrides configs/llm.yaml: cache.path (tests point it at a temp file)
    llm_provider: Literal["groq", "anthropic"] | None = None  # EVENTSHOCK_LLM_PROVIDER overrides configs/llm.yaml: provider
    # provider keys are read from the environment / .env only, under the providers' own names (never from a config file)
    anthropic_api_key: str | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "EVENTSHOCK_ANTHROPIC_API_KEY"))
    groq_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GROQ_API_KEY", "EVENTSHOCK_GROQ_API_KEY"))

    def llm_key(self, provider: str) -> str | None:
        return {"anthropic": self.anthropic_api_key, "groq": self.groq_api_key}.get(provider)


class TaxonomyEntry(BaseModel):
    id: EventCategory
    label: str
    description: str
    default_scenario: str


class Taxonomy(BaseModel):
    version: str
    categories: list[TaxonomyEntry]

    @model_validator(mode="after")
    def _complete(self) -> Taxonomy:
        ids = [c.id for c in self.categories]
        if set(ids) != set(EventCategory) or len(ids) != len(set(ids)):
            raise ValueError("taxonomy must list every EventCategory exactly once")
        return self


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"missing config file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def load_app_config(settings: Settings) -> AppConfig:
    cfg = AppConfig.model_validate(_read_yaml(settings.config_dir / "app.yaml"))
    if settings.trigger_threshold is not None:
        cfg.stress.trigger_threshold = settings.trigger_threshold
    if settings.profile is not None:
        cfg.data.profile = settings.profile
    return cfg


def load_taxonomy(settings: Settings) -> Taxonomy:
    return Taxonomy.model_validate(_read_yaml(settings.config_dir / "event_taxonomy.yaml"))


def load_scenarios(settings: Settings) -> tuple[str, list[Scenario]]:
    data = _read_yaml(settings.config_dir / "scenarios.yaml")
    scenarios = [Scenario.model_validate(s) for s in data.get("scenarios", [])]
    return str(data.get("version", "0")), scenarios


def resolve_fixtures_dir(settings: Settings, cfg: AppConfig) -> Path:
    path = settings.fixtures_dir or Path(cfg.data.fixtures_dir)
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_replay_dir(settings: Settings, cfg: AppConfig) -> Path:
    path = settings.replay_dir or Path(cfg.data.replay_dir)
    return path if path.is_absolute() else REPO_ROOT / path
