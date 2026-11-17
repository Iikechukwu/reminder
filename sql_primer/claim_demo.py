"""Part C demo: run the SQL in claim.sql inside a transaction, then HOLD it open.

Run this in two terminals at nearly the same time to see how two workers
behave when they try to claim a job concurrently.

Usage:  python sql_primer/claim_demo.py worker_A
"""
import pathlib
import os
import sys
import time

import psycopg
from dotenv import load_dotenv

load_dotenv()  # reads DATABASE_URL_DIRECT from .env (never printed)

name = sys.argv[1] if len(sys.argv) > 1 else "worker"
sql = pathlib.Path(__file__).with_name("claim.sql").read_text()

# Leaving the `with conn` block without an error COMMITS the transaction.
with psycopg.connect(os.environ["DATABASE_URL_DIRECT"]) as conn:
    with conn.cursor() as cur:
        print(f"[{name}] running claim query...", flush=True)
        cur.execute(sql)
        print(f"[{name}] result: {cur.fetchall()}", flush=True)
        print(f"[{name}] holding transaction open for 15s...", flush=True)
        time.sleep(15)
print(f"[{name}] committed", flush=True)
