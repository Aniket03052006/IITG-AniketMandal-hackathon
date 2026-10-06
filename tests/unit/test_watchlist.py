"""Watchlists: CRUD and persistence, a closed vocabulary (free text never becomes a company), matching that reads resolved scope only, unresolved events matching nothing,
disabled lists inert, and deterministic replay activity."""

from __future__ import annotations

import pytest

from eventshock.monitor.models import Mode
from eventshock.watchlist.models import WatchItem, WatchKind, WatchlistInput
from eventshock.watchlist.service import WatchlistInvalid
from eventshock.watchlist.store import WatchlistLimit, WatchlistNotFound
from tests.intel_helpers import JPM, XOM, sig
from tests.monitor_helpers import FakeAssess, FakeProp, watch_service

JPM_FINE = "JPMorgan Chase fined $920 million over spoofing by US regulators"
XOM_FIRE = "Exxon Mobil shuts down Gulf refinery after fire, output halted"
BANKS = "Bank regulators warn lenders over rising credit losses in commercial real estate loans"
OIL = "Oil prices jump as OPEC crude supply cut deepens, Brent tops $90 a barrel"
UNREL = "Somebody said something about something that is hard to pin down"


def signals():  # noqa: ANN201
    return [
        sig("jpm", JPM_FINE, entity=JPM, minutes=0, source="Wire A", url="https://a.example/1"),
        sig("xom", XOM_FIRE, entity=XOM, minutes=30, source="Wire B", url="https://b.example/1", category="OPERATIONS" and sig("x", "x").event.category),
        sig("oil", OIL, minutes=60, source="Wire C", url="https://c.example/1"),
        sig("bank", BANKS, minutes=90, source="Wire D", url="https://d.example/1"),
        sig("unres", UNREL, minutes=120, source="Wire E", url="https://e.example/1"),
        sig("xom2", "Exxon Mobil names Jane Holloway chief financial officer after board vote", entity=XOM, minutes=30 * 60, source="Wire F", url="https://f.example/1"),   # first seen in a later cycle
    ]


@pytest.fixture()
def ws(tmp_path):  # noqa: ANN001, ANN201
    svc, mon, repo = watch_service(signals(), tmp_path, assess=FakeAssess(default=6), prop=FakeProp(level={"jpm": "HIGH", "xom": "MEDIUM"}, share={"jpm": 0.3, "xom": 0.1}))
    return svc


def make(ws, *items, name="Mine", enabled=True):  # noqa: ANN001, ANN002, ANN201
    return ws.create(WatchlistInput(name=name, enabled=enabled, items=[WatchItem(kind=k, value=v) for k, v in items]))


def act(ws, w, **kw):  # noqa: ANN001, ANN003, ANN201
    return ws.activity(w, mode=Mode.REPLAY, **kw)


# ----------------------------------------------------------------------------------------------------------------------------------- CRUD
def test_create_get_list_update_delete_and_persistence(ws, tmp_path):  # noqa: ANN001
    w = make(ws, (WatchKind.COMPANY, "JPM"), (WatchKind.SECTOR, "Energy"))
    assert w.id.startswith("wl_") and [i.value for i in w.items] == ["ENT_JPM", "Energy"]      # a ticker is stored as the entity id; labels are filled in
    assert w.items[0].label == "JPMorgan Chase (JPM)"
    assert [x.id for x in ws.list()] == [w.id] and ws.get(w.id) == w
    w2 = ws.update(w.id, WatchlistInput(name="Renamed", enabled=False, items=[WatchItem(kind=WatchKind.RISK_THEME, value="rates")]))
    assert w2.name == "Renamed" and not w2.enabled and w2.created_at == w.created_at and w2.updated_at >= w.updated_at
    from eventshock.watchlist.store import WatchlistStore
    again = WatchlistStore(tmp_path / "w", max_watchlists=20)                                   # a restart: the file is the state
    assert [x.name for x in again.list()] == ["Renamed"]
    ws.delete(w.id)
    assert ws.list() == []
    with pytest.raises(WatchlistNotFound):
        ws.get(w.id)
    with pytest.raises(WatchlistNotFound):
        ws.delete(w.id)


def test_ids_cannot_escape_the_directory(ws):  # noqa: ANN001
    for bad in ("../x", "wl_../../etc", "default", ""):
        with pytest.raises(WatchlistNotFound):
            ws.get(bad)


def test_duplicate_items_are_folded_and_the_limit_is_enforced(ws):  # noqa: ANN001
    w = make(ws, (WatchKind.COMPANY, "JPM"), (WatchKind.COMPANY, "ent_jpm"), (WatchKind.COMPANY, "JPMorgan"[:0] + "JPM"))
    assert len(w.items) == 1
    for i in range(ws.cfg.max_watchlists - 1):
        make(ws, (WatchKind.SECTOR, "Energy"), name=f"l{i}")
    with pytest.raises(WatchlistLimit):
        make(ws, (WatchKind.SECTOR, "Energy"), name="one too many")


