"""SEC EDGAR "current filings" as a live source: new 8-Ks become documents for the same engine that reads news.

Why a second live source: EDGAR is a different kind of source from GDELT news. A filing is first-party (the company says it), carries an
official event type (the 8-K *item codes*) and an exact acceptance time, and costs nothing. An event that appears in both is corroborated by
two independent sources, which the evidence strength already counts.

What a document is here: the filer, the form and the item titles *as SEC publishes them*. The headline is composed from those fields
("<Company> files Form 8-K: Item 2.04 ..."), so it is marked ``synthesized_headline`` in the metadata and it adds nothing the feed did not say.
No filing text is read. The domain has two source types (NEWS, SOCIAL); a filing is carried as NEWS from source ``sec.gov`` with
``raw_metadata.form`` saying what it is.

Which filings: the feed lists every 8-K, mostly small companies and routine items. A filing is kept when its issuer is in the entity master
(matched by CIK, never by name) or when one of its items is in ``edgar.items`` of ``configs/live.yaml``. Both are judgement priors, not
validated. Everything else is counted and dropped, never turned into a signal.

Network boundary: one GET per poll through ``fetch.get_bytes`` with the SEC-declared User-Agent (``edgar.sec_contact``): SEC asks for a
declared contact and at most 10 requests per second; a poll is one request. A failure is a failed poll, never an invented filing.
"""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from ..domain import RawDocument, SourceType, TimestampOrigin
from .base import RejectCode, Rejected
from .edgar import CONTACT_VAR, sec_contact, sec_transport
from .fetch import FetchError, Transport, get_bytes
from .live import EdgarSourceConfig, LivePoll

FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form}&company=&dateb=&owner=include&start=0&count={count}&output=atom"
ADAPTER = "sec-edgar-live"
SOURCE_NAME = "sec.gov"
MAX_FEED_BYTES = 2_000_000
_NS = {"a": "http://www.w3.org/2005/Atom"}
_TITLE = re.compile(r"^(?P<form>[\w.\-/]+) - (?P<name>.+?) \((?P<cik>\d{1,10})\) \((?P<role>[^)]*)\)\s*$")
_ITEM = re.compile(r"Item\s+(?P<code>\d\.\d{2})\s*:?\s*(?P<title>[^\n<]*)")
_ACCESSION = re.compile(r"AccNo:\s*(?P<acc>\d{10}-\d{2}-\d{6})")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


class FeedError(ValueError):
    """The feed could not be read as the Atom document it should be."""


def parse_feed(data: bytes) -> list[dict]:
    """Atom bytes -> one dict per entry: form, name, cik, role, accession, items [(code, title)], url, accepted (UTC datetime).

    An entry missing any of those comes back as ``{"invalid": <its title>}`` so the caller can count it; a document that is not an
    Atom feed at all raises ``FeedError``.
    """
    if len(data) > MAX_FEED_BYTES:
        raise FeedError(f"feed is {len(data)} bytes, over the {MAX_FEED_BYTES} limit")
    try:
        root = ET.fromstring(data)  # noqa: S314 (sec.gov over https, size-capped; no DTD is fetched)
    except ET.ParseError as exc:
        raise FeedError(f"not valid XML: {exc}") from exc
    if not root.tag.endswith("feed"):
        raise FeedError(f"not an Atom feed (root element {root.tag!r})")
    out: list[dict] = []
    for entry in root.findall("a:entry", _NS):
        title = (entry.findtext("a:title", default="", namespaces=_NS) or "").strip()
        summary = _TAG.sub("", _BR.sub("\n", html.unescape(entry.findtext("a:summary", default="", namespaces=_NS) or "")))  # the summary is escaped HTML
        m = _TITLE.match(title)
        acc = _ACCESSION.search(summary)
        link = entry.find("a:link", _NS)
        updated = (entry.findtext("a:updated", default="", namespaces=_NS) or "").strip()
        try:
            accepted = datetime.fromisoformat(updated).astimezone(UTC)
        except ValueError:
            accepted = None
        if not (m and acc and link is not None and link.get("href") and accepted is not None):
            out.append({"invalid": title[:80] or "(untitled entry)"})
            continue
        out.append({
            "form": m["form"], "name": m["name"].strip(), "cik": int(m["cik"]), "role": m["role"], "accession": acc["acc"],
            "items": [(i["code"], i["title"].strip()) for i in _ITEM.finditer(summary)], "url": link.get("href"), "accepted": accepted,
        })
    return out


