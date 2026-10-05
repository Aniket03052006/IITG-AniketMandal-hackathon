"""Stage 8: point-in-time analogue search and the index pack. Synthetic vectors only (no encoder, no prices)."""

from __future__ import annotations

import numpy as np
import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.modeling.evidence_v3 import load_evidence_v3
from eventshock.retrieval.index import AnalogueIndex
from eventshock.retrieval.model import AnalogueSet
from eventshock.retrieval.search import SearchParams, search

DIM = 32
BASELINES = {"ISSUER": {"p_abs_z_ge_2": 0.05}, "MARKET": {"p_abs_z_ge_2": 0.05}}
PRE, _ = load_evidence_v3(REPO_ROOT / "configs")


def unit(rng: np.random.Generator, base: np.ndarray | None = None, noise: float = 0.0) -> np.ndarray:
    v = (base if base is not None else 0) + (rng.standard_normal(DIM) * (noise if base is not None else 1.0))
    return (v / np.linalg.norm(v)).astype(np.float32)


def make_row(i: int, *, ticker: str | None, s0: int, date: str, avail: str, scope: str = "ISSUER", car: float = 0.01, z: float = 0.5, episode: str | None = None,
             event: str = "MA_CORPORATE_ACTION", sector: str = "Tech") -> dict:
    return {"id": f"d{i:04d}", "episode": episode or f"{ticker}|{date}", "scope": scope, "ticker": ticker, "sector": sector, "s0": s0, "s0_date": date, "available_from": avail,
            "published_at": f"{date}T21:00:00+00:00", "timing": "OFF_HOURS", "clock": "TRUSTED", "text": f"headline {i}", "event_top": event, "vix_level": 18.0,
            "car": car, "z": z, "abs_z": abs(z), "outcome_version": "outcome-v3"}


def make_index(rows: list[dict], vecs: np.ndarray) -> AnalogueIndex:
    return AnalogueIndex(vecs, rows, {"format": "analogue-index-v1", "version": "test", "baselines": BASELINES})


def date(day: int) -> str:
    return f"2024-{1 + (day - 1) // 28:02d}-{1 + (day - 1) % 28:02d}"


def cluster_index(n: int, *, noise: float = 0.05, seed: int = 0, tickers=("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"), stride: int = 20):
    """n past reports about one topic (a tight cluster), spaced out so none is a duplicate story, on rotating tickers."""
    rng = np.random.default_rng(seed)
    topic = unit(rng)
    rows, vecs = [], []
    for i in range(n):
        d = 1 + i * stride
        rows.append(make_row(i, ticker=tickers[i % len(tickers)], s0=d, date=date(d), avail=date(d + 7), car=0.002 * (i % 5 - 2), z=0.4 * (i % 5 - 2)))
        vecs.append(unit(rng, topic, noise))
    return make_index(rows, np.stack(vecs)), topic


PARAMS = SearchParams(k=5, similarity_floor=0.8)
LATE = "2030-01-01"


