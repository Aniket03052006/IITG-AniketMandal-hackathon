"""The trained event model, serving side: load a verified artifact and turn text into a calibrated event decision.

Training and evaluation live in ``eventshock.modeling.event_train`` and import *this* module, so the text preparation and the
decision rule that are evaluated are the very code that serves (no train/serve skew). Nothing here fits anything.

What the model says about a text (``decide``):
* it scores nine classes: the eight taxonomy categories and ``NONE`` (not a market event: chatter, promotion, opinion, a notice);
* the arg-max of the calibrated nine-class posterior is committed only when its probability reaches ``commit_threshold``
  (0.5: "more likely than not", meaningful because the probabilities are calibrated; not tuned);
* ``NO_EVENT``   when the committed class is ``NONE``;
* ``CLASSIFIED`` when it is one of the eight event classes, unless the model card flags that class unreliable (never asserted:
  the card says why), in which case the document is ``UNCERTAIN``;
* ``UNCERTAIN``  when nothing reaches the threshold.

Failure policy (nothing is invented), same as the sentiment model:
* a missing, tampered or version-mismatched artifact raises ``ConfigError`` at start-up, never a silent fall-back;
* a text the model cannot score raises ``EventInputError``; the pipeline asks ``unscorable_reason`` first and quarantines it.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..domain import EventCategory, EventStatus
from .event_card import EventModelCard
from .sentiment_model import (
    _PLACEHOLDERS,
    _WORD,
    PRECISION,
    _file_sha256,
    prepare_text,
    text_key,
)

ARTIFACT_FILE = "model.joblib"
CARD_FILE = "model_card.json"
EVENT_CLASSES = tuple(c.value for c in EventCategory)
NONE_CLASS = "NONE"
CLASSES = (*EVENT_CLASSES, NONE_CLASS)  # fixed order of every probability vector in this module


class EventInputError(ValueError):
    """The text cannot be scored (not a string, empty, or no usable words)."""


@dataclass(frozen=True)
class EventDecision:
    category: EventCategory  # arg-max event class: a best guess, a finding only when status is CLASSIFIED
    probabilities: dict[EventCategory, float]  # P(class | event), rounded, sums to 1, arg-max is `category`
    no_event_probability: float
    status: EventStatus
    confidence: float  # calibrated P(category) among all nine classes: the chance this exact label is right
    unreliable_class: bool
    seen_in_training: bool


def _round_event_probs(cond: list[float]) -> dict[EventCategory, float]:
    """Round to PRECISION so the eight still sum to 1 (the arg-max class takes the remainder) and the arg-max survives rounding."""
    cats = list(EventCategory)
    top = max(range(len(cats)), key=lambda i: (cond[i], -i))
    out = {c: round(p, PRECISION) for c, p in zip(cats, cond, strict=True)}
    rest = sum(v for c, v in out.items() if c is not cats[top])
    out[cats[top]] = round(max(0.0, 1.0 - rest), PRECISION)
    rival = max(v for c, v in out.items() if c is not cats[top])
    if out[cats[top]] <= rival:  # rounding noise (<= 4e-4 in total) must never move the arg-max; the contract allows 1e-3 on the sum
        out[cats[top]] = round(rival + 10 ** -PRECISION, PRECISION)
    return out


class EventModel:
    def __init__(self, card: EventModelCard, payload: dict[str, Any]) -> None:
        self.card = card
        self._pipe = payload["pipeline"]
        self._temperature: float = float(payload["temperature"])
        self._classes: list[str] = list(payload["classes"])
        self.preprocessing: str = payload["preprocessing"]
        self._train_keys: frozenset[str] = frozenset(payload["train_keys"])
        self.commit_threshold: float = float(payload["commit_threshold"])
        self.unreliable: frozenset[str] = frozenset(payload["unreliable"])
        self.route_unreliable: bool = bool(payload["route_unreliable"])
        if self._classes != list(CLASSES):
            raise ConfigError(f"event artifact has classes {self._classes}, expected {list(CLASSES)}")
        fitted = [str(c) for c in self._pipe.named_steps["m"].classes_]
        if sorted(fitted) != sorted(CLASSES):
            raise ConfigError(f"event classifier was fitted on {fitted}, expected the nine classes {list(CLASSES)}")
        self._order = [fitted.index(c) for c in CLASSES]  # scikit-learn sorts classes alphabetically; ours have a fixed order
        if not 0 < self.commit_threshold < 1:
            raise ConfigError("event artifact commit_threshold must lie strictly between 0 and 1")
        if not self.unreliable <= set(EVENT_CLASSES):
            raise ConfigError(f"event artifact flags unknown classes as unreliable: {sorted(self.unreliable - set(EVENT_CLASSES))}")
        self.model_id = card.id
        self.model_version = card.version
        self.artifact_sha256 = card.artifact_sha256

    @classmethod
    def load(cls, model_dir: Path) -> EventModel:
        hint = "run `make train-event` to rebuild it (needs data/modeling/event_train.jsonl, see docs/EVENT_MODEL.md)"
        card_path, art_path = model_dir / CARD_FILE, model_dir / ARTIFACT_FILE
        for p in (card_path, art_path):
            if not p.is_file():
                raise ConfigError(f"event model file missing: {p}; {hint}")
        try:
            card = EventModelCard.model_validate_json(card_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConfigError(f"invalid event model card {card_path}: {exc}") from exc
        actual = _file_sha256(art_path)
        if actual != card.artifact_sha256:
            raise ConfigError(f"event artifact {art_path} does not match its model card (sha256 {actual[:12]} != "
                              f"{card.artifact_sha256[:12]}): the file was modified or replaced; {hint}")
        installed = metadata.version("scikit-learn")
        built = card.libraries.get("scikit-learn")
        if installed != built:
            raise ConfigError(f"event artifact was built with scikit-learn {built}, installed is {installed}; "
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
            return "no feature of the text is known to the event model"
        return None

    def unscorable_reason(self, text: object) -> str | None:
        """Why this text cannot be scored, or None."""
        return self._reason(text)

    def logits(self, x: Any) -> Any:
        """Uncalibrated decision values of a feature matrix, columns in ``CLASSES`` order."""
        return self._pipe.named_steps["m"].decision_function(x)[:, self._order]

    def probabilities(self, texts: list[str]) -> Any:
        """Calibrated (n, 9) class probabilities in ``CLASSES`` order, unrounded. Raises ``EventInputError``."""
        import numpy as np

        if not texts:
            return np.zeros((0, len(CLASSES)))
        bad = [t for t in texts if not isinstance(t, str)]
        if bad:
            raise EventInputError(f"text is {type(bad[0]).__name__}, not str")
        x = self._features(texts)
        for i, t in enumerate(texts):
            reason = self._reason(t, x[i])
            if reason:
                raise EventInputError(reason)
        logits = self.logits(x) / self._temperature
        logits = logits - logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        return e / e.sum(axis=1, keepdims=True)

    def status_for(self, p: Any) -> tuple[EventStatus, int]:
        """The served status of one probability row, and the index of its arg-max event class. The single decision rule."""
        ev = [float(v) for v in p[: len(EVENT_CLASSES)]]
        top = max(range(len(ev)), key=lambda i: (ev[i], -i))
        p_none = float(p[CLASSES.index(NONE_CLASS)])
        if p_none >= ev[top]:  # the nine-class arg-max is NONE (ties go to NONE)
            return (EventStatus.NO_EVENT if p_none >= self.commit_threshold else EventStatus.UNCERTAIN), top
        if ev[top] < self.commit_threshold or (self.route_unreliable and EVENT_CLASSES[top] in self.unreliable):
            return EventStatus.UNCERTAIN, top
        return EventStatus.CLASSIFIED, top

    def decide_many(self, texts: list[str]) -> list[EventDecision]:
        probs = self.probabilities(texts)
        out = []
        for text, row in zip(texts, probs, strict=True):
            status, top = self.status_for(row)
            ev = [float(v) for v in row[: len(EVENT_CLASSES)]]
            total = sum(ev)
            cond = [v / total for v in ev] if total > 0 else [1.0 / len(ev)] * len(ev)
            rounded = _round_event_probs(cond)
            cat = EventCategory(EVENT_CLASSES[top])
            out.append(EventDecision(
                category=cat, probabilities=rounded, no_event_probability=round(float(row[CLASSES.index(NONE_CLASS)]), PRECISION),
                status=status, confidence=round(ev[top], PRECISION), unreliable_class=cat.value in self.unreliable,
                seen_in_training=text_key(text) in self._train_keys))
        return out

    def decide(self, text: str) -> EventDecision:
        return self.decide_many([text])[0]
