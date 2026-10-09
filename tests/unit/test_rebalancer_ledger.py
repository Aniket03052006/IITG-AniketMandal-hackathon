"""The simulated ledger: append-only, hash-chained, partial approvals that still balance, stale proposals detected, nothing sent anywhere."""

from __future__ import annotations

import json

import pytest

from eventshock.rebalancer.ledger import GENESIS, LedgerError, LedgerStore, approved_allocation, view
from eventshock.rebalancer.models import LedgerAction
from eventshock.rebalancer.weights import turnover
from tests.rebalancer_helpers import risk_inputs, service, sig

TECH = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META"]


def busy_service():
    sigs = [sig(f"{t}{i}", t, x, hours=1 + i, source=f"s{i}") for t, x in (("AAPL", 0.9), ("NVDA", 0.9), ("JPM", -0.9), ("XOM", -0.9), ("PFE", 0.8), ("WMT", -0.7)) for i in range(8)]
    return service(sigs, real_sectors=True, risk=risk_inputs(), as_of_hours=120)


def proposal(svc, strategy=None):
    p = svc.resolve_params(tilt=6.0, max_turnover=0.04)
    cycles = svc.timeline(p, strategy=strategy).cycles
    i = max(range(len(cycles)), key=lambda k: (cycles[k].turnover, -k))
    return svc.decisions(i, p, strategy=strategy)


def record(store, d, **kw):
    approved, acc, rej = approved_allocation(d, kw.pop("accepted", None))
    return store.record(d, action=kw.pop("action", LedgerAction.APPROVE), approved=approved, accepted=acc, rejected=rej, note=kw.pop("note", ""), analyst=kw.pop("analyst", "ana"),
                        include_live=False)


def test_a_full_approval_is_the_proposal_and_conserves_the_index():
    svc = busy_service()
    d = proposal(svc)
    w, acc, rej = approved_allocation(d, None)
    assert w == pytest.approx([x.after for x in sorted(d.decisions, key=lambda x: d.tickers.index(x.ticker))], abs=1e-12)
    assert sum(w) == pytest.approx(1.0, abs=1e-12) and rej == [] and set(acc) == {x.ticker for x in d.decisions if x.side.value != "HOLD"}


def test_a_partial_approval_balances_buys_against_sells_and_stays_between_old_and_new():
    svc = busy_service()
    d = proposal(svc)
    buys = [x.ticker for x in d.decisions if x.side.value == "BUY"]
    sells = [x.ticker for x in d.decisions if x.side.value == "SELL"]
    accepted = buys[:1] + sells
    w, acc, rej = approved_allocation(d, accepted)
    assert sum(w) == pytest.approx(1.0, abs=1e-12)
    by = {x.ticker: x for x in d.decisions}
    for t, wi in zip(d.tickers, w, strict=True):
        lo, hi = sorted((by[t].before, by[t].after))
        assert lo - 1e-12 <= wi <= hi + 1e-12
    assert set(rej) == set(buys[1:]) and set(acc) == set(accepted)
    svc.check_allocation(None, w)


def test_accepting_only_buys_or_only_sells_cannot_be_funded():
    d = proposal(busy_service())
    buys = [x.ticker for x in d.decisions if x.side.value == "BUY"]
    with pytest.raises(LedgerError, match="cannot be funded"):
        approved_allocation(d, buys)
    with pytest.raises(LedgerError, match="not in the index"):
        approved_allocation(d, ["ZZZZ"])


def test_the_ledger_is_append_only_and_hash_chained(tmp_path):
    path = tmp_path / "ledger.jsonl"
    store, svc = LedgerStore(path), busy_service()
    d = proposal(svc)
    a = record(store, d, note="first")
    b = record(store, d, action=LedgerAction.REJECT, accepted=[], note="changed my mind")
    assert (a.seq, b.seq) == (1, 2) and a.prev_hash == GENESIS and b.prev_hash == a.entry_hash
    assert a.tracking_difference == pytest.approx(0.0, abs=1e-12) and a.turnover == pytest.approx(d.turnover, abs=1e-9)
    assert b.approved == b.before and b.turnover == pytest.approx(0.0, abs=1e-12) and b.est_cost == pytest.approx(0.0, abs=1e-12)
    again = LedgerStore(path)   # a restart reads the same history
    assert [e.id for e in again.all()] == [a.id, b.id] and again.chain_ok
    assert again.latest_for(d.strategy, d.index, (d.params.tilt, d.params.half_life_hours, d.params.max_turnover), False).id == b.id   # the last decision wins


def test_editing_a_line_breaks_the_chain_and_the_ledger_refuses_new_entries(tmp_path):
    path = tmp_path / "ledger.jsonl"
    store, svc = LedgerStore(path), busy_service()
    d = proposal(svc)
    record(store, d)
    record(store, d, note="second")
    lines = path.read_text(encoding="utf-8").splitlines()
    doctored = json.loads(lines[0])
    doctored["note"] = "rewritten history"
    path.write_text("\n".join([json.dumps(doctored), lines[1]]) + "\n", encoding="utf-8")
    broken = LedgerStore(path)
    assert not broken.chain_ok and broken.broken_at == 1
    with pytest.raises(LedgerError, match="hash chain is broken"):
        record(broken, d)
    removed = tmp_path / "removed.jsonl"
    removed.write_text(lines[1] + "\n", encoding="utf-8")
    assert not LedgerStore(removed).chain_ok   # a deleted first line is caught too


def test_a_decision_goes_stale_when_the_proposal_changes():
    svc = busy_service()
    store = LedgerStore(None)
    d = proposal(svc)
    e = record(store, d)
    v = view(store, svc)
    assert v.chain_ok and v.entries[0].stale is False and v.paper_book is not None and v.approvals == 1 and v.rejections == 0
    forged = e.model_copy(update={"proposal_sha256": "0" * 64})
    store._items[0] = forged   # noqa: SLF001  (a proposal whose evidence moved since the decision)
    assert view(store, svc).entries[0].stale is True


def test_the_cost_of_an_approval_follows_what_was_actually_traded():
    svc = busy_service()
    store = LedgerStore(None)
    d = proposal(svc)
    full = record(store, d)
    buys = [x.ticker for x in d.decisions if x.side.value == "BUY"]
    sells = [x.ticker for x in d.decisions if x.side.value == "SELL"]
    part = record(store, d, accepted=buys[:1] + sells)
    assert full.est_cost == pytest.approx(d.est_cost, abs=1e-12)
    assert 0 < part.est_cost < full.est_cost
    assert part.turnover == pytest.approx(turnover(part.before, part.approved), abs=1e-12)
