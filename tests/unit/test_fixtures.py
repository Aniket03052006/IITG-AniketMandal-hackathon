"""Fixture integrity: the committed demo data must parse, link up, and stay honest."""

from __future__ import annotations

import json

import pytest

from eventshock.config import REPO_ROOT, resolve_fixtures_dir
from eventshock.domain import DataOrigin, EventCategory, SignalStatus, SourceType
from eventshock.domain.enums import AssetClass
from eventshock.ingestion.replay import ReplayFixtureAdapter
from eventshock.store import load_portfolio_repository, load_signal_repository


@pytest.fixture(scope="module")
def fx(settings):
    from eventshock.config import load_app_config
    return resolve_fixtures_dir(settings, load_app_config(settings))


def test_signals_parse_and_are_all_marked_demo(fx):
    repo = load_signal_repository(fx)
    signals = repo.list()
    assert len(signals) >= 12
    assert all(s.data_origin is DataOrigin.DEMO_FIXTURE for s in signals)
    assert all("fixture" in s.model_versions.sentiment for s in signals)


def test_at_least_two_source_types(fx):
    types = {s.document.source_type for s in load_signal_repository(fx).list()}
    assert types == {SourceType.NEWS, SourceType.SOCIAL}


def test_every_event_category_is_represented(fx):
    cats = {s.event.category for s in load_signal_repository(fx).list()}
    assert cats == set(EventCategory)


def test_impact_range_covers_low_to_high_and_has_trigger_cases(fx):
    scores = [s.impact.score for s in load_signal_repository(fx).list() if s.impact]
    assert min(scores) <= 3 and max(scores) >= 8
    assert sum(1 for x in scores if x >= 7) >= 4


def test_contains_failure_cases(fx):
    signals = load_signal_repository(fx).list()
    assert any(s.status is SignalStatus.PARTIAL and s.impact is None for s in signals)
    assert any(s.entity.is_unknown for s in signals)
    assert any(s.evidence.contradicted_by for s in signals)
    assert any(s.evidence.source_count >= 4 for s in signals)


def test_no_timestamps_after_replay_clock(fx):
    repo = load_signal_repository(fx)
    for s in repo.list():
        assert s.document.published_at <= repo.as_of
        assert s.created_at <= repo.as_of
        for c in s.evidence.corroborating:
            assert c.published_at <= repo.as_of


def test_contradiction_links_are_reciprocal_and_resolve(fx):
    repo = load_signal_repository(fx)
    for s in repo.list():
        for other_id in s.evidence.contradicted_by:
            other = repo.get(other_id)
            assert other is not None and s.id in other.evidence.contradicted_by


def test_resolved_entities_exist_in_entity_master(fx):
    pf = load_portfolio_repository(fx)
    known = {e.entity_id for e in pf.entities()}
    for s in load_signal_repository(fx).list():
        assert s.entity.is_unknown or s.entity.entity_id in known


def test_portfolio_has_all_asset_classes_and_scale(fx):
    pf = load_portfolio_repository(fx).get()
    assert {a.asset_type for a in pf.assets} == {AssetClass.EQUITY, AssetClass.BOND, AssetClass.LOAN, AssetClass.DERIVATIVE}  # CASH/OTHER exist only in user portfolios
    assert 40 <= len(pf.assets) <= 100
    assert len({a.entity_id for a in pf.assets}) >= 10
    assert "SYNTHETIC" in pf.description.upper()


def test_signal_entities_have_portfolio_exposure(fx):
    pf = load_portfolio_repository(fx).get()
    held = {a.entity_id for a in pf.assets}
    for s in load_signal_repository(fx).list():
        if not s.entity.is_unknown:
            assert s.entity.entity_id in held, s.id


def test_replay_adapter_emits_two_source_types_as_raw_documents(fx):
    docs = list(ReplayFixtureAdapter(fx).fetch())
    assert {d.source_type for d in docs} == {SourceType.NEWS, SourceType.SOCIAL}
    assert len({d.id for d in docs}) == len(docs)


def test_fixtures_are_regenerated_byte_identically(tmp_path, monkeypatch):
    """The generator is deterministic: running it must not change committed files."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen", REPO_ROOT / "scripts" / "generate_fixtures.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    monkeypatch.setattr(gen, "OUT", tmp_path)
    gen.main()
    for name in ("entities.json", "portfolio.json", "portfolio_v2.json", "signals.json"):
        assert json.loads((tmp_path / name).read_text()) == json.loads(
            (REPO_ROOT / "data" / "fixtures" / name).read_text()
        ), name
