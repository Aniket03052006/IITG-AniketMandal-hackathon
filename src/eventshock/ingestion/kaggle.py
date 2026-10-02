"""Kaggle dataset downloads. The API token is read from the environment (never from the repo, never written).

    KAGGLE_API_TOKEN=... python -m eventshock.ingestion.kaggle [--only SLUG] [--force]

If the variable is unset, ``~/.kaggle/access_token`` is read (Kaggle's own location). The zip is streamed to a
temporary file, unpacked into ``data/raw/kaggle/<slug>/`` and deleted. The token is never printed or logged.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ..config import REPO_ROOT, ConfigError
from .fetch import USER_AGENT, FetchError

API = "https://www.kaggle.com/api/v1/datasets/download/"
Downloader = Callable[[str, dict[str, str], Path, float], None]


def find_token(env: dict[str, str] | None = None, home: Path | None = None) -> str:
    env = os.environ if env is None else env
    if env.get("KAGGLE_API_TOKEN", "").strip():
        return env["KAGGLE_API_TOKEN"].strip()
    f = (home or Path.home()) / ".kaggle" / "access_token"
    if f.is_file() and f.read_text(encoding="utf-8").strip():
        return f.read_text(encoding="utf-8").strip()
    raise ConfigError("no Kaggle token: set KAGGLE_API_TOKEN or create ~/.kaggle/access_token (kaggle.com > Settings > API)")


def stream_download(url: str, headers: dict[str, str], dest: Path, timeout: float) -> None:
    if not url.startswith("https://"):
        raise FetchError(f"refusing non-https url: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as out:  # noqa: S310
            shutil.copyfileobj(resp, out, length=1 << 20)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"{url.removeprefix(API)}: HTTP {exc.code}") from exc  # the token is not in the message
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"{url.removeprefix(API)}: {exc}") from exc


def load_plan(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or REPO_ROOT / "configs" / "external_datasets.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    plan = data.get("datasets") if isinstance(data, dict) else None
    if not plan or any({"ref", "licence", "commit", "purpose"} - set(d) for d in plan):
        raise ConfigError(f"{path}: every dataset needs ref, licence, commit and purpose")
    return plan


def download_dataset(ref: str, dest_root: Path, token: str, *, downloader: Downloader = stream_download,
                     force: bool = False) -> tuple[str, list[str]]:
    """Returns ("downloaded" | "skipped", files). The zip never remains on disk."""
    slug = ref.split("/", 1)[1]
    dest = dest_root / slug
    if dest.is_dir() and any(dest.iterdir()) and not force:
        return "skipped", sorted(p.name for p in dest.iterdir())
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest_root) as tmp:
        zpath = Path(tmp) / "download.zip"
        downloader(API + ref, {"Authorization": f"Bearer {token}"}, zpath, 3600.0)
        try:
            with zipfile.ZipFile(zpath) as z:
                for name in z.namelist():
                    if name.startswith("/") or ".." in Path(name).parts:
                        raise FetchError(f"{ref}: unsafe path in archive: {name}")
                z.extractall(dest)
        except zipfile.BadZipFile as exc:
            raise FetchError(f"{ref}: response was not a zip file (bad token or dataset needs acceptance?)") from exc
    return "downloaded", sorted(p.name for p in dest.iterdir())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "raw" / "kaggle")
    ap.add_argument("--only", default=None, help="dataset slug to fetch")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    try:
        token = find_token()
        plan = [d for d in load_plan() if not args.only or d["ref"].endswith(args.only)]
    except ConfigError as exc:
        print(f"error: {exc}")
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for d in plan:
        try:
            status, files = download_dataset(d["ref"], args.out, token, force=args.force)
            print(f"{status:10} {d['ref']}  [{d['licence']}, commit: {d['commit']}]  {', '.join(files[:5])}")
        except FetchError as exc:
            failed += 1
            print(f"FAILED     {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