def headline(name: str, form: str, items: list[tuple[str, str]], limit: int) -> str:
    """"<Company> files Form 8-K: Item 2.04 Triggering Events ...; Item 9.01 ...", cut at a word boundary to ``limit`` characters."""
    parts = [f"Item {code} {title.split(';')[0].split(':')[0].strip()}".strip() for code, title in items]
    text = f"{name} files Form {form}" + (": " + "; ".join(parts) if parts else "")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(";:, ") + "…"


def to_document(e: dict, *, now: datetime, cfg: EdgarSourceConfig) -> RawDocument | Rejected:
    ref = e["accession"]
    try:
        return RawDocument(
            id="edgar-" + hashlib.sha1(ref.encode("utf-8")).hexdigest()[:12],  # noqa: S324
            source=SOURCE_NAME, source_type=SourceType.NEWS, published_at=e["accepted"], ingested_at=max(now, e["accepted"]),
            headline=headline(e["name"], e["form"], e["items"], cfg.max_headline_chars), url=e["url"], language="en",
            raw_metadata={
                "timestamp_origin": TimestampOrigin.SOURCE.value, "adapter": ADAPTER, "snapshot_id": "live", "record_ref": ref,
                "content_sha256": hashlib.sha256(f"{ref}|{e['accepted'].isoformat()}".encode()).hexdigest(),
                "provider": "sec-edgar", "form": e["form"], "filer": e["name"], "cik": e["cik"], "accession": ref,
                "items": [c for c, _ in e["items"]], "item_titles": [t for _, t in e["items"]], "synthesized_headline": True,
            })
    except ValueError as exc:
        return Rejected(ADAPTER, ref, RejectCode.SCHEMA, str(exc).splitlines()[0], e["name"][:120])


def note(c: dict[str, int], lookback_hours: float) -> str:
    """"SEC filings: 100 listed, 43 in the last 6 h, 2 matched"; what a quiet poll means, in the poll's own numbers."""
    recent = c["entries"] - c["old"] - c["invalid"] - c["other_form"]
    return f"SEC filings: {c['entries']} listed, {recent} in the last {lookback_hours:g} h, {c['kept']} matched"


class EdgarLiveSource:
    mode = "EDGAR"
    kind = "edgar"
    interval_seconds: float | None = None  # None: the service's poll_interval_seconds

    def __init__(self, cfg: EdgarSourceConfig, *, tracked_ciks: frozenset[int] = frozenset(), transport: Transport | None = None,
                 clock: Callable[[], datetime] | None = None, contact: str | None = None) -> None:
        self.cfg, self.tracked = cfg, tracked_ciks
        # a contact is required even when a transport is supplied: the declared contact is what SEC's fair-access policy asks for
        declared = sec_contact(env={CONTACT_VAR: contact}, dotenv=None) if contact is not None else None
        self._transport = transport if transport is not None else sec_transport(declared if declared is not None else sec_contact())
        self._clock = clock or (lambda: datetime.now(UTC))
        self.last_counts: dict[str, int] = {}

    def keep(self, e: dict) -> bool:
        if e["form"] != self.cfg.form:
            return False
        if self.cfg.tracked_issuers and e["cik"] in self.tracked:
            return True
        return bool(set(self.cfg.items) & {c for c, _ in e["items"]})

    def poll(self) -> LivePoll:
        now = self._clock()
        url = FEED_URL.format(form=quote(self.cfg.form), count=self.cfg.count)
        try:
            entries = parse_feed(get_bytes(url, transport=self._transport, retries=1))
        except (FetchError, FeedError) as exc:
            return LivePoll(self.mode, now, queries_failed=1, errors=[f"{type(exc).__name__}: {str(exc)[:200]}"])
        cutoff = now - timedelta(hours=self.cfg.lookback_hours)
        seen: set[str] = set()
        docs: list[RawDocument | Rejected] = []
        counts = {"entries": len(entries), "invalid": 0, "other_form": 0, "old": 0, "not_kept": 0, "duplicate": 0, "kept": 0}
        for e in entries:
            if "invalid" in e:
                counts["invalid"] += 1
            elif e["form"] != self.cfg.form:
                counts["other_form"] += 1
            elif e["accepted"] < cutoff:
                counts["old"] += 1
            elif e["accession"] in seen:
                counts["duplicate"] += 1  # the feed lists a filing once per role (filer, subject)
            elif not self.keep(e):
                counts["not_kept"] += 1
            else:
                seen.add(e["accession"])
                docs.append(to_document(e, now=now, cfg=self.cfg))
                counts["kept"] += 1
        self.last_counts = counts
        return LivePoll(self.mode, now, queries_ok=1, documents=docs, note=note(counts, self.cfg.lookback_hours))
