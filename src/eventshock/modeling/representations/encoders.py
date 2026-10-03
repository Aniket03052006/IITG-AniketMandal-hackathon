"""Frozen encoders with an on-disk embedding cache (needs torch + transformers: run with ``.venv-emb/bin/python``; never imported by the product).

Two kinds, both frozen (no fine-tuning, so nothing here can overfit the small label sets):
* ``dense``  sentence embedding: pooled last hidden state, L2-normalised (per-model prefix and pooling, from the model cards);
* ``affect`` a classification head's probabilities (finance tone, emotions): a handful of dimensions per text.

The cache (``data/modeling/embeddings/<slug>.npz``, git-ignored) maps ``sha1(text)[:16]`` -> vector, so every consumer reads the same numbers and
a text is encoded once. Loading prefers the local Hugging Face cache and otherwise downloads anonymously (``token=False``): a stale token in the
environment makes even public downloads fail with 401. Cost (ms per text, peak resident memory) is measured on the texts actually encoded and
written next to the vectors, because "is it worth carrying" needs a number.
"""

from __future__ import annotations

import hashlib
import json
import resource
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
CACHE_DIR = ROOT / "data" / "modeling" / "embeddings"
MAX_TOKENS = 128


@dataclass(frozen=True)
class EncoderSpec:
    name: str
    kind: str                     # "dense" | "affect"
    pooling: str = "mean"         # dense: "mean" | "cls"
    prefix: str = ""
    labels: tuple[str, ...] = ()  # affect: class names in the head's order (read from the model config at load, checked against this)


SPECS: dict[str, EncoderSpec] = {s.name: s for s in [
    EncoderSpec("intfloat/multilingual-e5-small", "dense", "mean", "query: "),
    EncoderSpec("intfloat/multilingual-e5-base", "dense", "mean", "query: "),
    EncoderSpec("intfloat/multilingual-e5-large", "dense", "mean", "query: "),
    EncoderSpec("BAAI/bge-base-en-v1.5", "dense", "cls", ""),
    EncoderSpec("thenlper/gte-base", "dense", "mean", ""),
    EncoderSpec("yiyanghkust/finbert-tone", "affect", labels=("neutral", "positive", "negative")),
    EncoderSpec("ProsusAI/finbert", "affect", labels=("positive", "negative", "neutral")),
    EncoderSpec("j-hartmann/emotion-english-distilroberta-base", "affect",
                labels=("anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise")),
]}


def text_key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]  # noqa: S324 (cache key, not a security use)


def slug(name: str) -> str:
    return name.replace("/", "__")


def load_cache(name: str, cache_dir: Path = CACHE_DIR) -> dict[str, np.ndarray]:
    p = cache_dir / f"{slug(name)}.npz"
    if not p.is_file():
        return {}
    z = np.load(p, allow_pickle=False)
    return {k: v for k, v in zip(z["keys"].tolist(), z["vectors"], strict=True)}


