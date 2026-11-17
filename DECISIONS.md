# DECISIONS

One entry per decision. **IMPORTANT:** every entry below was written by the AI
during the autonomous build you requested. The "My reasoning" lines are empty on
purpose: they must be filled in **in your own words**, and you should only keep
a decision whose reasoning you can defend aloud. Rewrite or reject any you
disagree with.

## Template

### D<N>: <title> (Milestone <M>)
- **Decision:**
- **Alternatives considered:**
- **My reasoning (own words):**
- **Trade-offs I accept:**

---

### D1: Neon Postgres for dev, test and (later) deployment (M0)
- **Decision:** Neon free tier; `production` branch for dev data, `test` branch for pytest.
- **Alternatives considered:** local Postgres install; Docker Postgres; SQLite.
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** network latency makes the test suite slow; free tier auto-suspends; SQLite was never an option because `SKIP LOCKED` needs real Postgres.

### D2: Synchronous FastAPI endpoints + psycopg 3 (M1)
- **Decision:** plain `def` endpoints (run in FastAPI's thread pool) with a blocking connection pool. Only the signature dependency is `async`, because reading the raw body needs `await`.
- **Alternatives considered:** fully async (asyncpg / psycopg async); an ORM (SQLAlchemy).
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** fewer concurrent connections per process than async; in return the code is simple enough to explain line by line. Raw SQL instead of an ORM keeps the queue queries (`SKIP LOCKED`, `ON CONFLICT`) visible.

### D3: Plain SQL migrations with a ~40-line runner (M1)
- **Decision:** `migrations/NNN_name.sql`, applied in order, each in a transaction, tracked in `schema_migrations`, guarded by an advisory lock.
- **Alternatives considered:** Alembic (needs SQLAlchemy); hand-run SQL.
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** no autogenerate, no downgrade scripts; migrations are append-only (`002` fixes `001`'s assumptions rather than editing it).

### D4: Signature = HMAC-SHA256 over the raw body, `X-Signature: sha256=<hex>` (M2)
- **Decision:** verify before parsing; `hmac.compare_digest`.
- **Alternatives considered:** also sign a timestamp (Stripe style) for a replay window; verify the re-serialised JSON.
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** no replay window (idempotency makes replays harmless for events); re-serialised JSON was rejected because whitespace/key order would break the match.

### D5: Idempotency check and business effects in ONE transaction (M2)
- **Decision:** `INSERT ... ON CONFLICT (id) DO NOTHING RETURNING id`, then apply effects in the same transaction. No row returned = duplicate, still 200.
- **Alternatives considered:** SELECT-then-INSERT (race); record the event first in its own transaction then process (crash loses the reminder); catch the unique-violation error.
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** a concurrent duplicate waits for the first transaction to finish before answering.

### D6: Claim by flipping status to `running` and committing (lease), not by holding a transaction (M3)
- **Decision:** single `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`; `attempts + 1` in SQL; `locked_at` is a lease, expired leases are re-claimed; results are fenced with `attempts = <claimed value>`.
- **Alternatives considered:** keep the claiming transaction open while sending (holds locks and a connection during slow network calls; a crash rolls back cleanly but throughput suffers); `LISTEN/NOTIFY` instead of polling.
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** at-least-once sending (crash after send, before marking succeeded, re-sends after the lease). Polling every 2 s adds up to 2 s latency.
- **Assumption beyond your brief:** you specified `ORDER BY id`; I used `ORDER BY run_at, id` because retried jobs get a later `run_at` and should not jump the queue by id.

### D7: Exponential backoff with FULL jitter (M4)
- **Decision:** `uniform(0, min(cap, base * 2^(attempt-1)))`; defaults base 30 s, cap 1 h, 5 attempts; then `dead`.
- **Alternatives considered:** equal jitter (half fixed + half random); no jitter; fixed delay.
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** a retry can occasionally happen almost immediately (random draw near 0).

### D8: Cancellation semantics (M4)
- **Decision:** cancel only `pending` jobs in SQL; the worker re-checks the booking after claiming; cancel-before-create stores a placeholder booking so a late `booking.created` cannot resurrect it; no reminder for bookings that already started.
- **Alternatives considered:** also cancel `running` jobs (cannot un-send); 409 on unknown booking and rely on sender retries.
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** a tiny window between the worker's re-check and the send.

### D9: `/events` needs API key AND signature; keys stored hashed (M5)
- **Decision:** order = API key + rate limit, then signature, then parse. SHA-256 of a 256-bit random key.
- **Alternatives considered:** signature only; bcrypt/argon2 for keys (pointless for high-entropy keys).
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** one DB lookup per request; the sender must hold two secrets.

### D10: In-memory fixed-window rate limiter (M5)
- **Decision:** per API key, per process, 60/min default.
- **Alternatives considered:** token bucket / sliding window; Postgres or Redis counters (correct across instances, costs a round trip per request).
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** up to 2x burst at window edges; limit multiplies with the number of API processes.

### D11: LLM step behind an interface, fake only, always falls back (M6)
- **Decision:** `LLMClient` protocol; timeout via a bounded thread pool; validate output; template fallback.
- **Alternatives considered:** a real provider (no key available); no validation.
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** a timed-out call keeps running in its thread (Python cannot kill threads); a real client must also set its own HTTP timeout.

### D12: Compose file written but untested (M5)
- **Decision:** ship `Dockerfile` + `docker-compose.yml`, labelled UNTESTED.
- **Alternatives considered:** omit them (the brief asked for Compose).
- **My reasoning (own words):** _TODO (you)_
- **Trade-offs I accept:** may contain errors until run on a machine with Docker.
