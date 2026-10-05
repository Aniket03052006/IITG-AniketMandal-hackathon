"""Stage 8: the analogue service's degradation paths and its read-only contract (no app, no encoder: signals are stand-ins)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np

from eventshock.domain.scope import ScopeLevel
from eventshock.pipeline.embeddings import EmbeddingUnavailable
from eventshock.retrieval.search import SearchParams
from eventshock.services.analogues import AnalogueService, retrieval_scope, route
from tests.unit.test_analogue_search import LATE, cluster_index

PARAMS = SearchParams(k=5, similarity_floor=0.8)


def fake_signal(sid="sig_1", headline="Acme recalls vehicles", level=ScopeLevel.COMPANY, published=datetime(2030, 1, 1, 12, tzinfo=UTC)):
    return SimpleNamespace(id=sid, scope=SimpleNamespace(level=level), document=SimpleNamespace(id=f"doc_{sid}", headline=headline, body="", published_at=published))


class Fixed:
    def __init__(self, vec):
        self.vec, self.calls, self.dim = vec, 0, len(vec)

    def embed(self, texts):
        self.calls += 1
        return np.stack([self.vec for _ in texts])


class Missing:
    dim = 32

    def embed(self, texts):
        raise EmbeddingUnavailable("not pinned and no encoder installed")


def test_scope_mapping_company_and_sector_use_company_reports_market_uses_market_reports():
    assert [retrieval_scope(x) for x in (ScopeLevel.COMPANY, ScopeLevel.SECTOR, ScopeLevel.MARKET)] == ["ISSUER", "ISSUER", "MARKET"]


def test_sector_reports_are_filtered_to_the_sector_and_unresolved_ones_are_refused():
    sec = fake_signal(level=ScopeLevel.SECTOR)
    sec.scope.sector = "Tech"
    assert route(sec) == ("ISSUER", "Tech", None)
    scope, sector, why = route(fake_signal(level=ScopeLevel.UNRESOLVED))
    assert sector is None and why and "could not be tied" in why


def test_no_index_is_unavailable_with_the_reason_never_an_empty_answer():
    svc = AnalogueService(None, PARAMS, None, unavailable_reason="no analogue index is installed")
    r = svc.for_signal(fake_signal())
    assert not svc.available and r.status == "UNAVAILABLE" and "no analogue index" in r.reason and r.items == []


def test_missing_encoder_for_new_text_is_unavailable_and_says_how_to_fix_it():
    idx, _ = cluster_index(12)
    r = AnalogueService(idx, PARAMS, Missing()).for_signal(fake_signal())
    assert r.status == "UNAVAILABLE" and "requirements-embed" in r.reason and r.scope == "ISSUER"
    assert AnalogueService(idx, PARAMS, None).for_signal(fake_signal()).status == "UNAVAILABLE"


def test_answers_from_the_index_and_memoises_per_signal():
    idx, topic = cluster_index(20)
    emb = Fixed(topic)
    svc = AnalogueService(idx, PARAMS, emb)
    a = svc.for_signal(fake_signal())
    b = svc.for_signal(fake_signal())
    assert a.status == "OK" and a.model_dump() == b.model_dump() and emb.calls == 1
    assert a.query_date == "2030-01-01" and a.scope == "ISSUER"


def test_a_report_dated_before_the_index_history_gets_nothing_from_the_future():
    idx, topic = cluster_index(20)
    r = AnalogueService(idx, PARAMS, Fixed(topic)).for_signal(fake_signal(published=datetime(2000, 1, 1, tzinfo=UTC)))
    assert r.status == "NO_RELIABLE_ANALOGUE" and r.eligible == 0 and r.items == []


def test_the_regime_note_uses_the_supplied_market_state_and_never_invents_one():
    idx, topic = cluster_index(20)
    with_vix = AnalogueService(idx, PARAMS, Fixed(topic), vix_now=lambda s: (31.5, "2029-12-31")).for_signal(fake_signal())
    assert any("VIX was 31.5" in c and "2029-12-31" in c for c in with_vix.caveats)
    without = AnalogueService(idx, PARAMS, Fixed(topic), vix_now=lambda s: (None, None)).for_signal(fake_signal())
    assert any("not available" in c for c in without.caveats)


def test_market_wide_reports_search_the_market_scope_only():
    idx, topic = cluster_index(20)   # the fixture holds issuer rows only
    r = AnalogueService(idx, PARAMS, Fixed(topic)).for_signal(fake_signal(level=ScopeLevel.MARKET))
    assert r.scope == "MARKET" and r.status == "NO_RELIABLE_ANALOGUE" and r.eligible == 0
    _ = LATE


def test_an_unresolved_report_is_refused_with_the_reason_and_the_encoder_is_never_called():
    idx, topic = cluster_index(20)
    emb = Fixed(topic)
    r = AnalogueService(idx, PARAMS, emb).for_signal(fake_signal(level=ScopeLevel.UNRESOLVED))
    assert r.status == "NO_RELIABLE_ANALOGUE" and "could not be tied" in r.reason and r.items == [] and r.aggregate is None and emb.calls == 0


def test_a_sector_report_only_sees_that_sectors_company_reports():
    idx, topic = cluster_index(20)
    for i, row in enumerate(idx.rows):
        row["sector"] = "Tech" if i % 2 else "Energy"
    sig = fake_signal(level=ScopeLevel.SECTOR)
    sig.scope.sector = "Tech"
    r = AnalogueService(idx, SearchParams(k=5, similarity_floor=0.8, min_distinct_episodes=3), Fixed(topic)).for_signal(sig)
    assert r.status == "OK" and r.items and all(i.sector == "Tech" for i in r.items)