def _save_cache(name: str, vecs: dict[str, np.ndarray], cost: dict[str, Any], cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    keys = sorted(vecs)
    np.savez_compressed(cache_dir / f"{slug(name)}.npz", keys=np.array(keys), vectors=np.stack([vecs[k] for k in keys]).astype(np.float32))
    (cache_dir / f"{slug(name)}.cost.json").write_text(json.dumps(cost, indent=1, sort_keys=True) + "\n")


BERT_NO_TYPE = frozenset({"yiyanghkust/finbert-tone"})  # their config.json has no model_type: load as the BERT classifier it declares


def _load_hf(name: str, head: bool):
    from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer

    if name in BERT_NO_TYPE:
        from transformers import BertForSequenceClassification, BertTokenizer

        def load(**kw):
            return BertTokenizer.from_pretrained(name, **kw), BertForSequenceClassification.from_pretrained(name, **kw).eval()
    else:
        cls = AutoModelForSequenceClassification if head else AutoModel

        def load(**kw):
            return AutoTokenizer.from_pretrained(name, **kw), cls.from_pretrained(name, **kw).eval()
    try:
        return load(local_files_only=True)
    except (OSError, ValueError):
        return load(token=False)


def _peak_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1e6 if sys.platform == "darwin" else r / 1e3  # bytes on macOS, KiB on Linux


def encode(name: str, texts: Sequence[str], *, cache_dir: Path = CACHE_DIR, batch: int = 32, log=print) -> dict[str, Any]:
    """Encode every text not yet cached; return the cost record. Deterministic: eval mode, fixed length cap, no sampling."""
    import torch

    spec = SPECS[name]
    vecs = load_cache(name, cache_dir)
    todo = sorted({t for t in texts if text_key(t) not in vecs}, key=len)  # length-bucketed batches: far less padding
    prior_cost: dict[str, Any] = {}
    cost_path = cache_dir / f"{slug(name)}.cost.json"
    if cost_path.is_file():
        prior_cost = json.loads(cost_path.read_text())
    if not todo:
        return prior_cost
    tok, model = _load_hf(name, head=spec.kind == "affect")
    if spec.kind == "affect":
        cfg_labels = [model.config.id2label[i].lower() for i in range(len(model.config.id2label))]
        if tuple(cfg_labels) != spec.labels:
            raise RuntimeError(f"{name}: head labels {cfg_labels} differ from the registered {list(spec.labels)}")
    torch.set_num_threads(max(1, torch.get_num_threads()))
    t0 = time.time()
    with torch.no_grad():
        for s in range(0, len(todo), batch):
            chunk = todo[s:s + batch]
            enc = tok([spec.prefix + t for t in chunk], padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
            if spec.kind == "affect":
                out = torch.softmax(model(**enc).logits, dim=-1).numpy()
            else:
                h = model(**enc).last_hidden_state
                if spec.pooling == "cls":
                    v = h[:, 0]
                else:
                    m = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
                    v = (h * m).sum(1) / m.sum(1).clamp(min=1)
                out = torch.nn.functional.normalize(v, dim=1).numpy()
            for t, vec in zip(chunk, out, strict=True):
                vecs[text_key(t)] = vec.astype(np.float32)
            if (s // batch) % 40 == 0:
                log(f"  {name} {s}/{len(todo)} {time.time() - t0:.0f}s")
    secs = time.time() - t0
    n_new = len(todo)
    cost = {"model": name, "kind": spec.kind, "dim": int(len(next(iter(vecs.values())))), "ms_per_text": round(1000 * secs / n_new, 2),
            "texts_encoded_for_cost": n_new, "peak_rss_mb": round(_peak_mb()), "torch": torch.__version__,
            "threads": torch.get_num_threads(), "device": "cpu", "max_tokens": MAX_TOKENS}
    _save_cache(name, vecs, cost, cache_dir)
    log(f"{name}: +{n_new} texts, {cost['ms_per_text']} ms/text, peak {cost['peak_rss_mb']} MB, dim {cost['dim']}")
    return cost


def benchmark(names: Sequence[str], texts: Sequence[str], *, n: int = 192, threads: int = 4, repeats: int = 3, cache_dir: Path = CACHE_DIR, log=print) -> dict[str, Any]:
    """Controlled cost: per-text latency at batch 1 and at batch 32 on a fixed, sorted sample, fixed thread count, one warm-up, best of ``repeats``.

    Run it on a quiet machine: the cost measured while building the cache shares the CPU with other jobs and is only an upper bound. Also checks that two
    encodings of the same sample are bit-identical (the determinism part of the adoption rule).
    """
    import torch

    torch.set_num_threads(threads)
    sample = sorted(set(texts), key=lambda t: (len(t), t))[:: max(1, len(set(texts)) // n)][:n]
    out: dict[str, Any] = {"threads": threads, "sample": len(sample), "torch": torch.__version__, "models": {}}
    for name in names:
        spec = SPECS[name]
        tok, model = _load_hf(name, head=spec.kind == "affect")

        def run(batch: int, _spec=spec, _tok=tok, _model=model) -> np.ndarray:
            vecs = []
            with torch.no_grad():
                for s in range(0, len(sample), batch):
                    enc = _tok([_spec.prefix + t for t in sample[s:s + batch]], padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
                    if _spec.kind == "affect":
                        vecs.append(torch.softmax(_model(**enc).logits, dim=-1).numpy())
                    else:
                        h = _model(**enc).last_hidden_state
                        v = h[:, 0] if _spec.pooling == "cls" else (h * enc["attention_mask"].unsqueeze(-1)).sum(1) / enc["attention_mask"].sum(1, keepdim=True)
                        vecs.append(torch.nn.functional.normalize(v, dim=1).numpy())
            return np.concatenate(vecs)

        run(8)  # warm-up
        times = {}
        for batch in (1, 32):
            best = float("inf")
            for _ in range(repeats):
                t0 = time.perf_counter()
                first = run(batch)
                best = min(best, time.perf_counter() - t0)
            times[batch] = 1000 * best / len(sample)
        second = run(32)
        out["models"][name] = {"kind": spec.kind, "ms_per_text_batch1": round(times[1], 2), "ms_per_text_batch32": round(times[32], 2),
                               "parameters_m": round(sum(p.numel() for p in model.parameters()) / 1e6, 1), "peak_rss_mb": round(_peak_mb()),
                               "deterministic_double_run": bool(np.array_equal(first, second) if first.shape == second.shape else False)}
        log(f"{name}: {out['models'][name]}")
        del model, tok
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "cost_benchmark.json"
    if path.is_file():  # re-measuring one model must not discard the others
        prior = json.loads(path.read_text())
        out = {**prior, **{k: v for k, v in out.items() if k != "models"}, "models": {**prior.get("models", {}), **out["models"]}}
    path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--texts", type=Path, required=True, help="JSONL with a 'text' field per line (see representations.corpus)")
    ap.add_argument("--models", nargs="+", default=list(SPECS))
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--benchmark", action="store_true", help="measure controlled per-text cost and determinism instead of encoding (quiet machine)")
    args = ap.parse_args(argv)
    texts = [json.loads(x)["text"] for x in args.texts.read_text(encoding="utf-8").split("\n") if x.strip()]
    if args.benchmark:
        benchmark([m for m in args.models if m in SPECS], texts)
        return 0
    for m in args.models:
        if m not in SPECS:
            ap.error(f"unknown model {m!r}; registered: {sorted(SPECS)}")
        encode(m, texts, batch=args.batch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
