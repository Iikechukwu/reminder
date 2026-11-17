"""Shared fixtures.

SAFETY: tests run ONLY against TEST_DATABASE_URL_DIRECT (the Neon `test`
branch). Every test TRUNCATEs the tables, so a hard guard refuses to run if the
test URL points at the same Neon endpoint as the dev/production URLs.
"""
import os
import urllib.parse

import psycopg
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.auth import generate_key, hash_key
from app.config import Settings
from app.main import create_app
from app.migrate import migrate

load_dotenv()

TEST_SECRET = "test-webhook-secret"


def _endpoint(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname or ""
    return host.replace("-pooler", "")


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL_DIRECT")
    if not url:
        pytest.exit("TEST_DATABASE_URL_DIRECT is not set; refusing to run.", returncode=2)
    for name in ("DATABASE_URL", "DATABASE_URL_DIRECT"):
        other = os.environ.get(name)
        if other and _endpoint(other) == _endpoint(url):
            pytest.exit(
                f"TEST_DATABASE_URL_DIRECT points at the same endpoint as {name}. "
                "Refusing to run: tests wipe tables.",
                returncode=2,
            )
    migrate(url)
    return url


@pytest.fixture
def clean_db(test_db_url):
    """Empties all tables. Requested (directly or indirectly) by every fixture
    that touches the database, so pure unit tests stay fast."""
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute("TRUNCATE jobs, bookings, events RESTART IDENTITY CASCADE")
        # api_keys exists from migration 002 onwards.
        conn.execute(
            "DO $$ BEGIN IF to_regclass('api_keys') IS NOT NULL THEN "
            "TRUNCATE api_keys RESTART IDENTITY CASCADE; END IF; END $$"
        )
    yield


@pytest.fixture
def settings(test_db_url) -> Settings:
    return Settings(
        _env_file=None,
        database_url=test_db_url,
        database_url_direct=test_db_url,
        webhook_secret=TEST_SECRET,
        rate_limit_per_minute=1000,
        backoff_base_seconds=10,
        backoff_cap_seconds=100,
    )


@pytest.fixture
def api_key(conn) -> str:
    key = generate_key()
    conn.execute("INSERT INTO api_keys (name, key_hash) VALUES ('test', %s)", (hash_key(key),))
    return key


@pytest.fixture
def anon_client(settings, clean_db):
    """Client with NO API key header."""
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def client(anon_client, api_key):
    """Client that sends a valid API key on every request."""
    anon_client.headers["X-API-Key"] = api_key
    return anon_client


@pytest.fixture
def pool(test_db_url, clean_db):
    from app.db import make_pool

    p = make_pool(test_db_url, max_size=4)
    yield p
    p.close()


@pytest.fixture
def conn(test_db_url, clean_db):
    """Plain connection for assertions and for setting up rows."""
    with psycopg.connect(test_db_url, autocommit=True, row_factory=dict_row) as c:
        yield c
