"""Cue-phrase matching that reports *where* in the original text a phrase was found (so a hit can become a quotable evidence span)."""

from __future__ import annotations

import re
from functools import lru_cache

from ..pipeline.normalize import match_form

_WORD = "0-9A-Za-z$%"


@lru_cache(maxsize=4096)
def cue_pattern(cue: str) -> re.Pattern[str]:
    """A case-insensitive pattern for ``cue`` that tolerates punctuation between its words ("sell-off" = "sell off") and matches whole words only."""
    tokens = match_form(cue).split()
    if not tokens:
        raise ValueError(f"cue {cue!r} folds to nothing")
    body = rf"[^{_WORD}]+".join(re.escape(t) for t in tokens)
    return re.compile(rf"(?<![{_WORD}]){body}(?![{_WORD}])", re.IGNORECASE)


def find_cue(text: str, cue: str) -> tuple[int, int] | None:
    m = cue_pattern(cue).search(text)
    return (m.start(), m.end()) if m else None


def cue_weight(cue: str) -> int:
    """A multi-word phrase is more specific than a single word: it counts double when picking a subtype."""
    return 2 if len(match_form(cue).split()) > 1 else 1


def find_literal(text: str, needle: str) -> tuple[int, int] | None:
    """``needle`` verbatim in ``text`` (case-sensitive first, then ignoring case and runs of whitespace). Used to ground model claims."""
    if not needle.strip():
        return None
    i = text.find(needle)
    if i >= 0:
        return i, i + len(needle)
    parts = [re.escape(p) for p in needle.split()]
    if not parts:
        return None
    m = re.search(r"\s+".join(parts), text, re.IGNORECASE)
    return (m.start(), m.end()) if m else None
