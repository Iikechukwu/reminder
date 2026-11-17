-- Every webhook event we have accepted. The PRIMARY KEY on id is what makes
-- ingestion idempotent: a second INSERT of the same id conflicts.
CREATE TABLE events (
    id          text PRIMARY KEY,
    type        text NOT NULL,
    payload     jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bookings (
    id             text PRIMARY KEY,
    customer_email text NOT NULL,
    customer_name  text NOT NULL,
    starts_at      timestamptz NOT NULL,
    status         text NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'cancelled')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- The job queue. A "job" here is "send the reminder for this booking".
-- States: pending -> running -> succeeded
--                    running -> pending (retry, with a later run_at)
--                    running -> dead    (retries exhausted: dead-letter)
--         pending -> cancelled          (booking cancelled)
CREATE TABLE jobs (
    id           bigserial PRIMARY KEY,
    booking_id   text NOT NULL REFERENCES bookings (id),
    kind         text NOT NULL DEFAULT 'reminder',
    status       text NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'running', 'succeeded', 'dead', 'cancelled')),
    run_at       timestamptz NOT NULL DEFAULT now(),
    attempts     integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    locked_at    timestamptz,
    last_error   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- At most one reminder job per booking, even if events are replayed.
CREATE UNIQUE INDEX jobs_one_per_booking_kind ON jobs (booking_id, kind);

-- Lets the worker find "due pending jobs" without scanning the whole table.
CREATE INDEX jobs_due_idx ON jobs (run_at, id) WHERE status = 'pending';
