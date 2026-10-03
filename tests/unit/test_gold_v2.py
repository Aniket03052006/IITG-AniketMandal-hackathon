from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.modeling import gold_v2 as G
from eventshock.modeling.corpora import HistoryDoc
from eventshock.modeling.event_labels import read_csv
from eventshock.pipeline.event_context import EventCalendar

ITEMS = {"groups": {"earnings": ["2.02"], "deal": ["1.01"], "distress": [], "financing": [], "leadership": []}, "exhibit_only_items": ["9.01"]}


def doc(i: int, text: str, ph="MARKET_VALUATION", ticker="AAA", when="2024-03-05T15:00:00+00:00", multi=False) -> HistoryDoc:
    return HistoryDoc(id=f"d{i}", adapter="gdelt-gkg", source_type="NEWS", text=text, published_at=datetime.fromisoformat(when), origin="SOURCE", ticker=ticker,
                      entity_id="E", link_confidence=0.95, multi_entity=multi, er_rule="LEGAL_NAME", novelty=0.0, dataset_tickers=(), cluster_id="c", member_count=1,
                      placeholder_event=ph, placeholder_sentiment=0.0)


def words(k: int) -> str:
    """Eight pseudo-words unique to ``k`` (digits would be folded away by the template collapser)."""
    import random

    rng = random.Random(k)
    syl = ["ba", "ko", "mi", "ra", "tu", "lo", "ne", "sha", "vi", "zu", "pe", "da"]
    return " ".join("".join(rng.choice(syl) for _ in range(3)) for _ in range(8))


def pool():
    docs, k = [], 0
    for ph, n in (("MARKET_VALUATION", 200), ("EARNINGS_FINANCIAL_PERFORMANCE", 60), ("CREDIT_FUNDING", 60), ("GEOPOLITICAL", 60), ("MA_CORPORATE_ACTION", 60)):
        for _ in range(n):
            k += 1
            docs.append(doc(k, words(k), ph))
    return docs


def cal():
    return EventCalendar([{"ticker": "AAA", "acceptance_utc": "2024-03-05T14:00:00Z", "accession": "x", "form": "8-K", "items": ["2.02"]}], [], ITEMS)


KW = dict(exclude_texts=[], exclude_ids=set(), rows=300, seed=5, near_duplicate_threshold=0.8,
          quota={"EARNINGS_FINANCIAL_PERFORMANCE": 30, "CREDIT_FUNDING": 30, "GEOPOLITICAL": 30, "MA_CORPORATE_ACTION": 30})


def test_sample_has_the_planned_strata_is_blind_and_deterministic():
    sheet, man = G.build(pool(), cal(), **KW)
    assert len(sheet) == 300 and set(sheet[0]) == set(G.SHEET_COLUMNS)           # blind: no stratum, no placeholder class
    st = man["strata"]
    assert st["rand"]["sampled"] + st["filing"]["sampled"] + sum(v["sampled"] for k, v in st.items() if k.startswith("kw:")) == 300
    assert all(st[f"kw:{c}"]["sampled"] == 30 for c in KW["quota"]) and st["filing"]["sampled"] == 30
    assert man["items"]["V0001"]["origin_id"].startswith("d")
    sheet2, man2 = G.build(pool(), cal(), **KW)
    assert sheet == sheet2 and man == man2


def test_nothing_excluded_is_ever_drawn_and_thin_pools_fail_loudly():
    docs = pool()
    banned_ids = {d.id for d in docs[:150]}
    banned_text = [docs[300].text]
    sheet, man = G.build(docs, cal(), **{**KW, "exclude_ids": banned_ids, "exclude_texts": banned_text, "rows": 120, "quota": {k: 10 for k in KW["quota"]}})
    drawn = {v["origin_id"] for v in man["items"].values()}
    assert not drawn & banned_ids and docs[300].id not in drawn and docs[300].text not in {r["text"] for r in sheet}
    with pytest.raises(ConfigError, match="quota"):
        G.build(docs[:100], cal(), **KW)


def test_documents_outside_2023_2025_are_never_sampled():
    docs = pool() + [doc(9000 + i, words(9000 + i), when="2022-12-31T23:00:00+00:00") for i in range(50)]
    _, man = G.build(docs, cal(), **KW)
    assert not any(v["origin_id"].startswith("d9") and int(v["origin_id"][1:]) >= 9000 for v in man["items"].values())


def test_filing_stratum_finds_news_within_a_day_after_a_strong_filing_only():
    docs = pool()
    sheet, man = G.build(docs, cal(), **KW)
    filing_ids = [v["origin_id"] for v in man["items"].values() if v["stratum"] == "filing"]
    assert len(filing_ids) == 30
    by_id = {d.id: d for d in docs}
    assert all(by_id[i].published_at >= datetime(2024, 3, 5, 14, tzinfo=UTC) for i in filing_ids)


def labels(a: str, b: str):
    return {"event_class": a, "secondary_class": "", "notes": ""}, {"event_class": b, "secondary_class": "", "notes": ""}


def test_merge_reports_agreement_queues_disagreements_and_never_invents_a_human_label():
    sheet = [{"label_id": f"V{i:04d}", "source": "s", "ticker": "AAA", "published_at": "2024-01-01", "text": f"t{i}"} for i in range(1, 7)]
    man = {"items": {r["label_id"]: {"stratum": "rand"} for r in sheet}}
    ca = {r["label_id"]: labels("NONE", "NONE")[0] for r in sheet}
    cb = dict(ca)
    ca["V0003"], cb["V0003"] = labels("CREDIT_FUNDING", "NONE")
    ca["V0005"], cb["V0005"] = labels("GEOPOLITICAL", "GEOPOLITICAL")
    rows, rep, queue = G.merge(sheet, man, ca, cb)
    assert rep["agreed_rows"] == 5 and [q["label_id"] for q in queue] == ["V0003"] and queue[0]["human_event_class"] == ""
    assert rep["overall"]["agreement"] == pytest.approx(5 / 6, abs=1e-3) and rep["per_class"]["GEOPOLITICAL"]["share_agreed"] == 1.0
    assert rows[2]["agreed"] == "n" and rows[4]["agreed"] == "y"


def test_passes_are_ordered_differently_and_answers_are_validated(tmp_path):
    sheet, man = G.build(pool(), cal(), **KW)
    paths = G.write_passes(tmp_path, sheet, man)
    a = [r["label_id"] for p in sorted(paths) if "passA" in p.name for r in read_csv(p)]
    b = [r["label_id"] for p in sorted(paths) if "passB" in p.name for r in read_csv(p)]
    assert sorted(a) == sorted(b) and a != b
    ans = tmp_path / "answers"
    ans.mkdir()
    (ans / "x.jsonl").write_text('{"label_id": "V0001", "event_class": "BOGUS"}\n')
    with pytest.raises(ConfigError, match="invalid"):
        G.read_pass(ans, {"V0001"})
    (ans / "x.jsonl").write_text('{"label_id": "V0001", "event_class": "NONE"}\n')
    with pytest.raises(ConfigError, match="not labelled"):
        G.read_pass(ans, {"V0001", "V0002"})


def test_exclusion_texts_cover_gold_v1_and_every_event_label():
    texts, ids = G.exclusion_texts(REPO_ROOT)
    assert len(texts) >= 400 + 3000 and len(ids) >= 400
