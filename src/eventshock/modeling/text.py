"""Text identity for modeling: exact keys, template keys and near-duplicate groups.

Reuses the pipeline's own notion of "the same text" (``pipeline.normalize``) so a document the pipeline folded as a
duplicate is also a duplicate here. Everything is deterministic and order independent.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..pipeline.normalize import clean_text, content_tokens, dedup_key, jaccard

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION = re.compile(r"@\w+")
_CASHTAG = re.compile(r"\$[A-Za-z][A-Za-z.]{0,6}\b")
_NUMBER = re.compile(r"\d[\d.,]*")
_WS = re.compile(r"\s+")


def exact_key(text: str) -> str:
    """Equality key used to fold exact duplicates (case, punctuation, URLs and outlet suffix ignored)."""
    return dedup_key(clean_text(text))


def template_key(text: str) -> str:
    """Key shared by boilerplate/spam that differs only in tickers, numbers, handles and links.

    ``$AAPL 190c > 188 | 180p < 185`` and ``$TSLA 1100c > 1055 | ...`` share a key; so do "Form 8.3 - X plc" notices.
    """
    t = clean_text(text)
    t = _URL.sub(" ", t)
    t = _MENTION.sub(" @ ", t)
    t = _CASHTAG.sub(" $ ", t)
    t = _NUMBER.sub("0", t)
    return _WS.sub(" ", re.sub(r"[^0-9a-z$@ ]+", " ", t.casefold())).strip()


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:  # the smaller index becomes the root, so group ids do not depend on merge order
            self.parent[max(ra, rb)] = min(ra, rb)


def _postings(token_sets: Sequence[frozenset[str]], max_posting: int) -> dict[str, list[int]]:
    inv: dict[str, list[int]] = {}
    for i, toks in enumerate(token_sets):
        for tok in toks:
            inv.setdefault(tok, []).append(i)
    return {t: p for t, p in inv.items() if len(p) <= max_posting}


def near_duplicate_groups(texts: Sequence[str], threshold: float, *, max_posting: int = 1500) -> list[int]:
    """Group id (= smallest member index) per text; texts are in one group if linked by Jaccard >= threshold.

    Exact duplicates (equal ``exact_key``) and equal ``template_key`` with at least 4 content tokens are always linked.
    Tokens occurring in more than ``max_posting`` texts are too common to propose candidates.
    """
    n = len(texts)
    sets = [content_tokens(t) for t in texts]
    inv = _postings(sets, max_posting)
    uf = _UnionFind(n)
    first_key: dict[str, int] = {}
    first_tpl: dict[str, int] = {}
    for i, t in enumerate(texts):
        k = exact_key(t)
        if k:
            if k in first_key:
                uf.union(first_key[k], i)
            else:
                first_key[k] = i
        tk = template_key(t)
        if len(tk.split()) >= 4:
            if tk in first_tpl:
                uf.union(first_tpl[tk], i)
            else:
                first_tpl[tk] = i
    for i, toks in enumerate(sets):
        if not toks:
            continue
        need = min(2, len(toks))
        counts: dict[int, int] = {}
        for tok in toks:
            for j in inv.get(tok, ()):
                if j < i:
                    counts[j] = counts.get(j, 0) + 1
        for j, c in counts.items():
            if c >= need and jaccard(toks, sets[j]) >= threshold:
                uf.union(j, i)
    return [uf.find(i) for i in range(n)]


def has_near_duplicate(query: Sequence[str], reference: Sequence[str], threshold: float, *,
                       max_posting: int = 300) -> list[bool]:
    """For each query text: does any reference text have Jaccard >= threshold (or an equal exact key)?

    Candidates are proposed only through tokens that are rare in the reference (<= ``max_posting`` texts): a pair with
    Jaccard >= 0.5 shares most of its tokens, so it shares rare ones unless the text is made only of common words,
    in which case it is also compared through its common tokens' neighbours being absent (accepted blind spot).
    """
    ref_sets = [content_tokens(t) for t in reference]
    inv = _postings(ref_sets, max_posting)
    ref_keys = {exact_key(t) for t in reference}
    out: list[bool] = []
    for q in query:
        if exact_key(q) in ref_keys:
            out.append(True)
            continue
        toks = content_tokens(q)
        rare = [t for t in toks if t in inv]
        if not rare:
            out.append(False)
            continue
        need = min(2, len(rare))
        counts: dict[int, int] = {}
        for tok in rare:
            for j in inv[tok]:
                counts[j] = counts.get(j, 0) + 1
        out.append(any(c >= need and jaccard(toks, ref_sets[j]) >= threshold for j, c in counts.items()))
    return out
