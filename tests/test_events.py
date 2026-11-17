import json
import threading
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from app.events import ACCEPTED, DUPLICATE, ingest_event
from app.schemas import EVENT_ADAPTER
from tests.helpers import cancelled_event, created_event, post_event


def count(conn, table):
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def test_created_event_creates_booking_and_one_reminder_job(client, conn):
    payload = created_event(hours_ahead=72)
    r = post_event(client, payload)
    assert r.status_code == 200
    assert r.json() == {"status": "accepted", "event_id": "evt_1"}

    assert count(conn, "events") == 1
    booking = conn.execute("SELECT * FROM bookings WHERE id = 'b1'").fetchone()
    assert booking["status"] == "active"
    job = conn.execute("SELECT * FROM jobs WHERE booking_id = 'b1'").fetchone()
    assert job["status"] == "pending"
    # default lead time is 24h before the booking starts
    expected = booking["starts_at"] - timedelta(hours=24)
    assert abs((job["run_at"] - expected).total_seconds()) < 1


def test_duplicate_event_returns_200_and_has_no_extra_effect(client, conn):
    payload = created_event()
    first = post_event(client, payload)
    second = post_event(client, payload)
    third = post_event(client, payload)
    assert first.status_code == second.status_code == third.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"
    assert third.json()["status"] == "duplicate"
    assert count(conn, "events") == 1
    assert count(conn, "bookings") == 1
    assert count(conn, "jobs") == 1


def test_concurrent_duplicate_deliveries_are_applied_exactly_once(settings, test_db_url, conn):
    """Race: many deliveries of the same event id at the same instant."""
    event = EVENT_ADAPTER.validate_python(created_event())
    raw = created_event()
    n = 8
    barrier = threading.Barrier(n)
    outcomes, errors = [], []

    def deliver():
        try:
            with psycopg.connect(test_db_url) as c:  # commits on clean exit
                barrier.wait()
                outcomes.append(ingest_event(c, event, raw, settings))
        except Exception as exc:  # pragma: no cover - would fail the test below
            errors.append(exc)

    threads = [threading.Thread(target=deliver) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert not errors
    assert outcomes.count(ACCEPTED) == 1
    assert outcomes.count(DUPLICATE) == n - 1
    assert count(conn, "events") == 1
    assert count(conn, "jobs") == 1


def test_different_event_ids_for_same_booking_do_not_duplicate_the_job(client, conn):
    post_event(client, created_event(event_id="evt_a"))
    post_event(client, created_event(event_id="evt_b"))
    assert count(conn, "events") == 2
    assert count(conn, "jobs") == 1


def test_invalid_json_with_valid_signature_is_400(client, conn):
    r = post_event(client, None, raw=b"{not json")
    assert r.status_code == 400
    assert count(conn, "events") == 0


def test_unknown_event_type_is_422(client, conn):
    r = post_event(client, {"id": "evt_x", "type": "booking.exploded", "data": {}})
    assert r.status_code == 422
    assert count(conn, "events") == 0


def test_naive_timestamp_is_422(client, conn):
    payload = created_event()
    payload["data"]["starts_at"] = "2030-01-01T10:00:00"  # no timezone
    assert post_event(client, payload).status_code == 422


def test_422_response_does_not_echo_customer_data(client):
    payload = created_event(email="not-an-email")
    r = post_event(client, payload)
    assert r.status_code == 422
    assert "not-an-email" not in r.text


def test_booking_in_the_past_creates_no_job(client, conn):
    r = post_event(client, created_event(hours_ahead=-5))
    assert r.status_code == 200
    assert count(conn, "bookings") == 1
    assert count(conn, "jobs") == 0


def test_reminder_time_already_passed_runs_immediately(client, conn):
    post_event(client, created_event(hours_ahead=2))  # reminder was due 22h ago
    job = conn.execute("SELECT run_at FROM jobs").fetchone()
    assert job["run_at"] <= datetime.now(timezone.utc)


def test_cancel_before_create_keeps_booking_cancelled_and_makes_no_job(client, conn):
    assert post_event(client, cancelled_event(booking_id="b9")).status_code == 200
    assert post_event(client, created_event(booking_id="b9")).status_code == 200
    booking = conn.execute("SELECT * FROM bookings WHERE id = 'b9'").fetchone()
    assert booking["status"] == "cancelled"
    assert booking["customer_email"] == "ada@example.com"  # details filled in
    assert count(conn, "jobs") == 0


def test_failure_while_applying_effects_rolls_back_the_event_row(settings, test_db_url, conn):
    """If effects fail, the event id must NOT be recorded; else a retry would be
    wrongly treated as a duplicate and the reminder lost."""
    event = EVENT_ADAPTER.validate_python(created_event())
    with psycopg.connect(test_db_url) as c:
        # DDL is transactional in Postgres: this rename is undone by the rollback
        # below, so the schema is left untouched. It makes the job insert fail.
        c.execute("ALTER TABLE jobs RENAME TO jobs_tmp")
        with pytest.raises(psycopg.errors.UndefinedTable):
            ingest_event(c, event, created_event(), settings)
        c.rollback()
    assert count(conn, "events") == 0
    assert count(conn, "bookings") == 0
