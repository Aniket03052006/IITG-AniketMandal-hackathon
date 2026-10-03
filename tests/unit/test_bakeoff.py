from __future__ import annotations

import numpy as np
import pytest

from eventshock.config import REPO_ROOT
from eventshock.modeling.event_eval import LABELS, NONE_IDX, UNCERTAIN_IDX, K
from eventshock.modeling.representations import bakeoff as B
from eventshock.modeling.representations import encoders as E
from eventshock.modeling.representations.corpus import LabelledSet, _set, pooled
from eventshock.modeling.representations.lexicon import Lexicon
from eventshock.pipeline.config import load_event_model_config
from eventshock.pipeline.event_model import EventModel

MODEL = EventModel.load(REPO_ROOT / load_event_model_config(REPO_ROOT / "configs").model_dir)


def test_served_labels_equal_the_production_decision_rule_row_by_row():
    rng = np.random.default_rng(0)
    probs = rng.dirichlet(np.full(K, 0.4), size=500)
    mine = B.served_labels(probs, frozenset(LABELS.index(c) for c in MODEL.unreliable))
    ev = {"CLASSIFIED": None, "NO_EVENT": NONE_IDX, "UNCERTAIN": UNCERTAIN_IDX}
    for p, got in zip(probs, mine, strict=True):
        status, top = MODEL.status_for(p)
        want = top if status.value == "CLASSIFIED" else ev[status.value]
        assert got == want


def test_precision_at_coverage_is_monotone_in_confidence_and_handles_full_coverage():
    rng = np.random.default_rng(1)
    y = rng.integers(0, K, 400)
    probs = np.full((400, K), 0.02)
    probs[np.arange(400), y] = 0.5
    wrong = rng.random(400) < 0.3
    probs[wrong, y[wrong]] = 0.02
    probs[wrong, (y[wrong] + 1) % K] = 0.4                      # wrong rows are less confident than right ones
    w = np.ones(400)
    lo, hi = B.precision_at_coverage(probs, y, w, 1.0), B.precision_at_coverage(probs, y, w, 0.5)
    assert hi > lo and hi == pytest.approx(1.0) and lo == pytest.approx(1 - wrong.mean(), abs=0.02)


def test_paired_bootstrap_detects_a_real_difference_and_not_a_null_one():
    rng = np.random.default_rng(2)
    y = rng.integers(0, 3, 600)
    good = np.where(rng.random(600) < 0.9, y, (y + 1) % 3)
    bad = np.where(rng.random(600) < 0.5, y, (y + 1) % 3)
    acc = lambda yy, p, w: float((w * (yy == p)).sum() / w.sum())  # noqa: E731
    pt, lo, hi = B.paired_bootstrap(acc, y, good, bad, np.ones(600), n=300)
    assert lo > 0.2 and pt > 0.3
    pt0, lo0, hi0 = B.paired_bootstrap(acc, y, good, good.copy(), np.ones(600), n=300)
    assert pt0 == 0 and lo0 == 0 and hi0 == 0


def test_pooled_weights_each_set_by_its_row_count_not_its_inclusion_scale():
    a = _set("a", ["x"] * 100, ["NONE"] * 100, [1000.0] * 50 + [1.0] * 50)
    b = _set("b", ["y"] * 20, ["NONE"] * 20)
    p = pooled({"a": a, "b": b}, ("a", "b"))
    assert p.n == 120 and p.w[:100].sum() == pytest.approx(100) and p.w[100:].sum() == pytest.approx(20)
    assert a.w[:50].min() > a.w[50:].max()                      # inclusion weights are kept within a set


def test_lexicon_matches_whole_words_and_phrases_only():
    lex = Lexicon({"upside": ["beat", "crushing earnings"], "risk": ["risk"]})
    assert lex.counts("Apple posts crushing earnings and a beat") == {"risk": 0, "upside": 2}
    assert lex.counts("a brisk beating") == {"risk": 0, "upside": 0}
    f = lex.features(["beat beat", "nothing here"])
    assert f.shape == (2, 3) and f[1].sum() == 0 and f[0, lex.names.index("upside")] > 0


def test_embedding_cache_round_trips_and_is_keyed_by_text(tmp_path):
    vecs = {E.text_key("hello"): np.arange(4, dtype=np.float32), E.text_key("world"): np.ones(4, dtype=np.float32)}
    E._save_cache("intfloat/multilingual-e5-small", vecs, {"ms_per_text": 1.0}, tmp_path)
    got = E.load_cache("intfloat/multilingual-e5-small", tmp_path)
    assert set(got) == set(vecs) and np.array_equal(got[E.text_key("hello")], vecs[E.text_key("hello")])
    assert E.load_cache("BAAI/bge-base-en-v1.5", tmp_path) == {}


def test_affect_specs_declare_label_orders_and_every_configured_model_is_registered():
    import yaml

    reg = yaml.safe_load((REPO_ROOT / "configs/evidence_v2.yaml").read_text())["representation"]
    for m in [*reg["dense_models"], *reg["affect_models"]]:
        assert m in E.SPECS, m
    assert E.SPECS["j-hartmann/emotion-english-distilroberta-base"].labels[2] == "fear" and len(E.SPECS["yiyanghkust/finbert-tone"].labels) == 3


def test_labelled_set_defaults():
    s = LabelledSet("s", ["t"], np.array([0]), np.array([1.0]))
    assert s.n == 1 and s.groups == []
