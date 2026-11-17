"""Mock email provider. Only logs; sends nothing."""
import logging
import random
from typing import Callable, Protocol

log = logging.getLogger("reminder.email")


class ProviderError(Exception):
    """The email provider failed (timeout, 5xx, ...). Worth retrying."""


class EmailProvider(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


def _mask(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


class MockEmailProvider:
    def __init__(self, fail_rate: float = 0.0, rng: Callable[[], float] = random.random):
        self.fail_rate = fail_rate
        self._rng = rng

    def send(self, to: str, subject: str, body: str) -> None:
        if self._rng() < self.fail_rate:
            raise ProviderError("mock provider unavailable")
        # Mask the address and do not log the body: it contains customer data.
        log.info(
            "mock email sent",
            extra={"to": _mask(to), "subject": subject, "body_chars": len(body)},
        )
