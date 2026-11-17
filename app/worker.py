"""The reminder worker: claims due jobs and sends the reminder.

Run with the DIRECT Neon URL:   python -m app.worker
"""
import logging
import random
import signal
import threading

from psycopg_pool import ConnectionPool

from app import jobs
from app.backoff import backoff_delay
from app.config import Settings
from app.db import make_pool
from app.email_provider import EmailProvider, MockEmailProvider
from app.logging_config import configure_logging
from app.reminders import compose_reminder

log = logging.getLogger("reminder.worker")

# Outcomes of process_one
SENT, RETRY, DEAD, CANCELLED, LOST = "sent", "retry", "dead", "cancelled", "lease_lost"


def process_one(
    pool: ConnectionPool,
    settings: Settings,
    provider: EmailProvider,
    rng=random.random,
) -> str | None:
    """Claim and process at most one job. Returns the outcome, or None if idle."""
    with pool.connection() as conn:
        job = jobs.claim_job(conn, settings.visibility_timeout_seconds)
    if job is None:
        return None

    ctx = {"job_id": job["id"], "booking_id": job["booking_id"], "attempt": job["attempts"]}

    # A previous attempt may have crashed the worker while 'running'. Each
    # re-claim counts as an attempt, so a poison job cannot crash workers forever.
    if job["attempts"] > job["max_attempts"]:
        with pool.connection() as conn:
            jobs.mark_dead(conn, job, "exceeded max attempts (worker crashed mid-job?)")
        log.error("job dead: attempts exhausted by crashes", extra=ctx)
        return DEAD

    # Re-check the booking AFTER claiming: it may have been cancelled while the
    # job was already running (cancellation only touches pending jobs).
    with pool.connection() as conn:
        booking = conn.execute(
            "SELECT * FROM bookings WHERE id = %s", (job["booking_id"],)
        ).fetchone()
    if booking is None or booking["status"] != "active":
        with pool.connection() as conn:
            jobs.mark_cancelled(conn, job)
        log.info("job cancelled: booking no longer active", extra=ctx)
        return CANCELLED

    try:
        subject, body = compose_reminder(booking, settings)
        provider.send(booking["customer_email"], subject, body)
    except Exception as exc:  # any provider/compose failure is retried
        error = f"{type(exc).__name__}: {exc}"
        delay = backoff_delay(
            job["attempts"], settings.backoff_base_seconds, settings.backoff_cap_seconds, rng
        )
        with pool.connection() as conn:
            new_status = jobs.mark_failed(conn, job, error, delay)
        if new_status is None:
            log.warning("lease lost while recording failure", extra=ctx)
            return LOST
        if new_status == "dead":
            log.error("job dead-lettered", extra={**ctx, "error": error})
            return DEAD
        log.warning(
            "job failed, will retry", extra={**ctx, "error": error, "retry_in_s": round(delay, 1)}
        )
        return RETRY

    with pool.connection() as conn:
        ok = jobs.mark_succeeded(conn, job)
    if not ok:
        log.warning("lease lost before recording success", extra=ctx)
        return LOST
    log.info("reminder sent", extra=ctx)
    return SENT


def run_worker(settings: Settings, provider: EmailProvider, stop: threading.Event) -> None:
    pool = make_pool(settings.database_url_direct, max_size=3)
    log.info("worker started")
    try:
        while not stop.is_set():
            try:
                outcome = process_one(pool, settings, provider)
            except Exception:
                # e.g. a dropped connection: log, back off, keep the loop alive.
                log.exception("worker iteration failed")
                stop.wait(settings.worker_poll_interval_seconds)
                continue
            if outcome is None:  # idle: nothing due
                stop.wait(settings.worker_poll_interval_seconds)
    finally:
        pool.close()
        log.info("worker stopped")


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    stop = threading.Event()
    # Finish the current job, then exit (Ctrl+C, or SIGTERM from a platform).
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run_worker(settings, MockEmailProvider(settings.mock_email_fail_rate), stop)


if __name__ == "__main__":
    main()
