"""FastAPI application factory. Serves the built web UI when ``web/dist`` exists."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .. import __version__
from ..config import Settings
from .deps import build_container
from .routers import (
    adjustments,
    analyze,
    events,
    evidence,
    feedback,
    lab,
    live,
    meta,
    models,
    monitor,
    pipeline,
    portfolio,
    portfolios,
    propagation,
    scenarios,
    scope,
    signals,
    stress,
    watchlists,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    container = build_container(settings)  # fail at startup, loudly, on bad config/fixtures

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container
        stop = asyncio.Event()
        poller = None
        if container.live is not None and container.live.source is not None:
            poller = asyncio.create_task(container.live.run(stop), name="eventshock-live")
        warm = None
        if container.monitor is not None:
            # the first monitoring cycles are computed in the background
            task = asyncio.to_thread(container.monitor.warm)
            warm = asyncio.create_task(task, name="eventshock-monitor-warm")
        try:
            yield
        finally:
            stop.set()
            if warm is not None:
                warm.cancel()
            if poller is not None:
                poller.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poller

    app = FastAPI(
        title="EventShock API",
        version=__version__,
        description="Event-driven risk signals and deterministic portfolio stress testing. "
        "Replay profile: real source documents through the ingestion pipeline (trained sentiment and event "
        "models; impact is a trained, labelled model where one can score a signal and a labelled "
        "placeholder rule elsewhere); "
        "demo profile: fixtures. The stress engine is real in both.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.container = container  # also available to TestClient without lifespan
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    for r in (meta.router, pipeline.router, models.router, evidence.router, signals.router, portfolio.router,
              portfolios.router, scenarios.router, stress.router, analyze.router, live.router, scope.router,
              propagation.router, adjustments.router, monitor.router, events.router, watchlists.router,
              lab.router, feedback.router):
        app.include_router(r, prefix="/api")

    dist = settings.web_dist_dir
    if (dist / "index.html").is_file():
        root = dist.resolve()

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(root / "index.html")

    return app
