"""Do richer language representations beat the shipped TF-IDF models on the SAME protocol? (main venv; reads the .npy files)

Rules fixed before looking at any number:
* EVENT. Frozen encoder -> multinomial logistic regression on the same annotated train rows; C and class_weight chosen by dev log-loss
  after one-parameter temperature scaling (the production selection rule); the shipped tfidf-lr-event-v1 is scored on the very same
  dev rows. Adopt only if it beats TF-IDF on dev log-loss AND its served macro-F1 on the gold history rows has a paired bootstrap
  interval of the difference entirely above zero. The gold set is read once, never selected on.
* IMPACT. Ridge on [market-state features + text representation] vs ridge on market-state alone, fitted on train episodes, alpha chosen on the last
  fifth of the TRAIN period, scored on 2022 val+test and on 2026 live news. Adopt only if the paired MAE improvement over the state-only
  ridge has an interval entirely below zero on val+test AND the rank correlation does not fall on the placebo window.
Writes docs/evidence/embedding_experiment.json.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.linear_model import LogisticRegression, Ridge  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from eventshock.modeling import impact_train as T  # noqa: E402
from eventshock.modeling.event_eval import LABELS, NONE_IDX, K, gold_event_sets  # noqa: E402
from eventshock.modeling.impact_dataset import load_table  # noqa: E402
from eventshock.modeling.impact_stats import (  # noqa: E402
    boot_indices,
    delta_mae_estimate,
    make_view,
    spearman,
    spearman_estimate,
)
from eventshock.modeling.sentiment_train import fit_temperature, nll, softmax  # noqa: E402
from eventshock.pipeline.config import load_event_model_config, load_impact_model_config  # noqa: E402
from eventshock.pipeline.event_model import EventModel  # noqa: E402

MODELS = ["intfloat__multilingual-e5-small", "intfloat__multilingual-e5-base", "ProsusAI__finbert"]
COMMIT = 0.5


def key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]  # noqa: S324


def load_emb(d: Path, slug: str) -> dict[str, np.ndarray]:
    keys = json.loads((d / "keys.json").read_text())
    x = np.load(d / f"{slug}.npy")
    return {k: x[i] for i, k in enumerate(keys)}


# ------------------------------------------------------------------------------------------------------------ event
def served(probs: np.ndarray) -> np.ndarray:
    """The production decision rule on a nine-class posterior -> served label index, or -1 for UNCERTAIN."""
    out = np.full(len(probs), -1)
    for i, p in enumerate(probs):
        top = int(np.argmax(p[:8]))
        if p[NONE_IDX] >= p[top]:
            out[i] = NONE_IDX if p[NONE_IDX] >= COMMIT else -1
        elif p[top] >= COMMIT:
            out[i] = top
    return out


def macro_f1(y: np.ndarray, pred: np.ndarray, w: np.ndarray) -> float:
    f = []
    for c in range(K):
        if not (y == c).any():
            continue
        tp = w[(y == c) & (pred == c)].sum()
        fp = w[(y != c) & (pred == c)].sum()
        fn = w[(y == c) & (pred != c)].sum()
        f.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f))


def detect_f1(y: np.ndarray, pred: np.ndarray, w: np.ndarray) -> float:
    tr, pe = y != NONE_IDX, (pred != NONE_IDX) & (pred != -1) | (pred == -1)  # UNCERTAIN counts as "an event" (not NONE)
    tp, fp, fn = w[tr & pe].sum(), w[~tr & pe].sum(), w[tr & ~pe].sum()
    return 0.0 if tp == 0 else float(2 * tp / (2 * tp + fp + fn))


def paired_boot(stat, y, p_a, p_b, w, n=1000, seed=3):
    rng = np.random.default_rng(seed)
    pr = w / w.sum()
    d = []
    for _ in range(n):
        i = rng.choice(len(y), len(y), p=pr)
        ones = np.ones(len(i))
        d.append(stat(y[i], p_a[i], ones) - stat(y[i], p_b[i], ones))
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def event_experiment(emb_dir: Path) -> dict:
    cfg = load_event_model_config(ROOT / "configs")
    prod = EventModel.load(ROOT / cfg.model_dir)
    rows = [json.loads(x) for x in (ROOT / cfg.table).read_text(encoding="utf-8").split("\n") if x.strip()]
    tr = [r for r in rows if r["split"] == "train" and r["kind"] == "annotated"]
    dev = [r for r in rows if r["split"] == "dev" and prod.unscorable_reason(r["text"]) is None]
    lab = {c: i for i, c in enumerate(LABELS)}
    ytr, ydev = np.array([lab[r["label"]] for r in tr]), np.array([lab[r["label"]] for r in dev])
    g = gold_event_sets(ROOT / "data/gold")["history"]
    gt, gy, gw = g[0], np.array([lab[c] for c in g[1]]), np.array(g[2])
    out: dict = {"train_rows": len(tr), "dev_rows": len(dev), "gold_history_rows": len(gt)}
    p_dev_t = prod.probabilities([r["text"] for r in dev])
    p_gold_t = prod.probabilities(gt)
    out["tfidf-lr-event-v1"] = {"dev_log_loss": round(nll(p_dev_t, ydev), 4),
                                "gold_served_macro_f1": round(macro_f1(gy, served(p_gold_t), gw), 4),
                                "gold_detection_f1": round(detect_f1(gy, served(p_gold_t), gw), 4)}
    for slug in MODELS:
        if not (emb_dir / f"{slug}.npy").is_file():
            continue
        e = load_emb(emb_dir, slug)
        xtr = np.stack([e[key(r["text"])] for r in tr])
        xdev = np.stack([e[key(r["text"])] for r in dev])
        xg = np.stack([e[key(t)] for t in gt])
        best = None
        for C in (0.3, 1, 3, 10, 30):
            for cw in (None, "balanced"):
                m = LogisticRegression(C=C, class_weight=cw, max_iter=3000)
                m.fit(xtr, ytr)
                order = [list(m.classes_).index(c) for c in range(K) if c in m.classes_]
                if len(order) != K:
                    continue
                z = m.decision_function(xdev)[:, order]
                T_ = fit_temperature(z, ydev, cfg.temperature_grid)
                ll = nll(softmax(z, T_), ydev)
                if best is None or ll < best[0]:
                    best = (ll, C, cw, T_, m, order)
        ll, C, cw, T_, m, order = best
        pg = softmax(m.decision_function(xg)[:, order], T_)
        sv_e, sv_t = served(pg), served(p_gold_t)
        lo, hi = paired_boot(lambda y, p, w: macro_f1(y, p, w), gy, sv_e, sv_t, gw)
        dlo, dhi = paired_boot(lambda y, p, w: detect_f1(y, p, w), gy, sv_e, sv_t, gw)
        out[slug] = {"C": C, "class_weight": cw, "temperature": T_, "dev_log_loss": round(ll, 4),
                     "gold_served_macro_f1": round(macro_f1(gy, sv_e, gw), 4), "gold_detection_f1": round(detect_f1(gy, sv_e, gw), 4),
                     "served_macro_f1_minus_tfidf_95ci": [round(lo, 4), round(hi, 4)], "detection_f1_minus_tfidf_95ci": [round(dlo, 4), round(dhi, 4)],
                     "adopt": bool(ll < out["tfidf-lr-event-v1"]["dev_log_loss"] and lo > 0)}
        print("event", slug, out[slug], flush=True)
    return out


# ------------------------------------------------------------------------------------------------------------ impact
def impact_experiment(emb_dir: Path) -> dict:
    cfg = load_impact_model_config(ROOT / "configs")
    rows = load_table(ROOT / cfg.table)
    res: dict = {}
    for scope in ("ISSUER", "MARKET"):
        fr = T.load_frame(rows, scope)
        _, first = np.unique(fr.ep, return_index=True)
        first = np.sort(first)
        txt = [fr.texts[i] for i in first]
        split = fr.split[first]
        cols = fr.cols(T.feature_names(scope, "R2"))
        X = fr.X[np.ix_(first, cols)]
        y, absz, placebo, score = fr.y[first], fr.absz[first], fr.placebo[first], fr.score[first]
        dates = fr.date[first]
        tr = np.flatnonzero(split == "train")
        cut = np.sort(dates[tr])[int(0.8 * len(tr))]
        fit_idx, tune_idx = tr[dates[tr] < cut], tr[dates[tr] >= cut]
        imp, sc = SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler()
        sc.fit(imp.fit_transform(X[tr]))
        S = sc.transform(imp.transform(X))
        reps: dict[str, np.ndarray] = {"state-only": np.zeros((len(first), 0))}
        tf = TfidfVectorizer(ngram_range=(1, 2), min_df=5, max_features=20000, sublinear_tf=True).fit([txt[i] for i in tr])
        reps["tfidf"] = tf.transform(txt)
        for slug in MODELS:
            if (emb_dir / f"{slug}.npy").is_file():
                e = load_emb(emb_dir, slug)
                reps[slug] = np.stack([e[key(t)] for t in txt])
        sets = {"val+test": np.flatnonzero(np.isin(split, ["val", "test"])), "live": np.flatnonzero(split == "live")}
        fits: dict[str, np.ndarray] = {}
        out_s: dict = {"episodes": {k: int(len(v)) for k, v in sets.items()}, "models": {}}
        for name, R in reps.items():
            from scipy.sparse import csr_matrix, hstack, issparse

            M = hstack([csr_matrix(S), R]).tocsr() if issparse(R) else (np.hstack([S, R]) if R.shape[1] else S)
            best = None
            for a in (10.0, 100.0, 1000.0, 3000.0, 10000.0):
                m = Ridge(alpha=a).fit(M[fit_idx], y[fit_idx])
                mae = float(np.abs(m.predict(M[tune_idx]) - y[tune_idx]).mean())
                if best is None or mae < best[0]:
                    best = (mae, a)
            m = Ridge(alpha=best[1]).fit(M[tr], y[tr])
            fits[name] = m.predict(M)
            out_s["models"][name] = {"alpha": best[1]}
        for set_id, ii in sets.items():
            view = make_view(np.arange(len(ii)).astype(str), y[ii], absz[ii], score[ii], placebo[ii])
            ib = boot_indices(view.n_ep, 1000, 7)
            base = fits["state-only"][ii]
            for name in reps:
                p = fits[name][ii]
                ok = ~np.isnan(placebo[ii])
                out_s["models"][name][set_id] = {
                    "mae": T.estimate(float(np.abs(p - y[ii]).mean()), *[float(v) for v in np.percentile(np.abs(p - y[ii])[ib].mean(axis=1), [2.5, 97.5])]).model_dump(),
                    "spearman": spearman_estimate(p, absz[ii], ib).model_dump(),
                    "placebo_spearman": round(float(spearman(p[ok], placebo[ii][ok])), 4),
                    "delta_mae_vs_state_only": delta_mae_estimate(p, base, view, ib).model_dump()}
        res[scope] = out_s
        for name, v in out_s["models"].items():
            vt = v["val+test"]
            print(f"impact {scope} {name:34s} val+test mae {vt['mae']['value']} sp {vt['spearman']['value']} placebo {vt['placebo_spearman']} d {vt['delta_mae_vs_state_only']['value']}", flush=True)
    return res


def main(emb_dir: Path) -> None:
    result = {"event": event_experiment(emb_dir), "impact": impact_experiment(emb_dir),
              "rules": __doc__.split("Writes")[0].strip(), "encoders": MODELS}
    out = ROOT / "docs" / "evidence" / "embedding_experiment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
