# LEARNING_LOG

## Concepts I can now explain
_(add an entry only when you could explain it to the panel without notes)_

## Still unclear
- Sync vs async Python (`async`/`await`): not yet learned; deliberately deferred.
- SQL beyond simple SELECTs: transactions, `ON CONFLICT`, `RETURNING`, locking (SQL primer block).
- Pooled vs direct Postgres connections (PgBouncer): to be learned in M1.


## Review checklist before the interview (added by the AI after the autonomous build)
For each, explain it aloud without looking, then tick it. Move it to "Concepts I can now explain" only when true.
- [ ] Why the signature is computed over the RAW body, and why `compare_digest`.
- [ ] `INSERT ... ON CONFLICT DO NOTHING RETURNING`: what comes back for new vs duplicate, and why the event insert and the effects share one transaction.
- [ ] What `FOR UPDATE SKIP LOCKED` does, and what goes wrong without it (see `tests/test_jobs.py`).
- [ ] Why the claim commits immediately (lease) instead of holding a transaction while sending.
- [ ] Why `attempts = attempts + 1` is done in SQL.
- [ ] Exponential backoff + jitter: what each part prevents.
- [ ] Why a running job is not cancelled by the event, and how the worker handles it.
- [ ] At-least-once vs exactly-once sending.
- [ ] Pooled (PgBouncer) vs direct connection, and why prepared statements are off.
- [ ] Why `def` endpoints are fine for blocking DB calls (thread pool) and what `async def` would change.
- [ ] Fixed-window rate limiting: the 2x boundary burst, and why in-memory limits do not scale across processes.

## From running this twice
INSERT INTO scratch.events (id, type) VALUES ('evt_1', 'booking.created');

ERROR: duplicate key value violates unique constraint "events_pkey" (SQLSTATE 23505)
DETAIL: Key (id)=(evt_1) already exists.
