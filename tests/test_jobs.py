"""Job claiming, including the concurrency guarantees."""
import threading

import psycopg
from psycopg.rows import dict_row

from app import jobs
from tests.helpers import seed_job

LEASE = 300


def connect(url, **kw):
    return psycopg.connect(url, row_factory=dict_row, **kw)


def test_claim_on_empty_queue_returns_none(conn):
    assert jobs.claim_job(conn, LEASE) is None


def test_claim_marks_job_running_and_counts_the_attempt(conn):
    seed_job(conn)
    job = jobs.claim_job(conn, LEASE)
    assert job["status"] == "running"
    assert job["attempts"] == 1
    assert job["locked_at"] is not None
    assert jobs.claim_job(conn, LEASE) is None  # nothing left to claim


def test_future_job_is_not_claimed(conn):
    seed_job(conn, run_in="1 hour")
    assert jobs.claim_job(conn, LEASE) is None


def test_most_overdue_job_is_claimed_first(conn):
    seed_job(conn, "b1", run_in="-3 days")
    seed_job(conn, "b2", run_in="-1 day")
    seed_job(conn, "b3", run_in="-2 days")
    order = [jobs.claim_job(conn, LEASE)["booking_id"] for _ in range(3)]
    assert order == ["b1", "b3", "b2"]


def test_only_pending_jobs_are_claimable(conn):
    for i, status in enumerate(["succeeded", "dead", "cancelled"]):
        seed_job(conn, f"b{i}", status=status, run_in="-1 day")
    assert jobs.claim_job(conn, LEASE) is None


def test_skip_locked_second_worker_gets_a_different_job_without_waiting(test_db_url, conn):
    """While worker A holds job X locked (uncommitted), worker B must skip X
    and take Y, instead of blocking on X or double-claiming it."""
    seed_job(conn, "b1", run_in="-2 hours")
    seed_job(conn, "b2", run_in="-1 hour")

    with connect(test_db_url) as a, connect(test_db_url) as b, connect(test_db_url) as c:
        # If SKIP LOCKED were missing, B would wait here; fail fast instead of hanging.
        b.execute("SET lock_timeout = '3s'")
        c.execute("SET lock_timeout = '3s'")

        job_a = jobs.claim_job(a, LEASE)  # NOT committed: row stays locked
        job_b = jobs.claim_job(b, LEASE)
        assert job_a["booking_id"] == "b1"
        assert job_b["booking_id"] == "b2"
        assert job_a["id"] != job_b["id"]

        # Both rows are locked now; a third worker sees an empty queue, no waiting.
        assert jobs.claim_job(c, LEASE) is None

        # A crashes before committing: its claim is undone, the job is free again.
        a.rollback()
        b.rollback()
        again = jobs.claim_job(c, LEASE)
        assert again["booking_id"] == "b1"
        c.rollback()


def test_many_concurrent_workers_never_claim_the_same_job(test_db_url, conn):
    n_jobs, n_workers = 24, 8
    for i in range(n_jobs):
        seed_job(conn, f"b{i}", run_in="-1 minute")

    claimed: list[int] = []
    lock = threading.Lock()
    errors: list[Exception] = []
    barrier = threading.Barrier(n_workers)

    def worker():
        try:
            with connect(test_db_url, autocommit=True) as c:
                barrier.wait()
                while (job := jobs.claim_job(c, LEASE)) is not None:
                    with lock:
                        claimed.append(job["id"])
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert not errors
    assert len(claimed) == n_jobs  # every job was claimed...
    assert len(set(claimed)) == n_jobs  # ...exactly once
    rows = conn.execute("SELECT attempts, status FROM jobs").fetchall()
    assert all(r["attempts"] == 1 and r["status"] == "running" for r in rows)


def test_job_stuck_running_is_reclaimed_after_the_lease_expires(conn):
    seed_job(conn, "b1", status="running", attempts=1, locked_ago="10 minutes")
    job = jobs.claim_job(conn, LEASE)
    assert job is not None and job["attempts"] == 2


def test_running_job_within_its_lease_is_left_alone(conn):
    seed_job(conn, "b1", status="running", attempts=1, locked_ago="1 minute")
    assert jobs.claim_job(conn, LEASE) is None


def test_stale_worker_cannot_overwrite_after_losing_its_lease(conn):
    seed_job(conn, "b1")
    stale = jobs.claim_job(conn, LEASE)  # attempt 1
    conn.execute("UPDATE jobs SET locked_at = now() - interval '1 hour'")
    fresh = jobs.claim_job(conn, LEASE)  # another worker, attempt 2
    assert fresh["attempts"] == 2

    assert jobs.mark_succeeded(conn, stale) is False  # stale result ignored
    assert conn.execute("SELECT status FROM jobs").fetchone()["status"] == "running"
    assert jobs.mark_succeeded(conn, fresh) is True
