"""The trained sentiment model, serving side: load a verified artifact and turn text into calibrated class probabilities.

Training and evaluation live in ``eventshock.modeling.sentiment_train`` and import *this* module, so the text preparation
that fits the model is the very code that serves it (no train/serve skew). Nothing here fits anything.

Failure policy (nothing is invented):
* a missing, tampered or version-mismatched artifact raises ``ConfigError`` at start-up, never a silent fall-back;
* a text the model cannot score raises ``SentimentInputError``; the pipeline asks ``unscorable_reason`` first and
  quarantines such documents (``RejectCode.UNSCORABLE_TEXT``) instead of inventing a neutral score.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from ..config import ConfigError
from .normalize import clean_text, dedup_key
from .sentiment_card import SentimentModelCard

ARTIFACT_FILE = "model.joblib"
CARD_FILE = "model_card.json"
CLASSES = ("negative", "neutral", "positive")  # fixed order of every probability vector in this module
PRECISION = 4  # probabilities are rounded here so the replay digest does not depend on float noise across platforms

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION = re.compile(r"@\w+")
_CASHTAG = re.compile(r"\$[A-Za-z][A-Za-z.]{0,6}\b")
_NUMBER = re.compile(r"\d[\d.,]*")
_WS = re.compile(r"\s+")
_PLACEHOLDERS = re.compile(r"_(?:user|cashtag|num)_")
_WORD = re.compile(r"[^\W\d_]{2,}")


class SentimentInputError(ValueError):
    """The text cannot be scored (not a string, empty, or no usable words)."""


def prepare_text(text: str, mode: str) -> str:
    """Model input from raw text. ``normalised`` drops URLs and handles and turns tickers and numbers into tokens."""
    if mode == "raw":
        return text
    if mode != "normalised":
        raise ValueError(f"unknown preprocessing {mode!r}")
    t = unicodedata.normalize("NFKC", text)
    t = _URL.sub(" ", t)
    t = _MENTION.sub(" _user_ ", t)
    t = _CASHTAG.sub(" _cashtag_ ", t)
    t = _NUMBER.sub(" _num_ ", t)
    return _WS.sub(" ", t).strip()


def text_key(text: str) -> str:
    """Identity of a text for the "was this in the training data" check: the pipeline's own exact-duplicate key, hashed."""
    return hashlib.sha1(dedup_key(clean_text(text)).encode("utf-8")).hexdigest()[:16]  # noqa: S324 (identity, not security)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class SentimentPrediction:
    negative: float
    neutral: float
    positive: float
    confidence: float
    seen_in_training: bool

    @property
    def score(self) -> float:
        return round(self.positive - self.negative, PRECISION)


def _round_probs(neg: float, neu: float, pos: float) -> tuple[float, float, float]:
    """Round to PRECISION so that the three still sum to 1 (neutral takes the remainder) and score = pos - neg exactly."""
    p, n = round(pos, PRECISION), round(neg, PRECISION)
    return n, round(max(0.0, 1.0 - p - n), PRECISION), p


class SentimentModel:
    def __init__(self, card: SentimentModelCard, payload: dict[str, Any]) -> None:
        self.card = card
        self._pipe = payload["pipeline"]
        self._temperature: float = float(payload["temperature"])
        self._classes: list[str] = list(payload["classes"])
        self.preprocessing: str = payload["preprocessing"]
        self._train_keys: frozenset[str] = frozenset(payload["train_keys"])
        if self._classes != list(CLASSES):
            raise ConfigError(f"sentiment artifact has classes {self._classes}, expected {list(CLASSES)}")
        self.model_id = card.id
        self.model_version = card.version
        self.artifact_sha256 = card.artifact_sha256

    @classmethod
    def load(cls, model_dir: Path) -> SentimentModel:
        hint = "run `make train-sentiment` to rebuild it (needs data/modeling/sentiment.jsonl, see docs/SENTIMENT_MODEL.md)"
        card_path, art_path = model_dir / CARD_FILE, model_dir / ARTIFACT_FILE
        for p in (card_path, art_path):
            if not p.is_file():
                raise ConfigError(f"sentiment model file missing: {p}; {hint}")
        try:
            card = SentimentModelCard.model_validate_json(card_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConfigError(f"invalid sentiment model card {card_path}: {exc}") from exc
        actual = _file_sha256(art_path)
        if actual != card.artifact_sha256:
            raise ConfigError(f"sentiment artifact {art_path} does not match its model card (sha256 {actual[:12]} != "
                              f"{card.artifact_sha256[:12]}): the file was modified or replaced; {hint}")
        installed = metadata.version("scikit-learn")
        built = card.libraries.get("scikit-learn")
        if installed != built:
            raise ConfigError(f"sentiment artifact was built with scikit-learn {built}, installed is {installed}; "
                              f"install the pinned version from requirements.txt or {hint}")
        import joblib  # sha256 verified above, so the pickle is exactly the committed artifact

        return cls(card, joblib.load(art_path))

    # ------------------------------------------------------------------------------------------ inference
    def _features(self, texts: list[str]) -> Any:
        return self._pipe.named_steps["f"].transform([prepare_text(t, self.preprocessing) for t in texts])

    def _reason(self, text: object, row: Any = None) -> str | None:
        if not isinstance(text, str):
            return f"text is {type(text).__name__}, not str"
        prepared = prepare_text(text, self.preprocessing)
        if not prepared.strip():
            return "text is empty after preparation"
        if not _WORD.search(_PLACEHOLDERS.sub(" ", prepared)):
            return "text has no words (only links, handles, tickers or numbers)"
        if (row if row is not None else self._features([text])).nnz == 0:
            return "no feature of the text is known to the model"
        return None

    def unscorable_reason(self, text: object) -> str | None:
        """Why this text cannot be scored, or None."""
        return self._reason(text)

    def probabilities(self, texts: list[str]) -> Any:
        """Calibrated (n, 3) class probabilities in ``CLASSES`` order, unrounded. Raises ``SentimentInputError``."""
        import numpy as np

        if not texts:
            return np.zeros((0, len(CLASSES)))
        bad = [t for t in texts if not isinstance(t, str)]
        if bad:
            raise SentimentInputError(f"text is {type(bad[0]).__name__}, not str")
        x = self._features(texts)
        for i, t in enumerate(texts):
            reason = self._reason(t, x[i])
            if reason:
                raise SentimentInputError(reason)
        logits = self._pipe.named_steps["m"].decision_function(x) / self._temperature
        logits = logits - logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        return e / e.sum(axis=1, keepdims=True)

    def predict_many(self, texts: list[str]) -> list[SentimentPrediction]:
        probs = self.probabilities(texts)
        out = []
        for text, row in zip(texts, probs, strict=True):
            neg, neu, pos = _round_probs(float(row[0]), float(row[1]), float(row[2]))
            out.append(SentimentPrediction(neg, neu, pos, round(float(row.max()), PRECISION), text_key(text) in self._train_keys))
        return out

    def predict(self, text: str) -> SentimentPrediction:
        return self.predict_many([text])[0]
