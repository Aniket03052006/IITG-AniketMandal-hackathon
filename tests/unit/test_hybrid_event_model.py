"""The hybrid event model: same contract as EventModel, vectors from pinned/live/in-memory sources, a missing encoder is a loud error, never a silent substitute."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from eventshock.config import REPO_ROOT, ConfigError
from eventshock.pipeline import embeddings as E
from eventshock.pipeline.event_model import CLASSES, EventInputError, EventModel
from eventshock.pipeline.hybrid_event_model import KIND, HybridEventModel, load_event_model

V1 = REPO_ROOT / "models/event/tfidf-lr-event-v1"
DIM = 8


def vec(text: str) -> np.ndarray:
    """A deterministic fake 'encoder': a unit vector derived from the text (the real one is exercised by the bake-off)."""
    h = hashlib.sha256(text.encode()).digest()
    v = np.frombuffer(h[: DIM * 2], dtype=np.uint16).astype(np.float32) - 32768
    return E.quantize(v / np.linalg.norm(v))


TEXTS = ["Tesla recalls 300,000 vehicles over a brake defect", "Fed holds rates steady and signals two cuts", "Pfizer beats EPS estimates and raises guidance",
         "Nice chart, bullish on $AAPL!!!", "Moody's downgrades the bank to junk after a funding squeeze"]


def toy_model(tmp_path, *, unreliable=("MA_CORPORATE_ACTION",)):
    """A hybrid built from the shipped TF-IDF featurizer and a classifier trained on fake vectors: enough to test every code path of the class."""
    import joblib
    from scipy.sparse import csr_matrix, hstack
    from sklearn.linear_model import LogisticRegression

    v1 = EventModel.load(V1)
    f = v1._pipe.named_steps["f"]  # noqa: SLF001
    rng = np.random.default_rng(0)
    texts = [f"{t} variant {i}" for t in TEXTS for i in range(20)]
    y = np.array([CLASSES[i % len(CLASSES)] for i in range(len(texts))])
    X = hstack([f.transform(texts), csr_matrix(2.0 * np.stack([vec(t) for t in texts]))]).tocsr()
    lr = LogisticRegression(C=10, max_iter=2000).fit(X, y)
    art = tmp_path / "model.joblib"
    joblib.dump({"kind": KIND, "tfidf": f, "lr": lr, "alpha": 2.0, "temperature": 1.0, "classes": list(CLASSES), "preprocessing": v1.preprocessing,
                 "train_keys": [], "commit_threshold": 0.5, "unreliable": list(unreliable), "route_unreliable": True,
                 "encoder": {"name": "fake", "dim": DIM, "prefix": "", "pooling": "mean", "max_tokens": 128, "precision": "float16"}}, art)
    card = json.loads((V1 / "model_card.json").read_text())
    card.update({"id": "hybrid-event-v2", "version": "hybrid-event-v2", "artifact_sha256": hashlib.sha256(art.read_bytes()).hexdigest()})
    (tmp_path / "model_card.json").write_text(json.dumps(card))
    return tmp_path, rng


def memory_source():
    return E.DictEmbeddings({E.text_key(t): vec(t) for t in TEXTS}, DIM)


def test_pinned_file_round_trips_quantised_and_is_hash_checked(tmp_path):
    vecs = {E.text_key(t): vec(t) for t in TEXTS}
    path = tmp_path / "pins.npz"
    sha = E.write_pinned(path, vecs, encoder="fake")
    p = E.PinnedEmbeddings(path, sha256=sha)
    got = p.embed(TEXTS)
    assert got.dtype == np.float32 and np.array_equal(got, np.stack([vec(t) for t in TEXTS])) and p.dim == DIM and len(p) == 5 and p.encoder == "fake"
    assert E.write_pinned(tmp_path / "again.npz", vecs, encoder="fake") == sha            # deterministic bytes
    with pytest.raises(ConfigError, match="pinned hash"):
        E.PinnedEmbeddings(path, sha256="0" * 64)
    with pytest.raises(E.EmbeddingUnavailable, match="not in the pinned"):
        p.embed(["never embedded"])


def test_quantize_is_idempotent_and_float16_exact():
    x = np.random.default_rng(1).normal(size=64).astype(np.float32)
    q = E.quantize(x)
    assert np.array_equal(E.quantize(q), q) and np.array_equal(q, x.astype(np.float16).astype(np.float32))


def test_chained_source_uses_pins_first_and_fails_loudly_without_an_encoder(tmp_path):
    p = E.PinnedEmbeddings(tmp_path / "p.npz", sha256=E.write_pinned(tmp_path / "p.npz", {E.text_key(TEXTS[0]): vec(TEXTS[0])}, encoder="fake"))
    chain = E.ChainedEmbeddings(p, None, DIM)
    assert np.array_equal(chain.embed([TEXTS[0]])[0], vec(TEXTS[0]))
    with pytest.raises(E.EmbeddingUnavailable, match="no pinned embedding and no encoder"):
        chain.embed([TEXTS[0], "something new"])
    assert chain.embed([]).shape == (0, DIM)


def test_live_encoder_without_torch_is_a_clear_error_not_a_substitute(monkeypatch):
    import builtins

    real = builtins.__import__

    def no_torch(name, *a, **k):
        if name in ("torch", "transformers"):
            raise ImportError("no torch here")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_torch)
    with pytest.raises(E.EmbeddingUnavailable, match="requirements-embed.txt"):
        E.LiveEncoder("intfloat/multilingual-e5-large", dim=1024).embed(["x"])


def test_hybrid_has_the_event_model_contract(tmp_path):
    d, _ = toy_model(tmp_path)
    m = HybridEventModel.load(d, memory_source())
    assert isinstance(m, EventModel) and m.model_id == "hybrid-event-v2"
    p = m.probabilities(TEXTS)
    assert p.shape == (5, len(CLASSES)) and np.allclose(p.sum(axis=1), 1.0)
    decisions = m.decide_many(TEXTS)
    assert len(decisions) == 5 and all(abs(sum(x.probabilities.values()) - 1) < 2e-3 for x in decisions)
    st, top = m.status_for(p[0])
    assert st.value in {"CLASSIFIED", "NO_EVENT", "UNCERTAIN"} and 0 <= top < 8
    assert np.array_equal(p, m.probabilities(TEXTS))                                    # deterministic


def test_scorability_never_touches_the_encoder_and_matches_tfidf_exactly(tmp_path):
    d, _ = toy_model(tmp_path)
    m = HybridEventModel.load(d, E.DictEmbeddings({}, DIM))                              # an EMPTY source: any embedding request would fail
    v1 = EventModel.load(V1)
    samples = ["", "   ", "https://t.co/abc @user $TSLA", "12345", "Boeing grounds the fleet", "zzzzqqqq xxxxyyyy"]
    assert m.unscorable_reasons(samples) == v1.unscorable_reasons(samples)
    assert [m.unscorable_reason(s) for s in samples] == [v1.unscorable_reason(s) for s in samples]
    with pytest.raises(EventInputError):
        m.probabilities(["https://t.co/abc"])
    assert m.unscorable_reason(7) is not None


def test_a_missing_vector_for_a_scorable_text_is_a_loud_error(tmp_path):
    d, _ = toy_model(tmp_path)
    m = HybridEventModel.load(d, memory_source())
    with pytest.raises(E.EmbeddingUnavailable):
        m.probabilities(["Airline cancels flights after a strike"])


def test_loader_rejects_tampering_dimension_mismatch_and_a_missing_source(tmp_path):
    d, _ = toy_model(tmp_path)
    with pytest.raises(ConfigError, match="embedding source"):
        HybridEventModel.load(d, None)
    with pytest.raises(ConfigError, match="dimension"):
        HybridEventModel.load(d, E.DictEmbeddings({}, DIM + 1))
    (d / "model.joblib").write_bytes((d / "model.joblib").read_bytes() + b"x")
    with pytest.raises(ConfigError, match="does not match its model card"):
        HybridEventModel.load(d, memory_source())


def test_factory_picks_the_class_from_the_card_and_never_loads_a_hybrid_without_vectors(tmp_path):
    d, _ = toy_model(tmp_path)
    assert isinstance(load_event_model(d, memory_source()), HybridEventModel)
    assert type(load_event_model(V1)) is EventModel
    with pytest.raises(ConfigError):
        load_event_model(d, None)
