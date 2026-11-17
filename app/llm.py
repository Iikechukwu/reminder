"""LLM drafting step for reminder text, with a timeout, validation and fallback.

The LLM is OPTIONAL polish, never a dependency: if it is slow, errors, or
returns something we do not trust, the reminder is still sent using the fixed
template. Only the FAKE client exists here; a real provider is a drop-in
implementation of `LLMClient` (see README, "Swapping in a real LLM").
"""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Protocol

log = logging.getLogger("reminder.llm")


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    def complete(self, prompt: str, *, timeout: float) -> str: ...


# ---- fake client -----------------------------------------------------------


class FakeLLM:
    """Stands in for a real model. `mode` picks a behaviour:

    ok       friendly, valid text
    slow     takes longer than any sane timeout
    garbage  returns something validation must reject
    error    raises, like a 5xx from a provider
    """

    def __init__(self, mode: str = "ok", slow_seconds: float = 2.0):
        self.mode = mode
        self.slow_seconds = slow_seconds

    def complete(self, prompt: str, *, timeout: float) -> str:
        if self.mode == "slow":
            time.sleep(self.slow_seconds)
        if self.mode == "error":
            raise LLMError("fake provider 503")
        if self.mode == "garbage":
            return "Dear {customer_name}, see http://evil.example/pay [link]"
        name = re.search(r"Customer name: (.*)", prompt)
        when = re.search(r"Booking time: (.*)", prompt)
        return (
            f"Hi {name.group(1) if name else 'there'}! Just a friendly nudge that your "
            f"booking is coming up at {when.group(1) if when else 'the scheduled time'}. "
            "We look forward to seeing you, and let us know if plans change."
        )


def build_client(mode: str) -> LLMClient | None:
    if mode.startswith("fake_"):
        return FakeLLM(mode.removeprefix("fake_"))
    return None  # "off" (or an unknown value): drafting disabled


# ---- prompt, validation ----------------------------------------------------


def _clean(value: str, limit: int = 100) -> str:
    # The customer name is untrusted text that ends up inside a prompt. Strip
    # newlines and cap the length so it cannot smuggle in extra "instructions".
    return " ".join(value.split())[:limit]


def build_prompt(name: str, starts_at) -> str:
    return (
        "Write a short, friendly reminder email body (2-3 sentences, plain text, "
        "no links, no placeholders) for an upcoming booking.\n"
        f"Customer name: {_clean(name)}\n"
        f"Booking time: {starts_at:%H:%M} UTC on {starts_at:%A %d %B %Y}\n"
        f"Include the time {starts_at:%H:%M} exactly."
    )


_FORBIDDEN = re.compile(r"[{}<>]|\[[^\]]*\]|https?://|www\.|@", re.IGNORECASE)


def validate_draft(text: str, starts_at) -> str | None:
    """Returns None if the draft is acceptable, else a short reason."""
    text = text.strip()
    if not 20 <= len(text) <= 600:
        return "length out of range"
    if _FORBIDDEN.search(text):
        return "contains placeholder, markup, link or address"
    if f"{starts_at:%H:%M}" not in text:
        return "missing booking time"
    return None


# ---- orchestration ---------------------------------------------------------

# A fixed pool, so a hung provider cannot spawn unbounded threads. Python
# cannot kill a running thread, so a timed-out call keeps running in the
# background; a real client must ALSO pass `timeout` to its HTTP library so the
# socket is actually abandoned.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm")


def draft_body(client: LLMClient, name: str, starts_at, timeout: float) -> str | None:
    """Return a validated draft, or None (caller falls back to the template)."""
    prompt = build_prompt(name, starts_at)
    future = _executor.submit(client.complete, prompt, timeout=timeout)
    try:
        text = future.result(timeout=timeout)
    except FutureTimeout:
        log.warning("llm draft failed", extra={"reason": "timeout", "timeout_s": timeout})
        return None
    except Exception as exc:
        log.warning("llm draft failed", extra={"reason": "error", "error": type(exc).__name__})
        return None
    problem = validate_draft(text, starts_at)
    if problem:
        log.warning("llm draft rejected", extra={"reason": problem})
        return None
    return text.strip()
