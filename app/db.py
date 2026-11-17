"""Database connection pool.

`prepare_threshold=None` turns off server-side prepared statements. Neon's
pooled endpoint sits behind PgBouncer in transaction mode, where a prepared
statement may be run on a different backend connection than the one that
prepared it, which breaks. Disabling them is safe on the direct URL too.
"""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def make_pool(url: str, *, min_size: int = 1, max_size: int = 5) -> ConnectionPool:
    pool = ConnectionPool(
        url,
        min_size=min_size,
        max_size=max_size,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
        # Neon free tier closes idle connections and suspends the compute;
        # validate a connection when it is checked out of the pool.
        check=ConnectionPool.check_connection,
        open=False,
    )
    # Generous timeout: the first query after a Neon auto-suspend is slow.
    pool.open(wait=True, timeout=30)
    return pool
