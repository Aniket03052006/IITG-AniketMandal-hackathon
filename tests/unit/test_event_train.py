"""Training, abstention tuning and evaluation of the event model on a tiny synthetic corpus (fast, offline)."""

from __future__ import annotations

import json
import random

import numpy as np
import pytest

from eventshock.config import ConfigError
from eventshock.domain import EventStatus
from eventshock.modeling import event_eval as ee
from eventshock.modeling.event_train import load_training_table, run
from eventshock.modeling.leakage import LeakageError
from eventshock.pipeline.config import EventModelConfig
from eventshock.pipeline.event_model import CLASSES, EVENT_CLASSES, NONE_CLASS, EventModel
from tests.pipe_helpers import ENRICH

PHRASES = {
    "GEOPOLITICAL": ["sanctions imposed after border conflict", "tariffs raised amid trade war with neighbour"],
    "MACROECONOMIC": ["central bank holds interest rates as inflation cools", "unemployment data beats forecast"],
    "CREDIT_FUNDING": ["agency downgrades bond rating after debt default", "firm refinances loan and issues notes"],
    "MA_CORPORATE_ACTION": ["agrees to acquire rival in merger deal", "announces spin-off and share buyback"],
    "REGULATORY_LEGAL": ["regulator opens investigation and fines firm", "court approves settlement of lawsuit"],
    "PRODUCT_OPERATIONS": ["recalls vehicles after plant outage", "launches new product amid strike at factory"],
    "EARNINGS_FINANCIAL_PERFORMANCE": ["reports quarterly earnings per share above estimates", "raises full year revenue guidance"],
    "MARKET_VALUATION": ["analyst raises price target and upgrades rating", "shares drift as index rebalances momentum"],
    "NONE": ["lol great chart today", "join our free discord for stock picks", "what do you think about this one", "to the moon rocket"],
}


def corpus(n_per_class: int = 50, seed: int = 1):
    rng = random.Random(seed)
    rows = []
    for label, phrases in PHRASES.items():
        for i in range(n_per_class):
            split = "train" if i < n_per_class * 0.7 else "dev" if i < n_per_class * 0.9 else "replay_check"
            pop = "history" if i % 2 == 0 else "tfn"
            text = f"${rng.choice('ABCDEFG')}{rng.choice('XYZ')} {rng.choice(phrases)} {rng.randint(1, 99)} item{len(rows)}"
            rows.append({"id": f"E{len(rows):04d}", "text": text, "label": label, "split": split, "kind": "annotated",
                         "group": len(rows), "sample_weight": 1.0, "pop_weight": 2.0, "stratum": f"rand:{pop}",
                         "population": pop, "source": "test"})
    return rows


def cfg(**over) -> EventModelConfig:
    base = dict(
        version="tiny-event", model_dir="models/tiny", table="data/modeling/event_train.jsonl", labels_file="data/event_labels/event_labels.csv",
        manifest_file="data/event_labels/manifest.json", seed=1,
        labels=dict(seed=1, near_duplicate_threshold=0.8, population_per_source={"x": 1}, rare_per_class=1, tfn_topic_rows={1: 1},
                    replay_check={"x": 1}, consistency_rows=0, dev_fraction=0.25),
        silver=dict(use=False, max_rows_per_class=10, sample_weight=0.5),
        word={"ngram_range": [1, 2], "min_df": 1}, char={"ngram_range": [2, 4], "min_df": 2}, max_iter=300,
        grid={"preprocessing": ["raw", "normalised"], "C": [1, 5], "class_weight": ["balanced", None]},
        abstention=dict(commit_threshold=0.5, min_train_examples=10, min_dev_support=3, dev_f1_floor=0.3, route_unreliable_to_uncertain=True),
        evaluation={"bootstrap_resamples": 100})
    return EventModelConfig.model_validate({**base, **over})


