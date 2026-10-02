"""Text and URL normalisation. Pure functions; the only place that decides what "the same text" means."""

from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­"), None)
_WS = re.compile(r"\s+")
_URL_IN_TEXT = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_NON_WORD = re.compile(r"[^0-9a-z$%]+")
# " - Reuters", " | Yahoo Finance": a short trailing outlet name is not part of the story.
_OUTLET_SUFFIX = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,40}$")

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "cmpid", "ocid", "ncid",
                    "igshid", "yclid", "_ga", "spm"}

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were will with "
    "after over amid about into than their his her they he she we you your our us new says say said".split()
)


def clean_text(text: str) -> str:
    """NFKC, unescape HTML entities, drop control/zero-width characters, collapse whitespace."""
    text = unicodedata.normalize("NFKC", html.unescape(text))
    text = text.translate(_ZERO_WIDTH)
    text = "".join(" " if unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} else c for c in text)
    return _WS.sub(" ", text).strip()


def canonical_url(url: str) -> str | None:
    """Lower-case host, no ``www.``/fragment/tracking params, sorted query, no trailing slash. None if invalid."""
    url = url.strip()
    if not url or len(url) > 2048:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.lower().removeprefix("www.")
    if "." not in host:
        return None
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    canon = canonical_url(url)
    return urlsplit(canon).hostname if canon else None


def dedup_key(text: str) -> str:
    """Equality key: URLs and outlet suffix removed, case/punctuation/whitespace folded."""
    text = _URL_IN_TEXT.sub(" ", text)
    text = _OUTLET_SUFFIX.sub("", text)
    return _WS.sub(" ", _NON_WORD.sub(" ", text.casefold())).strip()


def content_tokens(text: str) -> frozenset[str]:
    """Distinct content words used for similarity (stopwords and 1-char tokens dropped)."""
    return frozenset(t for t in dedup_key(text).split() if len(t) > 1 and t not in STOPWORDS)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def match_form(text: str) -> str:
    """Folded form for dictionary matching: case-folded, ``&``→and, dots/apostrophes dropped, punctuation→space."""
    text = unicodedata.normalize("NFKC", text).casefold().replace("&", " and ")
    text = re.sub(r"[.'’`]", "", text)
    return _WS.sub(" ", re.sub(r"[^0-9a-z$ ]+", " ", text)).strip()
