"""Finance lexicon channel (L): per-category counts as a small dense block. Pure Python, no extra dependency, deterministic.

Matching uses the pipeline's own folding (``pipeline.normalize.match_form``) and whole-word / whole-phrase boundaries, so "risk" does not match
"brisk". The features are ``log1p(count)`` of each category and the share of folded tokens they cover: a handful of numbers per text.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import yaml

from ...pipeline.normalize import match_form


class Lexicon:
    def __init__(self, categories: dict[str, list[str]], version: str = "1") -> None:
        self.version = version
        self.names = sorted(categories)
        self._re = {n: re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(match_form(w)) for w in sorted(set(ws), key=len, reverse=True))
                                  + r")(?![a-z0-9])") for n, ws in categories.items()}

    @classmethod
    def load(cls, path: Path) -> Lexicon:
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(d["categories"], str(d.get("version", "1")))

    @property
    def feature_names(self) -> list[str]:
        return [f"lex_{n}" for n in self.names] + ["lex_coverage"]

    def counts(self, text: str) -> dict[str, int]:
        folded = match_form(text)
        return {n: len(r.findall(folded)) for n, r in self._re.items()}

    def features(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), len(self.names) + 1))
        for i, t in enumerate(texts):
            c = self.counts(t)
            n_tok = max(1, len(match_form(t).split()))
            out[i, :-1] = [math.log1p(c[n]) for n in self.names]
            out[i, -1] = min(1.0, sum(c.values()) / n_tok)
        return out