def write_table(root, rows):
    path = root / "data" / "modeling" / "event_train.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (root / "data" / "event_labels").mkdir(parents=True, exist_ok=True)
    (root / "data" / "event_labels" / "event_labels.csv").write_text("label_id\n", encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("repo")
    write_table(root, corpus())
    card = run(cfg(), repo_root=root, enrichment_cfg=ENRICH)
    return root, card


class TestEndToEnd:
    def test_trains_selects_tunes_and_the_pair_reloads(self, trained):
        root, card = trained
        model = EventModel.load(root / "models/tiny")
        assert model.model_id == "tiny-event" and len(card.candidates) == 8
        assert sum(c.selected for c in card.candidates) == 1
        assert card.classes == list(CLASSES) and len(card.classes) == 9
        assert card.abstention.commit_threshold == 0.5 and card.abstention.dev_coverage > 0.5
        dev = next(e for e in card.evaluations if e.id == "dev_history")
        assert dev.model is not None and dev.model.macro_f1 > 0.8  # the synthetic task is easy
        assert dev.model.served.detection.f1 > 0.8

    def test_gold_and_replay_check_sets_are_reported_separately_from_dev(self, trained):
        _, card = trained
        ids = [e.id for e in card.evaluations]
        assert ids[:2] == ["dev_history", "dev_tfn_topics"] and "replay_check" in ids and "gold_history" in ids
        gold = next(e for e in card.evaluations if e.id == "gold_history")
        assert gold.status == "skipped", "no gold set in the synthetic repo: skipped, never invented"

    def test_baselines_are_scored_on_every_evaluated_set(self, trained):
        _, card = trained
        for e in card.evaluations:
            if e.model is not None:
                assert set(e.baselines) == {"majority_class", "placeholder_keywords", "tfn_topic_probe"}

    def test_training_is_deterministic_byte_for_byte(self, trained, tmp_path):
        root, card = trained
        write_table(tmp_path, corpus())
        again = run(cfg(), repo_root=tmp_path, enrichment_cfg=ENRICH)
        assert again.artifact_sha256 == card.artifact_sha256
        assert again.model_dump_json() == card.model_dump_json()

    def test_acceptance_is_recorded_not_assumed(self, trained):
        _, card = trained
        assert card.acceptance.rule and card.acceptance.checks
        assert not card.acceptance.met, "gold/replay evidence is absent in the synthetic repo, so the bar cannot be met"

    def test_rare_class_with_too_little_data_is_flagged_unreliable_and_routed_to_uncertain(self, tmp_path):
        rows = [r for r in corpus() if r["label"] != "GEOPOLITICAL" or int(r["id"][1:]) % 50 < 8]  # 5 train rows for one class
        write_table(tmp_path, rows)
        card = run(cfg(), repo_root=tmp_path, enrichment_cfg=ENRICH)
        geo = next(r for r in card.class_reliability if r.label == "GEOPOLITICAL")
        assert geo.status == "unreliable" and "training rows" in geo.reason
        assert "GEOPOLITICAL" in card.abstention.unreliable_classes
        model = EventModel.load(tmp_path / "models/tiny")
        d = model.decide("$AXX sanctions imposed after border conflict tariffs trade war 12")
        assert d.unreliable_class and d.status in (EventStatus.UNCERTAIN, EventStatus.NO_EVENT)


class TestTableGuards:
    def test_refuses_placeholder_ai_or_gold_columns(self, tmp_path):
        rows = corpus(20)
        for r in rows:
            r["placeholder_event"] = "MARKET_VALUATION"
        with pytest.raises(ConfigError, match="unexpected columns"):
            load_training_table(write_table(tmp_path, rows))

    def test_refuses_gold_rows(self, tmp_path):
        rows = corpus(20)
        with pytest.raises(ConfigError, match="gold-set rows"):
            load_training_table(write_table(tmp_path, rows), gold_origin_ids={rows[3]["id"]})

    def test_refuses_unknown_labels_and_missing_classes(self, tmp_path):
        rows = corpus(20)
        rows[0]["label"] = "BULLISH"
        with pytest.raises(ConfigError, match="unknown event labels"):
            load_training_table(write_table(tmp_path, rows))
        rows = [r for r in corpus(20) if r["label"] != "NONE"]
        with pytest.raises(ConfigError, match="no training rows for"):
            load_training_table(write_table(tmp_path, rows))

    def test_refuses_a_group_that_straddles_train_and_dev(self, tmp_path):
        rows = corpus(20)
        a = next(r for r in rows if r["split"] == "train")
        b = next(r for r in rows if r["split"] == "dev")
        b["group"] = a["group"]
        with pytest.raises(LeakageError):
            load_training_table(write_table(tmp_path, rows))

    def test_refuses_duplicate_ids_and_unknown_splits(self, tmp_path):
        rows = corpus(20)
        rows[1]["id"] = rows[0]["id"]
        with pytest.raises(ConfigError, match="duplicate row ids"):
            load_training_table(write_table(tmp_path, rows))
        rows = corpus(20)
        rows[0]["split"] = "test"
        with pytest.raises(ConfigError, match="unknown splits"):
            load_training_table(write_table(tmp_path, rows))


class TestMetrics:
    def test_served_scores_count_uncertain_as_wrong_and_exclude_it_from_coverage(self):
        k = len(CLASSES)
        probs = np.full((4, k), 1e-3)
        d = ee.Decisions(
            texts=list("abcd"), truth=["MACROECONOMIC", "NONE", "NONE", "GEOPOLITICAL"], weights=np.ones(4), probs=probs,
            status=np.array([ee.STATUS[EventStatus.CLASSIFIED], ee.STATUS[EventStatus.NO_EVENT], ee.STATUS[EventStatus.NO_EVENT],
                             ee.STATUS[EventStatus.UNCERTAIN]]),
            top=np.array([EVENT_CLASSES.index("MACROECONOMIC")] * 3 + [EVENT_CLASSES.index("GEOPOLITICAL")]), secondary=[""] * 4)
        s = ee.served_scores(d)
        assert s.accuracy == 0.75 and s.coverage == 0.75 and s.accuracy_when_decided == 1.0
        assert s.classified_precision == 1.0 and s.status_mix == {"CLASSIFIED": 0.25, "NO_EVENT": 0.5, "UNCERTAIN": 0.25}
        # both true events count as detected (CLASSIFIED and UNCERTAIN are both "an event"), both NONE rows were NO_EVENT
        assert (s.detection.precision, s.detection.recall) == (1.0, 1.0)
        assert ee.NONE_IDX == len(EVENT_CLASSES) and NONE_CLASS == "NONE"

    def test_detection_treats_uncertain_as_an_event(self):
        y = np.array([ee.NONE_IDX, 0, 1])
        d = ee.detection(y, np.array([False, True, True]), np.ones(3))
        assert (d.precision, d.recall, d.f1) == (1.0, 1.0, 1.0)
