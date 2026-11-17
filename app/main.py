"""FastAPI application factory.

Run with:  uvicorn --factory app.main:create_app
(a factory, so importing this module never needs real settings)
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.db import make_pool
from app.logging_config import configure_logging, request_id_var
from app.ratelimit import FixedWindowLimiter
from app.routes import router

log = logging.getLogger("reminder.http")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.pool = make_pool(settings.database_url)
        app.state.limiter = FixedWindowLimiter(settings.rate_limit_per_minute, 60.0)
        try:
            yield
        finally:
            app.state.pool.close()

    app = FastAPI(
        title="Reminder service",
        description=(
            "Webhook-driven booking reminders with a Postgres-backed job queue.\n\n"
            "Send signed `booking.created` / `booking.cancelled` events to `POST /events`; "
            "a separate worker process sends the reminders."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = uuid.uuid4().hex
        request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"method": request.method, "path": request.url.path})
            raise
        response.headers["X-Request-ID"] = request_id
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "api_key": getattr(request.state, "api_key_name", None),
            },
        )
        return response

    # Plain `def` endpoint on purpose: FastAPI runs it in a worker thread, so a
    # blocking database call does not stall the event loop.
    @app.get("/health", tags=["ops"])
    def health(request: Request):
        """Liveness + database connectivity. Public (no API key)."""
        try:
            with request.app.state.pool.connection() as conn:
                conn.execute("SELECT 1")
        except Exception:
            log.exception("health check failed")
            return JSONResponse({"status": "unhealthy", "db": "down"}, status_code=503)
        return {"status": "ok", "db": "ok"}

    app.include_router(router)
    return app
