"""API-key authentication and rate limiting."""
import hashlib
import logging
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

log = logging.getLogger("reminder.auth")

# Declares the header in the OpenAPI doc, so /docs shows an "Authorize" button.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def generate_key() -> str:
    return "rk_" + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    # A fast hash is fine here (unlike passwords): the key is 256 bits of
    # randomness, so there is nothing to brute-force.
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def authenticate(request: Request, key: str | None = Depends(api_key_header)) -> dict:
    """Require a valid, non-revoked API key; then apply that key's rate limit."""
    if not key:
        raise HTTPException(status_code=401, detail="missing API key")
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            "SELECT id, name FROM api_keys WHERE key_hash = %s AND revoked_at IS NULL",
            (hash_key(key),),
        ).fetchone()
    if row is None:
        log.warning("invalid API key rejected")
        raise HTTPException(status_code=401, detail="invalid API key")

    allowed, retry_after = request.app.state.limiter.check(row["id"])
    if not allowed:
        log.warning("rate limit exceeded", extra={"api_key": row["name"]})
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    request.state.api_key_name = row["name"]
    return row