def test_a_damaged_file_is_skipped_not_fatal(ws, tmp_path):  # noqa: ANN001
    make(ws, (WatchKind.SECTOR, "Energy"))
    (tmp_path / "w" / "wl_broken0001.json").write_text("{not json", encoding="utf-8")
    assert len(ws.list()) == 1


# ------------------------------------------------------------------------------------------------------------------------- the vocabulary
@pytest.mark.parametrize("kind,value", [
    (WatchKind.COMPANY, "Some Unlisted Startup"), (WatchKind.COMPANY, "UNKNOWN_ENTITY"), (WatchKind.SECTOR, "Space Tourism"), (WatchKind.GEOGRAPHY, "Atlantis"),
    (WatchKind.EVENT_TYPE, "VIBES"), (WatchKind.RISK_THEME, "mood"), (WatchKind.PORTFOLIO_EXPOSURE, "top:0"), (WatchKind.PORTFOLIO_EXPOSURE, "top:99"), (WatchKind.PORTFOLIO_EXPOSURE, "top:x"),
])
def test_free_text_never_becomes_a_subject(ws, kind, value):  # noqa: ANN001
    with pytest.raises(WatchlistInvalid):
        make(ws, (kind, value))


def test_every_kind_accepts_its_vocabulary(ws):  # noqa: ANN001
    w = make(ws, (WatchKind.COMPANY, "ENT_XOM"), (WatchKind.SECTOR, "financials"), (WatchKind.INDUSTRY, "Banks"), (WatchKind.GEOGRAPHY, "US"), (WatchKind.EVENT_TYPE, "CREDIT_FUNDING"),
             (WatchKind.RISK_THEME, "credit_stress"), (WatchKind.PORTFOLIO_EXPOSURE, "top:3"), (WatchKind.PORTFOLIO_EXPOSURE, "GS"))
    assert [i.value for i in w.items] == ["ENT_XOM", "Financials", "Banks", "US", "CREDIT_FUNDING", "credit_stress", "top:3", "ENT_GS"]
    v = ws.vocabulary()
    assert {e.value for e in v.companies} == {"ENT_JPM", "ENT_XOM", "ENT_GS", "ENT_KO"} and v.max_items == ws.cfg.max_items


def test_an_empty_name_is_refused_and_all_issues_are_reported_together(ws):  # noqa: ANN001
    with pytest.raises(WatchlistInvalid) as e:
        ws.create(WatchlistInput(name="  ", items=[WatchItem(kind=WatchKind.COMPANY, value="Nope Inc"), WatchItem(kind=WatchKind.SECTOR, value="Nope")]))
    assert len(e.value.issues) == 3


# ------------------------------------------------------------------------------------------------------------------------------- matching
def test_company_matches_only_the_resolved_company(ws):  # noqa: ANN001
    a = act(ws, make(ws, (WatchKind.COMPANY, "JPM")))
    it = a.items[0]
    assert it.status == "MATCHED" and it.matched_events == 1
    ev = it.events[0]
    assert "JPMorgan" in ev.headline and "resolved as the company" in ev.match_reason
    assert ev.materiality == "HIGH" and ev.exposure_share == 0.3 and ev.severity == 6 and ev.evidence_tier and ev.novelty in ("NEW", "UNKNOWN")
    assert it.rollup.max_severity == 6 and it.rollup.max_materiality == "HIGH"


def test_an_unresolved_event_never_matches_a_company_a_sector_or_anything_scoped(ws):  # noqa: ANN001
    w = make(ws, (WatchKind.COMPANY, "JPM"), (WatchKind.COMPANY, "XOM"), (WatchKind.SECTOR, "Financials"), (WatchKind.SECTOR, "Energy"), (WatchKind.GEOGRAPHY, "US"))
    for it in act(ws, w).items:
        assert all("pin down" not in e.headline for e in it.events)


def test_a_text_that_merely_names_the_company_without_a_resolved_entity_does_not_match(tmp_path):  # noqa: ANN001
    # the headline says "Exxon" but the pipeline resolved no entity: the text is a mention, not a company
    svc, *_ = watch_service([sig("ghost", "Exxon Mobil announces results", minutes=0, source="Wire", url="https://g.example/1")], tmp_path)
    it = act(svc, make(svc, (WatchKind.COMPANY, "XOM"))).items[0]
    assert it.status == "NO_MATCH" and it.events == []


def test_sector_matches_the_scope_path_of_company_and_sector_events(ws):  # noqa: ANN001
    fin = act(ws, make(ws, (WatchKind.SECTOR, "Financials"))).items[0]
    heads = " ".join(e.headline for e in fin.events)
    assert "JPMorgan" in heads                                              # a company event carries its sector from the entity master
    en = act(ws, make(ws, (WatchKind.SECTOR, "Energy"))).items[0]
    assert any("Exxon" in e.headline for e in en.events)


