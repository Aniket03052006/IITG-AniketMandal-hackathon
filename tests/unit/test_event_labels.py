"""Event-label pools, answer validation and the training table: determinism, blindness, disjointness from evaluation sets."""

from __future__ import annotations

import csv
import json
from collections import Counter

import pytest

from eventshock.config import ConfigError
from eventshock.modeling.corpora import prepare_text_pool
from eventshock.modeling.event_labels import (
    BATCH_COLUMNS,
    build_pools,
    build_table,
    check_disjoint,
    consistency,
    merge_labels,
    validate_answers,
    write_batches,
)
from eventshock.pipeline.config import EventModelConfig
from tests.modeling_helpers import make_doc
from tests.unit.test_event_train import cfg as train_cfg
from tests.unit.test_modeling_gold import sentence, sentiment_pool, tfn_pool

TOPICS = {1: 6, 2: 6}


def cfg() -> EventModelConfig:
    base = train_cfg().model_dump(mode="json")
    base["labels"] = dict(seed=5, near_duplicate_threshold=0.8, population_per_source={"top-tweets": 12, "headlines": 8}, rare_per_class=4,
                          tfn_topic_rows={str(k): v for k, v in TOPICS.items()}, replay_check={"gdelt-doc": 5}, consistency_rows=10,
                          dev_fraction=0.25)
    return EventModelConfig.model_validate(base)


PLACEHOLDER_CYCLE = ["MARKET_VALUATION"] * 5 + ["GEOPOLITICAL", "CREDIT_FUNDING", "REGULATORY_LEGAL", "MACROECONOMIC",
                                                   "MA_CORPORATE_ACTION", "PRODUCT_OPERATIONS", "EARNINGS_FINANCIAL_PERFORMANCE"]


def history(n: int = 300):
    return [make_doc(i, text=sentence(500 + i, "hist"), adapter=["top-tweets", "headlines"][i % 2], placeholder=PLACEHOLDER_CYCLE[i % 12])
            for i in range(n)]


def replay_docs(n: int = 30):
    return [make_doc(10_000 + i, text=sentence(9000 + i, "replay"), adapter="gdelt-doc") for i in range(n)]


def pools(gold_ids=frozenset(), gold_texts=(), docs=None, replay=None):
    return build_pools(cfg(), history=docs if docs is not None else history(),
                       topic_pool=prepare_text_pool(tfn_pool(), 0.7), sentiment_pool=prepare_text_pool(sentiment_pool(), 0.7),
                       replay=replay if replay is not None else replay_docs(), gold_ids=set(gold_ids), gold_texts=list(gold_texts))


class TestPools:
    def test_deterministic(self):
        a, b = pools(), pools()
        assert a[0] == b[0] and json.dumps(a[1], sort_keys=True) == json.dumps(b[1], sort_keys=True)

    def test_sheet_is_blind_and_ids_are_split_between_training_pool_and_replay_check(self):
        rows, man = pools()
        assert list(rows[0]) == BATCH_COLUMNS
        cells = " ".join(v for r in rows for k, v in r.items() if k != "text")
        assert "placeholder" not in cells and not any(s in cells for s in man["strata"])
        assert {i["role"] for i in man["items"].values() if i["population"] == "replay"} == {"replay-check"}
        assert sum(i["role"] == "replay-check" for i in man["items"].values()) == 5
        assert all(r["label_id"][0] in "ER" for r in rows)

    def test_weights_reconstruct_the_population_of_every_stratum(self):
        _, man = pools()
        for name, s in man["strata"].items():
            w = sum(i["weight"] for i in man["items"].values() if i["stratum"] == name)
            assert w == pytest.approx(s["population_size"], rel=1e-4), name

    def test_gold_ids_and_gold_lookalikes_are_never_drawn(self):
        docs = history()
        gold_text = docs[7].text
        gold_ids = {docs[3].id, docs[4].id}
        _, man = pools(gold_ids=gold_ids, gold_texts=[gold_text])
        drawn = {i["origin_id"] for i in man["items"].values()}
        assert not drawn & gold_ids and docs[7].id not in drawn

    def test_replay_check_lookalikes_never_enter_the_training_pool(self):
        docs, rep = history(), replay_docs()
        docs.append(make_doc(777, text=rep[0].text))  # a history document with the text of a replay-check candidate
        rows, man = pools(docs=docs, replay=rep)
        train_texts = [r["text"] for r in rows if r["label_id"].startswith("E")]
        replay_texts = [r["text"] for r in rows if r["label_id"].startswith("R")]
        assert not set(train_texts) & set(replay_texts)

    def test_a_stratum_that_cannot_meet_its_quota_fails_loudly(self):
        with pytest.raises(ConfigError, match="only .* candidates for a quota"):
            pools(replay=replay_docs(2))

    def test_consistency_rows_are_a_subset_of_training_rows_and_shuffled_in_the_batch(self, tmp_path):
        rows, man = pools()
        assert len(man["consistency"]) == 10 and all(lid.startswith("E") for lid in man["consistency"].values())
        paths = write_batches(tmp_path, rows, man)
        names = {p.name for p in paths}
        assert "consistency_01.csv" in names and "replay_01.csv" in names
        with (tmp_path / "consistency_01.csv").open(newline="", encoding="utf-8") as fh:
            ids = [r["label_id"] for r in csv.DictReader(fh)]
        assert sorted(ids) == sorted(man["consistency"]) and ids != sorted(ids)


