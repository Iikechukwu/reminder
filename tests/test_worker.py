"""Worker behaviour: success, retry with backoff, dead-letter, cancellation race."""
import threading

import pytest

from app import jobs
from app.email_provider import ProviderError
from app.worker import CANCELLED, DEAD, RETRY, SENT, process_one
from tests.helpers import seed_job


class RecordingProvider:
    def __init__(self):
        self.sent: list[str] = []
        self._lock = threading.Lock()

    def send(self, to, subject, body):
        with self._lock:
            self.sent.append(to)


class FailingProvider:
    def __init__(self, fail_times=10**9):
        self.calls = 0
        self.fail_times = fail_times

    def send(self, to, subject, body):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("boom")


def job_row(conn):
    return conn.execute("SELECT * FROM jobs").fetchone()


def make_due(conn):
    conn.execute("UPDATE jobs SET run_at = now() WHERE status = 'pending'")


HALF = lambda: 0.5  # noqa: E731  deterministic jitter


def test_idle_worker_returns_none(pool, settings):
    assert process_one(pool, settings, RecordingProvider()) is None


def test_successful_job_sends_once_and_is_marked_succeeded(pool, settings, conn):
    seed_job(conn, "b1")
    provider = RecordingProvider()
    assert process_one(pool, settings, provider) == SENT
    assert provider.sent == ["b1@example.com"]
    assert job_row(conn)["status"] == "succeeded"
    assert process_one(pool, settings, provider) is None  # not sent twice


def test_failure_schedules_a_retry_with_backoff(pool, settings, conn):
    seed_job(conn, "b1", max_attempts=5)
    assert process_one(pool, settings, FailingProvider(), rng=HALF) == RETRY
    j = job_row(conn)
    assert j["status"] == "pending"
    assert j["attempts"] == 1
    assert "ProviderError" in j["last_error"]
    # base=10 -> attempt 1 ceiling 10s; rng 0.5 -> exactly 5s after the failure
    assert (j["run_at"] - j["updated_at"]).total_seconds() == pytest.approx(5.0, abs=0.01)
    # not due yet, so it is not picked up straight away
    assert process_one(pool, settings, FailingProvider(), rng=HALF) is None


def test_backoff_grows_then_job_is_dead_lettered(pool, settings, conn):
    seed_job(conn, "b1", max_attempts=3)
    provider = FailingProvider()
    outcomes, delays = [], []
    for _ in range(3):
        make_due(conn)
        outcomes.append(process_one(pool, settings, provider, rng=HALF))
        j = job_row(conn)
        delays.append((j["run_at"] - j["updated_at"]).total_seconds())

    assert outcomes == [RETRY, RETRY, DEAD]
    assert delays[0] == pytest.approx(5.0, abs=0.01)  # 0.5 * 10
    assert delays[1] == pytest.approx(10.0, abs=0.01)  # 0.5 * 20
    j = job_row(conn)
    assert j["status"] == "dead"
    assert j["attempts"] == 3
    assert "ProviderError" in j["last_error"]
    # dead-letter: never picked up again automatically
    make_due(conn)
    conn.execute("UPDATE jobs SET run_at = now()")
    assert process_one(pool, settings, provider, rng=HALF) is None
    assert provider.calls == 3


def test_job_recovers_after_transient_failures(pool, settings, conn):
    seed_job(conn, "b1", max_attempts=5)
    provider = FailingProvider(fail_times=2)
    results = []
    for _ in range(3):
        make_due(conn)
        results.append(process_one(pool, settings, provider, rng=HALF))
    assert results == [RETRY, RETRY, SENT]
    j = job_row(conn)
    assert j["status"] == "succeeded" and j["attempts"] == 3
    assert j["last_error"] is None


def test_dead_job_can_be_requeued_by_an_operator(pool, settings, conn):
    seed_job(conn, "b1", status="dead", attempts=5)
    assert jobs.requeue_dead(conn, job_row(conn)["id"]) is True
    j = job_row(conn)
    assert j["status"] == "pending" and j["attempts"] == 0
    assert process_one(pool, settings, RecordingProvider()) == SENT


def test_job_crash_loop_is_stopped_after_max_attempts(pool, settings, conn):
    """A worker that dies mid-job leaves it 'running'. Each re-claim counts as an
    attempt, so after max_attempts it is dead-lettered, not retried forever."""
    seed_job(conn, "b1", status="running", attempts=3, max_attempts=3, locked_ago="10 minutes")
    provider = RecordingProvider()
    assert process_one(pool, settings, provider) == DEAD
    assert provider.sent == []
    assert job_row(conn)["status"] == "dead"


def test_booking_cancelled_while_job_was_running_is_not_sent(pool, settings, conn):
    """Cancellation only touches PENDING jobs; the worker must re-check the
    booking after claiming. Simulate the cancel landing after the claim."""
    seed_job(conn, "b1")
    conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = 'b1'")
    provider = RecordingProvider()
    assert process_one(pool, settings, provider) == CANCELLED
    assert provider.sent == []
    assert job_row(conn)["status"] == "cancelled"


def test_several_workers_send_each_reminder_exactly_once(pool, settings, conn):
    n = 12
    for i in range(n):
        seed_job(conn, f"b{i}", run_in="-1 minute")
    provider = RecordingProvider()

    def run():
        while process_one(pool, settings, provider) is not None:
            pass

    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert sorted(provider.sent) == sorted(f"b{i}@example.com" for i in range(n))
    statuses = {r["status"] for r in conn.execute("SELECT status FROM jobs").fetchall()}
    assert statuses == {"succeeded"}