class TestEligibility:
    def test_boundary_is_inclusive_and_nothing_later_is_used(self):
        idx, topic = cluster_index(12)
        avail = sorted(r["available_from"] for r in idx.rows)
        cut = avail[7]
        res = search(idx, topic, query_date=cut, scope="ISSUER", params=PARAMS)
        assert res.eligible == sum(1 for a in avail if a <= cut)
        before = search(idx, topic, query_date=date(1), scope="ISSUER", params=PARAMS)
        assert before.status == "NO_RELIABLE_ANALOGUE" and before.eligible == 0

    def test_future_invariance(self):
        """Adding episodes that are not yet available at the query date changes nothing about the answer."""
        idx, topic = cluster_index(14)
        query_date = sorted(r["available_from"] for r in idx.rows)[9]
        base = search(idx, topic, query_date=query_date, scope="ISSUER", params=PARAMS)
        rng = np.random.default_rng(99)
        extra_rows = [make_row(900 + i, ticker="ZZZ", s0=2000 + i, date="2030-05-01", avail="2030-06-01", car=0.5, z=9.0) for i in range(5)]
        extra_vecs = [topic for _ in range(5)]  # identical to the query: they would win if they were allowed in
        bigger = make_index([*idx.rows, *extra_rows], np.vstack([idx.vectors, np.stack(extra_vecs)]))
        again = search(bigger, topic, query_date=query_date, scope="ISSUER", params=PARAMS)
        assert base.model_dump() == again.model_dump()
        assert not any(i.id.startswith("d09") for i in again.items)
        _ = rng

    def test_own_episode_cannot_be_its_own_analogue(self):
        idx, topic = cluster_index(12)
        row = idx.rows[3]
        res = search(idx, idx.vectors[3], query_date=row["published_at"][:10], scope="ISSUER", params=PARAMS)
        assert row["id"] not in {i.id for i in res.items} | {i.id for i in res.below_bar}  # its own outcome window is still open on its own date
        res2 = search(idx, idx.vectors[3], query_date=LATE, scope="ISSUER", params=PARAMS, exclude_ids=frozenset({row["id"]}))
        assert row["id"] not in {i.id for i in res2.items}


class TestScopes:
    def test_issuer_and_market_reports_never_mix(self):
        idx, topic = cluster_index(10)
        mk_rows = [make_row(500 + i, ticker=None, s0=1 + i * 20, date=date(1 + i * 20), avail=date(8 + i * 20), scope="MARKET", sector=None, episode=f"MKT|{i}") for i in range(8)]
        rng = np.random.default_rng(1)
        idx2 = make_index([*idx.rows, *mk_rows], np.vstack([idx.vectors, np.stack([unit(rng, topic, 0.05) for _ in mk_rows])]))
        assert {i.scope for i in search(idx2, topic, query_date=LATE, scope="MARKET", params=PARAMS).items} == {"MARKET"}
        assert {i.scope for i in search(idx2, topic, query_date=LATE, scope="ISSUER", params=PARAMS).items} == {"ISSUER"}


class TestCollapseAndDiversity:
    def test_near_duplicate_stories_count_once(self):
        rng = np.random.default_rng(2)
        topic = unit(rng)
        rows, vecs = [], []
        for i in range(10):   # ten reports of ONE story: same ticker, consecutive sessions, nearly identical text
            rows.append(make_row(i, ticker="AAA", s0=10 + i, date=date(10 + i), avail=date(17 + i)))
            vecs.append(unit(rng, topic, 0.005))
        res = search(make_index(rows, np.stack(vecs)), topic, query_date=LATE, scope="ISSUER", params=PARAMS)
        assert res.status == "NO_RELIABLE_ANALOGUE" and res.above_floor == 10
        assert "1 distinct stor" in res.reason and res.items == [] and len(res.below_bar) == 3

    def test_one_analogue_per_episode(self):
        rng = np.random.default_rng(3)
        topic = unit(rng)
        rows, vecs = [], []
        for i in range(30):   # six episodes, five reports each (a market session holds many reports)
            e = i // 5
            rows.append(make_row(i, ticker=None, s0=1 + e * 20, date=date(1 + e * 20), avail=date(8 + e * 20), scope="MARKET", sector=None, episode=f"MKT|{e}"))
            vecs.append(unit(rng, topic, 0.05))
        res = search(make_index(rows, np.stack(vecs)), topic, query_date=LATE, scope="MARKET", params=PARAMS)
        assert res.status == "OK" and res.aggregate and res.aggregate.n_episodes == 6
        assert len({i.reaction_session for i in res.items}) == len(res.items)

    def test_per_ticker_cap(self):
        idx, topic = cluster_index(16, tickers=("AAA", "BBB"))
        res = search(idx, topic, query_date=LATE, scope="ISSUER", params=SearchParams(k=8, similarity_floor=0.8))
        counts = {t: sum(1 for i in res.items if i.ticker == t) for t in ("AAA", "BBB")}
        assert max(counts.values()) <= 3 and sum(counts.values()) <= 6


