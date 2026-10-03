"""GDELT GKG (Global Knowledge Graph) bulk files: parse, filter, adapt.

A GKG 2.1 file is a 15-minute, tab-separated snapshot (27 columns). We keep only rows that matter to the entity
master, and reshape them like DOC-API records so the same pipeline reads both. Compared with the DOC API, GKG adds
the publisher's own time (``PAGE_PRECISEPUBTIMESTAMP``), a machine tone score, and NER-tagged organisations.
Entity resolution still reads the *text only*: organisations and the matching rule are recorded for later stages,
never used to attribute a signal.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..domain import TimestampOrigin
from ..pipeline.normalize import match_form
from .gdelt import GdeltAdapter, untokenise

N_COLUMNS = 27
_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)
_PUB = re.compile(r"<PAGE_PRECISEPUBTIMESTAMP>(\d{14})</PAGE_PRECISEPUBTIMESTAMP>")


@dataclass(frozen=True)
class GkgFilter:
    """What to keep. ``org_forms``/``title_forms`` map a normalised name to an issuer id (``match_form`` spelling)."""

    org_forms: dict[str, str]
    title_forms: dict[str, str]
    market_themes: frozenset[str]
    market_cap_per_file: int = 10
    _title_re: re.Pattern[str] | None = field(default=None, repr=False, compare=False)

    @staticmethod
    def from_json(obj: dict[str, Any]) -> GkgFilter:
        return GkgFilter(
            org_forms=dict(obj["org_forms"]), title_forms=dict(obj["title_forms"]),
            market_themes=frozenset(obj["market_themes"]), market_cap_per_file=int(obj.get("market_cap_per_file", 10)))

    def title_regex(self) -> re.Pattern[str] | None:
        if not self.title_forms:
            return None
        alts = "|".join(re.escape(f) for f in sorted(self.title_forms, key=len, reverse=True))
        return re.compile(r"(?<![a-z0-9$])(" + alts + r")(?![a-z0-9])")


@dataclass
class GkgStats:
    rows: int = 0
    malformed: int = 0
    translated: int = 0
    no_title: int = 0
    kept_issuer: int = 0
    kept_market: int = 0

    def __iadd__(self, o: GkgStats) -> GkgStats:
        for k in self.__dataclass_fields__:
            setattr(self, k, getattr(self, k) + getattr(o, k))
        return self

    def as_dict(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _tone(raw: str) -> dict[str, float] | None:
    parts = raw.split(",")
    if len(parts) < 7:
        return None
    try:
        v = [float(x) for x in parts[:7]]
    except ValueError:
        return None
    return {"tone": v[0], "positive": v[1], "negative": v[2], "polarity": v[3], "words": int(v[6])}


def _fmt(ts: str) -> str:
    return f"{ts[:8]}T{ts[8:]}Z"


def filter_gkg(text: str, flt: GkgFilter, file_name: str = "") -> tuple[list[dict[str, Any]], GkgStats]:
    """Parse one decompressed GKG file and return the kept DOC-shaped records plus accounting for every row."""
    stats = GkgStats()
    title_re = flt.title_regex()
    issuer_rows: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        stats.rows += 1
        col = line.rstrip("\r").split("\t")
        if len(col) != N_COLUMNS:
            stats.malformed += 1
            continue
        if col[25].strip():  # TranslationInfo present: non-English source, translated by GDELT
            stats.translated += 1
            continue
        extras = col[26]
        m = _TITLE.search(extras)
        title = untokenise(html.unescape(m.group(1)).strip()) if m else ""
        url = col[4].strip()
        if not title or not url:
            stats.no_title += 1
            continue
        first_seen = col[1].strip()
        pub = _PUB.search(extras)
        origin, seen = TimestampOrigin.GDELT_FIRST_SEEN.value, first_seen
        if pub and len(first_seen) == 14 and pub.group(1) <= first_seen:
            origin, seen = TimestampOrigin.SOURCE.value, pub.group(1)  # the publisher's own clock
        if len(seen) != 14 or not seen.isdigit():
            stats.malformed += 1
            continue

        orgs = [match_form(o) for o in col[13].split(";") if o.strip()]
        issuers = {flt.org_forms[o] for o in orgs if o in flt.org_forms}
        in_title = {flt.title_forms[f] for f in (title_re.findall(match_form(title)) if title_re else [])}
        themes = [t.split(",")[0] for t in col[8].split(";") if t]
        rec = {
            "url": url, "title": title, "seendate": _fmt(seen), "domain": col[3].strip(), "language": "English",
            "x_gkg_id": col[0], "x_time_origin": origin, "x_file": file_name,
            "x_tone": _tone(col[15]), "x_orgs": sorted(set(orgs))[:6],
            "x_issuers": sorted(issuers | in_title), "x_in_title": sorted(in_title),
        }
        if issuers or in_title:
            stats.kept_issuer += 1
            issuer_rows.append(rec)
        elif flt.market_themes & set(themes):
            rec["x_themes"] = sorted(flt.market_themes & set(themes))
            market_rows.append(rec)
    # market-wide rows are plentiful: keep a deterministic, content-hash-ordered subset per file
    market_rows.sort(key=lambda r: hashlib.sha256(r["x_gkg_id"].encode()).hexdigest())
    kept_market = market_rows[: flt.market_cap_per_file]
    stats.kept_market = len(kept_market)
    return issuer_rows + kept_market, stats


class GkgAdapter(GdeltAdapter):
    """Reads GKG-derived records. Same shape as DOC records; also carries the publisher time, tone and orgs."""

    name = "gdelt-gkg"
    id_prefix = "gkg"

    def __init__(self, *, snapshot_id: str, as_of: datetime, source_name: str = "gdelt-gkg") -> None:
        super().__init__(snapshot_id=snapshot_id, as_of=as_of, source_name=source_name)

    def _extra_metadata(self, rec: dict[str, Any]) -> dict[str, Any]:
        origin = rec.get("x_time_origin")
        ok = origin in {o.value for o in TimestampOrigin}
        return {
            "timestamp_origin": origin if ok else TimestampOrigin.GDELT_FIRST_SEEN.value,
            "gkg_id": rec.get("x_gkg_id"),
            "gkg_tone": rec.get("x_tone"),
            "gkg_orgs": rec.get("x_orgs"),
        }


def utc_stamp(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def select_files(master_lines: Iterable[str], start: str, end: str, kind: str = "gkg.csv.zip",
                 slots: frozenset[str] | None = None) -> list[str]:
    """https URLs of masterfilelist entries of ``kind`` whose 14-digit timestamp lies in [start, end].

    ``slots`` (optional set of ``HHMM`` strings, UTC) keeps only files stamped at those times of day: a deterministic,
    evenly spread sample (e.g. six slots = 6 of GDELT's 96 daily files, about 6% of the flow). ``None`` keeps every file.
    """
    out = []
    for line in master_lines:
        parts = line.split()
        if len(parts) != 3 or not parts[2].endswith(kind):
            continue
        stamp = parts[2].rsplit("/", 1)[-1][:14]
        if not (stamp.isdigit() and start <= stamp <= end):
            continue
        if slots is not None and stamp[8:12] not in slots:
            continue
        out.append("https://" + parts[2].split("://", 1)[-1])  # the list says http; the server speaks https
    return sorted(set(out))
