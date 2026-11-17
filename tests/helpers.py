import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from tests.conftest import TEST_SECRET


def sign(body: bytes, secret: str = TEST_SECRET) -> str:
    """Independent re-implementation of the signature, so tests do not simply
    check app.security against itself."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def created_event(event_id="evt_1", booking_id="b1", hours_ahead=72, email="ada@example.com"):
    return {
        "id": event_id,
        "type": "booking.created",
        "data": {
            "booking_id": booking_id,
            "customer_email": email,
            "customer_name": "Ada",
            "starts_at": (datetime.now(timezone.utc) + timedelta(hours=hours_ahead)).isoformat(),
        },
    }


def cancelled_event(event_id="evt_2", booking_id="b1"):
    return {"id": event_id, "type": "booking.cancelled", "data": {"booking_id": booking_id}}


def seed_job(
    conn,
    booking_id="b1",
    *,
    status="pending",
    run_in="0 seconds",
    attempts=0,
    max_attempts=5,
    booking_status="active",
    locked_ago=None,
):
    """Insert a booking (if missing) and a reminder job directly. Returns the job row.

    run_in:    interval relative to now(); negative = overdue, e.g. '-1 day'.
    locked_ago: interval string like '10 minutes' (sets locked_at), or None.
    """
    conn.execute(
        "INSERT INTO bookings (id, customer_email, customer_name, starts_at, status) "
        "VALUES (%s, %s, 'Ada', now() + interval '3 days', %s) ON CONFLICT (id) DO NOTHING",
        (booking_id, f"{booking_id}@example.com", booking_status),
    )
    return conn.execute(
        "INSERT INTO jobs (booking_id, status, run_at, attempts, max_attempts, locked_at) "
        "VALUES (%s, %s, now() + %s::interval, %s, %s, now() - %s::interval) RETURNING *",
        (booking_id, status, run_in, attempts, max_attempts, locked_ago),
    ).fetchone()


def post_event(client, payload, *, secret=TEST_SECRET, signature=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    sig = signature if signature is not None else sign(body, secret)
    headers["X-Signature"] = sig
    return client.post("/events", content=body, headers=headers)
