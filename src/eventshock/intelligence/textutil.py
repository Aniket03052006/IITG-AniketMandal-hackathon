"""Small, pure text tools shared by the intelligence modules: cue matching with offsets, key facts, IDF cosine, sentence splitting."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from ..pipeline.normalize import STOPWORDS, content_tokens

_NUMBER = re.compile(r"[$€£]?\d[\d,]*(?:\.\d+)?\s?(?:%|percent|bps|bp|trillion|billion|million|bn|mn|m|k)?(?![A-Za-z0-9])", re.IGNORECASE)
_CAPITAL = re.compile(r"\b[A-Z][A-Za-z&]{2,}\b")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“‘])|\n+")
_WORD = re.compile(r"[A-Za-z0-9$%][A-Za-z0-9$%'’&-]*")

# capitalised words that are not names
_NOT_NAMES = frozenset(
    "the this that these those with after before amid over under into from about for and but its his her their our new says said "
    "monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september october "
    "november december breaking update exclusive report reports reuters according".split())


def cue_pattern(cues: Iterable[str]) -> re.Pattern[str] | None:
    """One longest-first, whole-word, case-insensitive alternation over ``cues`` (spaces and hyphens match either)."""
    forms = sorted({c.strip() for c in cues if c.strip()}, key=len, reverse=True)
    if not forms:
        return None

    def esc(c: str) -> str:
        return re.sub(r"(?:\\ |\\-)+", r"[\\s-]+", re.escape(c)).replace("'", "['’]").replace("\\'", "['’]")

    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(esc(c) for c in forms) + r")(?![A-Za-z0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class Hit:
    cue: str  # the text as written
    start: int
    end: int


def find_cues(pattern: re.Pattern[str] | None, text: str) -> list[Hit]:
    if pattern is None:
        return []
    return [Hit(m.group(0), m.start(), m.end()) for m in pattern.finditer(text)]


def key_facts(text: str) -> frozenset[str]:
    """Numbers (with their unit) and capitalised names in ``text``, lower-cased: what two accounts of one event tend to share."""
    facts: set[str] = set()
    for m in _NUMBER.finditer(text):
        raw = re.sub(r"[\s,]", "", m.group(0).lower())
        if len(re.sub(r"\D", "", raw)) >= 1 and raw not in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "0"}:
            facts.add(raw)
    for m in _CAPITAL.finditer(text):
        w = m.group(0).lower()
        if w not in _NOT_NAMES and w not in STOPWORDS:
            facts.add(w)
    return frozenset(facts)


def sentences(text: str) -> list[tuple[int, str]]:
    """(start offset, sentence) pairs; offsets index into ``text``."""
    out: list[tuple[int, str]] = []
    pos = 0
    for m in _SENTENCE.finditer(text):
        seg = text[pos:m.start()]
        if seg.strip():
            out.append((pos + (len(seg) - len(seg.lstrip())), seg.strip()))
        pos = m.end()
    seg = text[pos:]
    if seg.strip():
        out.append((pos + (len(seg) - len(seg.lstrip())), seg.strip()))
    return out


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def topic_tokens(text: str) -> frozenset[str]:
    return content_tokens(text)


class Idf:
    """Inverse document frequency over a fixed corpus of token sets, and the cosine of two binary bags under it."""

    def __init__(self, bags: Iterable[frozenset[str]]) -> None:
        df: dict[str, int] = {}
        n = 0
        for bag in bags:
            n += 1
            for t in bag:
                df[t] = df.get(t, 0) + 1
        self._n = n
        self._df = df
        self._cache: dict[str, float] = {}

    def weight(self, token: str) -> float:
        w = self._cache.get(token)
        if w is None:
            w = math.log((self._n + 1) / (self._df.get(token, 0) + 1)) + 1.0
            self._cache[token] = w
        return w

    def cosine(self, a: frozenset[str], b: frozenset[str]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(self.weight(t) ** 2 for t in a & b)
        na = math.sqrt(sum(self.weight(t) ** 2 for t in a))
        nb = math.sqrt(sum(self.weight(t) ** 2 for t in b))
        return dot / (na * nb) if na and nb else 0.0