def test_event_type_uses_the_assessed_class_and_never_matches_no_event(tmp_path):  # noqa: ANN001
    svc, mon, _ = watch_service(signals(), tmp_path, assess=FakeAssess(default=6, event_type="CREDIT_FUNDING"))
    n_events = len(svc._intel().index().events)  # noqa: SLF001
    assert act(svc, make(svc, (WatchKind.EVENT_TYPE, "CREDIT_FUNDING"))).items[0].matched_events == n_events      # every event is read as that class
    assert act(svc, make(svc, (WatchKind.EVENT_TYPE, "MARKET_VALUATION"), name="x")).items[0].status == "NO_MATCH"
    svc2, *_ = watch_service(signals(), tmp_path / "b", assess=FakeAssess(default=6, event_type="NO_EVENT"))
    assert act(svc2, make(svc2, (WatchKind.EVENT_TYPE, "CREDIT_FUNDING"))).items[0].status == "NO_MATCH"          # a text that is not a market event is never an event of any type


def test_portfolio_exposure_matches_events_whose_propagation_reaches_the_holding(tmp_path):  # noqa: ANN001
    from types import SimpleNamespace

    class Reach(FakeProp):
        def graph(self, signal, pf=None):  # noqa: ANN001, ANN201
            return SimpleNamespace(reached=[SimpleNamespace(entity_id="ENT_JPM")] if signal.id == "jpm" else [SimpleNamespace(entity_id="ENT_XOM")] if signal.id == "xom" else [])

    svc, *_ = watch_service(signals(), tmp_path, assess=FakeAssess(default=6), prop=Reach(level={"jpm": "HIGH", "xom": "MEDIUM"}, share={"jpm": 0.3, "xom": 0.1}))
    top = act(svc, make(svc, (WatchKind.PORTFOLIO_EXPOSURE, "top:1"))).items[0]
    assert top.status in ("MATCHED", "NO_MATCH")                                  # the test book's largest holding decides; both outcomes are explained
    held = act(svc, make(svc, (WatchKind.PORTFOLIO_EXPOSURE, "XOM"), name="x")).items[0]
    assert held.status == "MATCHED" and "reaches" in held.events[0].match_reason and "Exxon" in held.events[0].headline
    not_held = act(svc, make(svc, (WatchKind.PORTFOLIO_EXPOSURE, "KO"), name="y")).items[0]
    assert not_held.status == "NO_MATCH" and "not held" in not_held.reason


def test_a_disabled_list_is_inert_but_inspectable(ws):  # noqa: ANN001
    w = make(ws, (WatchKind.COMPANY, "JPM"), enabled=False)
    a = act(ws, w)
    assert a.status == "DISABLED" and a.items[0].status == "DISABLED" and a.items[0].events == [] and a.items[0].matched_events == 0
    assert a.watchlist.items[0].value == "ENT_JPM"


def test_activity_is_deterministic_and_order_is_stable(ws):  # noqa: ANN001
    w = make(ws, (WatchKind.SECTOR, "Financials"), (WatchKind.COMPANY, "JPM"))
    a, b = act(ws, w), act(ws, w)
    assert a.model_dump_json() == b.model_dump_json()
    assert [i.item.kind.value for i in a.items] == ["SECTOR", "COMPANY"]            # the order the user gave
    times = [e.last_seen for e in a.items[0].events]
    assert times == sorted(times, reverse=True)


def test_new_events_are_those_first_seen_inside_the_window(ws):  # noqa: ANN001
    w = make(ws, (WatchKind.COMPANY, "XOM"))
    cycles = ws._monitor.cycles()  # noqa: SLF001
    late = signals()[-1].document.published_at
    k = next(c.index for c in cycles if c.at >= late)                                  # the cycle whose window contains the later Exxon event
    assert act(ws, w, cycle=k, window=1).items[0].new_events == 1
    assert act(ws, w, cycle=len(cycles) - 1, window=1).items[0].new_events == 0         # a later cycle: nothing new any more
    assert act(ws, w, cycle=len(cycles) - 1, window=len(cycles) - 1).items[0].new_events >= 1
    assert act(ws, w, cycle=0, window=1).items[0].new_events == 0                       # the baseline cycle has no earlier boundary: nothing is new


def test_activity_before_an_event_exists_does_not_see_it(ws):  # noqa: ANN001
    w = make(ws, (WatchKind.COMPANY, "XOM"))
    first = act(ws, w, cycle=0).items[0]
    assert first.matched_events == 1 and all("Holloway" not in e.headline for e in first.events)     # only the first Exxon event exists at the baseline
    assert act(ws, w).items[0].matched_events == 2


def test_a_bad_cycle_is_reported_not_raised(ws):  # noqa: ANN001
    a = act(ws, make(ws, (WatchKind.COMPANY, "JPM")), cycle=999)
    assert a.status == "UNAVAILABLE" and "cycle" in a.reason
