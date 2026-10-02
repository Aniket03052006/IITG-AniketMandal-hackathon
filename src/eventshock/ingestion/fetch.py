"""Explicit network boundary. Nothing else in the package performs I/O against the internet.

``python -m eventshock.ingestion.fetch gdelt|tfn`` downloads into ``data/raw/`` (git-ignored). The server
never calls this; replay consumes the frozen pack built from these downloads (``make replay-pack``).
Failures are retried with backoff, then recorded in the returned log — never swallowed, never partial.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .snapshot import atomic_write_text

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
TFN_BASE = "https://huggingface.co/datasets/zeroshot/twitter-financial-news-sentiment/resolve/main/"
TFN_FILES = {"train": "sent_train.csv", "valid": "sent_valid.csv"}
TFN_TOPIC_BASE = "https://huggingface.co/datasets/zeroshot/twitter-financial-news-topic/resolve/main/"
TFN_TOPIC_FILES = {"train": "topic_train.csv", "valid": "topic_valid.csv"}
USER_AGENT = "Mozilla/5.0 (compatible; EventShock-hackathon/0.2; research prototype)"  # Yahoo rejects bare agents

Transport = Callable[[str, float], tuple[int, bytes]]


class FetchError(RuntimeError):
    """A request failed after all retries."""


def urllib_transport(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 (https only, see below)
    if not url.startswith("https://"):
        raise FetchError(f"refusing non-https url: {url}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"network error for {url}: {exc}") from exc


def get_bytes(url: str, *, transport: Transport = urllib_transport, retries: int = 3, backoff: float = 2.0,
              timeout: float = 30.0, sleep: Callable[[float], None] = time.sleep) -> bytes:
    last = "no attempt"
    for attempt in range(retries + 1):
        try:
            status, body = transport(url, timeout)
        except FetchError as exc:
            last = str(exc)
        else:
            if status == 200:
                return body
            last = f"HTTP {status}"
            if status not in {408, 425, 429, 500, 502, 503, 504}:
                raise FetchError(f"{url}: {last}")
        if attempt < retries:
            sleep(backoff * (2**attempt))
    raise FetchError(f"{url}: gave up after {retries + 1} attempts ({last})")


def get_json(url: str, **kw: Any) -> Any:
    """GDELT answers rate-limit and syntax errors with HTTP 200 + plain text, so a 200 is not trusted."""
    sleep = kw.get("sleep", time.sleep)
    retries = kw.get("retries", 3)
    for attempt in range(retries + 1):
        body = get_bytes(url, **kw)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            text = body[:200].decode("utf-8", errors="replace").strip()
            if "limit requests" in text.lower() and attempt < retries:
                sleep(5.0 * (attempt + 1))
                continue
            raise FetchError(f"{url}: non-JSON response: {text!r}") from None
    raise FetchError(f"{url}: rate limited after {retries + 1} attempts")


@dataclass
class GdeltFetchResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return sum(1 for e in self.log if e["status"] == "error")


def gdelt_url(query: str, start: str, end: str, maxrecords: int) -> str:
    params = {"query": f"{query} sourcelang:english", "mode": "artlist", "format": "json",
              "maxrecords": str(maxrecords), "startdatetime": start, "enddatetime": end, "sort": "hybridrel"}
    return f"{GDELT_URL}?{urllib.parse.urlencode(params)}"


def plan_item(item: str | dict[str, Any], default_max: int) -> tuple[str, int]:
    """A query-plan entry is a query string or ``{"query": ..., "maxrecords": ...}``."""
    if isinstance(item, str):
        return item, default_max
    return str(item["query"]), int(item.get("maxrecords", default_max))


def fetch_gdelt(queries: Iterable[str | dict[str, Any]], *, start: str, end: str, maxrecords: int = 30,
                transport: Transport = urllib_transport, sleep: Callable[[float], None] = time.sleep,
                throttle: float = 20.0, progress: Callable[[str], None] | None = None,
                seen: set[str] | None = None,
                on_query: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None = None) -> GdeltFetchResult:
    """One request per query (throttled). Articles are de-duplicated by URL across queries (first query wins)."""
    result = GdeltFetchResult()
    seen = set() if seen is None else seen
    for i, item in enumerate(queries):
        query, query_max = plan_item(item, maxrecords)
        if i:
            sleep(throttle)
        try:
            data = get_json(gdelt_url(query, start, end, query_max), transport=transport, sleep=sleep,
                            retries=2, backoff=30.0, timeout=45.0)
            # GDELT answers a query with no hits as {}; any other shape without 'articles' is an error.
            articles = data.get("articles", [] if data == {} else None) if isinstance(data, dict) else None
            if not isinstance(articles, list):
                raise FetchError(f"unexpected response shape: {str(data)[:120]}")
        except FetchError as exc:
            entry = {"query": query, "status": "error", "error": str(exc)}
            result.log.append(entry)
            if on_query:
                on_query([], entry)
            if progress:
                progress(f"[{i + 1}] {query}: ERROR {exc}")
            continue
        new: list[dict[str, Any]] = []
        for art in articles:
            url = art.get("url") if isinstance(art, dict) else None
            if isinstance(url, str) and url not in seen:
                seen.add(url)
                new.append({**art, "x_query": query})
        added = len(new)
        result.records.extend(new)
        entry = {"query": query, "status": "ok", "returned": len(articles), "added": added}
        result.log.append(entry)
        if on_query:
            on_query(new, entry)
        if progress:
            progress(f"[{i + 1}] {query}: {len(articles)} returned, {added} new")
    return result


def fetch_tfn(split: str, *, kind: str = "sentiment", transport: Transport = urllib_transport) -> list[dict[str, Any]]:
    """Twitter Financial News rows: ``kind`` is "sentiment" (3 labels) or "topic" (20 labels)."""
    base, files = (TFN_BASE, TFN_FILES) if kind == "sentiment" else (TFN_TOPIC_BASE, TFN_TOPIC_FILES)
    if kind not in {"sentiment", "topic"}:
        raise ValueError(f"unknown kind {kind!r}")
    if split not in files:
        raise ValueError(f"unknown split {split!r}; choose from {sorted(files)}")
    body = get_bytes(base + files[split], transport=transport, timeout=60)
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    if not rows or set(rows[0]) != {"text", "label"}:
        raise FetchError(f"unexpected TFN schema: {list(rows[0]) if rows else 'empty file'}")
    return [{"split": split, "row": i, "text": r["text"], "label": int(r["label"])} for i, r in enumerate(rows)]


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records]
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download source data into data/raw/ (git-ignored).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gdelt")
    g.add_argument("--queries-file", type=Path, required=True, help="JSON list of GDELT query strings")
    g.add_argument("--start", required=True, help="YYYYMMDDHHMMSS")
    g.add_argument("--end", required=True)
    g.add_argument("--throttle", type=float, default=20.0, help="seconds between requests")
    g.add_argument("--maxrecords", type=int, default=30, help="default for plan entries without their own")
    g.add_argument("--out", type=Path, required=True)
    t = sub.add_parser("tfn")
    t.add_argument("--split", default="train", choices=sorted(TFN_FILES))
    t.add_argument("--kind", default="sentiment", choices=["sentiment", "topic"])
    t.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    if args.cmd == "gdelt":
        queries = json.loads(args.queries_file.read_text(encoding="utf-8"))
        log_path = args.out.with_suffix(".log.jsonl")
        records = _read_lines(args.out)  # resume: keep what earlier (interrupted) runs already fetched
        log = _read_lines(log_path)
        done = {e["query"] for e in log if e.get("status") == "ok"}
        todo = [q for q in queries if plan_item(q, args.maxrecords)[0] not in done]
        print(f"gdelt: {len(queries) - len(todo)} of {len(queries)} planned queries already done, {len(todo)} to fetch",
              file=sys.stderr, flush=True)

        def persist(new: list[dict], entry: dict) -> None:  # checkpoint after every query
            records.extend(new)
            log.append(entry)
            write_jsonl(args.out, records)
            write_jsonl(log_path, log)

        res = fetch_gdelt(todo, start=args.start, end=args.end, maxrecords=args.maxrecords,
                          transport=urllib_transport, sleep=time.sleep, throttle=args.throttle, seen={r["url"] for r in records if "url" in r},
                          on_query=persist,
                          progress=lambda m: print(m, file=sys.stderr, flush=True))
        print(f"gdelt: {len(records)} articles total, {res.failed} of {len(todo)} queries failed this run -> {args.out}")
        for e in log:
            if e["status"] == "ok":
                print(f"  ok     {e['added']:>3} new / {e['returned']:>3} returned  {e['query'][:70]}")
        failed_now = {e["query"] for e in res.log if e["status"] == "error"}
        for q in sorted(failed_now):
            print(f"  FAILED (re-run `make fetch-gdelt` to retry): {q[:90]}")
        return 1 if todo and res.failed == len(todo) else 0
    rows = fetch_tfn(args.split, kind=args.kind)
    write_jsonl(args.out, rows)
    print(f"tfn: {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
