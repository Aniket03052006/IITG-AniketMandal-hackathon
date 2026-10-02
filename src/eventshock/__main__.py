"""``python -m eventshock`` — run the API (and the built UI if present)."""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="eventshock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    from .config import Settings

    dist = Settings().web_dist_dir
    ui = "serving the built UI at /" if (dist / "index.html").is_file() else (
        "UI not built (run `cd web && npm ci && npm run build`); API only"
    )
    print(f"EventShock on http://{args.host}:{args.port}  ·  {ui}  ·  API docs at /api/docs", flush=True)
    if args.reload:
        uvicorn.run("eventshock.api.main:create_app", factory=True, host=args.host,
                    port=args.port, reload=True)
    else:
        uvicorn.run("eventshock.api.main:create_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