class TestMarketDiversity:
    def test_market_wide_reports_are_not_capped_per_ticker_but_are_spread_over_months(self):
        rng = np.random.default_rng(6)
        topic = unit(rng)
        rows, vecs = [], []
        for i in range(24):   # 24 distinct market sessions, two per calendar month
            d = 1 + i * 14
            rows.append(make_row(i, ticker=None, s0=d, date=date(d), avail=date(d + 7), scope="MARKET", sector=None, episode=f"MKT|{i}"))
            vecs.append(unit(rng, topic, 0.05))
        res = search(make_index(rows, np.stack(vecs)), topic, query_date=LATE, scope="MARKET", params=SearchParams(k=5, similarity_floor=0.8))
        assert res.status == "OK" and len(res.items) == 5          # the company cap (3) must not apply to "no ticker"
        months = [i.reaction_session[:7] for i in res.items]
        assert all(months.count(m) <= 2 for m in set(months))


class TestReliability:
    def test_enough_analogues_ok_with_aggregate_and_provenance(self):
        idx, topic = cluster_index(20)
        res = search(idx, topic, query_date=LATE, scope="ISSUER", params=PARAMS)
        assert res.status == "OK" and 0 < len(res.items) <= 5
        assert all(i.origin == "RETRIEVED" for i in res.items)
        sims = [i.similarity for i in res.items]
        assert sims == sorted(sims, reverse=True) and min(sims) >= PARAMS.similarity_floor
        assert res.aggregate and res.aggregate.n_stories >= 3 and 3 <= res.aggregate.n_used <= min(res.aggregate.n_stories, PARAMS.aggregate_over)
        assert "hindsight" in res.outcome_note and any("forecast" in c for c in res.caveats)

    def test_no_reliable_analogue_is_explicit_and_pads_nothing(self):
        rng = np.random.default_rng(4)
        rows = [make_row(i, ticker=f"T{i}", s0=1 + 20 * i, date=date(1 + 20 * i), avail=date(8 + 20 * i)) for i in range(12)]
        res = search(make_index(rows, np.stack([unit(rng) for _ in rows])), unit(rng), query_date=LATE, scope="ISSUER", params=SearchParams(similarity_floor=0.95))
        assert res.status == "NO_RELIABLE_ANALOGUE" and res.items == [] and res.aggregate is None
        assert "distinct past episode" in res.reason and 0 < len(res.below_bar) <= 3
        assert all(b.similarity < 0.95 for b in res.below_bar)

    def test_empty_eligible_set(self):
        idx, topic = cluster_index(6)
        res = search(idx, topic, query_date="2000-01-01", scope="ISSUER", params=PARAMS)
        assert res.status == "NO_RELIABLE_ANALOGUE" and "old enough" in res.reason

    def test_a_quiet_looking_set_is_not_dressed_up_as_informative(self):
        idx, topic = cluster_index(20)   # outcomes are small by construction (|z| <= 0.8)
        res = search(idx, topic, query_date=LATE, scope="ISSUER", params=PARAMS)
        assert res.aggregate is not None and not res.aggregate.distinguishable_from_quiet_day and "not distinguishable" in res.aggregate.reading

    def test_a_set_of_big_moves_is_flagged_as_distinguishable(self):
        idx, topic = cluster_index(40)
        for r in idx.rows:
            r["z"], r["abs_z"], r["car"] = 4.0, 4.0, 0.06
        res = search(idx, topic, query_date=LATE, scope="ISSUER", params=SearchParams(k=5, similarity_floor=0.8, aggregate_over=20))
        assert res.aggregate and res.aggregate.distinguishable_from_quiet_day and res.aggregate.lift == pytest.approx(20.0, rel=0.1)


