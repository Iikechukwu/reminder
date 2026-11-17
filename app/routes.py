"""HTTP routes."""
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app import jobs
from app.auth import authenticate
from app.events import ingest_event
from app.schemas import EVENT_ADAPTER
from app.security import SIGNATURE_HEADER, verify_signature

log = logging.getLogger("reminder.api")

router = APIRouter()


async def verified_body(
    request: Request,
    x_signature: str | None = Header(
        default=None,
        alias=SIGNATURE_HEADER,
        description="`sha256=` + hex HMAC-SHA256 of the raw request body, keyed with the shared secret.",
    ),
) -> bytes:
    """Read the raw body and reject the request unless its signature is valid.

    This runs BEFORE any JSON parsing: we do not touch untrusted content until
    we know it came from the holder of the shared secret.
    """
    body = await request.body()
    secret = request.app.state.settings.webhook_secret
    if not verify_signature(secret, body, x_signature):
        log.warning("webhook signature rejected")
        raise HTTPException(status_code=401, detail="invalid signature")
    return body


# Order matters: API key + rate limit first (cheap, stops floods), then the
# signature (proves the body is authentic), then parsing and the database.
@router.post("/events", tags=["events"], dependencies=[Depends(authenticate)])
def receive_event(request: Request, body: bytes = Depends(verified_body)):
    """Receive a signed `booking.created` or `booking.cancelled` event.

    Idempotent on the event id: re-delivery returns 200 with status "duplicate"
    and has no further effect.
    """
    try:
        event = EVENT_ADAPTER.validate_json(body)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
        status = 400 if any(e["type"] == "json_invalid" for e in errors) else 422
        return JSONResponse({"detail": errors}, status_code=status)

    settings = request.app.state.settings
    # `with pool.connection()` commits on success and rolls back on any exception.
    with request.app.state.pool.connection() as conn:
        outcome = ingest_event(conn, event, json.loads(body), settings)

    log.info(
        "event processed",
        extra={"event_id": event.id, "event_type": event.type, "outcome": outcome},
    )
    return {"status": outcome, "event_id": event.id}


@router.get("/bookings/{booking_id}", tags=["inspect"], dependencies=[Depends(authenticate)])
def get_booking(booking_id: str, request: Request):
    """A booking and the state of its reminder jobs."""
    with request.app.state.pool.connection() as conn:
        booking = conn.execute(
            "SELECT id, status, starts_at, created_at, updated_at FROM bookings WHERE id = %s",
            (booking_id,),
        ).fetchone()
        if booking is None:
            raise HTTPException(status_code=404, detail="booking not found")
        job_rows = conn.execute(
            "SELECT id, kind, status, run_at, attempts, max_attempts, last_error "
            "FROM jobs WHERE booking_id = %s ORDER BY id",
            (booking_id,),
        ).fetchall()
    return {**booking, "jobs": job_rows}


@router.get("/jobs", tags=["inspect"], dependencies=[Depends(authenticate)])
def list_jobs(
    request: Request,
    status: Literal["pending", "running", "succeeded", "dead", "cancelled"] | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    """List jobs, optionally filtered by status (e.g. `dead` for the dead-letter queue)."""
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, booking_id, kind, status, run_at, attempts, max_attempts, last_error "
            "FROM jobs WHERE (%s::text IS NULL OR status = %s) ORDER BY id DESC LIMIT %s",
            (status, status, limit),
        ).fetchall()
    return {"jobs": rows}


@router.post("/jobs/{job_id}/requeue", tags=["inspect"], dependencies=[Depends(authenticate)])
def requeue_job(job_id: int, request: Request):
    """Give a dead-lettered job a fresh set of attempts."""
    with request.app.state.pool.connection() as conn:
        if not jobs.requeue_dead(conn, job_id):
            raise HTTPException(status_code=404, detail="no dead job with that id")
    log.info("dead job requeued", extra={"job_id": job_id})
    return {"status": "requeued", "job_id": job_id}
