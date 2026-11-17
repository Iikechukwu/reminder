# AI_USAGE

Honest record of how AI was used. Mistakes the AI made that I caught go in their own column.

## Template

### <Milestone / step>
- **What I asked:**
- **What the AI produced:**
- **What I changed or rejected, and why:**
- **Mistakes the AI made that I caught:**
- **Code I wrote myself (core logic):**

---

### M0: repo setup
- **What I asked:** Set up the project scaffolding for a webhook reminder service.
- **What the AI produced:** `.gitignore`, `.env.example`, and templates for DECISIONS.md, AI_USAGE.md, LEARNING_LOG.md.
- **What I changed or rejected, and why:** _(fill in after you review the files)_
- **Mistakes the AI made that I caught:** none.
- **Code I wrote myself:** none (no application code in M0).

### SQL primer (Parts A and B)
- **What I asked:** Learn `ON CONFLICT`, `RETURNING`, transactions, `UPDATE ... RETURNING` by hand in the Neon SQL editor.
- **What the AI produced:** the table definitions and exercise prompts only; it did not write the queries.
- **What I changed or rejected, and why:** I wrote A3, A4, B1, B2, B3 myself.
- **Mistakes I made that the AI caught (honest record):** my first explanation of A4 said a duplicate "returns the id" (it returns no row); my B2 query had a trailing comma and did not run.
- **Code I wrote myself:** the primer queries. Part C (`SKIP LOCKED` with two sessions) was skipped at my request.

### M1-M6: autonomous build (my instruction: "Build the rest of the plan autonomously")
- **What I asked:** after finishing Neon setup, I told the AI to build the whole plan itself with specified patterns (idempotent ingest query, `SKIP LOCKED` claim query, SQL-side `attempts + 1`, tests only on the test branch, pooled/direct URLs).
- **What the AI produced:** everything under `app/`, `migrations/`, `tests/`, `README.md`, `Dockerfile`, `docker-compose.yml`, and the entries in DECISIONS.md.
- **IMPORTANT, read before the interview:** this deviates from the original rules ("I write the core logic myself"). The AI wrote ALL core logic: signature verification, the idempotency query, the claim query, the backoff function, the cancellation queries, the rate limiter. **None of it is my own code.** Do not say in the interview that you wrote it. What you can honestly say: you specified the architecture and patterns, directed an AI agent, ran the tests, and reviewed the result. That only holds if you actually do the review below.
- **Things the AI added or decided beyond my brief (check each; keep or reject):**
  - `ORDER BY run_at, id` instead of `ORDER BY id` in the claim query.
  - Lease re-claim of stuck `running` jobs and the `attempts = <claimed>` fencing check.
  - Placeholder booking rows for cancel-before-create (`migrations/002`).
  - No reminder for bookings whose start time has passed.
  - Extra endpoints: `GET /bookings/{id}`, `GET /jobs`, `POST /jobs/{id}/requeue`; `app/manage.py` key CLI.
  - `/events` requires BOTH an API key and a signature.
  - One test (`test_events.py::test_failure_while_applying_effects_rolls_back_the_event_row`) renames a table inside a transaction to force a failure.
- **Mistakes the AI made and corrected itself:**
  - First `app/main.py` created a module-level `app` that needed real env vars at import time; changed to an app factory.
  - First version of the rollback test did DDL clean-up by hand; simplified to rely on transactional DDL.
  - Wrong expected line count in a prompt-injection test (5 vs 4), caught by running it.
- **Verification the AI did:** ran the test suite against the Neon `test` branch; ran one mutation check (removed `FOR UPDATE SKIP LOCKED`, confirmed the two concurrency tests fail, restored it).
- **Mistakes the AI made that I caught:** none yet. _(Add yours after you review.)_
- **Code I wrote myself:** none for M1-M6.