class TestDeterminismAndFilters:
    def test_identical_calls_are_identical_and_ties_break_by_id(self):
        rng = np.random.default_rng(5)
        topic = unit(rng)
        rows = [make_row(i, ticker=f"T{i}", s0=1 + 20 * i, date=date(1 + 20 * i), avail=date(8 + 20 * i)) for i in range(10)]
        idx = make_index(rows, np.stack([topic] * 10))  # every similarity is exactly equal
        a = search(idx, topic, query_date=LATE, scope="ISSUER", params=PARAMS)
        b = search(idx, topic, query_date=LATE, scope="ISSUER", params=PARAMS)
        assert a.model_dump() == b.model_dump()
        assert [i.id for i in a.items] == sorted(i.id for i in a.items)

    def test_sector_and_event_filters(self):
        idx, topic = cluster_index(20)
        for i, r in enumerate(idx.rows):
            r["sector"], r["event_top"] = ("Tech" if i % 2 else "Energy"), ("MA_CORPORATE_ACTION" if i % 4 else "REGULATORY_LEGAL")
        res = search(idx, topic, query_date=LATE, scope="ISSUER", params=SearchParams(k=5, similarity_floor=0.8, min_distinct_episodes=3), sector="Tech", event_type="MA_CORPORATE_ACTION")
        assert res.items and all(i.sector == "Tech" and i.model_event_type == "MA_CORPORATE_ACTION" for i in res.items)

    def test_bad_queries_fail_loudly(self):
        idx, _ = cluster_index(6)
        with pytest.raises(ValueError):
            search(idx, np.zeros(DIM), query_date=LATE, scope="ISSUER", params=PARAMS)
        with pytest.raises(ValueError):
            search(idx, np.ones(DIM + 1), query_date=LATE, scope="ISSUER", params=PARAMS)

    def test_params_come_from_the_preregistration(self):
        p = SearchParams.from_config(PRE, 0.85)
        assert (p.k, p.min_distinct_episodes, p.min_distinct_stories, p.dedup_cosine, p.max_per_ticker) == (5, 5, 3, 0.92, 3)
        assert p.similarity_floor == 0.85


class TestIndexPack:
    def _build(self, tmp_path):
        idx, _ = cluster_index(8)
        idx.manifest.update({"encoder": "test", "rows": 8})
        idx.save(tmp_path)
        return idx

    def test_round_trip_preserves_everything_searched(self, tmp_path):
        idx = self._build(tmp_path)
        again = AnalogueIndex.load(tmp_path)
        assert [r["id"] for r in again.rows] == [r["id"] for r in idx.rows]
        assert np.abs(again.vectors - idx.vectors.astype(np.float16).astype(np.float32)).max() == 0
        assert again.manifest["vectors_sha256"] and again.manifest["rows_sha256"]

    def test_a_modified_pack_is_refused(self, tmp_path):
        self._build(tmp_path)
        p = tmp_path / "analogues.jsonl"
        p.write_text(p.read_text().replace("headline 1", "headline X", 1))
        with pytest.raises(ConfigError, match="modified"):
            AnalogueIndex.load(tmp_path)

    def test_missing_index_says_how_to_build_it(self, tmp_path):
        with pytest.raises(ConfigError, match="analogue-index"):
            AnalogueIndex.load(tmp_path)

    def test_misaligned_vectors_are_refused(self):
        rows = [make_row(0, ticker="A", s0=1, date=date(1), avail=date(8))]
        with pytest.raises(ConfigError):
            AnalogueIndex(np.zeros((2, DIM), dtype=np.float32), rows, {"baselines": BASELINES})

    def test_the_result_is_a_strict_validated_model(self):
        with pytest.raises(Exception):  # noqa: B017
            AnalogueSet(status="OK", reason="x", surprise=1)  # type: ignore[call-arg]
