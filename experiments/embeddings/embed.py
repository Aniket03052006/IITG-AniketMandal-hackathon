"""Frozen-encoder embeddings for texts.jsonl (isolated venv: torch + transformers; never imported by the product).

    .venv-emb/bin/python experiments/embeddings/embed.py <texts.jsonl> <out_dir> <model> [batch] [local_dir]

Models: intfloat/multilingual-e5-small, intfloat/multilingual-e5-base (sentence embeddings, mean pooling, "query: " prefix),
ProsusAI/finbert (financial BERT: mean-pooled last hidden state). Output: <out_dir>/<model-slug>.npy (float32, L2-normalised) + keys.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

MAXLEN = 128


def main(texts_path: Path, out_dir: Path, model_name: str, batch: int = 32, local: str | None = None) -> None:
    rows = [json.loads(x) for x in texts_path.read_text(encoding="utf-8").split("\n") if x.strip()]
    keys, texts = [r["key"] for r in rows], [r["text"] for r in rows]
    prefix = "query: " if "e5" in model_name else ""
    tok = AutoTokenizer.from_pretrained(local or model_name)
    model = AutoModel.from_pretrained(local or model_name).eval()
    torch.set_num_threads(max(1, torch.get_num_threads()))
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # length-bucketed batches: far less padding
    out = np.zeros((len(texts), model.config.hidden_size), dtype=np.float32)
    t0 = time.time()
    with torch.no_grad():
        for s in range(0, len(order), batch):
            idx = order[s:s + batch]
            enc = tok([prefix + texts[i] for i in idx], padding=True, truncation=True, max_length=MAXLEN, return_tensors="pt")
            h = model(**enc).last_hidden_state
            m = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
            v = (h * m).sum(1) / m.sum(1).clamp(min=1)
            v = torch.nn.functional.normalize(v, dim=1)
            out[idx] = v.numpy()
            if (s // batch) % 50 == 0:
                print(f"  {model_name} {s}/{len(order)} {time.time() - t0:.0f}s", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = model_name.replace("/", "__")
    np.save(out_dir / f"{slug}.npy", out)
    (out_dir / "keys.json").write_text(json.dumps(keys))
    print(f"{model_name}: {out.shape} in {time.time() - t0:.0f}s -> {out_dir / (slug + '.npy')}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 32,
         sys.argv[5] if len(sys.argv) > 5 else None)
