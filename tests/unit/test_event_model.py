"""The shipped event artifact: loading, integrity, determinism, contract validity, the decision rule and the failure policy."""

from __future__ import annotations

import json
import random
import shutil
import string

import numpy as np
import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.domain import EventClassification, EventStatus
from eventshock.pipeline.config import load_event_model_config
from eventshock.pipeline.event_model import (
    CARD_FILE,
    CLASSES,
    EVENT_CLASSES,
    EventInputError,
    EventModel,
    _round_event_probs,
)

MODEL_DIR = REPO_ROOT / load_event_model_config(REPO_ROOT / "configs").model_dir
RECALL = "Boeing recalls 737 jets after regulator finds door plug defect and halts production"
CHATTER = "lol this chart is wild 🚀🚀 join the discord for more picks"
FED = "Federal Reserve holds interest rates steady as inflation cools, signals cuts"


@pytest.fixture(scope="module")
def model() -> EventModel:
    return EventModel.load(MODEL_DIR)


class TestDecisionRule:
    def row(self, none: float, **ev: float):
        p = np.zeros(len(CLASSES))
        for k, v in ev.items():
            p[EVENT_CLASSES.index(k)] = v
        p[CLASSES.index("NONE")] = none
        return p

    def test_commits_the_nine_class_argmax_only_at_the_threshold(self, model):
        t = model.commit_threshold
        assert model.status_for(self.row(t + 0.05, PRODUCT_OPERATIONS=1 - t - 0.05))[0] is EventStatus.NO_EVENT
        assert model.status_for(self.row(0.1, REGULATORY_LEGAL=t + 0.1, MARKET_VALUATION=0.9 - t - 0.1))[0] in (
            EventStatus.CLASSIFIED, EventStatus.UNCERTAIN)  # UNCERTAIN only if REGULATORY_LEGAL is flagged unreliable
        status, _ = model.status_for(self.row(0.3, REGULATORY_LEGAL=0.36, MARKET_VALUATION=0.34))
        assert status is EventStatus.UNCERTAIN, "nothing reaches the threshold"

    def test_none_wins_ties_and_a_weak_none_is_uncertain_not_no_event(self, model):
        status, _ = model.status_for(self.row(0.4, GEOPOLITICAL=0.4, MACROECONOMIC=0.2))
        assert status is EventStatus.UNCERTAIN  # NONE is the arg-max (tie) but below the threshold

    def test_an_unreliable_class_is_never_asserted(self, model):
        for cls in model.unreliable:
            status, top = model.status_for(self.row(0.0, **{cls: 1.0}))
            assert EVENT_CLASSES[top] == cls and status is EventStatus.UNCERTAIN

    def test_rounding_never_moves_the_argmax_or_breaks_the_contract(self):
        rng = np.random.RandomState(3)
        for _ in range(500):
            cond = rng.dirichlet(np.ones(8) * rng.choice([0.1, 1, 10]))
            probs = _round_event_probs([float(x) for x in cond])
            top = max(probs, key=probs.__getitem__)
            EventClassification(category=top, probabilities=probs)  # the real validators
            assert top.value == EVENT_CLASSES[int(np.argmax(cond))]


class TestPredictions:
    def test_direction_on_clear_sentences(self, model):
        assert model.decide(CHATTER).status is not EventStatus.CLASSIFIED
        assert model.decide(CHATTER).no_event_probability > model.decide(RECALL).no_event_probability
        r = model.decide(RECALL)
        assert r.category.value == "PRODUCT_OPERATIONS"
        assert model.decide(FED).category.value == "MACROECONOMIC"

    def test_decisions_are_valid_for_the_contract(self, model):
        rng = random.Random(11)
        words = RECALL.split() + CHATTER.split() + FED.split() + ["$MSFT", "http://x.co/a", "12.5%", "ünïcode", "…"]
        texts = [" ".join(rng.choice(words) for _ in range(rng.randint(1, 25))) for _ in range(150)]
        texts = [t for t in texts if model.unscorable_reason(t) is None]
        assert len(texts) > 100
        for d in model.decide_many(texts):
            EventClassification(category=d.category, probabilities=d.probabilities, status=d.status, no_event_probability=d.no_event_probability)
            assert 0 <= d.confidence <= 1 and 0 <= d.no_event_probability <= 1
            assert d.confidence + d.no_event_probability <= 1 + 1e-3, "two of nine probabilities cannot exceed 1"
            if d.status is EventStatus.CLASSIFIED:
                assert d.confidence >= model.commit_threshold - 1e-3 and not d.unreliable_class

    def test_deterministic_across_loads_and_batch_equals_single(self, model):
        again = EventModel.load(MODEL_DIR)
        texts = [RECALL, CHATTER, FED, "$TSLA recall ahead?"]
        assert model.decide_many(texts) == again.decide_many(texts)
        assert [model.decide(t) for t in texts] == model.decide_many(texts)

    def test_seen_in_training_flags_the_exact_text_only(self, model):
        row = next(json.loads(line) for line in (REPO_ROOT / "data/modeling/event_train.jsonl").open() if '"split": "train"' in line
                   and '"kind": "annotated"' in line)
        assert model.decide(row["text"]).seen_in_training
        assert model.decide(row["text"].upper() + " https://t.co/zzz").seen_in_training
        assert not model.decide("A sentence about nothing the model has seen: zebra quarterly xylophone").seen_in_training

    def test_class_order_is_fixed_and_the_card_says_so(self, model):
        assert tuple(model.card.classes) == CLASSES and CLASSES[-1] == "NONE" and len(CLASSES) == 9


