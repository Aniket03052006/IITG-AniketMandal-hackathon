"""The shipped sentiment artifact: loading, integrity, determinism, score validity, and the failure policy."""

from __future__ import annotations

import json
import random
import shutil
import string

import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.domain import SentimentResult
from eventshock.pipeline.config import load_sentiment_model_config
from eventshock.pipeline.sentiment_model import (
    CARD_FILE,
    CLASSES,
    SentimentInputError,
    SentimentModel,
    prepare_text,
    text_key,
)

MODEL_DIR = REPO_ROOT / load_sentiment_model_config(REPO_ROOT / "configs").model_dir
POS = "Apple beats earnings estimates and raises full-year guidance, shares surge"
NEG = "Company misses estimates, cuts outlook and shares plunge after fraud probe"
NEUTRAL = "Company to present at investor conference next Tuesday"


@pytest.fixture(scope="module")
def model() -> SentimentModel:
    return SentimentModel.load(MODEL_DIR)


class TestPrepareText:
    def test_normalised_replaces_links_handles_tickers_numbers(self):
        out = prepare_text("$AAPL up 3.5% https://t.co/x via @user", "normalised")
        assert out == "_cashtag_ up _num_ % via _user_"

    def test_raw_is_untouched_and_unknown_mode_fails(self):
        assert prepare_text("$AAPL  up", "raw") == "$AAPL  up"
        with pytest.raises(ValueError):
            prepare_text("x", "bogus")

    def test_text_key_ignores_case_punctuation_and_links(self):
        assert text_key("Apple Beats, Estimates! https://t.co/a") == text_key("apple beats estimates")


class TestPredictions:
    def test_direction_on_clear_sentences(self, model):
        pos, neg, neu = model.predict(POS), model.predict(NEG), model.predict(NEUTRAL)
        assert pos.score > 0.3 > -0.3 > neg.score
        assert abs(neu.score) < 0.3 and neu.neutral > neu.positive and neu.neutral > neu.negative

    def test_probabilities_are_valid_for_the_contract(self, model):
        rng = random.Random(11)
        words = POS.split() + NEG.split() + ["$MSFT", "http://x.co/a", "12.5%", "ünïcode", "…"]
        texts = [" ".join(rng.choice(words) for _ in range(rng.randint(1, 25))) for _ in range(150)]
        texts = [t for t in texts if model.unscorable_reason(t) is None]
        assert len(texts) > 100
        for p in model.predict_many(texts):
            assert min(p.negative, p.neutral, p.positive) >= 0 and 0 <= p.confidence <= 1
            assert abs(p.negative + p.neutral + p.positive - 1) < 1e-3
            assert abs(p.score - (p.positive - p.negative)) < 1e-3 and -1 <= p.score <= 1
            SentimentResult(positive=p.positive, neutral=p.neutral, negative=p.negative, score=p.score)  # the real contract

    def test_deterministic_across_loads_and_batch_equals_single(self, model):
        again = SentimentModel.load(MODEL_DIR)
        texts = [POS, NEG, NEUTRAL, "$TSLA recall ahead?"]
        assert model.predict_many(texts) == again.predict_many(texts)
        assert [model.predict(t) for t in texts] == model.predict_many(texts)
        assert model.predict(POS) == model.predict(POS)

    def test_confidence_is_the_largest_probability(self, model):
        p = model.predict(NEG)
        assert p.confidence == pytest.approx(max(p.negative, p.neutral, p.positive), abs=1e-3)

    def test_seen_in_training_flags_the_exact_text_only(self, model):
        row = next(json.loads(line) for line in (REPO_ROOT / "data/modeling/sentiment.jsonl").open() if '"split":"train"' in line)
        assert model.predict(row["text"]).seen_in_training
        assert model.predict(row["text"].upper() + " https://t.co/zzz").seen_in_training  # case and links are ignored
        assert not model.predict("A sentence about nothing the model has ever seen: zebra quarterly xylophone").seen_in_training

    def test_class_order_is_fixed(self, model):
        assert tuple(model.card.classes) == CLASSES == ("negative", "neutral", "positive")


class TestUnscorableText:
    @pytest.mark.parametrize("text", ["", "   ", "\n\t", "https://t.co/abc", "$SPY $IWM $DAL", "@user", "12.5 3,000", "!!! ???"])
    def test_reason_is_given_and_predict_raises(self, model, text):
        assert model.unscorable_reason(text)
        with pytest.raises(SentimentInputError):
            model.predict(text)

    @pytest.mark.parametrize("bad", [None, 3, 1.5, b"bytes", ["a"], {"a": 1}])
    def test_non_strings_are_rejected_not_coerced(self, model, bad):
        assert "not str" in (model.unscorable_reason(bad) or "")
        with pytest.raises(SentimentInputError):
            model.predict_many([bad])

    def test_one_bad_text_fails_the_whole_batch_loudly(self, model):
        with pytest.raises(SentimentInputError):
            model.predict_many([POS, ""])

    def test_scorable_text_has_no_reason(self, model):
        assert model.unscorable_reason(POS) is None

    def test_empty_batch_is_empty(self, model):
        assert model.predict_many([]) == []

    def test_fuzz_never_crashes_or_returns_invalid(self, model):
        rng = random.Random(5)
        alphabet = string.printable + "éÃ©�中😀"
        for _ in range(300):
            t = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
            if model.unscorable_reason(t):
                with pytest.raises(SentimentInputError):
                    model.predict(t)
            else:
                p = model.predict(t)
                assert abs(p.negative + p.neutral + p.positive - 1) < 1e-3


class TestArtifactIntegrity:
    def copy(self, tmp_path):
        d = tmp_path / "m"
        shutil.copytree(MODEL_DIR, d)
        return d

    def test_missing_files_fail_loudly_with_the_fix(self, tmp_path):
        with pytest.raises(ConfigError, match="make train-sentiment"):
            SentimentModel.load(tmp_path)

    def test_modified_artifact_is_refused(self, tmp_path):
        d = self.copy(tmp_path)
        with (d / "model.joblib").open("ab") as fh:
            fh.write(b"\0")
        with pytest.raises(ConfigError, match="does not match its model card"):
            SentimentModel.load(d)

    def test_wrong_scikit_learn_version_is_refused(self, tmp_path):
        d = self.copy(tmp_path)
        card = json.loads((d / CARD_FILE).read_text())
        card["libraries"]["scikit-learn"] = "0.0.1"
        (d / CARD_FILE).write_text(json.dumps(card))
        with pytest.raises(ConfigError, match="scikit-learn 0.0.1"):
            SentimentModel.load(d)

    def test_malformed_card_is_refused(self, tmp_path):
        d = self.copy(tmp_path)
        (d / CARD_FILE).write_text('{"id": "x"}')
        with pytest.raises(ConfigError, match="invalid sentiment model card"):
            SentimentModel.load(d)

    def test_card_describes_the_loaded_artifact(self, model):
        assert model.card.id == model.model_id and len(model.artifact_sha256) == 64
        ids = {e.id for e in model.card.evaluations}
        assert {"tfn_test", "phrasebank", "gold_history", "gold_tfn"} <= ids
        tfn = next(e for e in model.card.evaluations if e.id == "tfn_test")
        assert tfn.model is not None and tfn.model.macro_f1 > tfn.baselines["placeholder_lexicon"].macro_f1 + 0.1
        assert tfn.model.macro_f1 > tfn.baselines["majority_class"].macro_f1 + 0.3
