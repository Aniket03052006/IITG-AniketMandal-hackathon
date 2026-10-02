"""Training, selection, calibration and evaluation of the sentiment model, on a tiny synthetic corpus (fast, offline)."""

from __future__ import annotations

import json
import random

import numpy as np
import pytest

from eventshock.config import ConfigError
from eventshock.modeling.leakage import LeakageError
from eventshock.modeling.sentiment_eval import (
    LABELS,
    bootstrap_macro_f1,
    brier,
    confusion,
    log_loss,
    prf,
    product_labels,
    reliability,
)
from eventshock.modeling.sentiment_train import fit_temperature, load_training_table, nll, run, softmax
from eventshock.pipeline.config import SentimentModelConfig
from eventshock.pipeline.sentiment_model import SentimentModel
from tests.pipe_helpers import ENRICH

POS = ["shares surge after record profit", "stock rallies on strong upgrade", "company beats estimates and raises guidance",
       "bullish breakout as sales jump", "analysts upgrade on growth and approval"]
NEG = ["shares plunge after fraud probe", "stock tumbles on weak outlook and downgrade", "company misses estimates and cuts guidance",
       "bearish slump as losses widen", "regulator fines firm over breach and lawsuit"]
NEU = ["company to hold annual meeting on tuesday", "board announces date of investor conference call",
       "firm files routine report with the regulator", "executive to speak at industry panel", "quarterly dividend payable next month"]


def corpus(n_per_class: int = 60, seed: int = 1):
    rng = random.Random(seed)
    rows = []
    for label, phrases in (("positive", POS), ("negative", NEG), ("neutral", NEU)):
        for i in range(n_per_class):
            split = "train" if i < n_per_class * 0.7 else "valid" if i < n_per_class * 0.85 else "test"
            text = f"${rng.choice('ABCDEFG')}{rng.choice('XYZ')} - {rng.choice(phrases)} {rng.randint(1, 99)} item{len(rows)}"
            rows.append({"id": f"tfn-sent-train-{len(rows)}", "text": text, "label": label, "split": split, "group": len(rows),
                         "published_split": "train"})
    return rows


def cfg(**over) -> SentimentModelConfig:
    base = dict(version="tiny-v1", model_dir="models/tiny", table="data/modeling/sentiment.jsonl", seed=1,
                word={"ngram_range": [1, 2], "min_df": 1}, char={"ngram_range": [2, 4], "min_df": 2}, max_iter=300,
                grid={"preprocessing": ["raw", "normalised"], "C": [0.5, 5], "class_weight": ["balanced", None]},
                evaluation={"bootstrap_resamples": 100})
    return SentimentModelConfig.model_validate({**base, **over})


def write_table(root, rows):
    path = root / "data" / "modeling" / "sentiment.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("repo")
    write_table(root, corpus())
    card = run(cfg(), repo_root=root, enrichment_cfg=ENRICH)
    return root, card


class TestEndToEnd:
    def test_trains_selects_evaluates_and_the_pair_reloads(self, trained):
        root, card = trained
        model = SentimentModel.load(root / "models/tiny")
        assert model.model_id == "tiny-v1" and len(card.candidates) == 8
        assert sum(c.selected for c in card.candidates) == 1
        tfn = next(e for e in card.evaluations if e.id == "tfn_test")
        assert tfn.model is not None and tfn.model.macro_f1 > 0.9  # the synthetic task is easy
        assert tfn.model.macro_f1_ci95 is not None and tfn.model.macro_f1_ci95[0] <= tfn.model.macro_f1 <= tfn.model.macro_f1_ci95[1]

    def test_selected_candidate_has_the_lowest_valid_log_loss(self, trained):
        _, card = trained
        sel = next(c for c in card.candidates if c.selected)
        assert sel.valid_log_loss == min(c.valid_log_loss for c in card.candidates)

    def test_missing_external_sets_are_reported_as_skipped_not_invented(self, trained):
        _, card = trained
        by = {e.id: e for e in card.evaluations}
        assert by["phrasebank"].status == "skipped" and by["phrasebank"].model is None and by["phrasebank"].note
        assert by["gold_history"].status == "skipped"

    def test_retraining_gives_identical_bytes_and_card(self, trained, tmp_path):
        root, card = trained
        again = run(cfg(), repo_root=root, enrichment_cfg=ENRICH, out_dir=tmp_path / "again")
        assert again.artifact_sha256 == card.artifact_sha256
        assert (tmp_path / "again/model_card.json").read_bytes() == (root / "models/tiny/model_card.json").read_bytes()

    def test_card_records_only_training_split_label_counts(self, trained):
        _, card = trained
        assert card.training.rows == {"train": 126, "valid": 27, "test": 27}
        assert sum(card.training.label_distribution.values()) == 126


