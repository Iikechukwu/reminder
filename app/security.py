"""Webhook signature verification (HMAC-SHA256).

The sender computes HMAC-SHA256(secret, raw_request_body), hex-encodes it, and
sends `X-Signature: sha256=<hex>`. We recompute it over the exact bytes we
received and compare. It must be the RAW body: re-serialising parsed JSON can
change whitespace or key order and break the match.
"""
import hashlib
import hmac

SIGNATURE_HEADER = "X-Signature"
_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return _PREFIX + digest


def verify_signature(secret: str, body: bytes, header_value: str | None) -> bool:
    """True only if header_value is the correct signature for body.

    hmac.compare_digest takes time independent of where the strings differ, so
    an attacker cannot recover the signature byte by byte by timing responses
    (a plain `==` returns as soon as the first byte differs).
    """
    if not header_value:
        return False
    expected = compute_signature(secret, body)
    # Compare as bytes: compare_digest on str raises TypeError for non-ASCII.
    return hmac.compare_digest(expected.encode("utf-8"), header_value.encode("utf-8"))
