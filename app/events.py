"""Event ingestion: idempotency + business effects, in ONE transaction.

Why one transaction: if we recorded the event id first and crashed before
creating the job, the sender's retry would be seen as a duplicate and the
reminder would be lost forever. With one transaction, either the event id AND
its effects are saved, or neither is and a retry starts clean.
"""
import logging

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.config import Settings
from app.schemas import BookingCancelledEvent, BookingCreatedEvent

log = logging.getLogger("reminder.events")

ACCEPTED = "accepted"
DUPLICATE = "duplicate"


def ingest_event(conn: Connection, event, raw_payload: dict, settings: Settings) -> str:
    """Record the event and apply its effects. Caller owns the transaction.

    Returns ACCEPTED for a new event, DUPLICATE if this event id was seen before.
    """
    # Atomic "have I seen this id?" check. A second concurrent insert of the
    # same id BLOCKS on the unique index until the first transaction commits,
    # then conflicts and returns no row. A returned row means new event.
    row = conn.execute(
        "INSERT INTO events (id, type, payload) VALUES (%s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING RETURNING id",
        (event.id, event.type, Jsonb(raw_payload)),
    ).fetchone()
    if row is None:
        return DUPLICATE

    if isinstance(event, BookingCreatedEvent):
        _apply_booking_created(conn, event, settings)
    elif isinstance(event, BookingCancelledEvent):
        _apply_booking_cancelled(conn, event)
    return ACCEPTED


def _apply_booking_created(conn: Connection, event: BookingCreatedEvent, settings: Settings):
    d = event.data
    # New booking -> insert. Existing row -> only fill in details if it is a
    # placeholder created by an early cancellation (email IS NULL); never
    # change status, so a cancelled booking stays cancelled.
    conn.execute(
        "INSERT INTO bookings (id, customer_email, customer_name, starts_at) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET "
        "  customer_email = EXCLUDED.customer_email, "
        "  customer_name = EXCLUDED.customer_name, "
        "  starts_at = EXCLUDED.starts_at, "
        "  updated_at = now() "
        "WHERE bookings.customer_email IS NULL",
        (d.booking_id, d.customer_email, d.customer_name, d.starts_at),
    )
    # Schedule the reminder only for an active booking that has not started.
    # GREATEST(..., now()): if the reminder time already passed, send it now.
    # The unique index (booking_id, kind) makes this safe to repeat.
    conn.execute(
        "INSERT INTO jobs (booking_id, run_at, max_attempts) "
        "SELECT b.id, GREATEST(b.starts_at - make_interval(hours => %s), now()), %s "
        "FROM bookings b "
        "WHERE b.id = %s AND b.status = 'active' AND b.starts_at > now() "
        "ON CONFLICT (booking_id, kind) DO NOTHING",
        (settings.reminder_lead_hours, settings.max_attempts, d.booking_id),
    )


def _apply_booking_cancelled(conn: Connection, event: BookingCancelledEvent):
    booking_id = event.data.booking_id
    # Upsert: also handles a cancellation that arrives BEFORE its creation.
    conn.execute(
        "INSERT INTO bookings (id, status) VALUES (%s, 'cancelled') "
        "ON CONFLICT (id) DO UPDATE SET status = 'cancelled', updated_at = now()",
        (booking_id,),
    )
    # Only PENDING jobs are cancelled. A job already 'running' is handled by the
    # worker, which re-checks the booking status before sending (see worker.py).
    cur = conn.execute(
        "UPDATE jobs SET status = 'cancelled', updated_at = now() "
        "WHERE booking_id = %s AND status = 'pending'",
        (booking_id,),
    )
    log.info(
        "booking cancelled",
        extra={"booking_id": booking_id, "jobs_cancelled": cur.rowcount},
    )
