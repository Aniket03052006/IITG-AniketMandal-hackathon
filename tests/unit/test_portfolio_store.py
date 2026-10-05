"""Saved portfolios: CRUD, persistence across instances, caps, damaged files, the read-only default."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from eventshock.portfolio.models import DEFAULT_ID, PortfolioInput
from eventshock.portfolio.service import PortfolioInvalid, PortfolioService
from eventshock.portfolio.store import PortfolioLimit, PortfolioNotFound, PortfolioStore
from eventshock.store import InMemoryPortfolioRepository
from tests.helpers import make_asset, make_portfolio
from tests.portfolio_helpers import ENTITIES, make_resolver, weights


def store(tmp_path, n=5):
    ticks = iter(datetime(2026, 10, 1, tzinfo=UTC) + timedelta(minutes=i) for i in range(1000))
    ids = iter(f"pf_test{i:04d}" for i in range(1000))
    return PortfolioStore(tmp_path / "pfs", max_portfolios=n, clock=lambda: next(ticks), id_factory=lambda: next(ids))


def service(tmp_path, n=5):
    default = InMemoryPortfolioRepository(make_portfolio([make_asset(entity_id="ENT_AAPL")]), ENTITIES)
    return PortfolioService(default, store(tmp_path, n), make_resolver(), clock=lambda: datetime(2026, 10, 1, tzinfo=UTC))


def test_crud_and_persistence_across_instances(tmp_path) -> None:
    s = store(tmp_path)
    a = s.create(weights({"AAPL": 100}, name="A"))
    assert (tmp_path / "pfs" / f"{a.id}.json").is_file()
    again = PortfolioStore(tmp_path / "pfs", max_portfolios=5)  # a restart
    assert again.get(a.id).name == "A" and [p.id for p in again.list()] == [a.id]
    upd = again.update(a.id, weights({"AAPL": 50, "JPM": 50}, name="A2"))
    assert upd.name == "A2" and upd.created_at == a.created_at and upd.updated_at >= a.updated_at
    again.delete(a.id)
    assert again.list() == []
    with pytest.raises(PortfolioNotFound):
        again.get(a.id)
    with pytest.raises(PortfolioNotFound):
        again.delete(a.id)


def test_ids_cannot_escape_the_directory(tmp_path) -> None:
    s = store(tmp_path)
    for bad in ("../x", "..", "pf_/../../etc", "default", ""):
        with pytest.raises(PortfolioNotFound):
            s.get(bad)


def test_cap_on_saved_portfolios(tmp_path) -> None:
    s = store(tmp_path, n=2)
    s.create(weights({"AAPL": 100}))
    s.create(weights({"AAPL": 100}))
    with pytest.raises(PortfolioLimit):
        s.create(weights({"AAPL": 100}))


def test_a_damaged_file_is_skipped_not_fatal(tmp_path) -> None:
    s = store(tmp_path)
    ok = s.create(weights({"AAPL": 100}, name="fine"))
    (tmp_path / "pfs" / "pf_broken01.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "pfs" / "pf_wrongshape.json").write_text(json.dumps({"id": "pf_wrongshape"}), encoding="utf-8")
    assert [p.id for p in s.list()] == [ok.id]


def test_the_service_lists_the_default_first_and_it_is_read_only(tmp_path) -> None:
    svc = service(tmp_path)
    created = svc.create(weights({"AAPL": 100}, name="Mine"))
    items = svc.list()
    assert [i.kind for i in items] == ["DEFAULT", "USER"] and items[0].id == DEFAULT_ID and items[1].id == created.id
    for fn in (lambda: svc.delete(DEFAULT_ID), lambda: svc.update(DEFAULT_ID, weights({"AAPL": 100})), lambda: svc.duplicate(DEFAULT_ID)):
        with pytest.raises(PortfolioNotFound):
            fn()
    assert svc.get_portfolio(None) is svc.get_portfolio(DEFAULT_ID)  # no id = the default, untouched


def test_an_invalid_portfolio_is_never_saved(tmp_path) -> None:
    svc = service(tmp_path)
    with pytest.raises(PortfolioInvalid) as e:
        svc.create(weights({"AAPL": 60}))
    assert any(i.code == "WEIGHTS_SUM" for i in e.value.issues)
    assert len(svc.list()) == 1


def test_duplicate_copies_the_holdings_under_a_new_name(tmp_path) -> None:
    svc = service(tmp_path)
    a = svc.create(weights({"AAPL": 40, "JPM": 60}, name="Core"))
    b = svc.duplicate(a.id)
    assert b.id != a.id and b.stored is not None and b.stored.name == "Core (copy)" and len(b.stored.holdings) == 2
    assert svc.get_portfolio(a.id).content_hash() != svc.get_portfolio(b.id).content_hash()  # id and name are part of the run identity


def test_editing_changes_the_portfolio_hash_so_old_runs_are_not_reused(tmp_path) -> None:
    svc = service(tmp_path)
    a = svc.create(weights({"AAPL": 100}, name="X"))
    h1 = svc.get_portfolio(a.id).content_hash()
    svc.update(a.id, weights({"AAPL": 50, "JPM": 50}, name="X"))
    assert svc.get_portfolio(a.id).content_hash() != h1


def test_input_models_reject_unknown_keys() -> None:
    with pytest.raises(ValueError):
        PortfolioInput.model_validate({"name": "x", "holdings": [], "bogus": 1})
