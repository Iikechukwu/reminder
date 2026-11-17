"""Minimal SQL migration runner.

Applies migrations/*.sql in filename order, each in its own transaction, and
records applied versions in `schema_migrations`. Run with the DIRECT Neon URL
(advisory locks and DDL do not belong behind a transaction-mode pooler):

    python -m app.migrate
"""
import pathlib

import psycopg

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"
# Arbitrary constant: only one migration runner at a time.
_ADVISORY_LOCK_KEY = 7_265_001


def migrate(database_url: str) -> list[str]:
    """Apply pending migrations. Returns the versions applied by this call."""
    applied_now: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version text PRIMARY KEY,"
                " applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.stem in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,)
                    )
                applied_now.append(path.stem)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
    return applied_now


if __name__ == "__main__":
    from app.config import Settings

    applied = migrate(Settings().database_url_direct)
    print("applied:", applied or "nothing (already up to date)")