class TestLeakageGuards:
    def table(self, tmp_path, rows):
        return write_table(tmp_path, rows)

    @pytest.mark.parametrize("col", ["ai_sentiment", "placeholder_sentiment", "human_label", "gold_id", "nb_sentiment"])
    def test_label_like_columns_from_other_sources_are_refused(self, tmp_path, col):
        rows = corpus(10)
        rows[0][col] = "x"
        with pytest.raises(ConfigError, match="can never be labels"):
            load_training_table(self.table(tmp_path, rows))

    def test_non_tfn_rows_are_refused(self, tmp_path):
        rows = corpus(10)
        rows[3]["id"] = "sig_123"
        with pytest.raises(ConfigError, match="not TFN sentiment rows"):
            load_training_table(self.table(tmp_path, rows))

    def test_gold_rows_are_refused(self, tmp_path):
        rows = corpus(10)
        with pytest.raises(ConfigError, match="gold-set rows"):
            load_training_table(self.table(tmp_path, rows), gold_origin_ids={rows[2]["id"]})

    def test_group_straddling_two_splits_is_refused(self, tmp_path):
        rows = corpus(10)
        a, b = next(r for r in rows if r["split"] == "train"), next(r for r in rows if r["split"] == "test")
        b["group"] = a["group"]
        with pytest.raises(LeakageError):
            load_training_table(self.table(tmp_path, rows))

    def test_unknown_label_and_missing_split_are_refused(self, tmp_path):
        rows = corpus(10)
        rows[0]["label"] = "bullish"
        with pytest.raises(ConfigError, match="unknown sentiment labels"):
            load_training_table(self.table(tmp_path, rows))
        d = tmp_path / "b"
        d.mkdir()
        with pytest.raises(ConfigError, match="no rows in split"):
            load_training_table(write_table(d, [r for r in corpus(10) if r["split"] != "test"]))

    def test_missing_table_says_how_to_build_it(self, tmp_path):
        with pytest.raises(ConfigError, match="make audit"):
            load_training_table(tmp_path / "nope.jsonl")


class TestConfigIsStrict:
    def test_typo_and_bad_values_fail_loudly(self):
        with pytest.raises(ValueError):
            cfg(grdi={})
        with pytest.raises(ValueError):
            cfg(grid={"preprocessing": ["stemmed"], "C": [1], "class_weight": [None]})
        with pytest.raises(ValueError):
            cfg(grid={"preprocessing": ["raw"], "C": [-1], "class_weight": [None]})
        with pytest.raises(ValueError):
            cfg(selection_rule="best_f1")
        with pytest.raises(ValueError):
            cfg(temperature_grid=[2.0, 1.0, 0.1])

    def test_shipped_config_loads(self):
        from eventshock.config import REPO_ROOT
        from eventshock.pipeline.config import load_sentiment_model_config

        c = load_sentiment_model_config(REPO_ROOT / "configs")
        assert c.selection_rule == "valid_log_loss_after_temperature" and c.version == "tfidf-lr-v1"


class TestMetrics:
    def test_temperature_scaling_never_worsens_the_fitted_loss(self):
        rng = np.random.RandomState(0)
        logits = rng.normal(size=(300, 3)) * 4  # overconfident
        y = (logits + rng.normal(size=(300, 3)) * 6).argmax(axis=1)
        t = fit_temperature(logits, y, (0.5, 8.0, 0.05))
        assert t > 1 and nll(softmax(logits, t), y) <= nll(softmax(logits), y)

    def test_softmax_rows_sum_to_one_and_survive_huge_logits(self):
        p = softmax(np.array([[1e4, 0.0, -1e4], [0.0, 0.0, 0.0]]))
        assert np.allclose(p.sum(axis=1), 1) and np.isfinite(p).all()

    def test_confusion_and_prf_by_hand(self):
        y = np.array([0, 0, 1, 1, 2, 2])
        pred = np.array([0, 1, 1, 1, 2, 0])
        conf = confusion(y, pred, np.ones(6))
        per, acc, macro = prf(conf)
        assert conf.tolist() == [[1, 1, 0], [0, 2, 0], [1, 0, 1]]
        assert acc == pytest.approx(4 / 6)
        assert per["neutral"].precision == pytest.approx(2 / 3, abs=1e-4) and per["neutral"].recall == 1.0
        assert macro == pytest.approx((0.5 + 0.8 + 2 / 3) / 3, abs=1e-3)

    def test_weights_change_the_scores(self):
        y, pred = np.array([0, 1]), np.array([0, 0])
        assert prf(confusion(y, pred, np.array([1.0, 1.0])))[1] == 0.5
        assert prf(confusion(y, pred, np.array([9.0, 1.0])))[1] == 0.9

    def test_ece_is_zero_for_perfectly_calibrated_and_large_for_overconfident(self):
        y = np.array([0] * 8 + [1] * 2)
        calibrated = np.tile([0.8, 0.2, 0.0], (10, 1))
        ece, table = reliability(calibrated, y, np.ones(10), 10)
        assert ece == pytest.approx(0.0, abs=1e-9) and sum(b.n for b in table) == 10
        over = np.tile([0.99, 0.01, 0.0], (10, 1))
        assert reliability(over, y, np.ones(10), 10)[0] == pytest.approx(0.19, abs=1e-6)

    def test_log_loss_and_brier_known_values(self):
        probs = np.array([[0.5, 0.5, 0.0], [0.0, 1.0, 0.0]])
        y, w = np.array([0, 1]), np.ones(2)
        assert log_loss(probs, y, w) == pytest.approx(np.log(2) / 2)
        assert brier(probs, y, w) == pytest.approx(0.25)

    def test_product_labels_use_the_ui_cut(self):
        out = product_labels(np.array([-0.5, -0.15, 0.0, 0.149, 0.15, 0.9]), 0.15)
        assert [LABELS[i] for i in out] == ["negative", "negative", "neutral", "neutral", "positive", "positive"]

    def test_bootstrap_interval_is_seeded_and_brackets_the_estimate(self):
        rng = np.random.RandomState(3)
        y = rng.randint(0, 3, 400)
        pred = np.where(rng.rand(400) < 0.8, y, rng.randint(0, 3, 400))
        a = bootstrap_macro_f1(y, pred, np.ones(400), resamples=200, seed=1)
        assert a == bootstrap_macro_f1(y, pred, np.ones(400), resamples=200, seed=1)
        assert a[0] < prf(confusion(y, pred, np.ones(400)))[2] < a[1]
