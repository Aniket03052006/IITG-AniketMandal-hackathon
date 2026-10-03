"""Bulk download of GDELT GKG files, filtered on the fly. Zips never touch the disk unless ``--keep-zips`` is given.

    python -m eventshock.ingestion.gkg_fetch --master data/raw/gdelt_gkg/masterfilelist.txt \\
        --start 20260917000000 --end 20260930235959 --filter data/raw/gdelt_gkg/filter.json \\
        --out data/raw/gdelt_gkg/filtered.jsonl

Each 15-minute file is downloaded, decompressed in memory, filtered (``gkg.filter_gkg``) and appended to the output;
a checkpoint line is written per file, so an interrupted run resumes without re-downloading finished files.
Failures are logged per file and retried on the next run; they never abort the run.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fetch import FetchError, Transport, get_bytes, urllib_transport, write_jsonl
from .gkg import GkgFilter, GkgStats, filter_gkg, select_files


def _lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x.strip()]


@dataclass
class GkgFetchResult:
    files_total: int = 0
    files_done: int = 0
    files_failed: list[str] = field(default_factory=list)
    stats: GkgStats = field(default_factory=GkgStats)
    records: int = 0


def process_file(url: str, flt: GkgFilter, *, transport: Transport, keep_dir: Path | None,
                 sleep: Callable[[float], None]) -> tuple[list[dict[str, Any]], GkgStats]:
    name = url.rsplit("/", 1)[-1]
    body = get_bytes(url, transport=transport, timeout=120.0, backoff=3.0, sleep=sleep)
    if keep_dir:
        keep_dir.mkdir(parents=True, exist_ok=True)
        (keep_dir / name).write_bytes(body)
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            text = z.read(z.namelist()[0]).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, IndexError, KeyError) as exc:
        raise FetchError(f"{name}: not a valid zip ({exc})") from exc
    return filter_gkg(text, flt, name)


def fetch_gkg(master: Path, flt: GkgFilter, *, start: str, end: str, out: Path, workers: int = 4,
              keep_dir: Path | None = None, transport: Transport = urllib_transport,
              sleep: Callable[[float], None] | None = None,
              progress: Callable[[str], None] | None = None,
              slots: frozenset[str] | None = None) -> GkgFetchResult:
    import time

    sleep = sleep or time.sleep
    log_path = out.with_suffix(".log.jsonl")
    urls = select_files(master.read_text(encoding="utf-8").split("\n"), start, end, slots=slots)
    records = _lines(out)
    log = _lines(log_path)
    done = {e["file"] for e in log if e.get("status") == "ok"}
    todo = [u for u in urls if u.rsplit("/", 1)[-1] not in done]
    res = GkgFetchResult(files_total=len(urls), files_done=len(urls) - len(todo))
    if progress:
        progress(f"gkg: {len(urls)} files in range, {len(done & {u.rsplit('/', 1)[-1] for u in urls})} already done, {len(todo)} to fetch")

    out.parent.mkdir(parents=True, exist_ok=True)

    def append(path: Path, rows: list[dict[str, Any]]) -> None:
        if rows:
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))

    def checkpoint(entry: dict[str, Any], new: list[dict[str, Any]]) -> None:
        # append-only: O(new rows) per file, and a crash can lose at most the file in flight
        records.extend(new)
        append(out, new)
        append(log_path, [entry])

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process_file, u, flt, transport=transport, keep_dir=keep_dir, sleep=sleep): u
                   for u in todo}
        for i, fut in enumerate(as_completed(futures), start=1):
            url = futures[fut]
            name = url.rsplit("/", 1)[-1]
            try:
                new, stats = fut.result()
            except FetchError as exc:
                res.files_failed.append(name)
                checkpoint({"file": name, "status": "error", "error": str(exc)[-200:]}, [])
                if progress:
                    progress(f"[{i}/{len(todo)}] {name}: ERROR {exc}")
                continue
            res.files_done += 1
            res.stats += stats
            res.records += len(new)
            checkpoint({"file": name, "status": "ok", **stats.as_dict(), "kept": len(new)}, new)
            if progress and (i % 20 == 0 or i == len(todo)):
                progress(f"[{i}/{len(todo)}] {name}: {len(new)} kept; {res.records} so far")
    # consolidate: unique by GKG id (resume-safe), stable order
    uniq = {r["x_gkg_id"]: r for r in records}
    write_jsonl(out, sorted(uniq.values(), key=lambda r: (r["seendate"], r["url"])))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", type=Path, required=True)
    ap.add_argument("--start", required=True, help="YYYYMMDDHHMMSS")
    ap.add_argument("--end", required=True)
    ap.add_argument("--filter", type=Path, required=True, help="JSON written by scripts/replay_universe.py")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--slots", default=None,
                    help="comma-separated HHMM (UTC) file slots to sample per day, e.g. 0000,0400,0800,1200,1600,2000 (default: every file)")
    ap.add_argument("--keep-zips", type=Path, default=None, help="also save the downloaded zips here (default: discard)")
    args = ap.parse_args(argv)
    flt = GkgFilter.from_json(json.loads(args.filter.read_text(encoding="utf-8")))
    slots = frozenset(x.strip() for x in args.slots.split(",") if x.strip()) if args.slots else None
    if slots and not all(len(x) == 4 and x.isdigit() for x in slots):
        ap.error("--slots must be HHMM values such as 0400")
    res = fetch_gkg(args.master, flt, start=args.start, end=args.end, out=args.out, workers=args.workers,
                    keep_dir=args.keep_zips, slots=slots, progress=lambda m: print(m, file=sys.stderr, flush=True))
    s = res.stats
    print(f"gkg: {res.files_done}/{res.files_total} files ok, {len(res.files_failed)} failed; this run read {s.rows} rows "
          f"(translated {s.translated}, no title {s.no_title}, malformed {s.malformed}) and kept "
          f"{s.kept_issuer} issuer + {s.kept_market} market rows -> {args.out}")
    for f in res.files_failed[:20]:
        print(f"  FAILED (re-run to retry): {f}")
    return 1 if res.files_total and res.files_done == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