class TestAnswers:
    def test_vocabulary_is_enforced(self):
        good = {"label_id": "E1", "event_class": "NONE", "secondary_class": "", "notes": ""}
        assert validate_answers([good], {"E1"}) == []
        errs = validate_answers([{**good, "event_class": "BULLISH"}, {**good, "label_id": "E9"}, {**good, "secondary_class": "NONE"},
                                 {**good, "event_class": "GEOPOLITICAL", "secondary_class": "GEOPOLITICAL"}, good, good], {"E1"})
        joined = " | ".join(errs)
        assert "BULLISH" in joined and "unknown id" in joined and "must be one of the 8 classes" in joined and "labelled twice" in joined

    def test_merge_refuses_unlabelled_rows_and_bad_answers(self, tmp_path):
        rows, man = pools()
        batches, answers = tmp_path / "b", tmp_path / "a"
        answers.mkdir()
        write_batches(batches, rows, man)
        with pytest.raises(ConfigError, match="not labelled yet"):
            merge_labels(batches, answers, man)
        (answers / "x.jsonl").write_text(json.dumps({"label_id": "E0001", "event_class": "WHATEVER"}) + "\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="invalid answer"):
            merge_labels(batches, answers, man)

    def test_merge_collects_both_passes_and_reports_self_consistency(self, tmp_path):
        rows, man = pools()
        batches, answers = tmp_path / "b", tmp_path / "a"
        answers.mkdir()
        write_batches(batches, rows, man)
        first = [{"label_id": lid, "event_class": "NONE" if k % 2 else "PRODUCT_OPERATIONS"} for k, lid in enumerate(sorted(man["items"]))]
        by_first = {a["label_id"]: a["event_class"] for a in first}
        second = [{"label_id": cid, "event_class": by_first[lid] if k < 8 else "MACROECONOMIC"}
                  for k, (cid, lid) in enumerate(sorted(man["consistency"].items()))]
        (answers / "first.jsonl").write_text("".join(json.dumps(a) + "\n" for a in first), encoding="utf-8")
        (answers / "second.jsonl").write_text("".join(json.dumps(a) + "\n" for a in second), encoding="utf-8")
        merged, cons = merge_labels(batches, answers, man)
        assert len(merged) == len(man["items"]) and {r["annotator"] for r in merged} == {"ai:claude"}
        assert cons["n"] == 10 and cons["agreement"] == 0.8

    def test_consistency_statistics(self):
        assert consistency([])["agreement"] is None
        c = consistency([("A", "A"), ("B", "B"), ("A", "A"), ("B", "B")])
        assert c["agreement"] == 1.0 and c["kappa"] == 1.0
        c = consistency([("A", "B"), ("B", "A")])
        assert c["agreement"] == 0.0 and c["kappa"] < 0


class TestTable:
    def labelled(self):
        rows, man = pools()
        labels = [{**r, "event_class": ["NONE", "GEOPOLITICAL", "PRODUCT_OPERATIONS"][k % 3], "secondary_class": "", "notes": "",
                   "annotator": "ai:claude", "batch": "x"} for k, r in enumerate(rows)]
        return labels, man

    def silver(self):
        return [{"id": f"tfn-topic-train-{k}", "text": sentence(7000 + k, "silver"), "event_class": "MACROECONOMIC", "tier": "strong",
                 "topic": 14, "group": k, "split": "train", "train_eligible": True, "gold_reserved": False} for k in range(30)]

    def test_splits_are_group_clean_and_replay_check_is_never_trained_on(self):
        labels, man = self.labelled()
        rows = build_table(cfg(), labels, man, self.silver(), gold_texts=[], gold_ids=set())
        by = Counter(r["split"] for r in rows)
        assert by["train"] > 0 and by["dev"] > 0 and by["replay_check"] == 5
        groups: dict = {}
        for r in rows:
            if r["kind"] == "annotated" and r["split"] in ("train", "dev"):
                groups.setdefault(r["group"], set()).add(r["split"])
        assert all(len(v) == 1 for v in groups.values())
        assert check_disjoint(rows, [], set()) == []

    def test_dev_weights_reconstruct_each_strata_population_within_the_split(self):
        labels, man = self.labelled()
        rows = build_table(cfg(), labels, man, [], gold_texts=[], gold_ids=set())
        for name, s in man["strata"].items():
            for split in ("dev", "replay_check"):
                w = sum(r["pop_weight"] for r in rows if r["stratum"] == name and r["split"] == split)
                if any(r["stratum"] == name and r["split"] == split for r in rows):
                    assert w == pytest.approx(s["population_size"], rel=1e-3), (name, split)

    def test_silver_is_capped_and_never_resembles_dev_or_gold(self):
        labels, man = self.labelled()
        c = cfg().model_copy(update={"silver": cfg().silver.model_copy(update={"use": True, "max_rows_per_class": 7})})
        gold_text = self.silver()[0]["text"]
        rows = build_table(c, labels, man, self.silver(), gold_texts=[gold_text], gold_ids=set())
        silver = [r for r in rows if r["kind"] == "silver"]
        assert len(silver) == 7 and all(r["split"] == "train" and r["sample_weight"] == c.silver.sample_weight for r in silver)
        assert gold_text not in [r["text"] for r in silver]

    def test_check_disjoint_catches_a_training_row_that_is_a_gold_or_dev_lookalike(self):
        labels, man = self.labelled()
        rows = build_table(cfg(), labels, man, [], gold_texts=[], gold_ids=set())
        train = next(r for r in rows if r["split"] == "train")
        assert any("near-duplicates of gold" in p for p in check_disjoint(rows, [train["text"]], set()))
        assert any("is a gold row" in p for p in check_disjoint(rows, [], {train["id"]}))
        dev = next(r for r in rows if r["split"] == "dev")
        leaked = [*rows, {**train, "id": "leak", "text": dev["text"], "group": 9_999_999}]
        assert any("near-duplicates of dev" in p for p in check_disjoint(leaked, [], set()))
