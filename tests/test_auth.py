import hashlib
import json
import logging

from fastapi.testclient import TestClient

from app.auth import generate_key, hash_key
from app.logging_config import JsonFormatter
from app.main import create_app
from app.ratelimit import FixedWindowLimiter
from tests.helpers import created_event, post_event, seed_job, sign


def test_health_is_public(anon_client):
    assert anon_client.get("/health").status_code == 200


def test_protected_endpoints_require_an_api_key(anon_client):
    assert anon_client.get("/jobs").status_code == 401
    assert anon_client.get("/bookings/b1").status_code == 401
    assert anon_client.post("/jobs/1/requeue").status_code == 401
    body = json.dumps(created_event()).encode()
    r = anon_client.post("/events", content=body, headers={"X-Signature": sign(body)})
    assert r.status_code == 401
    assert "API key" in r.json()["detail"]  # rejected on the key, before the signature


def test_invalid_key_rejected(anon_client):
    r = anon_client.get("/jobs", headers={"X-API-Key": "rk_not-a-real-key"})
    assert r.status_code == 401


def test_revoked_key_rejected(client, conn, api_key):
    assert client.get("/jobs").status_code == 200
    conn.execute("UPDATE api_keys SET revoked_at = now()")
    assert client.get("/jobs").status_code == 401


def test_api_key_is_stored_hashed_not_in_plaintext(client, conn, api_key):
    row = conn.execute("SELECT key_hash FROM api_keys").fetchone()
    assert row["key_hash"] == hashlib.sha256(api_key.encode()).hexdigest()
    assert api_key not in row["key_hash"]


def test_valid_key_with_bad_signature_is_rejected_on_the_signature(client):
    r = post_event(client, created_event(), secret="wrong")
    assert r.status_code == 401
    assert "signature" in r.json()["detail"]


# ---- inspection endpoints -------------------------------------------------


def test_get_booking_shows_its_jobs(client, conn):
    post_event(client, created_event(booking_id="b1"))
    r = client.get("/bookings/b1")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "active"
    assert [j["status"] for j in data["jobs"]] == ["pending"]
    assert client.get("/bookings/nope").status_code == 404


def test_dead_letter_listing_and_requeue(client, conn):
    job = seed_job(conn, "b1", status="dead", attempts=5)
    seed_job(conn, "b2", status="pending")
    listed = client.get("/jobs", params={"status": "dead"}).json()["jobs"]
    assert [j["id"] for j in listed] == [job["id"]]

    assert client.post(f"/jobs/{job['id']}/requeue").status_code == 200
    assert conn.execute("SELECT status FROM jobs WHERE id = %s", (job["id"],)).fetchone()["status"] == "pending"
    assert client.post(f"/jobs/{job['id']}/requeue").status_code == 404  # no longer dead


def test_invalid_status_filter_is_422(client):
    assert client.get("/jobs", params={"status": "bogus"}).status_code == 422


# ---- rate limiting ---------------------------------------------------------


def test_rate_limit_returns_429_with_retry_after(settings, conn):
    limited = settings.model_copy(update={"rate_limit_per_minute": 3})
    key = generate_key()
    conn.execute("INSERT INTO api_keys (name, key_hash) VALUES ('k', %s)", (hash_key(key),))
    with TestClient(create_app(limited)) as c:
        c.headers["X-API-Key"] = key
        codes = [c.get("/jobs").status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]
        r = c.get("/jobs")
        assert int(r.headers["Retry-After"]) >= 1
        assert c.get("/health").status_code == 200  # health is not rate limited


def test_rate_limit_is_per_key(settings, conn):
    limited = settings.model_copy(update={"rate_limit_per_minute": 2})
    keys = [generate_key(), generate_key()]
    for i, k in enumerate(keys):
        conn.execute("INSERT INTO api_keys (name, key_hash) VALUES (%s, %s)", (f"k{i}", hash_key(k)))
    with TestClient(create_app(limited)) as c:
        a = [c.get("/jobs", headers={"X-API-Key": keys[0]}).status_code for _ in range(3)]
        b = [c.get("/jobs", headers={"X-API-Key": keys[1]}).status_code for _ in range(2)]
    assert a == [200, 200, 429]
    assert b == [200, 200]  # key 2 unaffected by key 1 being limited


def test_limiter_window_resets_with_fake_clock():
    now = [0.0]
    lim = FixedWindowLimiter(2, 60.0, clock=lambda: now[0])
    assert lim.check("k") == (True, 0)
    assert lim.check("k") == (True, 0)
    allowed, retry = lim.check("k")
    assert not allowed and 1 <= retry <= 61
    now[0] = 60.0  # next window
    assert lim.check("k") == (True, 0)


# ---- logging ---------------------------------------------------------------


def test_json_formatter_emits_one_json_object_with_extras():
    record = logging.LogRecord("reminder.x", logging.INFO, __file__, 1, "hello %s", ("w",), None)
    record.job_id = 7
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "hello w"
    assert out["level"] == "INFO"
    assert out["job_id"] == 7
    assert "ts" in out


def test_request_log_has_request_id_and_no_customer_data(client, caplog):
    caplog.set_level(logging.INFO, logger="reminder")
    r = post_event(client, created_event(email="ada@example.com"))
    assert r.headers["X-Request-ID"]
    everything = " ".join(str(rec.__dict__) for rec in caplog.records)
    assert "ada@example.com" not in everything
    assert any(rec.getMessage() == "request" for rec in caplog.records)
