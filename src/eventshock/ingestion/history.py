"""Adapters for the historical Kaggle datasets used for modelling (2015-2022): dated headlines and tweets.

Unlike the replay sources these carry real publication times (tweets) or dates (headlines), which makes them usable
to line events up with price moves. They are read from JSONL built by ``scripts/build_history_pack.py``. A ticker
column, where one exists, is kept as ``x_ticker`` metadata only: entity resolution still reads the text.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..domain import RawDocument, SourceType, TimestampOrigin
from .base import RejectCode, Rejected
from .snapshot import RawLine, iter_jsonl

_ET = ZoneInfo("America/New_York")
_CNBC = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET\s+\w+,\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
OUTLETS = {"reuters": "reuters.com", "cnbc": "cnbc.com", "guardian": "theguardian.com"}


def parse_headline_time(outlet: str, raw: object) -> tuple[datetime, TimestampOrigin] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    try:
        if outlet == "cnbc":
            m = _CNBC.search(raw)
            if not m:
                return None
            hh, mm, ap, d, mon, y = m.groups()
            dt = datetime.strptime(f"{d} {mon[:3]} {y} {int(hh) % 12 + (12 if ap.upper() == 'PM' else 0)}:{mm}", "%d %b %Y %H:%M")
            return dt.replace(tzinfo=_ET).astimezone(UTC), TimestampOrigin.SOURCE
        if outlet == "reuters":
            return datetime.strptime(raw, "%b %d %Y").replace(tzinfo=UTC), TimestampOrigin.SOURCE_DATE_ONLY
        if outlet == "guardian":
            return datetime.strptime(raw, "%d-%b-%y").replace(tzinfo=UTC), TimestampOrigin.SOURCE_DATE_ONLY
    except ValueError:
        return None
    return None


class _Base:
    name = ""
    source_type = SourceType.SOCIAL

    def __init__(self, *, snapshot_id: str, as_of: datetime, source_name: str | None = None) -> None:
        self.snapshot_id, self.as_of = snapshot_id, as_of
        self.source_name = source_name or self.name

    def read(self, path: Path, display_name: str) -> Iterator[RawDocument | Rejected]:
        for line in iter_jsonl(path, display_name):
            yield self.parse(line)

    def parse(self, line: RawLine) -> RawDocument | Rejected:
        def reject(code: RejectCode, detail: str) -> Rejected:
            return Rejected(self.source_name, line.ref, code, detail, line.preview)

        if line.obj is None:
            return reject(RejectCode.MALFORMED_RECORD, line.error or "unreadable record")
        built = self.build(line.obj, reject)
        if isinstance(built, Rejected):
            return built
        doc_id, source, text, body, published, origin, extra = built
        if published > self.as_of:
            return reject(RejectCode.FUTURE_TIMESTAMP, f"{published.isoformat()} after replay clock")
        try:
            return RawDocument(
                id=doc_id, source=source, source_type=self.source_type, published_at=published, ingested_at=self.as_of,
                headline=text, body=body, language="en",
                raw_metadata={"adapter": self.name, "snapshot_id": self.snapshot_id, "record_ref": line.ref,
                              "content_sha256": line.sha256, "timestamp_origin": origin.value, "domain": None, **extra})
        except ValidationError as exc:
            return reject(RejectCode.SCHEMA, str(exc).splitlines()[0])

    def build(self, rec: dict[str, Any], reject: Any) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError


class StockTweetsAdapter(_Base):
    """equinxx/stock-tweets-for-sentiment-analysis-and-prediction: ``{row, date, text, ticker, company}``."""

    name = "stock-tweets"

    def build(self, rec: dict[str, Any], reject: Any) -> Any:
        text, date, row = rec.get("text"), rec.get("date"), rec.get("row")
        if not isinstance(text, str) or not isinstance(row, int) or isinstance(row, bool):
            return reject(RejectCode.SCHEMA, "missing text/row")
        if not text.strip():
            return reject(RejectCode.EMPTY_TEXT, "empty tweet")
        try:
            published = datetime.fromisoformat(str(date))
        except ValueError:
            return reject(RejectCode.BAD_TIMESTAMP, f"unparseable date {date!r}")
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        return (f"stw-{row}", "Stock Tweets (Kaggle)", text, "", published.astimezone(UTC), TimestampOrigin.SOURCE,
                {"x_ticker": rec.get("ticker")})


class HeadlinesAdapter(_Base):
    """notlucasp/financial-news-headlines: ``{outlet, row, time, text, description}``; Reuters/Guardian have dates only."""

    name = "headlines"
    source_type = SourceType.NEWS

    def build(self, rec: dict[str, Any], reject: Any) -> Any:
        outlet, text, row = rec.get("outlet"), rec.get("text"), rec.get("row")
        if outlet not in OUTLETS or not isinstance(text, str) or not isinstance(row, int) or isinstance(row, bool):
            return reject(RejectCode.SCHEMA, "missing/invalid outlet, text or row")
        if not text.strip():
            return reject(RejectCode.EMPTY_TEXT, "empty headline")
        parsed = parse_headline_time(outlet, rec.get("time"))
        if parsed is None:
            return reject(RejectCode.BAD_TIMESTAMP, f"unparseable {outlet} time {rec.get('time')!r}")
        desc = rec.get("description")
        return (f"{outlet}-{row}", OUTLETS[outlet], text, desc if isinstance(desc, str) else "", parsed[0], parsed[1],
                {"domain": OUTLETS[outlet]})


class TopTweetsAdapter(_Base):
    """omermetinn/tweets-about-the-top-companies-from-2015-to-2020: ``{tweet_id, writer, post_date, text, tickers}``."""

    name = "top-tweets"

    def build(self, rec: dict[str, Any], reject: Any) -> Any:
        tid, text, ts = rec.get("tweet_id"), rec.get("text"), rec.get("post_date")
        if not isinstance(text, str) or not tid:
            return reject(RejectCode.SCHEMA, "missing text/tweet_id")
        if not text.strip():
            return reject(RejectCode.EMPTY_TEXT, "empty tweet")
        if isinstance(ts, bool) or not isinstance(ts, int) or not 0 < ts < 4_102_444_800:
            return reject(RejectCode.BAD_TIMESTAMP, f"bad post_date {ts!r}")
        return (f"ttw-{tid}", "Top Companies Tweets (Kaggle)", text, "", datetime.fromtimestamp(ts, UTC),
                TimestampOrigin.SOURCE, {"x_tickers": rec.get("tickers")})
