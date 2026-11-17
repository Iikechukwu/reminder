"""The Postgres-backed job queue: claim, complete, fail, cancel.

Design: a worker CLAIMS a job in one short transaction that flips it to
'running' and COMMITS. It does NOT hold a transaction (and its row lock) open
while it calls the slow external email provider. The 'running' status plus
`locked_at` is the lease; a job whose lease expired (worker crashed) can be
claimed again.
"""
from psycopg import Connection

# One statement does find + lock + mark + return, atomically.
#
# FOR UPDATE      locks the chosen row so no one else can change it meanwhile.
# SKIP LOCKED     rows locked by another transaction are skipped instead of
#                 waited for, so concurrent workers each get a DIFFERENT job
#                 and never block each other.
# attempts + 1    done in SQL: the database applies it atomically.
#
# ORDER BY run_at, id: oldest-due first (not just id), because retried jobs are
# re-scheduled with a later run_at.
CLAIM_SQL = """
UPDATE jobs
SET status = 'running',
    attempts = attempts + 1,
    locked_at = now(),
    updated_at = now()
WHERE id = (
    SELECT id FROM jobs
    WHERE (status = 'pending' AND run_at <= now())
       OR (status = 'running' AND locked_at < now() - make_interval(secs => %(lease)s))
    ORDER BY run_at, id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING *
"""


def claim_job(conn: Connection, lease_seconds: float) -> dict | None:
    """Claim the next due job, or return None if there is none."""
    return conn.execute(CLAIM_SQL, {"lease": lease_seconds}).fetchone()


# The `attempts = %s` condition is a fencing token. If our lease expired and
# another worker re-claimed the job, attempts has changed, so our late result
# is ignored instead of overwriting theirs. Returns False if we lost the lease.


def mark_succeeded(conn: Connection, job: dict) -> bool:
    cur = conn.execute(
        "UPDATE jobs SET status = 'succeeded', locked_at = NULL, last_error = NULL, "
        "updated_at = now() WHERE id = %s AND status = 'running' AND attempts = %s",
        (job["id"], job["attempts"]),
    )
    return cur.rowcount == 1


def mark_cancelled(conn: Connection, job: dict) -> bool:
    cur = conn.execute(
        "UPDATE jobs SET status = 'cancelled', locked_at = NULL, updated_at = now() "
        "WHERE id = %s AND status = 'running' AND attempts = %s",
        (job["id"], job["attempts"]),
    )
    return cur.rowcount == 1


def mark_failed(conn: Connection, job: dict, error: str, delay_seconds: float) -> str | None:
    """Record a failed attempt.

    Out of attempts -> 'dead' (dead-letter: kept for inspection, never retried
    automatically). Otherwise back to 'pending' with run_at pushed into the
    future by the backoff delay. Returns the new status, or None if the lease
    was lost.
    """
    row = conn.execute(
        "UPDATE jobs SET "
        "  status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END, "
        "  run_at = CASE WHEN attempts >= max_attempts THEN run_at "
        "                ELSE now() + make_interval(secs => %s) END, "
        "  last_error = %s, locked_at = NULL, updated_at = now() "
        "WHERE id = %s AND status = 'running' AND attempts = %s "
        "RETURNING status",
        (delay_seconds, error[:500], job["id"], job["attempts"]),
    ).fetchone()
    return row["status"] if row else None


def mark_dead(conn: Connection, job: dict, error: str) -> bool:
    cur = conn.execute(
        "UPDATE jobs SET status = 'dead', last_error = %s, locked_at = NULL, "
        "updated_at = now() WHERE id = %s AND status = 'running' AND attempts = %s",
        (error[:500], job["id"], job["attempts"]),
    )
    return cur.rowcount == 1


def requeue_dead(conn: Connection, job_id: int) -> bool:
    """Operator action: give a dead-lettered job a fresh set of attempts."""
    cur = conn.execute(
        "UPDATE jobs SET status = 'pending', attempts = 0, run_at = now(), "
        "last_error = NULL, updated_at = now() WHERE id = %s AND status = 'dead'",
        (job_id,),
    )
    return cur.rowcount == 1
