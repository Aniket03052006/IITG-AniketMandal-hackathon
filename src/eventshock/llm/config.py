"""``configs/llm.yaml`` plus the environment overrides (``EVENTSHOCK_LLM*``). The API key is read from the environment only, never from a file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import REPO_ROOT, ConfigError
from ..pipeline.config import _load


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CacheConfig(_Strict):
    path: str
    max_entries: int = Field(ge=10)


class GroundingConfig(_Strict):
    min_quote_chars: int = Field(ge=1)
    max_quotes: int = Field(ge=1)
    max_entities: int = Field(ge=1)
    max_quote_share: float = Field(gt=0, le=1, description="a quote covering more than this share of a longer text points at nothing and is dropped")
    share_applies_above_chars: int = Field(ge=1)


class ProviderConfig(_Strict):
    model: str
    api_url: str
    api_version: str = ""
    key_env: str = Field(description="the environment variable the API key is read from (never a file)")
    request_extra: dict[str, Any] = Field(default_factory=dict, description="extra fields merged into the request body (e.g. a reasoning-effort setting)")


class LLMConfig(_Strict):
    version: str
    enabled: bool = False
    provider: str = "groq"
    providers: dict[str, ProviderConfig]
    # the active provider's values, filled from `providers` (see `for_provider`); not written in the YAML
    model: str = ""
    api_url: str = ""
    api_version: str = ""
    key_env: str = ""
    request_extra: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0, le=5)
    retry_backoff_seconds: float = Field(ge=0)
    max_retry_after_seconds: float = Field(ge=0)
    max_total_seconds: float = Field(gt=0)
    max_output_tokens: int = Field(ge=100)
    max_chars_sent: int = Field(ge=100)
    max_calls_per_minute: int = Field(ge=1)
    cache: CacheConfig
    grounding: GroundingConfig

    @model_validator(mode="after")
    def _activate(self) -> LLMConfig:
        if self.provider not in self.providers:
            raise ValueError(f"provider {self.provider!r} is not one of {sorted(self.providers)}")
        p = self.providers[self.provider]
        self.model, self.api_url, self.api_version, self.key_env = p.model, p.api_url, p.api_version, p.key_env
        self.request_extra = dict(p.request_extra)
        return self

    def for_provider(self, provider: str, model: str | None = None) -> LLMConfig:
        """The same configuration with another provider (and optionally another model) active."""
        if provider not in self.providers:
            raise ConfigError(f"unknown LLM provider {provider!r}: choose one of {sorted(self.providers)}")
        data = self.model_dump()
        data["provider"] = provider
        if model:
            data["providers"][provider]["model"] = model
        return LLMConfig.model_validate(data)

    def cache_path(self, override: Path | None = None) -> Path:
        p = override or Path(self.cache.path)
        return p if p.is_absolute() else REPO_ROOT / p


def load_llm_config(config_dir: Path) -> LLMConfig:
    path = config_dir / "llm.yaml"
    try:
        return LLMConfig.model_validate(_load(path))
    except ValueError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
