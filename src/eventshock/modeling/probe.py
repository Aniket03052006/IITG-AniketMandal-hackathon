"""Audit probes: tiny, fast, classical baselines that answer "is this data learnable, and does a shortcut explain it?".

They are NOT the product models: no tuning beyond one regularisation choice on validation, nothing is saved, and the
numbers exist to set the bar the real models must clear. Needs the optional ``ml`` extra (numpy + scikit-learn).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.config import EnrichmentConfig
from ..pipeline.enrich import EnrichmentInput, PlaceholderEnricher
from .corpora import read_jsonl
from .leakage import spearman


def _need_ml():
    try:
        import numpy as np
        import sklearn  # noqa: F401
    except ImportError as exc:
        raise ConfigError("probe needs the optional ML extra: `uv pip install -r requirements-ml.txt`") from exc
    return np


def _text_model(c: float):
    from scipy.sparse import hstack  # noqa: F401  (scikit-learn depends on scipy)
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    feats = FeatureUnion([
        ("w", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, lowercase=True)),
        ("c", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, sublinear_tf=True, lowercase=True))])
    return Pipeline([("f", feats), ("m", LogisticRegression(C=c, max_iter=400, class_weight="balanced"))])


def _scores(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, f1_score

    labels = sorted(set(y_true))
    per = f1_score(y_true, y_pred, labels=labels, average=None, zero_division=0)
    return {"n": len(y_true), "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "macro_f1": round(float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
            "f1_per_class": {lab: round(float(f), 3) for lab, f in zip(labels, per, strict=True)}}


def _fit_choose_c(train, valid, label_key: str, grid=(0.3, 1.0, 3.0)):
    from sklearn.metrics import f1_score

    best = None
    for c in grid:
        m = _text_model(c).fit([r["text"] for r in train], [r[label_key] for r in train])
        f = f1_score([r[label_key] for r in valid], m.predict([r["text"] for r in valid]), average="macro", zero_division=0)
        if best is None or f > best[0]:
            best = (f, c, m)
    assert best is not None
    return best[2], best[1]


def probe_sentiment(modeling_dir: Path, enrichment_cfg: EnrichmentConfig) -> dict[str, Any]:
    rows = read_jsonl(modeling_dir / "sentiment.jsonl")
    tr, va, te = ([r for r in rows if r["split"] == s] for s in ("train", "valid", "test"))
    enr = PlaceholderEnricher(enrichment_cfg)

    def lexicon(t: str) -> str:
        s = enr.enrich(EnrichmentInput(t, None, 1)).sentiment.score
        return "positive" if s > 0.12 else "negative" if s < -0.12 else "neutral"

    majority = max({r["label"] for r in tr}, key=[r["label"] for r in tr].count)
    model, c = _fit_choose_c(tr, va, "label")
    out: dict[str, Any] = {"chosen_C": c, "train_rows": len(tr)}
    for name, part in (("valid", va), ("test", te)):
        y = [r["label"] for r in part]
        out[name] = {"majority": _scores(y, [majority] * len(y)), "placeholder_lexicon": _scores(y, [lexicon(r["text"]) for r in part]),
                     "tfidf_logreg": _scores(y, list(model.predict([r["text"] for r in part])))}
    # published split (exact duplicates removed only): near-duplicate leakage makes this optimistic
    ptr, pva = ([r for r in rows if r["published_split"] == s] for s in ("train", "valid"))
    pm = _text_model(c).fit([r["text"] for r in ptr], [r["label"] for r in ptr])
    out["published_valid_tfidf_logreg"] = _scores([r["label"] for r in pva], list(pm.predict([r["text"] for r in pva])))
    pb = modeling_dir / "phrasebank_eval.jsonl"
    if pb.exists():
        ev = read_jsonl(pb)
        y = [r["label"] for r in ev]
        out["phrasebank_eval_only"] = {"majority": _scores(y, [majority] * len(y)), "placeholder_lexicon": _scores(y, [lexicon(r["text"]) for r in ev]),
                                       "tfidf_logreg_trained_on_tfn": _scores(y, list(model.predict([r["text"] for r in ev])))}
    out["_model"] = model  # popped by the caller (used for the gold check), never serialised
    return out


def probe_event(modeling_dir: Path, enrichment_cfg: EnrichmentConfig) -> dict[str, Any]:
    rows = [r for r in read_jsonl(modeling_dir / "event_silver.jsonl") if r["train_eligible"]]
    tr, va, te = ([r for r in rows if r["split"] == s] for s in ("train", "valid", "test"))
    enr = PlaceholderEnricher(enrichment_cfg)
    majority = max({r["event_class"] for r in tr}, key=[r["event_class"] for r in tr].count)
    model, c = _fit_choose_c(tr, va, "event_class")
    out: dict[str, Any] = {"chosen_C": c, "train_rows": len(tr), "classes": sorted({r["event_class"] for r in tr})}
    for name, part in (("valid", va), ("test", te)):
        y = [r["event_class"] for r in part]
        out[name] = {"majority": _scores(y, [majority] * len(y)),
                     "placeholder_keywords": _scores(y, [enr.enrich(EnrichmentInput(r["text"], None, 1)).event.category.value for r in part]),
                     "tfidf_logreg": _scores(y, list(model.predict([r["text"] for r in part])))}
    allrows = [r for r in read_jsonl(modeling_dir / "event_silver.jsonl") if r["train_eligible"]]
    ptr, pva = ([r for r in allrows if r["published_split"] == s] for s in ("train", "valid"))
    pm = _text_model(c).fit([r["text"] for r in ptr], [r["event_class"] for r in ptr])
    out["published_valid_tfidf_logreg"] = _scores([r["event_class"] for r in pva], list(pm.predict([r["text"] for r in pva])))
    out["_model"] = model
    return out


def probe_impact(modeling_dir: Path) -> dict[str, Any]:
    np = _need_ml()
    from sklearn.ensemble import HistGradientBoostingRegressor

    rows = read_jsonl(modeling_dir / "impact_events.jsonl")
    feats = ["novelty", "link_confidence", "dow", "local_hour", "f_sigma_60", "f_beta_market", "f_beta_sector", "f_ret_1d", "f_ret_5d",
             "f_ret_20d", "f_mkt_ret_5d", "f_sector_ret_5d", "f_volume_ratio", "f_vix_level", "f_vix_chg_5d"]

    def mat(part):
        x = np.array([[r.get(f) if r.get(f) is not None else np.nan for f in feats] + [1.0 if r["source_type"] == "NEWS" else 0.0] for r in part], dtype=float)
        return x

    tr = [r for r in rows if r["split"] == "train"]
    out: dict[str, Any] = {"features": [*feats, "is_news"], "train_rows": len(tr), "target": "log1p(abs_z), episode-weighted", "splits": {}}
    for target in ("abs_z", "placebo_abs_z"):
        trt = [r for r in tr if r.get(target) is not None]
        m = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, random_state=0)
        m.fit(mat(trt), np.log1p([r[target] for r in trt]), sample_weight=[r["weight"] for r in trt])
        for split in ("val", "test", "live"):
            part = [r for r in rows if r["split"] == split and r.get(target) is not None]
            if len(part) < 20:
                continue
            pred = m.predict(mat(part))
            y = [r[target] for r in part]
            ranked = sorted(range(len(part)), key=lambda i: -pred[i])
            top = ranked[: max(1, len(part) // 10)]
            lift = (sum(y[i] for i in top) / len(top)) / (sum(y) / len(y))
            out["splits"].setdefault(split, {})[target] = {"n": len(part), "spearman": round(spearman(list(pred), y), 4), "top_decile_lift": round(lift, 3)}
    out["interpretation"] = ("compare with metadata_only_baseline in audit.json; skill on placebo_abs_z that rivals skill on abs_z would indicate leakage "
                             "or a regime/seasonality shortcut rather than event information")
    return out


def run_probe(modeling_dir: Path, enrichment_cfg: EnrichmentConfig, out_path: Path) -> dict[str, Any]:
    _need_ml()
    for need in ("sentiment.jsonl", "event_silver.jsonl", "impact_events.jsonl"):
        if not (modeling_dir / need).exists():
            raise ConfigError(f"{modeling_dir / need} missing: run `python -m eventshock.modeling audit` first")
    s = probe_sentiment(modeling_dir, enrichment_cfg)
    e = probe_event(modeling_dir, enrichment_cfg)
    models = {"sentiment": s.pop("_model"), "event": e.pop("_model")}
    res = {"sentiment": s, "event": e, "impact": probe_impact(modeling_dir),
           "note": "audit probes, not product models; see docs/notes/MODELING_READINESS.md"}
    res["_models"] = models  # for the gold check; stripped before writing
    clean = {k: v for k, v in res.items() if k != "_models"}
    atomic_write_text(out_path, json.dumps(clean, indent=1, sort_keys=True) + "\n")
    return res


__all__ = ["run_probe", "probe_sentiment", "probe_event", "probe_impact"]
