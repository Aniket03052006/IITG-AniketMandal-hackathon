from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eventshock.api.deps import Container, build_container
from eventshock.api.main import create_app
from eventshock.config import Settings

# Pasting text journals its input; no test may read or write the developer's real data/live/journal.jsonl.
os.environ.setdefault("EVENTSHOCK_JOURNAL_PATH", str(Path(tempfile.mkdtemp(prefix="eventshock-test-live-")) / "journal.jsonl"))
# The language model is never called from a test, and no test may read or write the developer's real extraction cache (EVENTSHOCK_LLM wins over .env).
os.environ["EVENTSHOCK_LLM"] = "0"
os.environ.setdefault("EVENTSHOCK_LLM_CACHE_PATH", str(Path(tempfile.mkdtemp(prefix="eventshock-test-llm-")) / "llm_cache.jsonl"))


# Saved personal portfolios live in a temp directory: no test may read or write the developer's real data/live/portfolios.
os.environ.setdefault("EVENTSHOCK_PORTFOLIO_STORE_PATH", str(Path(tempfile.mkdtemp(prefix="eventshock-test-portfolios-")) / "portfolios"))
# Manual adjustments of the side-cars live in a temp file: no test may read or write the developer's real data/live/overrides (tests that adjust use their own).
os.environ.setdefault("EVENTSHOCK_OVERRIDES_PATH", str(Path(tempfile.mkdtemp(prefix="eventshock-test-overrides-")) / "overrides.json"))


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Stage-1 tests assert fixture facts (golden run, fictional issuers), so they pin the demo profile."""
    return Settings(profile="demo")


@pytest.fixture(scope="session")
def replay_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    # its own journal: text pasted in one test app must never be warm-started into another
    return Settings(profile="replay", journal_path=tmp_path_factory.mktemp("live") / "journal.jsonl")


@pytest.fixture(scope="session")
def replay_container(replay_settings: Settings) -> Container:
    return build_container(replay_settings)


@pytest.fixture(scope="session")
def replay_client(replay_settings: Settings) -> TestClient:
    return TestClient(create_app(replay_settings))


@pytest.fixture()
def container(settings: Settings) -> Container:
    return build_container(settings)


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
