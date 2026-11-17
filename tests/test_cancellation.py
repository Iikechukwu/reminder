from app import jobs
from tests.helpers import cancelled_event, created_event, post_event, seed_job


def statuses(conn):
    rows = conn.execute("SELECT booking_id, status FROM jobs ORDER BY booking_id").fetchall()
    return {r["booking_id"]: r["status"] for r in rows}


def test_cancel_event_cancels_the_pending_reminder(client, conn):
    post_event(client, created_event(event_id="e1", booking_id="b1"))
    assert statuses(conn) == {"b1": "pending"}

    r = post_event(client, cancelled_event(event_id="e2", booking_id="b1"))
    assert r.status_code == 200
    assert statuses(conn) == {"b1": "cancelled"}
    assert conn.execute("SELECT status FROM bookings").fetchone()["status"] == "cancelled"


def test_cancelled_job_is_never_claimed(client, conn):
    post_event(client, created_event(booking_id="b1", hours_ahead=2))  # due now
    post_event(client, cancelled_event(booking_id="b1"))
    assert jobs.claim_job(conn, 300) is None


def test_cancelling_one_booking_leaves_others_alone(client, conn):
    post_event(client, created_event(event_id="e1", booking_id="b1"))
    post_event(client, created_event(event_id="e2", booking_id="b2"))
    post_event(client, cancelled_event(event_id="e3", booking_id="b1"))
    assert statuses(conn) == {"b1": "cancelled", "b2": "pending"}


def test_cancel_does_not_rewrite_history_of_finished_jobs(client, conn):
    seed_job(conn, "b1", status="succeeded")
    post_event(client, cancelled_event(booking_id="b1"))
    assert statuses(conn) == {"b1": "succeeded"}


def test_cancel_also_cancels_a_job_waiting_for_retry(client, conn):
    seed_job(conn, "b1", status="pending", attempts=2, run_in="10 minutes")
    post_event(client, cancelled_event(booking_id="b1"))
    assert statuses(conn) == {"b1": "cancelled"}


def test_cancel_does_not_touch_a_job_that_is_already_running(client, conn):
    """Documented behaviour: a running job is left to the worker, which re-checks
    the booking before sending (see test_worker)."""
    seed_job(conn, "b1", status="running", attempts=1, locked_ago="5 seconds")
    post_event(client, cancelled_event(booking_id="b1"))
    assert statuses(conn) == {"b1": "running"}


def test_duplicate_cancel_event_is_harmless(client, conn):
    post_event(client, created_event(booking_id="b1"))
    first = post_event(client, cancelled_event(event_id="e2", booking_id="b1"))
    second = post_event(client, cancelled_event(event_id="e2", booking_id="b1"))
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"
    assert statuses(conn) == {"b1": "cancelled"}
