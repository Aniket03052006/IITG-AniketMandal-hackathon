"""The hybrid event model (keywords + semantics), serving side. Same contract as ``EventModel``, so the pipeline, the evaluation and the card do not change.

What it is: ``[TF-IDF (word + char n-grams) || alpha * frozen sentence embedding]`` -> one multinomial logistic regression -> temperature scaling -> the same fixed 0.5 commit
rule and unreliable-class routing as ``tfidf-lr-event-v1``. It was adopted by the pre-registered rule of ``configs/evidence_v2.yaml`` (see ``docs/notes/EVIDENCE_V2.md``): early fusion beat the
TF-IDF model on every held-out set and on the pooled set with semantic near-duplicates of training text removed, while dense vectors alone and late fusion did not.

What is different at serving time: a text needs a vector. ``embeddings`` supplies it (pinned for the frozen replay pack, the live encoder otherwise, or a clear
``EmbeddingUnavailable``). Whether a text can be scored at all is decided from its TF-IDF part alone, exactly as in v1, so the quarantine set never depends on an encoder.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix, hstack

from ..config import ConfigError
from .embeddings import EmbeddingSource
from .event_card import EventModelCard
from .event_model import ARTIFACT_FILE, CARD_FILE, CLASSES, EVENT_CLASSES, EventInputError, EventModel
from .sentiment_model import _PLACEHOLDERS, _WORD, _file_sha256, prepare_text

KIND = "hybrid-event"


class HybridEventModel(EventModel):
    def __init__(self, card: EventModelCard, payload: dict[str, Any], embeddings: EmbeddingSource) -> None:  # noqa: D107 (parent contract)
        if payload.get("kind") != KIND:
            raise ConfigError(f"artifact kind {payload.get('kind')!r} is not {KIND!r}")
        self.card = card
        self._tfidf = payload["tfidf"]
        self._lr = payload["lr"]
        self.alpha: float = float(payload["alpha"])
        self._temperature = float(payload["temperature"])
        self._classes = list(payload["classes"])
        self.preprocessing = payload["preprocessing"]
        self._train_keys = frozenset(payload["train_keys"])
        self.commit_threshold = float(payload["commit_threshold"])
        self.unreliable = frozenset(payload["unreliable"])
        self.route_unreliable = bool(payload["route_unreliable"])
        self.encoder: dict[str, Any] = dict(payload["encoder"])
        self.embeddings = embeddings
        if self._classes != list(CLASSES):
            raise ConfigError(f"hybrid artifact has classes {self._classes}, expected {list(CLASSES)}")
        fitted = [str(c) for c in self._lr.classes_]
        if sorted(fitted) != sorted(CLASSES):
            raise ConfigError(f"hybrid classifier was fitted on {fitted}, expected the nine classes {list(CLASSES)}")
        self._order = [fitted.index(c) for c in CLASSES]
        if not 0 < self.commit_threshold < 1:
            raise ConfigError("hybrid artifact commit_threshold must lie strictly between 0 and 1")
        if not self.unreliable <= set(EVENT_CLASSES):
            raise ConfigError(f"hybrid artifact flags unknown classes as unreliable: {sorted(self.unreliable - set(EVENT_CLASSES))}")
        if embeddings.dim != int(self.encoder["dim"]):
            raise ConfigError(f"embedding source has dimension {embeddings.dim}, the model was fitted on {self.encoder['dim']}")
        self.model_id = card.id
        self.model_version = card.version
        self.artifact_sha256 = card.artifact_sha256

    @classmethod
    def load(cls, model_dir: Path, embeddings: EmbeddingSource | None = None) -> HybridEventModel:  # type: ignore[override]
        hint = "run `make train-event-hybrid` to rebuild it (needs data/modeling/embeddings, see docs/notes/EVIDENCE_V2.md)"
        card_path, art_path = model_dir / CARD_FILE, model_dir / ARTIFACT_FILE
        for p in (card_path, art_path):
            if not p.is_file():
                raise ConfigError(f"hybrid event model file missing: {p}; {hint}")
        try:
            card = EventModelCard.model_validate_json(card_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConfigError(f"invalid event model card {card_path}: {exc}") from exc
        actual = _file_sha256(art_path)
        if actual != card.artifact_sha256:
            raise ConfigError(f"hybrid artifact {art_path} does not match its model card (sha256 {actual[:12]} != {card.artifact_sha256[:12]}): "
                              f"the file was modified or replaced; {hint}")
        installed, built = metadata.version("scikit-learn"), card.libraries.get("scikit-learn")
        if installed != built:
            raise ConfigError(f"hybrid artifact was built with scikit-learn {built}, installed is {installed}; install the pinned version or {hint}")
        import joblib  # sha256 verified above

        payload = joblib.load(art_path)
        if embeddings is None:
            raise ConfigError("a hybrid event model needs an embedding source (pinned vectors and/or an encoder)")
        return cls(card, payload, embeddings)

    # ------------------------------------------------------------------------------------------ inference
    def _tfidf_features(self, texts: list[str]) -> Any:
        return self._tfidf.transform([prepare_text(t, self.preprocessing) for t in texts])

    def _features(self, texts: list[str]) -> Any:
        x = self._tfidf_features(texts)
        return hstack([x, csr_matrix(self.alpha * self.embeddings.embed(texts))]).tocsr()

    def _reason(self, text: object, row: Any = None) -> str | None:
        """Scorable or not from the TF-IDF part only (never calls the encoder): identical to ``EventModel`` for the same vectoriser."""
        if not isinstance(text, str):
            return f"text is {type(text).__name__}, not str"
        prepared = prepare_text(text, self.preprocessing)
        if not prepared.strip():
            return "text is empty after preparation"
        if not _WORD.search(_PLACEHOLDERS.sub(" ", prepared)):
            return "text has no words (only links, handles, tickers or numbers)"
        if (row if row is not None else self._tfidf_features([text])).nnz == 0:
            return "no feature of the text is known to the event model"
        return None

    def unscorable_reasons(self, texts: list[str]) -> list[str | None]:
        if not texts:
            return []
        good = [i for i, t in enumerate(texts) if isinstance(t, str)]
        out: list[str | None] = [f"text is {type(t).__name__}, not str" if not isinstance(t, str) else None for t in texts]
        if good:
            x = self._tfidf_features([texts[i] for i in good])
            for k, i in enumerate(good):
                out[i] = self._reason(texts[i], x[k])
        return out

    def logits(self, x: Any) -> Any:
        return self._lr.decision_function(x)[:, self._order]

    def probabilities(self, texts: list[str]) -> Any:
        if not texts:
            return np.zeros((0, len(CLASSES)))
        bad = [t for t in texts if not isinstance(t, str)]
        if bad:
            raise EventInputError(f"text is {type(bad[0]).__name__}, not str")
        xt = self._tfidf_features(texts)
        for i, t in enumerate(texts):
            reason = self._reason(t, xt[i])
            if reason:
                raise EventInputError(reason)
        x = hstack([xt, csr_matrix(self.alpha * self.embeddings.embed(texts))]).tocsr()
        z = self.logits(x) / self._temperature
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)


def load_event_model(model_dir: Path, embeddings: EmbeddingSource | None = None) -> EventModel:
    """The right class for an artifact directory: hybrid when its payload says so, the TF-IDF ``EventModel`` otherwise."""
    art = model_dir / ARTIFACT_FILE
    if not art.is_file():
        return EventModel.load(model_dir)  # raises the standard "file missing" error
    card_path = model_dir / CARD_FILE
    if card_path.is_file() and '"hybrid-event' in card_path.read_text(encoding="utf-8")[:4000]:
        return HybridEventModel.load(model_dir, embeddings)
    return EventModel.load(model_dir)
