import json

import pytest

from app.security import compute_signature, verify_signature
from tests.helpers import created_event, post_event, sign

SECRET = "s3cret"
BODY = b'{"id":"evt_1"}'


def test_known_vector_matches_independent_implementation():
    assert compute_signature(SECRET, BODY) == sign(BODY, SECRET)


def test_valid_signature_accepted():
    assert verify_signature(SECRET, BODY, sign(BODY, SECRET))


@pytest.mark.parametrize(
    "header",
    [None, "", "sha256=", "sha256=deadbeef", "deadbeef", "SHA256=abc", "sha256=é"],
)
def test_bad_headers_rejected_without_crashing(header):
    assert not verify_signature(SECRET, BODY, header)


def test_tampered_body_rejected():
    sig = sign(BODY, SECRET)
    assert not verify_signature(SECRET, BODY + b" ", sig)


def test_wrong_secret_rejected():
    assert not verify_signature(SECRET, BODY, sign(BODY, "other"))


def test_signature_must_cover_raw_bytes_not_parsed_json():
    pretty = b'{ "id": "evt_1" }'
    compact = json.dumps(json.loads(pretty)).encode()
    assert pretty != compact
    assert not verify_signature(SECRET, pretty, sign(compact, SECRET))


# ---- through the HTTP endpoint ------------------------------------------


def test_endpoint_rejects_missing_signature(client, conn):
    r = client.post("/events", content=json.dumps(created_event()).encode())
    assert r.status_code == 401
    assert conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0


def test_endpoint_rejects_wrong_signature_and_stores_nothing(client, conn):
    r = post_event(client, created_event(), secret="not-the-secret")
    assert r.status_code == 401
    assert conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 0


def test_endpoint_rejects_body_modified_after_signing(client, conn):
    payload = created_event()
    body = json.dumps(payload).encode()
    sig = sign(body)
    tampered = body.replace(b"ada@example.com", b"evil@example.com")
    r = client.post("/events", content=tampered, headers={"X-Signature": sig})
    assert r.status_code == 401
    assert conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0