class TestUnscorableText:
    @pytest.mark.parametrize("text", ["", "   ", "https://t.co/abc", "$SPY $IWM $DAL", "@user", "12.5 3,000", "!!! ???"])
    def test_reason_is_given_and_decide_raises(self, model, text):
        assert model.unscorable_reason(text)
        with pytest.raises(EventInputError):
            model.decide(text)

    @pytest.mark.parametrize("bad", [None, 3, b"bytes", ["a"]])
    def test_non_strings_are_rejected_not_coerced(self, model, bad):
        assert "not str" in (model.unscorable_reason(bad) or "")
        with pytest.raises(EventInputError):
            model.decide_many([bad])

    def test_empty_batch_is_empty(self, model):
        assert model.decide_many([]) == []

    def test_fuzz_never_crashes_or_returns_invalid(self, model):
        rng = random.Random(5)
        alphabet = string.printable + "éÃ©�中😀"
        for _ in range(200):
            t = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
            if model.unscorable_reason(t):
                with pytest.raises(EventInputError):
                    model.decide(t)
            else:
                d = model.decide(t)
                assert abs(sum(d.probabilities.values()) - 1) < 1e-3


class TestArtifactIntegrity:
    def copy(self, tmp_path):
        d = tmp_path / "m"
        shutil.copytree(MODEL_DIR, d)
        return d

    def test_missing_files_fail_loudly_with_the_fix(self, tmp_path):
        with pytest.raises(ConfigError, match="make train-event"):
            EventModel.load(tmp_path)

    def test_modified_artifact_is_refused(self, tmp_path):
        d = self.copy(tmp_path)
        with (d / "model.joblib").open("ab") as fh:
            fh.write(b"\0")
        with pytest.raises(ConfigError, match="does not match its model card"):
            EventModel.load(d)

    def test_malformed_card_is_refused(self, tmp_path):
        d = self.copy(tmp_path)
        (d / CARD_FILE).write_text("{not json", encoding="utf-8")
        with pytest.raises(ConfigError, match="invalid event model card"):
            EventModel.load(d)

    def test_other_scikit_learn_version_is_refused(self, tmp_path):
        d = self.copy(tmp_path)
        card = json.loads((d / CARD_FILE).read_text(encoding="utf-8"))
        card["libraries"]["scikit-learn"] = "0.0.1"
        (d / CARD_FILE).write_text(json.dumps(card), encoding="utf-8")
        with pytest.raises(ConfigError, match="scikit-learn"):
            EventModel.load(d)


class TestShippedCard:
    def test_card_is_complete_and_honest(self, model):
        c = model.card
        assert c.limitations and c.acceptance.rule and c.acceptance.checks
        assert c.training.annotator == "ai:claude" and c.training.consistency.n > 0
        assert {r.label for r in c.class_reliability} == set(EVENT_CLASSES)
        flagged = {r.label for r in c.class_reliability if r.status == "unreliable"}
        assert flagged == set(c.abstention.unreliable_classes) == set(model.unreliable)
        ids = [e.id for e in c.evaluations]
        assert ids[:2] == ["dev_history", "dev_tfn_topics"] and {"gold_history", "replay_check"} <= set(ids)
        assert all(e.status == "ok" for e in c.evaluations), "the shipped card was produced by a full (not dev-only) run"

    def test_card_records_the_silver_ablation_and_what_was_chosen(self, model):
        a = model.card.ablation
        assert "dev_log_loss_without_silver" in a and a["silver_used"] in (0.0, 1.0)
