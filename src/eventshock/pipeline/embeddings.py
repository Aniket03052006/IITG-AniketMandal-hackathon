"""Where a text's dense embedding comes from at serving time, without the product depending on torch.

The hybrid event model (``hybrid_event_model``) needs one frozen-encoder vector per text. Three sources, one protocol (``embed(texts) -> (n, dim) float32``):

* ``PinnedEmbeddings``: a hash-pinned ``.npz`` of vectors keyed by ``text_key(text)``, produced offline for the frozen replay pack
  (``scripts/build_replay_embeddings.py``). It makes the default ``make run`` fully offline and deterministic, with no torch installed.
* ``LiveEncoder``: the encoder itself (``transformers`` + ``torch``, the optional ``requirements-embed.txt``), imported lazily. Needed only for text that is
  not in the pack (a new document); absent torch is a clear error, never a silent substitute.
* ``ChainedEmbeddings``: pinned first, live for the rest.

Every vector is L2-normalised and **rounded to float16 precision** (``quantize``), here and in training, so a stored vector, a freshly encoded vector and the vector the
model was fitted and evaluated on are the same numbers.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

from ..config import ConfigError

MAX_TOKENS = 128


class EmbeddingUnavailable(ConfigError):
    """No source can produce a vector for this text (not pinned, and no encoder installed)."""


def text_key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]  # noqa: S324 (a cache key, not a security use)


def quantize(x: np.ndarray) -> np.ndarray:
    """float16 precision, float32 storage: the one numeric form every embedding takes."""
    return np.asarray(x, dtype=np.float16).astype(np.float32)


class EmbeddingSource(Protocol):
    dim: int

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class PinnedEmbeddings:
    """Vectors fixed in a file whose sha256 the loader checks."""

    def __init__(self, path: Path, *, sha256: str | None = None) -> None:
        if not path.is_file():
            raise ConfigError(f"pinned embeddings missing: {path}; rebuild with `make replay-embeddings`")
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if sha256 is not None and actual != sha256:
            raise ConfigError(f"pinned embeddings {path} do not match their pinned hash ({actual[:12]} != {sha256[:12]}): the file was modified")
        z = np.load(path, allow_pickle=False)
        self._index = {k: i for i, k in enumerate(z["keys"].tolist())}
        self._vectors = z["vectors"].astype(np.float32)
        self.dim = int(self._vectors.shape[1])
        self.sha256 = actual
        self.encoder = str(z["encoder"]) if "encoder" in z.files else ""

    def __len__(self) -> int:
        return len(self._index)

    def has(self, text: str) -> bool:
        return text_key(text) in self._index

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        missing = [t for t in texts if text_key(t) not in self._index]
        if missing:
            raise EmbeddingUnavailable(f"{len(missing)} text(s) are not in the pinned embeddings (first: {missing[0][:60]!r})")
        return self._vectors[[self._index[text_key(t)] for t in texts]]


def write_pinned(path: Path, vectors: dict[str, np.ndarray], *, encoder: str) -> str:
    """Write the pinned file deterministically (sorted keys, float16) and return its sha256."""
    keys = sorted(vectors)
    mat = np.stack([quantize(vectors[k]) for k in keys]).astype(np.float16)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, keys=np.array(keys), vectors=mat, encoder=np.array(encoder))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LiveEncoder:
    """The frozen encoder, loaded on first use. Mean pooling with the ``query: `` prefix for e5 models (the same code path as ``modeling.representations.encoders``)."""

    def __init__(self, name: str, *, dim: int, prefix: str = "query: ", pooling: str = "mean", batch: int = 32) -> None:
        self.name, self.dim, self.prefix, self.pooling, self.batch = name, dim, prefix, pooling, batch
        self._tok = self._model = None
        self._memo: dict[str, np.ndarray] = {}

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch  # noqa: F401
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise EmbeddingUnavailable(f"the encoder {self.name} needs torch and transformers (pip install -r requirements-embed.txt): {exc}") from exc
        try:
            self._tok = AutoTokenizer.from_pretrained(self.name, local_files_only=True)
            self._model = AutoModel.from_pretrained(self.name, local_files_only=True).eval()
        except (OSError, ValueError):
            self._tok = AutoTokenizer.from_pretrained(self.name, token=False)
            self._model = AutoModel.from_pretrained(self.name, token=False).eval()

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        todo = [t for t in dict.fromkeys(texts) if t not in self._memo]
        if todo:
            self._load()
            import torch

            with torch.no_grad():
                for s in range(0, len(todo), self.batch):
                    chunk = todo[s:s + self.batch]
                    enc = self._tok([self.prefix + t for t in chunk], padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")  # type: ignore[misc]
                    h = self._model(**enc).last_hidden_state  # type: ignore[misc]
                    if self.pooling == "cls":
                        v = h[:, 0]
                    else:
                        m = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
                        v = (h * m).sum(1) / m.sum(1).clamp(min=1)
                    v = torch.nn.functional.normalize(v, dim=1).numpy()
                    for t, vec in zip(chunk, v, strict=True):
                        self._memo[t] = quantize(vec)
        return np.stack([self._memo[t] for t in texts]) if texts else np.zeros((0, self.dim), dtype=np.float32)


class ChainedEmbeddings:
    """Pinned vectors where they exist, the live encoder for anything else (and a clear error if there is no encoder)."""

    def __init__(self, pinned: PinnedEmbeddings | None, live: LiveEncoder | None, dim: int) -> None:
        self.pinned, self.live, self.dim = pinned, live, dim

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        rest: list[int] = []
        for i, t in enumerate(texts):
            if self.pinned is not None and self.pinned.has(t):
                out[i] = self.pinned.embed([t])[0]
            else:
                rest.append(i)
        if rest:
            if self.live is None:
                raise EmbeddingUnavailable(f"{len(rest)} text(s) have no pinned embedding and no encoder is configured")
            out[rest] = self.live.embed([texts[i] for i in rest])
        return out


class DictEmbeddings:
    """In-memory vectors (training and tests): the cache of ``modeling.representations.encoders``, quantised."""

    def __init__(self, vectors: dict[str, np.ndarray], dim: int) -> None:
        self._v, self.dim = vectors, dim

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        missing = [t for t in texts if text_key(t) not in self._v]
        if missing:
            raise EmbeddingUnavailable(f"{len(missing)} text(s) are not embedded (first: {missing[0][:60]!r})")
        return quantize(np.stack([self._v[text_key(t)] for t in texts])) if texts else np.zeros((0, self.dim), dtype=np.float32)


__all__ = ["ChainedEmbeddings", "DictEmbeddings", "EmbeddingSource", "EmbeddingUnavailable", "LiveEncoder", "PinnedEmbeddings", "quantize", "text_key", "write_pinned"]
